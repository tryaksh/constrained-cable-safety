"""CPU tests for the perception-study contract, error ladder, arms and metrics.

These check the parts that must agree between data collection and model fitting,
and the two rules the v3 post-mortem demanded: that a censored request is never
counted as a success, and that a margin the finest metric cannot resolve is
refused rather than reported. They compile no scene, run no physics and establish
no study result.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from assembly_recovery.cable_constraints_v4 import CONSTRAINTS
from assembly_recovery.cable_study_v4 import (
    ARM_COST,
    ARMS,
    FEATURE_NAMES,
    FORCE_FEATURE_NAMES,
    b0plus_margin_m,
    build_cases,
    build_contexts,
    check_margin_resolution,
    constraint_truth,
    coverage_by_context,
    effective_level,
    false_safe_at_coverage,
    feature_row,
    fit_threshold,
    isolation_contexts,
    kaplan_meier,
    level_by_id,
    per_context_regret,
    ranking_regret,
    ranking_regret_matched,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "configs/cable_perception_v4.json").read_text(encoding="utf-8-sig"))
CANDIDATES = json.loads(
    (ROOT / "configs/cable_perception_v4_candidates.json").read_text(encoding="utf-8-sig"))


def toy_contract(levels=("E0", "E1"), layouts=2):
    support_layouts = [
        {"id": f"L{i+1}", "run_direction_xy": [1.0, 0.0], "outward_xy": [1.0, 0.0],
         "route_waypoints_along_across_m": [[0.09, 0.0], [0.17, 0.0]], "clip_along_m": 0.17}
        for i in range(layouts)]
    groups = {"train": [], "dev": [], "test": []}
    for i, layout in enumerate(support_layouts):
        key = ("train", "test")[i % 2]
        for loop in (0.002, 0.004):
            groups[key].append(f"{layout['id']}_l{int(round(loop*1000))}")
    groups["dev"] = []
    return {
        "id": "toy", "created_on": "2026-09-11", "scope": "toy", "question": "toy",
        "registered_support": {
            "layouts": support_layouts, "installed_loop_m": [0.002, 0.004],
            "port_mount": [{"id": "rigid", "compliance": None}],
            "decision_pose": [{"id": "near_home", "at_s": 2.0}]},
        "error_model": {
            "levels": [dict(level_by_id(CONTRACT, name)) for name in levels],
            "camera": CONTRACT["error_model"]["camera"],
            "history": CONTRACT["error_model"]["history"],
            "isolation": {"at_level": levels[-1], "channels": ["socket", "centreline"]}},
        "action_design": CONTRACT["action_design"],
        "first_calibration_seed": 1000, "perception_seed_offset": 500000,
        "groups": groups,
    }


def test_the_zero_level_is_the_registered_anchor():
    anchor = level_by_id(CONTRACT, "E0")
    for key, value in anchor.items():
        if key == "id":
            continue
        assert value == 0.0, f"E0 must reproduce the v3 privileged interface exactly ({key})"


def test_the_ladder_is_monotone_in_every_channel():
    levels = CONTRACT["error_model"]["levels"]
    for key in ("socket_bias_m", "socket_jitter_m", "socket_orientation_deg",
                "centreline_visible_m", "centreline_occluded_m", "centreline_dropout_p",
                "process_force_n"):
        values = [level[key] for level in levels]
        assert values == sorted(values), f"{key} must not go backwards along the ladder"
        assert values[0] == 0.0 and values[-1] > 0.0


def test_socket_bias_ladder_spans_the_reported_industrial_range():
    biases = [level["socket_bias_m"] for level in CONTRACT["error_model"]["levels"]]
    assert biases[0] == 0.0
    # The ladder must start at the v3 anchor and end at the reported accuracy of
    # good 6-DoF industrial pose estimation, about 2 mm, which the pilot measured
    # is already past the point where this task saturates.
    assert max(biases) == 0.002
    # The first non-zero rung must sit near cobot repeatability, which is under
    # 0.2 mm, so the ladder resolves the regime a good robot already reaches.
    assert min(b for b in biases if b > 0) <= 0.00025
    assert CONTRACT["error_model"]["ladder_range_set_before_collection"]


def test_every_context_carries_a_level_and_a_split():
    contract = toy_contract()
    contexts = build_contexts(contract)
    assert contexts
    assert {c["error_level"] for c in contexts} == {"E0", "E1"}
    assert {c["split"] for c in contexts} <= {"train", "dev", "test"}
    assert len({c["id"] for c in contexts}) == len(contexts)


def test_isolation_cells_are_held_out_only_and_at_the_top_level():
    contract = toy_contract()
    cells = isolation_contexts(contract)
    assert cells
    assert {c["split"] for c in cells} == {"test"}
    assert {c["error_level"] for c in cells} == {"E1"}
    assert {c["isolation"] for c in cells} == {"socket", "centreline"}


def test_isolation_zeroes_every_other_channel():
    contract = toy_contract()
    socket = effective_level(contract, "E1", "socket")
    assert socket["socket_bias_m"] > 0.0
    assert socket["centreline_occluded_m"] == 0.0
    assert socket["process_force_n"] == 0.0
    centreline = effective_level(contract, "E1", "centreline")
    assert centreline["centreline_occluded_m"] > 0.0
    assert centreline["socket_bias_m"] == 0.0
    assert effective_level(contract, "E1", "all") == dict(level_by_id(contract, "E1"))
    with pytest.raises(ValueError, match="Unregistered isolation channel"):
        effective_level(contract, "E1", "made_up")


def test_cases_expand_to_the_declared_counts_and_carry_a_perception_seed():
    contract = toy_contract()
    ladder = build_contexts(contract)
    isolation = isolation_contexts(contract)
    cases = build_cases(contract)
    core = len(contract["action_design"]["core_grid"])
    sampled = contract["action_design"]["sampled_actions"]
    assert len(cases) == len(ladder)*(core+sampled)+len(isolation)*core
    assert len({c["id"] for c in cases}) == len(cases)
    assert len({c["calibration_seed"] for c in cases}) == len(cases)
    assert len({c["perception_seed"] for c in cases}) == len(cases)
    assert not {c["calibration_seed"] for c in cases} & {c["perception_seed"] for c in cases}
    for case in cases:
        assert case["error_level"] in ("E0", "E1")
        assert case["forced_macro"] == "parametric"


def test_isolation_cells_carry_only_the_shared_core_actions():
    contract = toy_contract()
    cases = [c for c in build_cases(contract) if c["error_isolation"] != "all"]
    assert cases
    assert {c["action_kind"] for c in cases} == {"core"}


def test_b0plus_margin_is_built_from_declared_numbers_only():
    level = level_by_id(CONTRACT, "E4")
    margin = b0plus_margin_m(level, coverage_sigma=2.0)
    expected = (level["socket_bias_m"]+2.0*level["socket_jitter_m"]
                + level["centreline_occluded_m"])
    assert math.isclose(margin, expected, rel_tol=1e-12)
    assert b0plus_margin_m(level_by_id(CONTRACT, "E0"), 2.0) == 0.0


def test_margin_resolution_check_refuses_the_v3_defect():
    # The v3 block registered a margin of 0.05 on a metric whose resolution was
    # also 0.05, and returned a verdict that was unresolvable by construction.
    refused = check_margin_resolution(0.05, [0.05])
    assert refused["verdict"] == "refused_margin_below_resolution"
    assert refused["required_margin"] == 0.1
    # Sixty test contexts give a resolution of 1/60, and the registered margin is
    # three times it.
    accepted = check_margin_resolution(0.05, [1/60, 1/480])
    assert accepted["verdict"] == "usable"
    # Fail closed: a metric whose resolution could not be measured refuses.
    unknown = check_margin_resolution(0.05, [None, float("nan")])
    assert unknown["verdict"] == "refused_margin_below_resolution"
    assert not np.isfinite(unknown["coarsest_resolution"])


def test_the_registered_margin_clears_the_registered_resolution():
    margin = CONTRACT["decision_rule"]["margin"]
    required = CONTRACT["groups"]["test_context_requirement"]
    assert check_margin_resolution(margin, [1/required])["verdict"] == "usable"


def rowset(states, scores, magnitudes=None):
    rows = []
    for i, state in enumerate(states):
        rows.append({
            "context": "ctx", "action_kind": "core", "action_index": i,
            "constraints": {name: {"state": state, "violation_progress_m": None,
                                   "censoring_progress_m": 0.01 if state == "censored" else None}
                            for name in CONSTRAINTS},
            "decision": {"insertion_axis": [0.0, 0.0, -1.0]},
            "action": {"retreat_m": (magnitudes or [0.0]*len(states))[i], "bearing_rad": 0.0,
                       "excursion_m": 0.0},
            "run_direction_xy": [1.0, 0.0],
        })
    return rows, np.asarray(scores)


def test_censored_actions_count_in_coverage_but_not_in_the_numerator():
    rows, scores = rowset(["violated", "censored", "respected", "respected"], [0.1, 0.2, 0.3, 0.4])
    violated, observed = constraint_truth(rows, "C1_clip")
    assert observed.tolist() == [True, False, True, True]
    result = false_safe_at_coverage(scores, violated, observed, coverage=3)
    assert result["coverage"] == 3
    assert result["censored"] == 1
    assert result["observed"] == 2
    # One violation among the two observed actions inside the coverage.
    assert math.isclose(result["rate"], 0.5, rel_tol=1e-12)


def test_a_censored_choice_is_reported_and_not_scored_as_a_success():
    rows, _ = rowset(["respected", "censored"], [0.1, 0.2], magnitudes=[0.01, 0.09])
    safe = np.array([True, True])
    per_context = per_context_regret(rows, safe, "C1_clip", retract_distance_m=0.006)
    # The largest commanded magnitude is the censored one, so it is chosen.
    assert per_context["ctx"] == "censored"
    metric = ranking_regret(rows, safe, "C1_clip", retract_distance_m=0.006)
    assert metric["censored_choices"] == 1
    assert metric["scored"] == 0
    assert metric["abstentions"] == 0


def test_abstention_is_not_scored_as_regret():
    rows, _ = rowset(["violated", "violated"], [0.1, 0.2])
    metric = ranking_regret(rows, np.array([False, False]), "C1_clip", retract_distance_m=0.006)
    assert metric["abstentions"] == 1
    assert metric["scored"] == 0
    assert not np.isfinite(metric["regret"])


def test_ranking_regret_reports_its_own_resolution():
    rows = []
    for context in range(4):
        part, _ = rowset(["respected", "violated"], [0.1, 0.2], magnitudes=[0.01, 0.09])
        for row in part:
            row["context"] = f"ctx{context}"
        rows.extend(part)
    metric = ranking_regret(rows, np.ones(len(rows), dtype=bool), "C1_clip",
                            retract_distance_m=0.006)
    assert metric["scored"] == 4
    assert math.isclose(metric["resolution"], 0.25, rel_tol=1e-12)
    assert math.isclose(metric["regret"], 1.0, rel_tol=1e-12)


def test_kaplan_meier_separates_events_from_censoring():
    progress = [0.01, 0.02, 0.03, 0.04]
    violated = np.array([True, False, True, False])
    observed = np.array([True, True, True, False])
    curve = kaplan_meier(progress, violated, observed)
    assert curve["events"] == 2
    assert curve["censored"] == 1
    assert 0.0 < curve["final_survival"] < 1.0


def test_threshold_fit_recovers_a_separable_boundary():
    values = np.array([0.1, 0.2, 0.3, 0.5, 0.6, 0.7])
    labels = np.array([0, 0, 0, 1, 1, 1])
    fit = fit_threshold(values, labels)
    assert 0.3 < fit["threshold_m"] < 0.5
    assert math.isclose(fit["train_balanced_accuracy"], 1.0, rel_tol=1e-12)


def test_feature_row_reads_the_estimate_and_the_declared_sigma():
    decision = {"insertion_axis": [0.0, 0.0, -1.0], "boot_position_m": [0.3, 0.0, 1.0],
                "anchor_site_m": [0.7, 0.0, 1.0], "boot_to_anchor_m": 0.4,
                "clip_margin_m": 0.008, "routed_length_m": 0.46, "depth_along_axis_m": 0.0,
                "anchor_reaction_n": 0.04, "cable_boot_load_n": 1.3, "connector_contact_n": 0.0,
                "shelf_contact_n": 0.36, "min_bend_radius_m": 0.05,
                "occluded_node_fraction": 0.25, "wrist_force_n": 1.0}
    action = {"retreat_m": 0.06, "bearing_rad": 0.0, "excursion_m": 0.03}
    context = {"run_direction_xy": [1.0, 0.0], "installed_loop_m": 0.004}
    level = level_by_id(CONTRACT, "E3")
    row = feature_row(decision, action, context, 0.006, level)
    assert set(FEATURE_NAMES) <= set(row)
    assert set(FORCE_FEATURE_NAMES) <= set(row)
    assert row["occluded_node_fraction"] == 0.25
    assert math.isclose(row["declared_socket_sigma_m"],
                        level["socket_bias_m"]+level["socket_jitter_m"], rel_tol=1e-12)
    assert math.isclose(row["declared_centreline_sigma_m"], level["centreline_occluded_m"],
                        rel_tol=1e-12)


def test_every_arm_declares_its_sensing_and_the_force_arm_sees_no_vision():
    assert set(ARMS) == set(ARM_COST)
    for name in ARMS:
        assert ARM_COST[name]["sensing"]
    vision_words = ("centreline", "pose", "shape")
    assert not any(word in ARM_COST["B2"]["sensing"].lower() for word in vision_words)
    for name in ("min_bend_radius_m", "occluded_node_fraction", "endpoint_boot_to_anchor_m"):
        assert name not in FORCE_FEATURE_NAMES


def test_the_contract_declares_a_falsifiable_prediction_for_all_three_constraints():
    prediction = CONTRACT["decision_rule"]["crossover_prediction"]
    assert prediction["declared_before_collection"] is True
    for name in CONSTRAINTS:
        assert name in prediction and len(prediction[name]) > 60


def test_candidate_layouts_cover_the_declared_width():
    layouts = CANDIDATES["layouts"]
    assert len(layouts) >= 12
    clips = {layout["clip_along_m"] for layout in layouts}
    assert len(clips) >= 4, "clip position must be varied"
    shelves = {tuple(sorted(layout.get("fixture_overrides", {}).items()))
               for layout in layouts}
    assert len(shelves) >= 3, "shelf height must be varied"
    corners = [layout for layout in layouts
               if any(abs(point[1]) >= 0.03
                      for point in layout["route_waypoints_along_across_m"])]
    assert corners, "at least one layout must turn a real corner so C2 is loaded"


def test_contract_scope_refuses_the_claims_the_project_forbids():
    text = " ".join(CONTRACT["scope_and_limitations"]).lower()
    assert "simulation only" in text
    assert "not camera perception" in text
    assert "no hardware access" in text


def test_matched_ranking_metric_scores_an_arm_that_abstains_everywhere():
    # The registered metric cannot score an arm that calls nothing safe. The
    # companion metric declared in the amendment asks the same question at the
    # baseline's own coverage, so an ordering is always scored.
    rows, scores = rowset(["respected", "violated"], [0.9, 0.95], magnitudes=[0.01, 0.09])
    safe_none = np.array([False, False])
    assert ranking_regret(rows, safe_none, "C1_clip", 0.006)["scored"] == 0
    coverage = coverage_by_context(rows, np.array([True, False]))
    assert coverage == {"ctx": 1}
    matched = ranking_regret_matched(rows, scores, coverage, "C1_clip", 0.006)
    assert matched["scored"] == 1
    assert matched["abstentions"] == 0
    # With coverage one, the arm issues only the action it ranks safest.
    assert matched["regret"] == 0.0


def test_matched_ranking_metric_uses_the_arms_own_order():
    rows, _ = rowset(["respected", "violated"], [0.0, 0.0], magnitudes=[0.01, 0.09])
    coverage = {"ctx": 1}
    # An arm that ranks the violating action safest is punished for it.
    bad = ranking_regret_matched(rows, np.array([0.9, 0.1]), coverage, "C1_clip", 0.006)
    good = ranking_regret_matched(rows, np.array([0.1, 0.9]), coverage, "C1_clip", 0.006)
    assert bad["regret"] == 1.0
    assert good["regret"] == 0.0


def test_matched_ranking_metric_floors_coverage_at_one():
    rows, scores = rowset(["violated", "violated"], [0.1, 0.2], magnitudes=[0.01, 0.09])
    matched = ranking_regret_matched(rows, scores, {"ctx": 0}, "C1_clip", 0.006)
    assert matched["scored"] == 1


def test_the_amendment_names_the_contract_it_amends_and_changes_no_rule():
    amendment = json.loads(
        (ROOT / "configs/cable_perception_v4_amendment_01.json").read_text(encoding="utf-8-sig"))
    from assembly_recovery.cable_study_v4 import content_sha256
    assert amendment["amends"] == "configs/cable_perception_v4.json"
    assert amendment["amends_content_sha256"] == content_sha256(
        ROOT / "configs/cable_perception_v4.json"), "the amended contract must still be frozen"
    assert amendment["declared_before_the_test_split_was_read"]
    assert "registered metrics and nothing else" in amendment["companion_metric"]["status"]
    assert amendment["companion_metric"]["what_it_cannot_do"]
