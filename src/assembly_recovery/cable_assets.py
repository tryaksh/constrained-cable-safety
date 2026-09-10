"""Explicit adapters for pinned AIC rigid assets; this is not a Gazebo converter.

Fixed SDF links are flattened into one MuJoCo body. Collision primitives and
rigid transforms are preserved, including tiny ferrules/keys and marker-link
mass. Explicit inertia is rotated into the model frame. SDF ``auto`` inertia is
computed from uniform-density, additive primitive volumes (overlaps counted),
then scaled to the declared mass; equivalence to Gazebo's auto-inertia backend
is not asserted. GLB node transforms are baked into visual-only OBJ vertices.

Contact solver parameters and torsional friction are backend-specific: callers
choose MuJoCo friction, with an isotropic SDF sliding coefficient overriding its
first component where present. No Gazebo plugin, latch, sensor, or controller is
implicitly ported. Unsupported moving joints or collision shapes raise errors.
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

AIC_REVISION = "e9145480c945f2afc3741f355233f44082cc3b06"
UR_DESCRIPTION_REVISION = "ef93882e17d8aa628837915da4b83208fe5e519a"
UR_DESCRIPTION_URL = "https://github.com/UniversalRobots/Universal_Robots_ROS2_Description"


def _numbers(text: str | None, count: int, default: str | None = None) -> tuple[float, ...]:
    result = tuple(float(x) for x in (text or default or "").split())
    if len(result) != count or not all(math.isfinite(x) for x in result):
        raise ValueError(f"Expected {count} finite numbers: {text!r}")
    return result


def _fmt(values) -> str:
    return " ".join(format(float(x), ".17g") for x in values)


def _qmul(a, b):
    w, x, y, z = a
    v, i, j, k = b
    return (w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j, w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v)


@dataclass(frozen=True)
class Pose:
    """Rigid transform using metres and scalar-first (wxyz) quaternion."""

    position: tuple[float, ...] = (0.0, 0.0, 0.0)
    quaternion: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0)

    def rotate(self, vector):
        w, x, y, z = self.quaternion
        return _qmul(_qmul(self.quaternion, (0.0, *vector)), (w, -x, -y, -z))[1:]

    def compose(self, other: Pose) -> Pose:
        rotated = self.rotate(other.position)
        return Pose(tuple(a+b for a, b in zip(self.position, rotated, strict=True)),
                    _qmul(self.quaternion, other.quaternion))

    def inverse(self) -> Pose:
        w, x, y, z = self.quaternion
        rotation = Pose(quaternion=(w, -x, -y, -z))
        return Pose(rotation.rotate(tuple(-x for x in self.position)), rotation.quaternion)

    def attributes(self) -> dict[str, str]:
        return {"pos": _fmt(self.position), "quat": _fmt(self.quaternion)}


def sdf_pose(element: ET.Element | None) -> Pose:
    """Interpret SDF extrinsic XYZ roll/pitch/yaw without MJCF Euler ambiguity."""
    if element is None:
        return Pose()
    if element.get("rotation_format", "euler_rpy") != "euler_rpy":
        raise ValueError("Only SDF euler_rpy pose encoding is supported")
    x, y, z, r, p, yaw = _numbers(element.text, 6, "0 0 0 0 0 0")
    if element.get("degrees", "false").lower() == "true":
        r, p, yaw = (math.radians(v) for v in (r, p, yaw))
    cr, cp, cy = (math.cos(v/2) for v in (r, p, yaw))
    sr, sp, sy = (math.sin(v/2) for v in (r, p, yaw))
    return Pose((x, y, z), (cr*cp*cy+sr*sp*sy, sr*cp*cy-cr*sp*sy,
                            cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy))


def _matrix_rotate(matrix, pose):
    columns = [pose.rotate(v) for v in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]]
    return [[sum(columns[k][i]*matrix[k][m]*columns[m][j] for k in range(3) for m in range(3))
             for j in range(3)] for i in range(3)]


def _combine_inertia(components):
    total = sum(mass for mass, _, _ in components)
    if total <= 0:
        return None
    center = tuple(sum(mass*position[i] for mass, position, _ in components)/total for i in range(3))
    matrix = [[0.0]*3 for _ in range(3)]
    for mass, position, inertia in components:
        offset = [position[i]-center[i] for i in range(3)]
        distance = sum(v*v for v in offset)
        for i in range(3):
            for j in range(3):
                matrix[i][j] += inertia[i][j] + mass*((distance if i == j else 0.0)-offset[i]*offset[j])
    return total, center, matrix


def _primitive(geometry):
    if geometry is None or len(geometry) != 1:
        raise ValueError("One collision primitive is required")
    shape = geometry[0]
    if shape.tag == "box":
        size = _numbers(shape.findtext("size"), 3)
        volume = math.prod(size)
        inertia_per_mass = tuple((size[(i+1)%3]**2+size[(i+2)%3]**2)/12 for i in range(3))
        mj_size = tuple(v/2 for v in size)
    elif shape.tag == "cylinder":
        radius, length = float(shape.findtext("radius")), float(shape.findtext("length"))
        size = (radius, length)
        volume = math.pi*radius**2*length
        inertia_per_mass = ((3*radius**2+length**2)/12,)*2+(radius**2/2,)
        mj_size = (radius, length/2)
    elif shape.tag == "sphere":
        radius = float(shape.findtext("radius"))
        size = (radius,)
        volume = 4*math.pi*radius**3/3
        inertia_per_mass = (2*radius**2/5,)*3
        mj_size = (radius,)
    else:
        raise ValueError(f"Unsupported collision geometry: {shape.tag}")
    if not all(math.isfinite(v) and v > 0 for v in size):
        raise ValueError("Collision dimensions must be positive and finite")
    return {"type": shape.tag, "size": _fmt(mj_size)}, volume, inertia_per_mass


def _safe_name(value):
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class ImportedAsset:
    body: ET.Element
    assets: list[ET.Element]
    frames: dict[str, Pose]
    report: dict


def import_sdf_model(
    sdf_path: Path,
    prefix: str,
    *,
    visual_directory: Path | None = None,
    friction: tuple[float, float, float] = (0.5, 0.005, 0.0001),
) -> ImportedAsset:
    """Import a single fixed rigid SDF model and expose model-local link frames.

    ``body`` is in the SDF model pose; its geoms/inertia are flattened into the
    model frame. The caller can replace body pos/quat for scene placement. Passing
    no visual_directory explicitly omits all visuals and records their names.
    Scene includes, plugins, moving joints, and unresolved frames are rejected.
    """
    sdf_path = Path(sdf_path).resolve()
    model = ET.parse(sdf_path).getroot().find("model")
    if model is None or model.find("include") is not None or model.find("model") is not None:
        raise ValueError("Expected one standalone SDF model without nested models/includes")
    if model.find("plugin") is not None:
        raise ValueError("SDF plugins require a separately implemented adapter")
    if len(friction) != 3 or not all(math.isfinite(v) and v >= 0 for v in friction):
        raise ValueError("Three finite nonnegative MuJoCo friction coefficients are required")
    for joint in model.findall("joint"):
        if joint.get("type") != "fixed":
            raise ValueError("Moving SDF joints require a separate articulated adapter")
    links = {link.attrib["name"]: link for link in model.findall("link")}
    frame_elements = {**links, **{f.attrib["name"]: f for f in model.findall("frame")}}
    frames = {"__model__": Pose()}
    active = set()

    def resolve(name):
        if name in frames:
            return frames[name]
        if name in active or name not in frame_elements:
            raise ValueError(f"Unknown or cyclic SDF frame: {name}")
        active.add(name)
        item = frame_elements[name]
        pose = item.find("pose")
        default_relative = item.get("attached_to", "__model__") if item.tag == "frame" else "__model__"
        relative = pose.get("relative_to", default_relative) if pose is not None else default_relative
        frames[name] = resolve(relative).compose(sdf_pose(pose))
        active.remove(name)
        return frames[name]

    def resolve_child(item, link_name):
        pose = item.find("pose")
        reference = pose.get("relative_to", link_name) if pose is not None else link_name
        return resolve(reference).compose(sdf_pose(pose))

    for name in frame_elements:
        resolve(name)
    body = ET.Element("body", name=prefix, **sdf_pose(model.find("pose")).attributes())
    assets = []
    components = []
    report = {"source": str(sdf_path), "source_sha256": _sha256(sdf_path),
              "collision_count": 0, "collision_sources": [], "omitted_visuals": [], "visuals": [],
              "inertia_adaptations": [], "contact_adaptation": {
                  "default_mujoco_friction": list(friction),
                  "rule": "SDF isotropic sliding coefficient overrides sliding only; torsion is not equivalent",
                  "solver_equivalence": False},
              "fixed_links_flattened": list(links), "forbidden_geometry_omissions": 0}
    names = set()
    for link_name, link in links.items():
        local_components = []
        for collision in link.findall("collision"):
            name = f"{prefix}__{_safe_name(link_name)}__{_safe_name(collision.attrib['name'])}"
            if name in names:
                raise ValueError(f"Collision name sanitization collision: {name}")
            names.add(name)
            attrs, volume, diagonal = _primitive(collision.find("geometry"))
            pose = resolve_child(collision, link_name)
            coefficient = collision.findtext("surface/friction/bullet/friction")
            coefficient2 = collision.findtext("surface/friction/bullet/friction2")
            if coefficient2 is not None and coefficient is not None and float(coefficient2) != float(coefficient):
                raise ValueError("Anisotropic SDF friction needs an explicit contact adapter")
            actual_friction = (float(coefficient), *friction[1:]) if coefficient is not None else friction
            ET.SubElement(body, "geom", name=name, **attrs, **pose.attributes(),
                          friction=_fmt(actual_friction), rgba="0.22 0.38 0.7 1", group="3")
            matrix = [[volume*diagonal[i] if i == j else 0.0 for j in range(3)] for i in range(3)]
            local_components.append((volume, pose.position, _matrix_rotate(matrix, pose)))
            report["collision_sources"].append({"name": collision.attrib["name"], "mjcf_name": name,
                                                 "source_surface": ET.tostring(collision.find("surface"), encoding="unicode")
                                                 if collision.find("surface") is not None else None})
        report["collision_count"] += len(local_components)
        inertial = link.find("inertial")
        if inertial is not None:
            mass = float(inertial.findtext("mass", "0"))
            if not math.isfinite(mass) or mass <= 0:
                raise ValueError("Declared link mass must be positive and finite")
            inertia = inertial.find("inertia")
            if inertia is not None:
                def entry(key, tensor=inertia):
                    return float(tensor.findtext(key, "0"))
                matrix = [[entry("ixx"), entry("ixy"), entry("ixz")],
                          [entry("ixy"), entry("iyy"), entry("iyz")],
                          [entry("ixz"), entry("iyz"), entry("izz")]]
                pose = resolve_child(inertial, link_name)
                components.append((mass, pose.position, _matrix_rotate(matrix, pose)))
                report["inertia_adaptations"].append({"link": link_name, "mass": mass, "method": "explicit_tensor"})
            elif inertial.get("auto", "false") == "true" and local_components:
                volume, center, matrix = _combine_inertia(local_components)
                components.append((mass, center, [[v*mass/volume for v in row] for row in matrix]))
                report["inertia_adaptations"].append({"link": link_name, "mass": mass,
                    "method": "uniform_additive_collision_volume_scaled_to_declared_mass"})
            else:
                raise ValueError(f"Link {link_name} has mass but no supported inertia")
        elif local_components:
            raise ValueError(f"Colliding link {link_name} has no declared inertia/mass")
        for visual_index, visual in enumerate(link.findall("visual")):
            if visual_directory is None:
                report["omitted_visuals"].append(visual.attrib["name"])
                continue
            pose = resolve_child(visual, link_name)
            geometry = visual.find("geometry")
            mesh = geometry.find("mesh") if geometry is not None else None
            visual_name = f"{prefix}__{_safe_name(link_name)}__visual_{visual_index}"
            if mesh is None:
                attrs, _, _ = _primitive(geometry)
                color = visual.findtext("material/diffuse", "0.7 0.7 0.7 1")
                ET.SubElement(body, "geom", name=visual_name, **attrs, **pose.attributes(),
                              contype="0", conaffinity="0", mass="0", group="2", rgba=color)
            else:
                uri = mesh.findtext("uri", "")
                if "://" in uri or Path(uri).is_absolute():
                    raise ValueError("Visual mesh URI must be relative to the source model")
                source = (sdf_path.parent/uri).resolve()
                scale = _numbers(mesh.findtext("scale"), 3, "1 1 1")
                visual_report = _glb_visual(source, Path(visual_directory), visual_name, scale, body, assets, pose)
                report["visuals"].append(visual_report)
    combined = _combine_inertia(components)
    if combined is not None:
        mass, center, matrix = combined
        ET.SubElement(body, "inertial", pos=_fmt(center), mass=format(mass, ".17g"),
                      fullinertia=_fmt([matrix[0][0], matrix[1][1], matrix[2][2],
                                        matrix[0][1], matrix[0][2], matrix[1][2]]))
        report["total_declared_mass_kg"] = mass
    for frame_name, frame in frames.items():
        if frame_name != "__model__":
            ET.SubElement(body, "site", name=f"{prefix}__frame__{_safe_name(frame_name)}",
                          **frame.attributes(), size="0.0005", rgba="1 0 0 0")
    return ImportedAsset(body, assets, frames, report)


def _glb_visual(source, destination, prefix, scale, body, assets, pose):
    """Bake GLTF scene-node transforms; preserve mesh triangles, approximate materials."""
    import trimesh

    if source.suffix.lower() != ".glb":
        raise ValueError("Only GLB visual meshes are supported")
    scene = trimesh.load(source, force="scene", process=False)
    destination.mkdir(parents=True, exist_ok=True)
    items = []
    for index, node in enumerate(sorted(scene.graph.nodes_geometry)):
        transform, mesh_name = scene.graph[node]
        mesh = scene.geometry[mesh_name].copy()
        mesh.apply_transform(transform)
        mesh.vertices *= scale
        asset_name = f"{prefix}__node_{index}"
        obj = trimesh.exchange.obj.export_obj(mesh, include_color=False, include_texture=False)
        digest = hashlib.sha256(obj.encode()).hexdigest()
        target = (destination/f"{asset_name}_{digest[:16]}.obj").resolve()
        if target.exists() and target.read_text(encoding="utf-8") != obj:
            raise FileExistsError(f"Derived visual asset collision: {target}")
        target.write_text(obj, encoding="utf-8")
        assets.append(ET.Element("mesh", name=asset_name, file=str(target), inertia="shell"))
        color = (0.25, 0.45, 0.8, 1.0)
        material = getattr(mesh.visual, "material", None)
        if material is not None and getattr(material, "main_color", None) is not None:
            color = tuple(float(v)/255 for v in material.main_color)
        ET.SubElement(body, "geom", name=asset_name, type="mesh", mesh=asset_name,
                      **pose.attributes(), contype="0", conaffinity="0", mass="0", group="2", rgba=_fmt(color))
        items.append({"node": node, "triangles": len(mesh.faces), "vertices": len(mesh.vertices),
                      "obj": str(target), "sha256": digest, "bounds": mesh.bounds.tolist()})
    return {"source": str(source), "source_sha256": _sha256(source), "nodes": items,
            "adaptation": "Scene transforms baked, exact triangles; textures replaced by material base color; visual only"}


def append_sdf_model(parent_body, asset_section, sdf_path, prefix, **kwargs) -> ImportedAsset:
    imported = import_sdf_model(sdf_path, prefix, **kwargs)
    parent_body.append(imported.body)
    asset_section.extend(imported.assets)
    return imported


def prepare_native_robot(aic_root: Path, mesh_directory: Path) -> tuple[ET.Element, dict]:
    """Restore native UR5e collision STLs; omit only explicitly noncolliding missing visuals.

    The caller provides the seven UR description collision STLs from release
    4.3.0. Every replacement must match the SHA1 in AIC's filename exactly.
    Downloading and revision capture are separate setup operations.
    """
    source = Path(aic_root).resolve()/"aic_utils/aic_mujoco/mjcf/aic_robot.xml"
    root = ET.parse(source).getroot()
    report = {"source": str(source), "source_sha256": _sha256(source),
              "aic_revision": AIC_REVISION, "robot_asset_revision": UR_DESCRIPTION_REVISION,
              "robot_asset_repository": UR_DESCRIPTION_URL, "restored_collision_meshes": [],
              "omitted_visual_geoms": [], "omitted_visual_meshes": [], "collision_geoms_removed": 0}
    parents = {child: parent for parent in root.iter() for child in parent}
    asset = root.find("asset")
    for mesh in list(asset.findall("mesh")):
        filename = mesh.attrib.get("file")
        if filename is None:
            continue
        native = source.parent/filename
        if native.is_file():
            mesh.set("file", str(native.resolve()))
            continue
        references = [geom for geom in root.findall(".//geom") if geom.get("mesh") == mesh.get("name")]
        colliding = [geom for geom in references
                     if geom.get("contype") != "0" or geom.get("conaffinity") != "0"]
        if colliding:
            match = re.fullmatch(r"(.+)-([0-9a-f]{40})\.stl", Path(filename).name)
            if match is None:
                raise FileNotFoundError(f"Missing collision mesh: {filename}")
            replacement = Path(mesh_directory)/f"{match[1]}.stl"
            data = replacement.read_bytes()
            if hashlib.sha1(data).hexdigest() != match[2]:
                raise ValueError(f"Collision mesh differs from native AIC bytes: {replacement}")
            mesh.set("file", str(replacement.resolve()))
            report["restored_collision_meshes"].append({"path": str(replacement.resolve()),
                "native_filename": filename, "sha1": match[2], "sha256": hashlib.sha256(data).hexdigest(),
                "geom_names": [g.get("name") for g in colliding]})
        else:
            for geom in references:
                report["omitted_visual_geoms"].append(geom.get("name"))
                parents[geom].remove(geom)
            report["omitted_visual_meshes"].append(mesh.attrib)
            asset.remove(mesh)
    report["preserved_collision_geom_count"] = sum(
        geom.get("contype") != "0" or geom.get("conaffinity") != "0" for geom in root.findall(".//worldbody//geom"))
    report["scope"] = "Native robot only, exact restored collision bytes; no world/cable/plugin conversion"
    return root, report
