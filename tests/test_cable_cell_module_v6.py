"""CPU tests for the one place a declared routing cell becomes a scene.

The CAD script, the settling screen and the routing block all read a cell through
this module, so if it drifts they drift apart silently. These tests compile no
scene and run no physics.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from assembly_recovery.cable_cell_v6 import (
    POST_ACROSS_M,
    POST_ALONG_M,
    cad_mesh_entries,
    cad_parts,
    cell_case,
    cell_fixture_overrides,
    clip_corners,
    group_id,
)

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = json.loads((ROOT / "configs/cable_cell_v6_candidates.json")
                        .read_text(encoding="utf-8-sig"))
BASE = json.loads((ROOT / "configs/cable_recovery_task_v2.json").read_text(encoding="utf-8-sig"))
RC1 = next(entry for entry in CANDIDATES["layouts"] if entry["id"] == "RC1")


def test_group_ids_resolve_loops_half_a_millimetre_apart():
    assert group_id("RC1", 0.0015) == "RC1_l15"
    assert group_id("RC1", 0.002) == "RC1_l20"
    # the collision a coarser id would have caused
    assert group_id("RC1", 0.0015) != group_id("RC1", 0.0025)


def test_the_registered_cell_declares_five_clips_at_three_heights_and_four_bearings():
    clips = RC1["clips"]
    assert len(clips) == 5
    assert len({c["up_m"] for c in clips}) == 3
    assert len({round(c["bearing_rad"], 6) for c in clips}) == 4


def test_every_clip_keeps_the_registered_cross_section():
    """The predicate reads these four numbers. Change one and every retention
    number this repository has published stops being comparable."""
    registered = BASE["fixture"]["clip"]
    for clip in RC1["clips"]:
        for key in ("half_width_m", "floor_height_m", "lip_height_m", "lip_gap_m"):
            assert clip[key] == registered[key], key


def test_the_clip_channel_can_still_contain_the_cable():
    from assembly_recovery.cable_routes import clip_passages

    radius = BASE["cable"]["radius_m"]
    for clip in RC1["clips"]:
        # clip_passages refuses dimensions that cannot contain the cable; a route
        # of four points well inside the channel must simply be accepted
        points = [[x, 0.0, clip["floor_height_m"] + radius + 0.001]
                  for x in (-0.02, -0.01, 0.01, 0.02)]
        state = clip_passages(points, half_width_m=clip["half_width_m"],
                              floor_height_m=clip["floor_height_m"],
                              lip_height_m=clip["lip_height_m"], cable_radius_m=radius)
        assert state["has_retained_passage"]


def test_a_route_waypoint_sits_where_its_clip_expects_the_cable():
    for clip, waypoint in zip(RC1["clips"], RC1["route_waypoints_along_across_m"], strict=True):
        assert waypoint[0] == pytest.approx(clip["along_m"])
        assert waypoint[1] == pytest.approx(clip["across_m"])
        # 2.5 mm above that clip's own origin, which is 3.5 mm above its floor
        assert waypoint[2] == pytest.approx(clip["up_m"] + 0.0025)


def test_fixture_overrides_move_the_post_clear_of_the_clip_line():
    overrides = cell_fixture_overrides(RC1, BASE)
    assert overrides["post"]["along_m"] == POST_ALONG_M
    assert overrides["post"]["across_m"] == POST_ACROSS_M
    # the registered post position would interpenetrate a clip wall
    outer = max(c["half_width_m"] + c["wall_thickness_m"] for c in RC1["clips"])
    assert abs(overrides["post"]["across_m"]) > outer + overrides["post"]["radius_m"]


def test_fixture_overrides_carry_the_declared_bow_leg_and_direction():
    overrides = cell_fixture_overrides(RC1, BASE)
    assert overrides["slack_bow_leg"] == RC1["slack_bow_leg"]
    assert [overrides["slack_bow_along"], overrides["slack_bow_across"],
            overrides["slack_bow_up"]] == RC1["slack_bow"]


def test_no_cad_is_attached_unless_a_cad_record_is_given():
    assert "cad_meshes" not in cell_fixture_overrides(RC1, BASE)
    cad = {"parts": [{"part": "board", "kind": "board", "file": "assets/cell_v6/b.stl",
                      "content_sha256": "abc"}]}
    overrides = cell_fixture_overrides(RC1, BASE, cad)
    assert overrides["cad_meshes"] == [{"name": "board", "file": "assets/cell_v6/b.stl",
                                        "content_sha256": "abc", "rgba": ".58 .60 .65 1"}]


def test_every_cad_mesh_entry_carries_the_hash_it_was_exported_with():
    record = json.loads((ROOT / "evidence/cable_cell_cad_v6.json").read_text(encoding="utf-8"))
    entries = cad_mesh_entries(record)
    assert len(entries) == len(record["parts"])
    assert all(len(e["content_sha256"]) == 64 for e in entries)


def test_a_case_carries_the_cell_and_whatever_the_study_adds():
    case = cell_case(RC1, 0.003, CANDIDATES, BASE, None, id="x", supervisor="filtered")
    assert case["installed_loop_m"] == 0.003
    assert case["id"] == "x" and case["supervisor"] == "filtered"
    assert case["run_direction_xy"] == CANDIDATES["run_direction_xy"]
    assert case["fixture_overrides"]["clips"] == RC1["clips"]


def test_clip_corners_convert_metres_to_millimetres_once():
    corners = clip_corners(RC1["clips"][2])
    assert corners["along_mm"] == pytest.approx(RC1["clips"][2]["along_m"] * 1000.0)
    assert corners["up_mm"] == pytest.approx(RC1["clips"][2]["up_m"] * 1000.0)
    assert corners["bearing_deg"] == pytest.approx(math.degrees(RC1["clips"][2]["bearing_rad"]))
    assert corners["outer_half_width_mm"] == pytest.approx(
        (RC1["clips"][2]["half_width_m"] + RC1["clips"][2]["wall_thickness_m"]) * 1000.0)


def test_cad_parts_cover_the_whole_cell():
    parts = cad_parts(RC1, BASE, 0.2374)
    kinds = [p["kind"] for p in parts]
    assert kinds.count("clip") == len(RC1["clips"])
    assert kinds.count("board") == 1 and kinds.count("clamp") == 1 and kinds.count("socket") == 1
    board = parts[0]
    assert board["half_mm"] == [h * 1000.0 for h in BASE["fixture"]["shelf_half_m"]]
    clamp = next(p for p in parts if p["kind"] == "clamp")
    assert clamp["across_mm"] == pytest.approx(RC1["strain_relief_across_m"] * 1000.0)


def test_the_cad_on_disk_was_authored_for_the_cell_the_screen_registered():
    cad = json.loads((ROOT / "evidence/cable_cell_cad_v6.json").read_text(encoding="utf-8"))
    screen = json.loads((ROOT / "evidence/cable_cell_screen_v6.json").read_text(encoding="utf-8"))
    assert cad["authored_from"]["cell"] == screen["registered_cell"]
    assert cad["all_watertight"] and cad["all_single_solid"]


def test_the_frozen_contract_points_at_the_registered_cell_and_its_hashes():
    contract = json.loads((ROOT / "configs/cable_routing_v6.json").read_text(encoding="utf-8-sig"))
    cad = json.loads((ROOT / "evidence/cable_cell_cad_v6.json").read_text(encoding="utf-8"))
    assert contract["status"] == "frozen_study_contract"
    assert contract["cell"]["registered_cell"] == "RC1"
    assert contract["cell"]["asset_sha256"] == {p["part"]: p["content_sha256"]
                                                for p in cad["parts"]}
    assert contract["decision_rule"]["margin"] == 0.05


def test_the_frozen_size_resolves_the_margin_at_every_error_level():
    contract = json.loads((ROOT / "configs/cable_routing_v6.json").read_text(encoding="utf-8-sig"))
    margin = contract["decision_rule"]["margin"]
    for level, size in contract["frozen_counts"]["routes_per_cell_by_error_level"].items():
        assert 1 / size <= margin / 2, level
