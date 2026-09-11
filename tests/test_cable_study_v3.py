"""CPU tests for the safe-repair boundary contract, action design and features.

These check the parts that must agree between data collection and model fitting.
They compile no scene, run no physics and establish no study result.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from assembly_recovery.cable_recovery_control_v2 import RepairMacro, parametric_macro
from assembly_recovery.cable_study_v3 import (
    FEATURE_NAMES,
    action_displacement,
    build_cases,
    build_contexts,
    content_sha256,
    core_actions,
    feature_row,
    halton,
    merge_runtime,
    normalised_bytes,
    outcome_label,
    raw_sha256,
    repair_basis,
    sampled_actions,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "configs/cable_repair_boundary_v3.json").read_text(encoding="utf-8-sig"))
AXIS = np.array([0.0, 0.0, -1.0])
RUN = np.array([1.0, 0.0, 0.0])


def test_content_hash_ignores_line_endings_and_byte_order_mark(tmp_path):
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{"a": 1}\n{"b": 2}\n')
    crlf.write_bytes(b'\xef\xbb\xbf{"a": 1}\r\n{"b": 2}\r\n')
    assert content_sha256(lf) == content_sha256(crlf)
    assert raw_sha256(lf) != raw_sha256(crlf)


def test_normalised_bytes_leaves_clean_content_alone():
    assert normalised_bytes(b'{"a": 1}\n') == b'{"a": 1}\n'


def test_halton_is_deterministic_and_inside_the_unit_cube():
    first, second = halton(16, skip=97), halton(16, skip=97)
    assert np.array_equal(first, second)
    assert first.shape == (16, 3)
    assert first.min() > 0.0 and first.max() < 1.0


def test_halton_skip_moves_the_stream():
    assert not np.array_equal(halton(8, skip=97), halton(8, skip=105))


def test_contract_group_split_covers_every_group_exactly_once():
    groups = CONTRACT["groups"]
    listed = groups["train"]+groups["dev"]+groups["test"]
    expected = {f"{layout['id']}_l{int(round(loop*1000))}"
                for layout in CONTRACT["registered_support"]["layouts"]
                for loop in CONTRACT["registered_support"]["installed_loop_m"]}
    assert len(listed) == len(set(listed)) == len(expected)
    assert set(listed) == expected


def test_every_layout_appears_in_the_test_split():
    test_layouts = {group.split("_")[0] for group in CONTRACT["groups"]["test"]}
    assert test_layouts == {layout["id"] for layout in CONTRACT["registered_support"]["layouts"]}


def test_build_cases_matches_the_declared_request_count():
    cases = build_cases(CONTRACT)
    assert len(cases) == CONTRACT["expected_requests"]
    assert len({c["id"] for c in cases}) == len(cases)
    assert len({c["calibration_seed"] for c in cases}) == len(cases)


def test_every_context_receives_the_same_shared_core_actions():
    cases = build_cases(CONTRACT)
    per_context: dict[str, list] = {}
    for case in cases:
        if case["action_kind"] == "core":
            per_context.setdefault(case["study_context"], []).append(case["repair_action"])
    reference = core_actions(CONTRACT["action_design"])
    assert len(per_context) == len(build_contexts(CONTRACT))
    for actions in per_context.values():
        assert actions == reference


def test_sampled_actions_differ_between_contexts_and_respect_the_bounds():
    design = CONTRACT["action_design"]
    first, second = sampled_actions(design, 0), sampled_actions(design, 1)
    assert first != second
    low, high = design["bounds"]["retreat_m"]
    for action in first+second:
        assert low <= action["retreat_m"] <= high
        assert 0.0 <= action["excursion_m"] <= design["bounds"]["excursion_m"][1]
        assert 0.0 <= action["bearing_rad"] <= 2*math.pi


def test_compliant_contexts_carry_compliance_and_rigid_ones_do_not():
    cases = {c["id"]: c for c in build_cases(CONTRACT)}
    compliant = [c for c in cases.values() if "compliant4000" in c["study_context"]]
    rigid = [c for c in cases.values() if "_rigid_" in c["study_context"]]
    assert compliant and rigid
    assert all("port_compliance" in c for c in compliant)
    assert all("port_compliance" not in c for c in rigid)


def test_action_displacement_matches_the_executed_macro_waypoint():
    """The analytic endpoint a predictor computes must be the motion that runs."""
    action = {"retreat_m": 0.07, "bearing_rad": 1.1, "excursion_m": 0.03, "speed_m_per_s": 0.02}
    retract = 0.006
    tip = np.array([0.3, -0.1, 0.5])
    macro = parametric_macro(action)
    retract_goal = tip-AXIS*retract
    executed = macro.waypoints(retract_goal, AXIS, RUN)[0]
    predicted = tip+action_displacement(action, AXIS, RUN, retract)
    assert np.allclose(executed, predicted, atol=1e-12)


def test_parametric_macro_returns_to_its_retreat_point():
    macro = parametric_macro({"retreat_m": 0.05, "bearing_rad": 0.0, "excursion_m": 0.02})
    points = macro.waypoints(np.zeros(3), AXIS, RUN)
    assert len(points) == 2
    assert np.allclose(points[-1], np.zeros(3))


def test_parametric_macro_defaults_to_the_clearance_speed():
    assert parametric_macro({"retreat_m": 0.0, "bearing_rad": 0.0, "excursion_m": 0.0}).speed_m_per_s == 0.02


def test_repair_basis_is_orthonormal_and_keeps_the_axis():
    basis = repair_basis(AXIS, RUN)
    assert np.allclose(basis.T @ basis, np.eye(3), atol=1e-12)
    assert np.allclose(basis[:, 2], AXIS)


def test_repair_basis_matches_the_macro_basis_for_a_skew_run():
    run = np.array([0.6, 0.8, 0.0])
    offset = (0.02, -0.01, -0.03)
    point = RepairMacro("m", (offset,)).waypoints(np.zeros(3), AXIS, run)[0]
    assert np.allclose(point, repair_basis(AXIS, run) @ np.asarray(offset), atol=1e-12)


def decision_state():
    return {"boot_position_m": [0.30, 0.0, 0.50], "anchor_site_m": [0.55, 0.0, 0.33],
            "insertion_axis": AXIS.tolist(), "boot_to_anchor_m": 0.3059411708155671,
            "clip_margin_m": 0.0085, "routed_length_m": 0.462, "depth_along_axis_m": 0.008,
            "anchor_reaction_n": 0.04, "cable_boot_load_n": 1.61,
            "connector_contact_n": 0.0, "shelf_contact_n": 0.34}


def test_feature_row_reports_every_declared_feature():
    row = feature_row(decision_state(), {"retreat_m": 0.05, "bearing_rad": 0.0, "excursion_m": 0.0},
                      {"run_direction_xy": [1.0, 0.0], "installed_loop_m": 0.004}, 0.006)
    assert set(row) == set(FEATURE_NAMES)
    assert all(np.isfinite(v) for v in row.values())


def test_retreating_away_from_the_anchor_increases_the_endpoint_distance():
    state = decision_state()
    context = {"run_direction_xy": [1.0, 0.0], "installed_loop_m": 0.004}
    near = feature_row(state, {"retreat_m": 0.0, "bearing_rad": 0.0, "excursion_m": 0.0}, context, 0.006)
    far = feature_row(state, {"retreat_m": 0.09, "bearing_rad": 0.0, "excursion_m": 0.0}, context, 0.006)
    assert far["endpoint_boot_to_anchor_m"] > near["endpoint_boot_to_anchor_m"]


def test_moving_toward_the_anchor_buys_back_endpoint_distance():
    state = decision_state()
    context = {"run_direction_xy": [1.0, 0.0], "installed_loop_m": 0.004}
    plain = feature_row(state, {"retreat_m": 0.09, "bearing_rad": 0.0, "excursion_m": 0.0}, context, 0.006)
    toward = feature_row(state, {"retreat_m": 0.09, "bearing_rad": 0.0, "excursion_m": 0.03}, context, 0.006)
    away = feature_row(state, {"retreat_m": 0.09, "bearing_rad": math.pi, "excursion_m": 0.03}, context, 0.006)
    assert toward["endpoint_boot_to_anchor_m"] < plain["endpoint_boot_to_anchor_m"]
    assert away["endpoint_boot_to_anchor_m"] > plain["endpoint_boot_to_anchor_m"]


@pytest.mark.parametrize(("result", "expected"), [
    ({"job": {"status": "completed", "failure_reason": None}, "terminal_clip_retained": True},
     "completed_clip_retained"),
    ({"job": {"status": "completed", "failure_reason": None}, "terminal_clip_retained": False},
     "completed_clip_lost"),
    ({"job": {"status": "failed", "failure_reason": "lost_required_clip"}, "terminal_clip_retained": False},
     "clip_lost"),
    ({"job": {"status": "failed", "failure_reason": "force_abort"}, "terminal_clip_retained": True},
     "load_abort"),
    ({"job": {"status": "failed", "failure_reason": "deadline"}, "terminal_clip_retained": True}, "deadline"),
    ({"job": {"status": "failed", "failure_reason": "settle_clip_not_retained"},
      "terminal_clip_retained": False}, "settling_rejected"),
    ({"job": {"status": "failed", "failure_reason": "construction_infeasible"},
      "terminal_clip_retained": False}, "construction_infeasible"),
])
def test_outcome_label_covers_the_registered_classes(result, expected):
    assert outcome_label(result) == expected
    assert expected in CONTRACT["labels"]["outcome_classes"]


def test_merge_runtime_applies_the_declared_overrides_only():
    base = json.loads((ROOT / "configs/cable_recovery_task_v2.json").read_text(encoding="utf-8-sig"))
    runtime = merge_runtime(base, CONTRACT)
    assert runtime["render_visuals"] is False
    assert runtime["force_guided_controller"]["repair_settle_s"] == 0.5
    assert runtime["force_guided_controller"]["max_retries"] == base["force_guided_controller"]["max_retries"]
    assert runtime["clocks"] == base["clocks"]
    assert runtime["job_limits"] == base["job_limits"]
    assert len(runtime["cases"]) == CONTRACT["expected_requests"]


def test_merge_runtime_does_not_mutate_the_base_task():
    base = json.loads((ROOT / "configs/cable_recovery_task_v2.json").read_text(encoding="utf-8-sig"))
    before = json.dumps(base, sort_keys=True)
    merge_runtime(base, CONTRACT)
    assert json.dumps(base, sort_keys=True) == before


def test_contract_declares_the_base_task_it_was_frozen_against():
    assert CONTRACT["base_config"]["content_sha256"] == content_sha256(
        ROOT / CONTRACT["base_config"]["path"])
