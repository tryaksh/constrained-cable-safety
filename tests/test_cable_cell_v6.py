"""CPU tests for the multi-clip routing cell: clip lists, route heights, retention.

These cover construction and predicate bookkeeping only. They compile no
simulator scene, run no physics and establish nothing about whether a route
settles or a clip is kept during a motion.
"""

from __future__ import annotations

import math
import types

import numpy as np
import pytest

from assembly_recovery.cable_constrained_v2 import clip_list, clip_state, route_point

REGISTERED_CLIP = {
    "along_m": 0.17, "across_m": 0.0, "length_m": 0.03, "half_width_m": 0.006,
    "floor_height_m": -0.001, "lip_height_m": 0.0125, "lip_gap_m": 0.005,
    "lip_thickness_m": 0.002, "wall_thickness_m": 0.003, "friction": [0.5, 0.005, 0.0001],
}


def fixture_frame():
    """The identity fixture frame: along -> x, across -> y, up -> z."""
    return lambda along, across, up: np.array([along, across, up], dtype=float)


def scene_with(clips, points):
    """A stand-in scene carrying only what ``clip_state`` reads."""
    return types.SimpleNamespace(
        clips=clips,
        clip_origin=np.asarray(clips[0]["origin_world"], dtype=float),
        clip_rotation=np.asarray(clips[0]["rotation_world"], dtype=float),
        clip_predicate=clips[0]["predicate"],
        _points=np.asarray(points, dtype=float),
    )


def compiled_clip(clip_id, origin, *, required=True, index=0):
    return {"id": clip_id, "index": index, "required": required,
            "origin_world": list(origin), "rotation_world": np.eye(3).tolist(),
            "predicate": {"half_width_m": 0.006, "floor_height_m": -0.001,
                          "lip_height_m": 0.0125, "cable_radius_m": 0.002}}


# -- the single-clip config keeps compiling exactly as it did -------------------

def test_a_registered_single_clip_config_reads_as_a_one_element_list():
    clips = clip_list({"clip": REGISTERED_CLIP})
    assert len(clips) == 1
    assert clips[0]["id"] == "clip" and clips[0]["required"] is True
    assert clips[0]["up_m"] == 0.0 and clips[0]["bearing_rad"] == 0.0
    # every registered dimension survives untouched
    for key, value in REGISTERED_CLIP.items():
        assert clips[0][key] == value


def test_clip_list_does_not_mutate_the_config_it_was_given():
    fixture_cfg = {"clip": dict(REGISTERED_CLIP)}
    clip_list(fixture_cfg)
    assert fixture_cfg["clip"] == REGISTERED_CLIP


def test_later_clips_inherit_every_key_the_first_one_declares():
    clips = clip_list({"clip": REGISTERED_CLIP,
                       "clips": [{"along_m": 0.09}, {"along_m": 0.15, "up_m": 0.004}]})
    assert [c["along_m"] for c in clips] == [0.09, 0.15]
    assert [c["half_width_m"] for c in clips] == [0.006, 0.006]
    assert [c["id"] for c in clips] == ["clip", "clip2"]
    assert clips[1]["up_m"] == 0.004 and clips[0]["up_m"] == 0.0


def test_a_clip_may_be_declared_not_required():
    clips = clip_list({"clip": REGISTERED_CLIP,
                       "clips": [{"along_m": 0.09}, {"along_m": 0.15, "required": False}]})
    assert [c["required"] for c in clips] == [True, False]


def test_an_empty_clip_list_is_refused():
    with pytest.raises(ValueError, match="at least one clip"):
        clip_list({"clip": REGISTERED_CLIP, "clips": []})


# -- route waypoints may carry their own height --------------------------------

def test_a_two_element_waypoint_keeps_the_registered_route_height():
    assert route_point(fixture_frame(), [0.09, 0.0], 0.0025).tolist() == [0.09, 0.0, 0.0025]


def test_a_three_element_waypoint_overrides_the_route_height():
    assert route_point(fixture_frame(), [0.09, 0.0, 0.0065], 0.0025).tolist() == [0.09, 0.0, 0.0065]


def test_a_waypoint_of_any_other_length_is_refused():
    with pytest.raises(ValueError, match="along, across"):
        route_point(fixture_frame(), [0.09], 0.0025)


# -- clip_state: the first clip is unchanged, the rest are added ---------------

