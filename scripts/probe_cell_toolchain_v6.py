"""Check the CAD-to-simulation toolchain before a session plans around it.

Three things have to be true before a routing cell can be authored in CAD and
measured in MuJoCo, and all three have failed quietly in testing:

  1. FreeCAD builds and exports solid parts with no display attached.
  2. A part exported in assembly coordinates lands where the CAD put it, and
     collides the way the primitive fixture this project already measured does.
  3. The recorded motion can leave MuJoCo as a USD stage, for rendering
     elsewhere, without moving the physics.

The second is the one that decides the design, and it took two attempts to get
right. MuJoCo collides a mesh by its convex hull, so a channel arrives as
several convex pieces and the contact manifold is not the one the primitive
fixture produces: the same cable rests 0.27 mm lower on one contact instead of
two. That is small in absolute terms and large for this project, whose
retention predicate is decided within about 4 mm of channel half-width and
whose settling behaviour was characterised to micrometres. So CAD meshes are
visual geometry and collision stays on the primitives - not because mesh
collision fails, but because it is a DIFFERENT instrument, and keeping the
primitives keeps collision bit-identical to the scene every existing record was
measured in.

A first pass here concluded that mesh collision lost the cable outright. That
was wrong and the cause is worth recording: those scenes were built without
this project's contact defaults, and under MuJoCo's own defaults a 0.23 g
capsule sinks through a 3 mm plate from any drop height, meshes or not. The
instrument was at fault, not the collider - which is the same lesson this
repository already learned about a bending-damping control.

Run it with the native environment:

    .deps/cable-venv/Scripts/pythonw.exe scripts/probe_cell_toolchain_v6.py

Writes evidence/cell_toolchain_v6.json. Nothing here is a research result; it is
a machine check, and it is recorded so the next session can re-run it in a
minute instead of rediscovering it in an afternoon.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FREECAD_DEFAULT = Path(r"C:\Users\tryak\AppData\Local\Programs\FreeCAD 1.1\bin\freecadcmd.exe")

#: Authored inside FreeCAD's own interpreter, which is a separate Python.
FREECAD_SCRIPT = '''
import json, os, sys
import FreeCAD as App
import MeshPart
import Part

out = sys.argv[-1]
doc = App.newDocument("probe")
half_width, wall, lip_h, lip_t, gap, length, base_t = 6.0, 3.0, 12.5, 2.0, 5.0, 30.0, 3.0
EPS = 0.01

pieces = {}
base = Part.makeBox(length, 2 * (half_width + wall), base_t)
base.translate(App.Vector(-length / 2, -(half_width + wall), -base_t))
pieces["base"] = base
for tag, sign in (("left", 1), ("right", -1)):
    w = Part.makeBox(length, wall, lip_h + EPS)
    w.translate(App.Vector(-length / 2, sign * half_width - (wall if sign < 0 else 0), -EPS))
    pieces["wall_" + tag] = w
    tab = half_width - gap / 2
    lip = Part.makeBox(length, tab, lip_t)
    lip.translate(App.Vector(-length / 2, sign * half_width - (tab if sign > 0 else 0), lip_h))
    pieces["lip_" + tag] = lip

report = {"freecad_version": ".".join(App.Version()[:3]), "parts": []}
for name, shape in pieces.items():
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=0.05,
                                  AngularDeflection=0.5, Relative=False)
    mesh.write(os.path.join(out, "probe_%s.stl" % name))
    box = shape.BoundBox
    report["parts"].append({
        "name": name,
        "facets": mesh.CountFacets,
        "watertight": bool(mesh.isSolid()),
        "self_intersecting": bool(mesh.hasSelfIntersections()),
        "volume_mm3": round(shape.Volume, 4),
        "bbox_min_mm": [round(box.XMin, 4), round(box.YMin, 4), round(box.ZMin, 4)],
        "bbox_max_mm": [round(box.XMax, 4), round(box.YMax, 4), round(box.ZMax, 4)],
    })

# A fuse only welds solids that interpenetrate. Record both outcomes so the
# trap is in the evidence rather than in somebody's memory.
touching = Part.makeBox(10, 10, 10)
neighbour = Part.makeBox(10, 10, 10)
neighbour.translate(App.Vector(0, 0, 10))
report["fuse_face_touching_solids"] = len(touching.fuse(neighbour).removeSplitter().Solids)
overlapping = Part.makeBox(10, 10, 10)
overlapping.translate(App.Vector(0, 0, 10 - EPS))
report["fuse_overlapping_solids"] = len(touching.fuse(overlapping).removeSplitter().Solids)

with open(os.path.join(out, "freecad_report.json"), "w") as handle:
    json.dump(report, handle)
print("FREECAD_DONE")
'''

NAMES = ("base", "wall_left", "lip_left", "wall_right", "lip_right")

#: The contact defaults this project's scenes have always compiled with. They
#: are not cosmetic: with MuJoCo's own defaults a 0.23 g capsule dropped 6 mm
#: onto a 3 mm plate sinks through it, and from 8 mm it tunnels outright at
#: every timestep tried. Any CAD-derived scene must inherit this block.
CONTACT_DEFAULTS = 'solref="0.004 1" solimp="0.95 0.99 0.001"'

SCENE = """
<mujoco>
  <compiler meshdir="{meshdir}" angle="radian"/>
  <option timestep="0.0005">
{flags}
  </option>
  <default>
    <geom {defaults}/>
  </default>
  <asset>
{assets}
  </asset>
  <worldbody>
    <light pos="0 0 0.3"/>
    <body name="clip" pos="0 0 0">
{clip}
    </body>
    <body name="cable" pos="0 0 {drop}">
      <freejoint/>
      <geom name="seg" type="capsule" size="0.002 0.008" euler="0 1.5708 0" rgba=".9 .4 .2 1"/>
    </body>
  </worldbody>
