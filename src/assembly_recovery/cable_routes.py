"""Geometry checks for a physically constrained cable route, independent of physics.

These are necessary feasibility/measurement helpers. They cannot certify dynamic
recoverability, clip retention, material calibration, or robot reachability.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float, float]


def checked_points(points: Sequence[Sequence[float]]) -> list[Point]:
    result = [tuple(float(x) for x in p) for p in points]
    if len(result) < 2 or any(len(p) != 3 or not all(math.isfinite(x) for x in p) for p in result):
        raise ValueError("A route needs at least two finite 3-D points")
    if any(math.dist(a, b) <= 1e-12 for a, b in zip(result, result[1:], strict=False)):
        raise ValueError("Consecutive route vertices must differ")
    return result


def route_length(points: Sequence[Sequence[float]]) -> float:
    route = checked_points(points)
    return sum(math.dist(a, b) for a, b in zip(route, route[1:], strict=False))


def resample_polyline(points: Sequence[Sequence[float]], segments: int) -> list[Point]:
    """Sample equal arclengths, retaining endpoints; chords can shorten corners.

    Always report/check the resulting chord length as well as original length.
    Do not silently infer model rest length from the source polyline arclength.
    """
    route = checked_points(points)
    if type(segments) is not int or segments < 1:
        raise ValueError("segments must be a positive integer")
    lengths = [math.dist(a, b) for a, b in zip(route, route[1:], strict=False)]
    total = sum(lengths)
    result = []
    j = 0
    before = 0.0
    for i in range(segments + 1):
        target = total * i / segments
        while j < len(lengths) - 1 and target > before + lengths[j]:
            before += lengths[j]
            j += 1
        u = min(1.0, max(0.0, (target - before) / lengths[j]))
        result.append(tuple(a + (b - a) * u for a, b in zip(route[j], route[j + 1], strict=True)))
    result[0] = route[0]
    result[-1] = route[-1]
    return result


def plane_crossings(points: Sequence[Sequence[float]], *, axis: int = 0, value: float = 0.0) -> list[dict]:
    """Find centerline crossings of a clip-local plane, including vertex hits.

    Coplanar spans are reported explicitly and do not automatically count as a
    retained passage. Each record carries cable arclength to distinguish loops.
    """
    route = checked_points(points)
    if axis not in (0, 1, 2) or not math.isfinite(value):
        raise ValueError("Invalid clip plane")
    result = []
    before = 0.0
    for i, (a, b) in enumerate(zip(route, route[1:], strict=False)):
        length = math.dist(a, b)
        da = a[axis] - value
        db = b[axis] - value
        if abs(da) < 1e-12 and abs(db) < 1e-12:
            result.append({"segment": i, "kind": "coplanar", "arclength_m": before, "point": list(a)})
        elif da * db <= 0:
            u = -da / (db - da)
            point = [x + (y - x) * u for x, y in zip(a, b, strict=True)]
            arc = before + u * length
            if not result or abs(result[-1]["arclength_m"] - arc) > 1e-10:
                result.append({"segment": i, "kind": "crossing", "arclength_m": arc, "point": point})
        before += length
    return result


def clip_passages(
    points_local: Sequence[Sequence[float]],
    *,
    half_width_m: float,
    floor_height_m: float,
    lip_height_m: float,
    cable_radius_m: float,
) -> dict:
    """Measure centerline passages through an open clip cross-section.

    Dimensions describe actual compiled geometry in the clip frame. This is a
    geometric passage predicate; independent physical release/retention controls
    are required before it may define a job endpoint.
    """
    dims = (half_width_m, floor_height_m, lip_height_m, cable_radius_m)
    if (
        not all(math.isfinite(v) for v in dims)
        or cable_radius_m <= 0
        or half_width_m <= cable_radius_m
        or lip_height_m <= floor_height_m + 2 * cable_radius_m
    ):
        raise ValueError("Clip cannot contain the cable at these dimensions")
    crossings = plane_crossings(points_local)
    retained = [
        c
        for c in crossings
        if c["kind"] == "crossing"
        and abs(c["point"][1]) <= half_width_m - cable_radius_m
        and floor_height_m + cable_radius_m <= c["point"][2] <= lip_height_m - cable_radius_m
    ]
    return {
        "retained_passages": retained,
        "all_crossings": crossings,
        "has_retained_passage": bool(retained),
        "ambiguous_multiple_passages": len(retained) > 1,
    }


def slack_filter(
    *, rest_length_m: float, required_routes: Sequence[Sequence[Sequence[float]]], reserve_m: float
) -> dict:
    """Reject impossible lengths; a pass is only a necessary geometric condition."""
    if (
        not math.isfinite(rest_length_m)
        or not math.isfinite(reserve_m)
        or rest_length_m <= 0
        or reserve_m <= 0
        or not required_routes
    ):
        raise ValueError("Positive finite length/reserve and candidate routes required")
    lengths = [route_length(r) for r in required_routes]
    longest = max(lengths)
    return {
        "rest_length_m": rest_length_m,
        "route_lengths_m": lengths,
        "max_route_length_m": longest,
        "reserve_m": reserve_m,
        "remaining_length_m": rest_length_m - longest,
        "passes_necessary_length_condition": longest + reserve_m <= rest_length_m,
        "dynamic_recoverability_established": False,
    }
