"""The replay adapter must preserve decision inputs and catch reproduction drift."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from assembly_recovery.recovery_inspector import RecoveryInspector
from scripts.export_recovery_replay import (
    capture_case,
    comparable_issued,
    decision_snapshot,
    differences,
    request_from_replay,
    stable_outcome,
)
from scripts.verify_recovery_replay import compare_decision, verify_replay

ROOT = Path(__file__).resolve().parents[1]


def tick() -> dict:
    return {
        "estimate": SimpleNamespace(
            time_s=2.0,
            cable_centerline=np.array([[0.3, 0.0, 0.0], [0.2, 0.0, 0.0]]),
            insertion_axis=np.array([0.0, 0.0, -1.0])),
        "scene": SimpleNamespace(fixture={"anchor_site_world": [0.0, 0.0, 0.0]}),
    }


def issued() -> dict:
    return {
        "step": 0, "time_s": 2.0, "abstained": False, "action_index": 0,
        "action": {"retreat_m": 0.0, "bearing_rad": 0.0, "excursion_m": 0.0},
        "magnitude_m": 0.006, "headroom_m": 0.05,
        "decision_boot_to_anchor_m": 0.3, "endpoint_boot_to_anchor_m": 0.304,
        "motion_completed": True, "requested": True,
        "verdict": {"safe": True, "unscored": [], "refused_by": []},
        "budget": {"C1_clip": {
            "headroom_at_decision_m": 0.05, "spent_by_this_motion_m": 0.004,
            "spent_fraction": 0.08, "headroom_left_m": 0.046,
            "units": "an incorrect historical label"}},
        "state_before": {"clips": {"required_retained": 5}},
        "state_after": {"clips": {"required_retained": 5}},
    }


def outcome() -> dict:
    clips = {"required_retained": 5, "required_count": 5,
             "retained": ["c1", "c2", "c3", "c4", "c5"], "lost": []}
    return {
        "case": {"id": "fixed_case", "supervisor": "conservative",
                 "run_direction_xy": [1.0, 0.0], "perception_seed": 123},
        "cell": {"id": "RC1", "required": clips["retained"]},
        "supervisor": "conservative", "error_level": "E0",
        "job": {"failure_reason": None, "elapsed_s": 11.7, "status": "completed"},
        "route_completed": True, "seated": True,
        "installed_clips": clips, "terminal_clips": clips,
        "clip_loss_attribution": {},
        "constraints": {"C1_clip": {"state": "respected"},
                        "C2_bend": {"state": "censored"},
                        "C3_anchor": {"state": "respected"}},
        "steps_offered": 1, "steps_issued": 1, "abstentions": 0,
        "privilege_guard": {"events": 0},
        "mutation_guard": {"forbidden_events": 0},
        "issued": [issued()],
    }


def test_snapshot_reads_the_estimate_and_declared_fixture_only():
    data = tick()
    data["truth"] = object()  # Any access to truth would be an error.
    snapshot = decision_snapshot(data)
    assert snapshot["boot_to_anchor_m"] == pytest.approx(0.3)
    assert snapshot["boot_position_m"] == [0.3, 0.0, 0.0]
    data["estimate"].cable_centerline[0, 0] = 0.8
    assert snapshot["boot_position_m"] == [0.3, 0.0, 0.0]


def test_adapter_does_not_hand_the_answer_key_to_the_inspector():
    replay = {"candidate_actions": [issued()["action"]]}
    case = {"request": "fixed_case", "run_direction_xy": [1.0, 0.0],
            "context": {"geometry_id": "RC1"},
            "declared_error": {"socket_bias_m": 0.0, "socket_jitter_m": 0.0,
                               "centreline_occluded_m": 0.0}}
    step = {"step": 0, "decision": decision_snapshot(tick()), "expected": issued()}
    request = request_from_replay(replay, case, step)
    assert request["request_id"] == "fixed_case:step0"
    assert "expected" not in request and "time_s" not in request["decision"]
    assert request["units"] == "m_rad_s"
    request["candidate_actions"][0]["retreat_m"] = 0.9
    request["decision"]["boot_position_m"][0] = 0.7
    assert replay["candidate_actions"][0]["retreat_m"] == 0.0
    assert step["decision"]["boot_position_m"][0] == 0.3


def test_comparison_preserves_censoring_and_detects_policy_or_seed_changes():
    original = stable_outcome(outcome())
    assert original["constraints"]["C2_bend"] == "censored"
    changed = copy.deepcopy(original)
    changed["issued"][0]["action_index"] = 3
    changed["case"]["perception_seed"] += 1
    changed["constraints"]["C2_bend"] = "respected"
    mismatch = differences(changed, original)
    assert set(mismatch) == {".issued[0].action_index", ".case.perception_seed",
                             ".constraints.C2_bend"}
    assert differences({"x": 1.0+1e-13}, {"x": 1.0}) == []
    assert differences({"x": 1.0+1e-8}, {"x": 1.0}) == [".x"]
    assert differences({"x": True}, {"x": 1}) == [".x"]


def test_legacy_unit_prose_is_omitted_without_changing_budget_values():
    row = comparable_issued(issued())
    assert "units" not in row["budget"]["C1_clip"]
    assert row["budget"]["C1_clip"]["spent_fraction"] == 0.08
    assert row["motion_completed"] is True


@pytest.mark.parametrize("drift", [False, True])
def test_capture_checks_the_original_and_copies_every_decision(tmp_path, monkeypatch, drift):
    original = outcome()
    reference_dir = tmp_path / "references"
    reference_path = reference_dir / "fixed_case" / "result.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(original), encoding="utf-8")

    def fake_run(runtime, case, directory, observer):
        measured = copy.deepcopy(original)
        observer(tick() | {"issued": measured["issued"]})
        observer(tick() | {"issued": measured["issued"]})  # Later tick, no new decision.
        if drift:
            measured["issued"][0]["action_index"] = 2
        return measured

    monkeypatch.setitem(sys.modules, "scripts.evaluate_cable_routing_v6",
                        SimpleNamespace(run_case=fake_run))
    runtime = {"cases": [original["case"]], "cable": {"segments": 23},
               "clocks": {"physics_hz": 4000},
               "perception": {"levels": [{"id": "E0", "socket_bias_m": 0.0,
                                           "socket_jitter_m": 0.0,
                                           "centreline_occluded_m": 0.0}]}}
    if drift:
        with pytest.raises(RuntimeError, match="Replay mismatch"):
            capture_case(runtime, "fixed_case", reference_dir, tmp_path / "capture", 1e-12)
    else:
        compact, check = capture_case(runtime, "fixed_case", reference_dir,
                                      tmp_path / "capture", 1e-12)
        assert check["reproduces_original"] is True
        assert len(compact["decisions"]) == 1
        assert compact["recorded_outcome"]["constraints"]["C2_bend"] == "censored"
        assert compact["context"]["required_clips"] == 5


def test_fixed_case_selection_covers_every_error_level_and_supervisor():
    config = json.loads((ROOT / "configs/recovery_inspector_demo.json").read_text(encoding="utf-8"))
    expected = {f"RC1_l15_compliant4000_m0_{level}_{supervisor}_r0"
                for level in ("E0", "E2", "E4")
                for supervisor in ("unfiltered", "filtered", "conservative")}
    assert set(config["cases"]) == expected
    assert len(config["cases"]) == len(expected)


def test_unfiltered_parity_checks_arithmetic_without_inventing_a_filtered_verdict():
    original = comparable_issued(issued())
    original["headroom_m"] = None
    original["verdict"] = {"safe": None, "note": "no filter was consulted"}
    candidate = {
        "action": original["action"], "magnitude_m": original["magnitude_m"],
        "headroom_m": 0.05,
        "constraints": {"C1_clip": {"state": "safe", "endpoint_distance_m": 0.304}},
        "budget": copy.deepcopy(original["budget"]),
    }
    report = {"policies": {"unfiltered": {"abstained": False, "action_index": 0}},
              "candidates": [candidate]}
    assert compare_decision(report, "unfiltered", original) == []
    candidate["budget"]["C1_clip"]["spent_fraction"] = 0.8
    assert compare_decision(report, "unfiltered", original) == [
        "chosen_candidate.budget.C1_clip.spent_fraction"]


def test_abstention_parity_requires_no_selected_candidate():
    report = {"policies": {"conservative": {"abstained": True, "action_index": None}},
              "candidates": []}
    expected = {"abstained": True, "action_index": None}
    assert compare_decision(report, "conservative", expected) == []
    report["policies"]["conservative"] = {"abstained": False, "action_index": 0}
    assert compare_decision(report, "conservative", expected) == [
        "policy.abstained", "policy.action_index"]


def portable_replay() -> dict:
    return json.loads((ROOT / "artifacts/showcase/recovery_replay.json").read_text(encoding="utf-8"))


def test_complete_portable_corpus_matches_every_original_policy_decision():
    replay = portable_replay()
    result = verify_replay(replay, RecoveryInspector.from_repository(ROOT))
    assert result["status"] == "verified"
    assert result["cases"] == 9 and result["decisions"] == 21
    assert result["mismatched_decisions"] == 0
    assert result["coverage_mismatches"] == []
    assert replay["provenance"]["dirty"] is False
    config = json.loads((ROOT / "configs/recovery_inspector_demo.json").read_text(encoding="utf-8"))
    assert replay["provenance"]["selected_cases"] == config["cases"]
    e4 = next(case for case in replay["cases"]
              if case["error_level"] == "E4" and case["supervisor"] == "conservative")
    assert e4["recorded_outcome"]["job"]["failure_reason"] == "controller_retries_exhausted"
    assert e4["recorded_outcome"]["route_completed"] is False


@pytest.mark.parametrize("corruption", ["budget", "missing_case"])
def test_portable_verification_rejects_arithmetic_drift_and_incomplete_coverage(corruption):
    replay = portable_replay()
    if corruption == "budget":
        replay["cases"][0]["decisions"][0]["expected"]["budget"]["C1_clip"]["spent_fraction"] += 0.01
    else:
        replay["cases"].pop()
    result = verify_replay(replay, RecoveryInspector.from_repository(ROOT))
    assert result["status"] == "FAILED"
    if corruption == "budget":
        assert result["mismatched_decisions"] == 1
        assert result["checks"][0]["mismatches"] == [
            "chosen_candidate.budget.C1_clip.spent_fraction"]
    else:
        assert "case selection differs from prelaunch" in result["coverage_mismatches"]
        assert "decision count differs from capture verification" in result["coverage_mismatches"]



def test_old_demo_outcome_has_an_explicit_correction_bound_to_original_result():
    demo = json.loads((ROOT / "artifacts/showcase/demo.json").read_text(encoding="utf-8"))
    correction = demo["superseded"]
    case = next(row for row in portable_replay()["cases"] if row["request"] == correction["request"])
    assert demo["levels"]["E4"]["recorded_job_outcome"] == correction["recorded_value_preserved"]
    assert correction["correct_value"] == case["recorded_outcome"]["job"]["failure_reason"]
    assert correction["original_result"] == case["source"]
    assert case["recorded_outcome"]["route_completed"] is False