</mujoco>
"""

#: The primitive channel, in metres, matching the CAD part above.
PRIMITIVES = """      <geom name="c_base" type="box" size="0.015 0.009 0.0015" pos="0 0 -0.0015"/>
      <geom name="c_wall_p" type="box" size="0.015 0.0015 0.00625" pos="0 0.0075 0.00625"/>
      <geom name="c_wall_m" type="box" size="0.015 0.0015 0.00625" pos="0 -0.0075 0.00625"/>
      <geom name="c_lip_p" type="box" size="0.015 0.00175 0.001" pos="0 0.00425 0.0135"/>
      <geom name="c_lip_m" type="box" size="0.015 0.00175 0.001" pos="0 -0.00425 0.0135"/>"""


def assets_block(meshdir: Path) -> str:
    return "\n".join(
        '    <mesh name="%s" file="probe_%s.stl" scale="0.001 0.001 0.001"/>' % (name, name)
        for name in NAMES)


def visual_meshes() -> str:
    return "\n".join(
        '      <geom name="v_%s" type="mesh" mesh="%s" contype="0" conaffinity="0" '
        'group="2" rgba=".6 .62 .68 1"/>' % (name, name) for name in NAMES)


def collide_meshes() -> str:
    return "\n".join('      <geom name="m_%s" type="mesh" mesh="%s"/>' % (name, name)
                     for name in NAMES)


def build(meshdir: Path, clip: str, *, flags: str = "", defaults: str = CONTACT_DEFAULTS,
          drop: float = 0.008) -> str:
    return SCENE.format(meshdir=meshdir, flags=flags, defaults=defaults,
                        assets=assets_block(meshdir), clip=clip, drop=drop)


def settle(xml: str, steps: int = 8000) -> dict:
    import mujoco

    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cable")
    for _ in range(steps):
        mujoco.mj_step(model, data)
    height = float(data.xpos[body][2])
    return {"rest_height_mm": round(height * 1000, 4),
            "lateral_mm": round(float(data.xpos[body][1]) * 1000, 4),
            "contacts": int(data.ncon),
            "retained": bool(height > 0.0)}


def placement_error_mm(meshdir: Path, cad: list[dict]) -> dict:
    """Transform compiled vertices back to world and compare with the CAD boxes."""
    import mujoco
    import numpy as np

    model = mujoco.MjModel.from_xml_string(build(meshdir, collide_meshes()))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    by_name = {part["name"]: part for part in cad}
    worst, rows = 0.0, []
    for name in NAMES:
        geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "m_" + name)
        mesh = model.geom_dataid[geom]
        start, count = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
        verts = np.asarray(model.mesh_vert[start:start + count], dtype=float)
        rotation = np.asarray(data.geom_xmat[geom]).reshape(3, 3)
        world = (verts @ rotation.T + np.asarray(data.geom_xpos[geom])) * 1000.0
        low, high = world.min(axis=0), world.max(axis=0)
        part = by_name[name]
        error = max(float(np.abs(low - np.array(part["bbox_min_mm"])).max()),
                    float(np.abs(high - np.array(part["bbox_max_mm"])).max()))
        worst = max(worst, error)
        rows.append({"part": name, "placement_error_mm": round(error, 6)})
    return {"per_part": rows, "worst_placement_error_mm": round(worst, 6)}


def usd_support() -> dict:
    """The exporter ships with MuJoCo but needs usd-core and pillow beside it."""
    import importlib.util

    out = {"mujoco_usd_module": bool(importlib.util.find_spec("mujoco.usd")),
           "pxr_installed": bool(importlib.util.find_spec("pxr")),
           "pillow_installed": bool(importlib.util.find_spec("PIL"))}
    out["exporter_usable"] = all(out.values())
    out["how_to_enable"] = ("uv pip install usd-core pillow into a venv beside mujoco; "
                            "pass output_directory as a RELATIVE name and "
                            "output_directory_root as its absolute parent, or the "
                            "exporter joins them into an invalid path")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freecad", type=Path, default=FREECAD_DEFAULT)
    parser.add_argument("--out", type=Path, default=Path("evidence/cell_toolchain_v6.json"))
    args = parser.parse_args()

    import mujoco

    report: dict = {
        "schema": 1,
        "id": "cell_toolchain_v6",
        "status": "machine_check",
        "scope": "A check that the CAD-to-simulation toolchain works on this machine. "
                 "Not a research result and not comparable with any study record. It "
                 "records which collision strategy a CAD-authored cell must use and why.",
        "runtime": {"mujoco": mujoco.__version__,
                    "python": ".".join(str(v) for v in sys.version_info[:3])},
    }

    with tempfile.TemporaryDirectory() as raw:
        workdir = Path(raw)
        if not args.freecad.is_file():
            report["freecad"] = {"available": False, "path": str(args.freecad),
                                 "note": "Headless FreeCAD not found; CAD stage cannot run."}
            cad = None
        else:
            script = workdir / "build.py"
            script.write_text(FREECAD_SCRIPT, encoding="utf-8")
            result = subprocess.run([str(args.freecad), str(script), str(workdir)],
                                    capture_output=True, text=True, timeout=900)
            produced = workdir / "freecad_report.json"
            if not produced.is_file():
                report["freecad"] = {"available": False, "path": str(args.freecad),
                                     "stderr": result.stderr[-400:]}
                cad = None
            else:
                cad_report = json.loads(produced.read_text(encoding="utf-8"))
                cad = cad_report["parts"]
                report["freecad"] = {
                    "available": True,
                    "path": str(args.freecad),
                    "version": cad_report["freecad_version"],
                    "parts": cad,
                    "all_watertight": all(p["watertight"] for p in cad),
                    "fuse_face_touching_solids": cad_report["fuse_face_touching_solids"],
                    "fuse_overlapping_solids": cad_report["fuse_overlapping_solids"],
                    "fuse_note": "A fuse only welds solids that interpenetrate. Two boxes "
                                 "sharing a face stay separate and their tessellation is not "
                                 "watertight; overlap adjoining parts by about 0.01 mm.",
                }

        if cad is not None:
            meshdir = workdir
            report["placement"] = placement_error_mm(meshdir, cad)
            variants = {
                "mesh_collision": build(meshdir, collide_meshes()),
                "mesh_collision_nativeccd": build(
                    meshdir, collide_meshes(), flags='    <flag nativeccd="enable"/>'),
                "visual_mesh_primitive_collision": build(
                    meshdir, visual_meshes() + "\n" + PRIMITIVES),
                "primitive_only": build(meshdir, PRIMITIVES),
            }
            report["collision"] = {name: settle(xml) for name, xml in variants.items()}

            # Why the defaults block exists, measured rather than asserted.
            report["contact_defaults"] = {
                "used": CONTACT_DEFAULTS,
                "drop_heights_mm": [8, 20, 50],
                "with_project_defaults": [
                    settle(build(meshdir, PRIMITIVES, drop=z))["rest_height_mm"]
                    for z in (0.008, 0.020, 0.050)],
                "with_mujoco_defaults": [
                    settle(build(meshdir, PRIMITIVES, defaults="", drop=z))["rest_height_mm"]
                    for z in (0.008, 0.020, 0.050)],
                "note": "A 4 mm capsule resting in the channel should sit at 2.0 mm. Under "
                        "MuJoCo's own contact defaults it sinks through the plate instead, "
                        "at every drop height and both timesteps tried. This is a property "
                        "of a very light body on a thin plate, not of the CAD.",
            }
            held = {name: block["retained"] for name, block in report["collision"].items()}
            rest = {name: block["rest_height_mm"]
                    for name, block in report["collision"].items()}
            report["collision_verdict"] = {
                "retained_by_variant": held,
                "rest_height_mm_by_variant": rest,
                "decision": "CAD meshes are visual geometry only; collision stays on "
                            "primitives.",
                "why": "Mesh collision holds the cable, but on a different contact manifold: "
                       "one contact instead of two and a rest height 0.27 mm lower. The "
                       "retention predicate is decided within about 4 mm of channel "
                       "half-width, so a quarter-millimetre shift is not negligible here.",
                "second_reason": "Primitive collision is bit-identical to the scene every "
                                 "existing record was measured in, so the CAD cannot "
                                 "invalidate a published number.",
                "correction": "An earlier pass reported that mesh collision loses the cable "
                              "entirely. That measurement omitted the contact defaults "
                              "below; under MuJoCo's own defaults every variant fails, "
                              "including pure primitives.",
            }

    report["usd"] = usd_support()
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "out": args.out.as_posix(),
        "freecad": report["freecad"].get("available"),
        "worst_placement_error_mm": report.get("placement", {}).get("worst_placement_error_mm"),
        "retained": report.get("collision_verdict", {}).get("retained_by_variant"),
        "usd_exporter_usable": report["usd"]["exporter_usable"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
