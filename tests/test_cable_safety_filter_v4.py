"""CPU tests for the shipped safety layer and its envelope.

The filter is the part of this project something other than the study might
actually call, so it is tested as an interface: that it refuses what it cannot
judge instead of quietly approving it, that its margin moves the right way with
the declared error, that the envelope it reports is the region its own rule
allows, and that abstention is a real answer rather than a crash.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from assembly_recovery.cable_safety_filter_v4 import ConstraintRule, SafetyFilter
from assembly_recovery.cable_study_v4 import level_by_id

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "configs/cable_perception_v4.json").read_text(encoding="utf-8-sig"))
RUN = [1.0, 0.0]

DECISION = {
    "insertion_axis": [0.0, 0.0, -1.0],
    "boot_position_m": [0.30, 0.0, 1.0],
    "anchor_site_m": [0.68, 0.0, 1.0],
    "boot_to_anchor_m": 0.38,
}


def build(threshold=0.395, constraints=("C1_clip",)) -> SafetyFilter:
    return SafetyFilter(
        rules={name: ConstraintRule(constraint=name, threshold_m=threshold,
                                    train_balanced_accuracy=0.88, coverage_sigma=2.0)
               for name in constraints},
        retract_distance_m=0.006)


def action(retreat=0.0, bearing=0.0, excursion=0.0):
    return {"retreat_m": retreat, "bearing_rad": bearing, "excursion_m": excursion}


def test_a_constraint_with_no_rule_is_refused_not_approved():
    only_clip = build(constraints=("C1_clip",))
    verdict = only_clip.verdict(DECISION, action(), RUN, level_by_id(CONTRACT, "E0"))
    assert verdict["unscored"] == ["C2_bend", "C3_anchor"]
    assert "C2_bend" in verdict["constraints"]
    assert verdict["constraints"]["C2_bend"]["state"] == "unscored"
    # A filter with no rule at all cannot call anything safe.
    nothing = SafetyFilter(rules={}, retract_distance_m=0.006)
    assert nothing.verdict(DECISION, action(), RUN, level_by_id(CONTRACT, "E0"))["safe"] is False


def test_the_margin_tightens_the_threshold_as_the_declared_error_grows():
    rule = ConstraintRule("C1_clip", threshold_m=0.41, train_balanced_accuracy=0.88)
    anchor = rule.effective_threshold(level_by_id(CONTRACT, "E0"))
    top = rule.effective_threshold(level_by_id(CONTRACT, "E4"))
    assert math.isclose(anchor, 0.41, rel_tol=1e-12), "no declared error means no margin"
    assert top < anchor
    assert math.isclose(anchor-top, rule.margin(level_by_id(CONTRACT, "E4")), rel_tol=1e-12)


def test_a_bigger_retreat_spends_more_of_the_budget_and_is_eventually_refused():
    filter_ = build()
    level = level_by_id(CONTRACT, "E0")
    small = filter_.verdict(DECISION, action(retreat=0.0), RUN, level)
    large = filter_.verdict(DECISION, action(retreat=0.12), RUN, level)
    assert small["safe"] and not large["safe"]
    assert large["refused_by"] == ["C1_clip"]
    assert (small["constraints"]["C1_clip"]["headroom_m"]
            > large["constraints"]["C1_clip"]["headroom_m"])


def test_budget_reports_what_is_left_for_the_next_step():
    filter_ = build()
    level = level_by_id(CONTRACT, "E0")
    budget = filter_.budget(DECISION, action(retreat=0.02), RUN, level)["C1_clip"]
    assert budget["headroom_at_decision_m"] > 0
    assert budget["spent_by_this_motion_m"] > 0
    assert 0 < budget["spent_fraction"] < 1
    assert math.isclose(budget["headroom_left_m"],
                        budget["headroom_at_decision_m"]-budget["spent_by_this_motion_m"],
                        abs_tol=1e-12)


def test_the_envelope_is_the_region_the_rule_allows():
    filter_ = build()
    level = level_by_id(CONTRACT, "E0")
    bounds = {"retreat_m": [0.0, 0.12], "excursion_m": [0.0, 0.05]}
    envelope = filter_.envelope(DECISION, RUN, level, bounds, resolution=8)
    grid = np.asarray(envelope["safe"])
    distance = np.asarray(envelope["endpoint_distance_m"])
    assert grid.shape == (8, 8, 8)
    # The grid is exactly the rule, so it must agree with the rule everywhere.
    assert np.array_equal(grid, distance <= envelope["effective_threshold_m"])
    assert 0.0 < envelope["safe_fraction"] < 1.0
    assert envelope["largest_safe_retreat_m"] is not None
    with pytest.raises(ValueError, match="No fitted rule"):
        filter_.envelope(DECISION, RUN, level, bounds, resolution=4, constraint="C2_bend")


def test_the_envelope_shrinks_when_the_declared_error_grows():
    filter_ = build()
    bounds = {"retreat_m": [0.0, 0.12], "excursion_m": [0.0, 0.05]}
    anchor = filter_.envelope(DECISION, RUN, level_by_id(CONTRACT, "E0"), bounds, resolution=8)
    top = filter_.envelope(DECISION, RUN, level_by_id(CONTRACT, "E4"), bounds, resolution=8)
    assert top["safe_fraction"] < anchor["safe_fraction"]


def test_best_action_prefers_the_largest_safe_motion_and_can_abstain():
    filter_ = build()
    level = level_by_id(CONTRACT, "E0")
    actions = [action(retreat=0.0), action(retreat=0.03), action(retreat=0.06)]
    largest = filter_.best_action(DECISION, actions, RUN, level, prefer="largest")
    safest = filter_.best_action(DECISION, actions, RUN, level, prefer="safest")
    assert largest["magnitude_m"] >= safest["magnitude_m"]
    assert safest["headroom_m"] >= largest["headroom_m"]
    # A filter tight enough to refuse everything abstains rather than guessing.
    tight = build(threshold=0.10)
    assert tight.best_action(DECISION, actions, RUN, level) is None


def test_binding_constraint_names_the_one_with_least_headroom():
    filter_ = SafetyFilter(
        rules={"C1_clip": ConstraintRule("C1_clip", 0.42, 0.88),
               "C2_bend": ConstraintRule("C2_bend", 0.40, 0.80)},
        retract_distance_m=0.006)
    verdict = filter_.verdict(DECISION, action(retreat=0.0), RUN, level_by_id(CONTRACT, "E0"))
    assert verdict["binding_constraint"] == "C2_bend"


def test_report_states_its_own_scope_and_what_it_cannot_judge():
    report = build().report()
    assert "C2_bend" in report["unscored"] and "C3_anchor" in report["unscored"]
    assert "no hardware" in report["scope"].lower()
    assert report["rules"]["C1_clip"]["threshold_m"] == 0.395


def test_the_sequence_contract_tests_the_filter_it_ships():
    contract = json.loads((ROOT / "configs/cable_sequence_v5.json").read_text(encoding="utf-8-sig"))
    assert contract["safety_filter"]["fit"] == "evidence/cable_perception_v4.json"
    assert contract["safety_filter"]["not_refitted"]
    # Its held-out contexts must come from the perception study's test split.
    assert contract["registered_support"]["split"] == "test"
    prediction = contract["decision_rule"]["prediction"]
    assert prediction["declared_before_collection"] is True
    for key in ("composition", "c2_and_c3", "value_of_the_filter", "falsification"):
        assert len(prediction[key]) > 60
    # Three steps is the whole point; a one-step sequence would test nothing.
    assert len(contract["sequence"]["decision_times_s"]) >= 3
    assert len(contract["sequence"]["candidate_actions"]) == 12


def test_a_real_estimator_can_drive_the_filter_without_the_registered_ladder():
    from assembly_recovery.cable_safety_filter_v4 import declared_error

    filter_ = build()
    # An estimator that reports 1.5 mm of bias, 0.3 mm of jitter and 5 mm of
    # worst-case error on a node it cannot see. No registered level involved.
    mine = declared_error(socket_bias_m=0.0015, socket_jitter_m=0.0003,
                          centreline_occluded_m=0.005)
    rule = filter_.rules["C1_clip"]
    assert math.isclose(rule.margin(mine), 0.0015+2*0.0003+0.005, rel_tol=1e-12)
    assert filter_.verdict(DECISION, action(), RUN, mine)["safe"] in (True, False)
    # An estimator that claims nothing gets no margin, which is the unsafe
    # default and the reason the argument is required rather than optional.
    assert filter_.rules["C1_clip"].margin(declared_error()) == 0.0


def test_the_shape_term_shifts_the_score_and_is_off_by_default():
    plain = build()
    shaped = SafetyFilter(
        rules={"C2_bend": ConstraintRule(
            "C2_bend", threshold_m=0.395, train_balanced_accuracy=0.60,
            shape={"channel": "min_bend_radius_m", "sign": -1.0, "weight_m": 0.02,
                   "standardisation": {"mean": 0.05, "scale": 0.01}})},
        retract_distance_m=0.006)
    level = level_by_id(CONTRACT, "E0")
    assert plain.rules["C1_clip"].shape_term(DECISION) == 0.0
    assert plain.report()["shape_matched"] is False
    # A cable already bent tighter than the fit's average scores WORSE, because
    # the channel enters negated: less curvature headroom, less budget.
    tight = {**DECISION, "min_bend_radius_m": 0.030}
    loose = {**DECISION, "min_bend_radius_m": 0.070}
    assert shaped.rules["C2_bend"].shape_term(tight) > 0
    assert shaped.rules["C2_bend"].shape_term(loose) < 0
    a = shaped.verdict(tight, action(), RUN, level)["constraints"]["C2_bend"]
    b = shaped.verdict(loose, action(), RUN, level)["constraints"]["C2_bend"]
    assert a["endpoint_distance_m"] == b["endpoint_distance_m"], "same motion, same geometry"
    assert a["score_m"] > b["score_m"], "but the tighter cable scores worse"
    assert a["headroom_m"] < b["headroom_m"]
    assert shaped.report()["shape_matched"] is True
    assert "EXPLORATORY" in shaped.report()["shape_matched_status"]


def test_the_sequence_study_is_sized_to_resolve_its_own_margin():
    contract = json.loads((ROOT / "configs/cable_sequence_v5.json").read_text(encoding="utf-8-sig"))
    perception = json.loads(
        (ROOT / "configs/cable_perception_v4.json").read_text(encoding="utf-8-sig"))
    support = contract["registered_support"]
    per_cell = (len(perception["groups"]["test"])*len(support["port_mount"])
                * int(support["repeats"]))
    margin = contract["decision_rule"]["margin"]
    # The v3 defect, checked before this study is ever launched: a per-step rate
    # over too few sequences cannot resolve the margin it is compared against.
    assert 1/per_cell <= 2*margin, (per_cell, 1/per_cell, margin)
    assert per_cell >= 40
    # Three motions per sequence need more clock than one does.
    assert contract["runtime_overrides"]["job_limits"]["deadline_s"] > 40.0
    # And a step whose motion was cut short must not be scored as safe.
    assert "cut short" in contract["labels"]["per_step_censoring"]
