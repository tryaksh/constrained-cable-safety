import math

import pytest

from assembly_recovery.cable_routes import clip_passages, plane_crossings, resample_polyline, route_length, slack_filter


def test_length_filter_rejects_arc_that_exceeds_remaining_cable():
    direct = [(0, 0, 0), (0.4, 0, 0)]
    repair = [(0, 0, 0), (0.2, 0, 0.3), (0.4, 0, 0)]
    report = slack_filter(rest_length_m=0.6, required_routes=[direct, repair], reserve_m=0.01)
    assert not report["passes_necessary_length_condition"]
    assert report["max_route_length_m"] == pytest.approx(2 * math.sqrt(0.13))
    assert not report["dynamic_recoverability_established"]


def test_sampling_does_not_invent_rest_length_at_a_corner():
    points = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
    sample = resample_polyline(points, 3)
    assert sample[0] == points[0] and sample[-1] == points[-1]
    assert route_length(sample) < route_length(points)


def test_clip_detects_segment_passage_without_vertex_inside_clip():
    result = clip_passages(
        [(-0.1, 0, 0.005), (0.1, 0, 0.005)],
        half_width_m=0.005,
        floor_height_m=0,
        lip_height_m=0.012,
        cable_radius_m=0.002,
    )
    assert result["has_retained_passage"]
    assert result["retained_passages"][0]["arclength_m"] == pytest.approx(0.1)


def test_physical_lift_clears_clip_predicate():
    result = clip_passages(
        [(-0.1, 0, 0.02), (0.1, 0, 0.02)],
        half_width_m=0.005,
        floor_height_m=0,
        lip_height_m=0.012,
        cable_radius_m=0.002,
    )
    assert not result["has_retained_passage"]


def test_corner_crossing_is_not_counted_twice():
    assert len(plane_crossings([(-1, 0, 0), (0, 0, 0), (1, 0, 0)])) == 1


def test_loop_is_reported_as_multiple_passages():
    result = clip_passages(
        [(-0.1, 0, 0.005), (0.1, 0, 0.005), (-0.1, 0, 0.006)],
        half_width_m=0.005,
        floor_height_m=0,
        lip_height_m=0.012,
        cable_radius_m=0.002,
    )
    assert result["ambiguous_multiple_passages"]


def test_coplanar_cable_is_not_assumed_retained():
    result = clip_passages(
        [(0, -0.1, 0.005), (0, 0.1, 0.005)],
        half_width_m=0.005,
        floor_height_m=0,
        lip_height_m=0.012,
        cable_radius_m=0.002,
    )
    assert not result["has_retained_passage"]
    assert result["all_crossings"][0]["kind"] == "coplanar"


@pytest.mark.parametrize("route", [[(0, 0, 0), (0, 0, 0)], [(0, 0, 0), (float("nan"), 0, 0)]])
def test_invalid_routes_fail_closed(route):
    with pytest.raises(ValueError):
        route_length(route)
