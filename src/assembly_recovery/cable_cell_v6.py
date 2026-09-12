"""The routing cell: one declared multi-clip jig, shared by the CAD, the screen and the block.

A cell is a piece of geometry, and three different things have to agree about it:
the FreeCAD script that draws it, the settling screen that decides whether a
cable can be installed in it, and the block that measures a supervisor routing
through it. If any of them carried its own copy of the numbers they would drift,
so all three read a cell out of a candidate file and turn it into fixture
overrides here.

Nothing in this module runs physics or decides anything. It is the one place that
knows how a declared cell becomes a scene, and it is deliberately parametric:
moving a clip is a config edit, never a code edit, because the workbench session
has to let an engineer move a clip and re-run.
"""

from __future__ import annotations

import math

#: Where the shallow post goes in a routing cell. Its registered position, along
#: 140 mm and across 12 mm, interpenetrates the wall of any clip near 140 mm.
#: Welded fixture geoms do not collide in MuJoCo, so that would have been
#: invisible in the physics and wrong in the picture.
POST_ALONG_M, POST_ACROSS_M = 0.060, 0.032

#: A clip raised by u wants its route waypoint at u + this, which puts the cable
#: 3.5 mm above that clip's own floor - exactly where the registered route puts
#: it above the registered clip floor.
ROUTE_CLEARANCE_M = 0.0025


def group_id(layout_id: str, loop_m: float) -> str:
    """The registered group name for one (cell, installed service loop).

    Tenths of a millimetre, because a routing cell is registered at loops half a
    millimetre apart and a coarser id would collide two groups into one.
    """
    return f"{layout_id}_l{int(round(loop_m*10000))}"


def cell_fixture_overrides(layout: dict, base: dict) -> dict:
    """Everything a declared cell changes about the registered fixture."""
    strain = {**base["fixture"]["strain_relief"], "across_m": layout["strain_relief_across_m"]}
    along, across, up = layout.get("slack_bow", [0.0, 1.0, 0.0])
    return {
        "clips": layout["clips"],
        "strain_relief": strain,
        "anchor_search_along_m": layout["anchor_search_along_m"],
        "slack_bow_leg": layout["slack_bow_leg"],
        "slack_bow_along": along, "slack_bow_across": across, "slack_bow_up": up,
        "post": {**base["fixture"]["post"],
                 "along_m": layout.get("post_along_m", POST_ALONG_M),
                 "across_m": layout.get("post_across_m", POST_ACROSS_M)},
    }


def cell_case(layout: dict, loop_m: float, candidates: dict, base: dict, **extra) -> dict:
    """One request against a declared cell, before any study-specific fields."""
    case = {
        "run_direction_xy": candidates["run_direction_xy"],
        "outward_xy": candidates["outward_xy"],
        "route_waypoints_along_across_m": layout["route_waypoints_along_across_m"],
        "fixture_overrides": cell_fixture_overrides(layout, base),
        "installed_loop_m": loop_m,
        "fixture_offset_m": [0.0, 0.0],
    }
    case.update(extra)
    return case


def clip_corners(clip: dict) -> dict:
    """One clip's solid dimensions in the fixture frame, in millimetres.

    The CAD draws exactly these: two walls, two lips, a pedestal under a raised
    clip, and the lead-in chamfer a real clip has. Millimetres, because FreeCAD
    works in millimetres and the scene works in metres, and the conversion
    happens once, here.
    """
    scale = 1000.0
    half_width = clip["half_width_m"]*scale
    wall = clip["wall_thickness_m"]*scale
    return {
        "id": clip["id"],
        "along_mm": clip["along_m"]*scale,
        "across_mm": clip["across_m"]*scale,
        "up_mm": clip["up_m"]*scale,
        "bearing_deg": math.degrees(clip["bearing_rad"]),
        "length_mm": clip["length_m"]*scale,
        "half_width_mm": half_width,
        "wall_mm": wall,
        "floor_mm": clip["floor_height_m"]*scale,
        "lip_height_mm": clip["lip_height_m"]*scale,
        "lip_gap_mm": clip["lip_gap_m"]*scale,
        "lip_thickness_mm": clip["lip_thickness_m"]*scale,
        "outer_half_width_mm": half_width+wall,
    }


def cad_parts(layout: dict, base: dict, anchor_along_m: float) -> list[dict]:
    """Every CAD part this cell needs, in fixture-frame millimetres.

    The board is drawn over the compiled shelf so the jig looks like one machined
    plate instead of five floating clips; the clips are drawn where the config
    puts them; the clamp sits over the strain relief and the socket surround over
    the port mounting plate. Every one of them is VISUAL: the collision primitives
    build_fixture already writes are what the cable actually touches, so the CAD
    cannot move a published number. See evidence/cell_toolchain_v6.json TRAP 4.
    """
    scale = 1000.0
    fixture = base["fixture"]
    shelf = fixture["shelf_half_m"]
    parts = [{
        "kind": "board",
        "centre_mm": [fixture["shelf_centre_along_m"]*scale,
                      fixture["shelf_centre_across_m"]*scale,
                      -shelf[2]*scale],
        "half_mm": [shelf[0]*scale, shelf[1]*scale, shelf[2]*scale],
        "rail_mm": 4.0, "chamfer_mm": 1.5,
    }]
    parts += [{"kind": "clip", **clip_corners(clip)} for clip in layout["clips"]]
    strain = fixture["strain_relief"]
    parts.append({
        "kind": "clamp",
        "along_mm": anchor_along_m*scale,
        "across_mm": layout["strain_relief_across_m"]*scale,
        "height_mm": strain["height_m"]*scale,
        "block_offset_mm": strain["block_offset_m"]*scale,
        "half_mm": [h*scale for h in strain["block_half_m"]],
    })
    parts.append({
        "kind": "socket",
        "along_mm": 0.0,
        "across_mm": 0.0,
        "plate_half_mm": [h*scale for h in fixture["plate_half_m"]],
        "drop_mm": fixture["shelf_drop_m"]*scale,
        "clearance_mm": fixture["plate_clearance_m"]*scale,
    })
    return parts
