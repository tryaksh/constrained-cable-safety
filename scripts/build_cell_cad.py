"""Author the v6 routing cell in FreeCAD and export it with provenance.

Run by the headless FreeCAD interpreter, never by the project venv:

    "C:/Users/tryak/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" \
        scripts/build_cell_cad.py

It reads the cell out of configs/cable_cell_v6_candidates.json, so moving a clip
is a config edit and never a code edit. Everything is authored in ASSEMBLY
coordinates - the fixture frame, in millimetres, with the shelf top at z = 0,
x along the run and y across it - because MuJoCo recentres every mesh on its own
centre of mass and rotates it to principal axes, and the geom frame compensates
exactly only if the mesh was exported in assembly coordinates (TRAP 2 of
evidence/cell_toolchain_v6.json).

Two rules from that record are load-bearing here. Solids that merely touch do not
fuse, so every adjoining part interpenetrates by 0.01 mm (TRAP 1). And a clip
needs a floor, so every clip carries its own base slab and a raised clip carries
a pedestal (TRAP 5).

What this produces is VISUAL geometry. The cable collides with the primitive
boxes and cylinders build_fixture already writes, not with these meshes, because
mesh collision holds the cable on a different contact manifold - one contact
instead of two, and a rest height 0.27 mm lower - and the retention predicate is
decided within about 4 mm (TRAP 4). The CAD makes the cell look like a real jig;
the primitives make it behave like the one that was measured.
"""

import hashlib
import json
import math
import os
import sys
from pathlib import Path

import FreeCAD as App  # noqa: N813
import Mesh  # noqa: F401 - importing it registers the mesh writers MeshPart needs
import MeshPart
import Part

# freecadcmd executes the file without binding __file__, so the repository root
# falls back to the working directory and can be overridden by CELL_ROOT.
try:
    _HERE = Path(__file__).resolve().parents[1]
except NameError:  # pragma: no cover - only under freecadcmd
    _HERE = Path.cwd()
ROOT = Path(os.environ.get("CELL_ROOT", _HERE))
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_cell_v6 import cad_parts  # noqa: E402

#: TRAP 1: a fuse only welds solids that interpenetrate.
OVERLAP = 0.01
#: Tessellation. 0.05 mm on a part whose smallest feature is a 2 mm lip.
LINEAR_DEFLECTION, ANGULAR_DEFLECTION = 0.05, 0.5