def straight_cable(across=0.0, up=0.0025):
    """A centreline running along x through every clip in the test cell."""
    return [[x, across, up] for x in np.linspace(0.0, 0.30, 31)]


def test_clip_state_on_a_single_clip_scene_is_exactly_the_old_predicate():
    clips = [compiled_clip("clip", [0.17, 0.0, 0.0])]
    scene = scene_with(clips, straight_cable())
    state = clip_state(scene, scene._points)
    assert state["has_retained_passage"] is True
    assert state["summary"]["required_count"] == 1
    # the legacy keys are still the first clip's own passage
    assert len(state["retained_passages"]) == 1


def test_clip_state_reports_every_clip_and_summarises_the_route():
    clips = [compiled_clip("c1", [0.09, 0.0, 0.0], index=0),
             compiled_clip("c2", [0.15, 0.0, 0.0], index=1),
             compiled_clip("c3", [0.21, 0.0, 0.0], index=2)]
    points = straight_cable()
    state = clip_state(scene_with(clips, points), points)
    assert [c["id"] for c in state["per_clip"]] == ["c1", "c2", "c3"]
    assert state["summary"]["all_required_retained"] is True
    assert state["summary"]["required_retained"] == 3
    assert state["summary"]["lost_required_ids"] == []


def test_a_cable_lifted_out_of_one_clip_loses_only_that_clip():
    clips = [compiled_clip("c1", [0.09, 0.0, 0.0], index=0),
             compiled_clip("c2", [0.15, 0.0, 0.0], index=1),
             compiled_clip("c3", [0.21, 0.0, 0.0], index=2)]
    # a cable that rises above the c2 lip exactly where c2 sits
    points = [[x, 0.0, 0.0025 + (0.02 if abs(x - 0.15) < 0.012 else 0.0)]
              for x in np.linspace(0.0, 0.30, 61)]
    state = clip_state(scene_with(clips, points), points)
    summary = state["summary"]
    assert summary["lost_required_ids"] == ["c2"]
    assert summary["required_retained"] == 2
    assert summary["all_required_retained"] is False


def test_an_optional_clip_does_not_decide_the_route_summary():
    clips = [compiled_clip("c1", [0.09, 0.0, 0.0], index=0),
             compiled_clip("c2", [0.15, 0.0, 0.0], index=1, required=False)]
    points = [[x, 0.0, 0.0025 + (0.02 if abs(x - 0.15) < 0.012 else 0.0)]
              for x in np.linspace(0.0, 0.30, 61)]
    state = clip_state(scene_with(clips, points), points)
    assert state["summary"]["all_required_retained"] is True
    assert state["per_clip"][1]["has_retained_passage"] is False


def test_a_raised_clip_judges_the_cable_in_its_own_frame():
    # the same cable, at the height a clip raised 8 mm expects
    clips = [compiled_clip("c1", [0.15, 0.0, 0.008])]
    good = [[x, 0.0, 0.0105] for x in np.linspace(0.0, 0.30, 31)]
    assert clip_state(scene_with(clips, good), good)["summary"]["all_required_retained"] is True
    low = [[x, 0.0, 0.0025] for x in np.linspace(0.0, 0.30, 31)]
    assert clip_state(scene_with(clips, low), low)["summary"]["all_required_retained"] is False


def test_a_rotated_clip_judges_the_cable_along_its_own_bearing():
    bearing = math.radians(45.0)
    rotation = np.array([[math.cos(bearing), -math.sin(bearing), 0.0],
                         [math.sin(bearing), math.cos(bearing), 0.0],
                         [0.0, 0.0, 1.0]])
    clip = compiled_clip("c1", [0.15, 0.0, 0.0])
    clip["rotation_world"] = rotation.tolist()
    # a cable running along the clip bearing passes; one running across it does not
    along = [[0.15 + t * math.cos(bearing), t * math.sin(bearing), 0.0025]
             for t in np.linspace(-0.1, 0.1, 41)]
    assert clip_state(scene_with([clip], along), along)["summary"]["all_required_retained"] is True
    offset = [[0.15 + t * math.cos(bearing) + 0.02, t * math.sin(bearing), 0.0025]
              for t in np.linspace(-0.1, 0.1, 41)]
    state = clip_state(scene_with([clip], offset), offset)
    assert state["summary"]["all_required_retained"] is False
