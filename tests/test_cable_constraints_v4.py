"""CPU tests for the three-constraint scorer and its censoring rules.

They run no physics. What they check is the part that decides what a request
means: that a bend radius is measured the way a circle says it is, that a
discretisation's own resolution limit is reported beside the spec, and that a
request cut short by the force abort is censored rather than counted as a
success.
"""

from __future__ import annotations

import math

import numpy as np

from assembly_recovery.cable_constraints_v4 import (
    CENSORED,
    CONSTRAINTS,
    RESPECTED,
    VIOLATED,
    ConstraintScorer,
    discrete_bend_radius,
    min_bend_radius,
    representable_radius_m,
)


def arc(radius_m: float, segment_m: float, count: int = 9) -> np.ndarray:
    """A polyline whose nodes lie on a circle of the given radius."""
    step = 2*math.asin(min(1.0, 0.5*segment_m/radius_m))
    angles = np.arange(count)*step
    return np.stack([radius_m*np.cos(angles), radius_m*np.sin(angles), np.zeros(count)], axis=1)


def test_bend_radius_of_a_circle_is_its_radius():
    for radius in (0.02, 0.05, 0.1):
        measured = min_bend_radius(arc(radius, 0.01))
        assert math.isclose(measured, radius, rel_tol=1e-9)


def test_a_straight_polyline_has_infinite_bend_radius():
    line = np.stack([np.linspace(0, 0.5, 26), np.zeros(26), np.zeros(26)], axis=1)
    assert not np.isfinite(min_bend_radius(line))
    assert discrete_bend_radius(line).shape == (24,)


def test_min_bend_radius_finds_the_tightest_corner():
    line = np.concatenate([arc(0.08, 0.01, 5), arc(0.02, 0.01, 5)+[0.3, 0.0, 0.0]])
    assert min_bend_radius(line) < 0.021


def test_representable_radius_states_the_discretisations_own_limit():
    # 20 mm segments at the 70 degree construction cap cannot express a radius
    # tighter than this, so a spec below it is a statement about a polyline.
    coarse = representable_radius_m(0.02, 70.0)
    fine = representable_radius_m(0.005, 70.0)
    assert math.isclose(coarse, 0.02/(2*math.sin(math.radians(35.0))), rel_tol=1e-12)
    assert fine < coarse
    assert coarse < 0.024, "the 24 mm primary spec must be resolvable at 20 mm segments"


def scorer() -> ConstraintScorer:
    return ConstraintScorer(bend_radius_spec_m=0.024, anchor_limit_n=0.3,
                            bend_radius_secondary_m=0.016, anchor_secondary_n=1.0)


def test_a_clean_completed_move_respects_all_three():
    s = scorer()
    line = arc(0.05, 0.02)
    for k in range(10):
        s.update(line, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.001*k)
    labels = s.labels(move_completed=True, terminal_clip_retained=True)
    assert {labels[name]["state"] for name in CONSTRAINTS} == {RESPECTED}
    assert s.report()["representable_radius_m"] < 0.024


def test_each_constraint_is_violated_by_its_own_channel_only():
    tight, loose = arc(0.02, 0.02), arc(0.05, 0.02)
    bend = scorer()
    bend.update(tight, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.01)
    labels = bend.labels(move_completed=True, terminal_clip_retained=True)
    assert labels["C2_bend"]["state"] == VIOLATED
    assert labels["C1_clip"]["state"] == RESPECTED
    assert labels["C3_anchor"]["state"] == RESPECTED

    anchor = scorer()
    anchor.update(loose, anchor_reaction_n=0.9, clip_retained=True, progress_m=0.01)
    labels = anchor.labels(move_completed=True, terminal_clip_retained=True)
    assert labels["C3_anchor"]["state"] == VIOLATED
    assert labels["C2_bend"]["state"] == RESPECTED

    clip = scorer()
    clip.update(loose, anchor_reaction_n=0.05, clip_retained=False, progress_m=0.01)
    labels = clip.labels(move_completed=False, terminal_clip_retained=False)
    assert labels["C1_clip"]["state"] == VIOLATED
    # A move cut short still censors the constraints that had not gone.
    assert labels["C2_bend"]["state"] == CENSORED


def test_an_aborted_move_censors_what_it_never_tested():
    s = scorer()
    line = arc(0.05, 0.02)
    for k in range(5):
        s.update(line, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.002*k)
    labels = s.labels(move_completed=False, terminal_clip_retained=True)
    for name in CONSTRAINTS:
        assert labels[name]["state"] == CENSORED
        assert labels[name]["censoring_progress_m"] is not None
        assert labels[name]["violation_progress_m"] is None


def test_violation_progress_records_where_the_constraint_first_went():
    s = scorer()
    loose, tight = arc(0.05, 0.02), arc(0.02, 0.02)
    s.update(loose, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.000)
    s.update(loose, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.004)
    s.update(tight, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.008)
    s.update(tight, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.012)
    labels = s.labels(move_completed=True, terminal_clip_retained=True)
    assert labels["C2_bend"]["state"] == VIOLATED
    assert math.isclose(labels["C2_bend"]["violation_progress_m"], 0.008, rel_tol=1e-12)


def test_a_terminal_clip_loss_counts_even_if_no_tick_saw_it():
    s = scorer()
    line = arc(0.05, 0.02)
    s.update(line, anchor_reaction_n=0.05, clip_retained=True, progress_m=0.01)
    labels = s.labels(move_completed=True, terminal_clip_retained=False)
    assert labels["C1_clip"]["state"] == VIOLATED


def test_report_carries_the_secondary_severities():
    s = scorer()
    s.update(arc(0.012, 0.005), anchor_reaction_n=1.4, clip_retained=True, progress_m=0.01)
    report = s.report()
    assert report["min_bend_radius_below_secondary"] is True
    assert report["peak_anchor_above_secondary"] is True
    assert report["peak_anchor_reaction_n"] == 1.4