def content_sha256(path: Path) -> str:
    """Hash LF-normalised bytes, the discipline every other asset here carries.

    A CRLF working tree and the LF blob git stores hash differently, which is how
    an earlier block came to record a config hash no committed file reproduces.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def box(length, width, height, centre):
    """A box of the given full dimensions centred on ``centre``."""
    x, y, z = centre
    return Part.makeBox(length, width, height,
                        App.Vector(x - length / 2.0, y - width / 2.0, z - height / 2.0))


def fuse(shapes):
    solid = shapes[0]
    for shape in shapes[1:]:
        solid = solid.fuse(shape)
    return solid.removeSplitter()


def rotate_z(shape, degrees, pivot):
    if abs(degrees) < 1e-12:
        return shape
    matrix = App.Matrix()
    matrix.move(App.Vector(-pivot[0], -pivot[1], 0.0))
    turn = App.Matrix()
    turn.rotateZ(math.radians(degrees))
    matrix = turn.multiply(matrix)
    back = App.Matrix()
    back.move(App.Vector(pivot[0], pivot[1], 0.0))
    return shape.transformGeometry(back.multiply(matrix))


def fillet_vertical_ends(solid, radius, half_length, centre_x):
    """Round the four vertical edges at both channel mouths: a real lead-in.

    Selected geometrically rather than by index, because an index into a fused
    shape is not stable. If OCC refuses the blend the part is kept unfilleted and
    the record says so, rather than the script failing on cosmetics.
    """
    edges = []
    for index, edge in enumerate(solid.Edges, start=1):
        start, end = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        if abs(start.x - end.x) > 1e-6 or abs(start.y - end.y) > 1e-6:
            continue
        if abs(end.z - start.z) < 2 * radius:
            continue
        if abs(abs(start.x - centre_x) - half_length) > 1e-6:
            continue
        edges.append(index)
    if not edges:
        return solid, False
    try:
        return solid.makeFillet(radius, [solid.Edges[i - 1] for i in edges]), True
    except Exception:  # noqa: BLE001 - a cosmetic blend must never fail the build
        return solid, False


def build_board(part):
    """The backing board: the machined plate the whole cell is built on."""
    cx, cy, cz = part["centre_mm"]
    hx, hy, hz = part["half_mm"]
    plate = box(2 * hx, 2 * hy, 2 * hz, (cx, cy, cz))
    rail = part["rail_mm"]
    pieces = [plate]
    # A perimeter rail, so the board reads as a jig plate and not as a slab.
    for sign in (1, -1):
        pieces.append(box(2 * hx, rail, rail + OVERLAP,
                          (cx, cy + sign * (hy - rail / 2.0), cz + hz - rail / 2.0 + OVERLAP)))
        pieces.append(box(rail, 2 * hy, rail + OVERLAP,
                          (cx + sign * (hx - rail / 2.0), cy, cz + hz - rail / 2.0 + OVERLAP)))
    # Four feet, so it stands on something.
    for sx in (-1, 1):
        for sy in (-1, 1):
            foot = Part.makeCylinder(
                6.0, 6.0 + OVERLAP,
                App.Vector(cx + sx * (hx - 18.0), cy + sy * (hy - 18.0), cz - hz - 6.0))
            pieces.append(foot)
    return fuse(pieces)


def build_clip(part):
    """One routing clip: base, two walls, two lips, a pedestal if it is raised."""
    length, half_width = part["length_mm"], part["half_width_mm"]
    wall, lip_gap = part["wall_mm"], part["lip_gap_mm"]
    lip_height, lip_thickness = part["lip_height_mm"], part["lip_thickness_mm"]
    up, floor = part["up_mm"], part["floor_mm"]
    outer = part["outer_half_width_mm"]
    x, y = part["along_mm"], part["across_mm"]

    # TRAP 5: a clip needs a floor. The base slab is that floor, and for a raised
    # clip it is the pedestal as well; it reaches from inside the board up to
    # just above the channel floor datum.
    base_top = up + floor + 1.6
    base_bottom = -3.0
    pieces = [box(length, 2 * outer, base_top - base_bottom,
                  (x, y, 0.5 * (base_top + base_bottom)))]
    for sign in (1, -1):
        wall_bottom = base_top - OVERLAP
        wall_top = up + lip_height
        pieces.append(box(length, wall, wall_top - wall_bottom,
                          (x, y + sign * (half_width + wall / 2.0),
                           0.5 * (wall_top + wall_bottom))))
        lip_width = half_width - lip_gap / 2.0
        pieces.append(box(length, lip_width + OVERLAP, lip_thickness + OVERLAP,
                          (x, y + sign * (half_width + lip_gap / 2.0) / 2.0
                           - sign * OVERLAP / 2.0,
                           up + lip_height + lip_thickness / 2.0 - OVERLAP / 2.0)))
    solid = fuse(pieces)
    solid, filleted = fillet_vertical_ends(solid, 1.0, length / 2.0, x)
    return rotate_z(solid, part["bearing_deg"], (x, y)), filleted


def build_clamp(part):
    """The strain-relief clamp at the anchored end: a saddle with two bolt bosses."""
    hx, hy, hz = part["half_mm"]
    x = part["along_mm"] + part["block_offset_mm"]
    y, z = part["across_mm"], part["height_mm"]
    body = box(2 * hx, 2 * hy, 2 * hz, (x, y, z))
    groove = Part.makeCylinder(2.6, 2 * hx + 2.0,
                               App.Vector(x - hx - 1.0, y, z + hz),
                               App.Vector(1, 0, 0))
    solid = body.cut(groove)
    for sign in (1, -1):
        boss = Part.makeCylinder(3.0, 6.0,
                                 App.Vector(x, y + sign * (hy - 3.0), z + hz - OVERLAP))
        solid = solid.fuse(boss)
    return solid.removeSplitter()


def build_socket(part):
    """The connector-socket surround at the far end: bezel plate plus standoffs."""
    hx, hy, hz = part["plate_half_mm"]
    top = part["drop_mm"] - part["clearance_mm"]
    plate = box(2 * hx, 2 * hy, 2 * hz, (0.0, 0.0, top - hz))
    aperture = box(24.0, 18.0, 2 * hz + 2.0, (0.0, 0.0, top - hz))
    solid = plate.cut(aperture)
    for sign in (1, -1):
        standoff = Part.makeCylinder(2.5, 5.5 + OVERLAP,
                                     App.Vector(0.0, sign * 18.3, top - OVERLAP))
        solid = solid.fuse(standoff)
    return solid.removeSplitter()


BUILDERS = {"board": build_board, "clip": build_clip, "clamp": build_clamp,
            "socket": build_socket}


def main() -> int:
    candidates = json.loads((ROOT / "configs/cable_cell_v6_candidates.json")
                            .read_text(encoding="utf-8-sig"))
    base = json.loads((ROOT / "configs/cable_recovery_task_v2.json")
                      .read_text(encoding="utf-8-sig"))
    screen = json.loads((ROOT / "evidence/cable_cell_screen_v6.json")
                        .read_text(encoding="utf-8"))
    cell_id = screen.get("registered_cell", "RC1")
    layout = next(entry for entry in candidates["layouts"] if entry["id"] == cell_id)
    accepted = [a for a in screen["accepted_cell_detail"] if a["layout"] == cell_id]
    if not accepted:
        raise SystemExit(f"The screen accepted no cell for {cell_id}")
    # The clamp is drawn at the anchor the MIDDLE accepted service loop solves to;
    # across the accepted loops that position moves by under 3.5 mm.
    anchor = sorted(a["solved_anchor_along_m"] for a in accepted)[len(accepted) // 2]
    anchor_span = (max(a["solved_anchor_along_m"] for a in accepted)
                   - min(a["solved_anchor_along_m"] for a in accepted))

    out = ROOT / "assets/cell_v6"
    out.mkdir(parents=True, exist_ok=True)
    document = App.newDocument("cell_v6")
    records = []
    for part in cad_parts(layout, base, anchor):
        name = part["id"] if part["kind"] == "clip" else part["kind"]
        built = BUILDERS[part["kind"]](part)
        solid, filleted = built if isinstance(built, tuple) else (built, None)
        obj = document.addObject("Part::Feature", name)
        obj.Shape = solid
        mesh = MeshPart.meshFromShape(Shape=solid, LinearDeflection=LINEAR_DEFLECTION,
                                      AngularDeflection=ANGULAR_DEFLECTION, Relative=False)
        path = out / f"cell_v6_{name}.stl"
        mesh.write(str(path))
        bound = solid.BoundBox
        records.append({
            "part": name, "kind": part["kind"],
            "file": path.relative_to(ROOT).as_posix(),
            "facets": int(mesh.CountFacets),
            "points": int(mesh.CountPoints),
            "watertight": bool(mesh.isSolid()),
            "self_intersecting": bool(mesh.hasSelfIntersections()),
            "solids_after_fuse": len(solid.Solids),
            "volume_mm3": round(float(solid.Volume), 3),
            "bbox_min_mm": [round(bound.XMin, 4), round(bound.YMin, 4), round(bound.ZMin, 4)],
            "bbox_max_mm": [round(bound.XMax, 4), round(bound.YMax, 4), round(bound.ZMax, 4)],
            "lead_in_filleted": filleted,
            "content_sha256": content_sha256(path),
        })
        print(json.dumps(records[-1]), flush=True)

    source = out / "cell_v6.FCStd"
    document.recompute()
    document.saveAs(str(source))
    report = {
        "schema": 1, "id": "cable_cell_cad_v6", "status": "authored_cad_asset",
        "created_on": candidates["created_on"],
        "scope": "Provenance for the CAD-authored v6 routing cell. Geometry only: these meshes "
                 "are VISUAL geoms in the compiled scene and collide with nothing. Not a study "
                 "result and not a hardware claim.",
        "freecad_version": ".".join(App.Version()[:3]),
        "freecad_build": App.Version(),
        "authored_from": {
            "candidates": "configs/cable_cell_v6_candidates.json",
            "cell": cell_id,
            "base_config": "configs/cable_recovery_task_v2.json",
            "screen": "evidence/cable_cell_screen_v6.json",
            "clamp_anchor_along_m": anchor,
            "clamp_anchor_span_over_accepted_loops_m": round(anchor_span, 6),
        },
        "frame": "Assembly coordinates: the fixture frame in millimetres, shelf top at z = 0, "
                 "x along the run direction, y across it. Exported this way on purpose - MuJoCo "
                 "recentres every mesh on its centre of mass and the geom frame compensates "
                 "exactly only for a mesh authored in assembly coordinates.",
        "collision": "None. Every mesh enters the scene with contype=0 conaffinity=0 group=2. "
                     "The cable collides with the primitive boxes and cylinders build_fixture "
                     "writes, which is bit-identical to the scene every published number was "
                     "measured in, so the CAD cannot invalidate one.",
        "tessellation": {"linear_deflection_mm": LINEAR_DEFLECTION,
                         "angular_deflection_rad": ANGULAR_DEFLECTION, "relative": False},
        "overlap_mm": OVERLAP,
        "source_document": {"file": source.relative_to(ROOT).as_posix(),
                            "content_sha256": content_sha256(source)},
        "parts": records,
        "all_watertight": all(r["watertight"] for r in records),
        "all_single_solid": all(r["solids_after_fuse"] == 1 for r in records),
        "total_facets": sum(r["facets"] for r in records),
    }
    target = ROOT / "evidence/cable_cell_cad_v6.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"parts": len(records), "all_watertight": report["all_watertight"],
                      "all_single_solid": report["all_single_solid"],
                      "total_facets": report["total_facets"],
                      "out": target.relative_to(ROOT).as_posix()}, indent=1))
    return 0


# freecadcmd executes this file under a module name of its own, so the usual
# __main__ guard never fires and the script would exit silently having done
# nothing. Call it directly; this file is only ever run by freecadcmd.
main()
