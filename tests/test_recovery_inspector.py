"""Exercise the external decision contract and preserve the historical policies."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from assembly_recovery.cable_constraints_v4 import CONSTRAINTS
from assembly_recovery.cable_safety_filter_v4 import ConstraintRule, SafetyFilter
from assembly_recovery.cable_study_v3 import content_sha256
from assembly_recovery.recovery_inspector import (
    ERROR_FIELDS,
    SOURCE_PATHS,
    InvalidRequest,
    RecoveryInspector,
    request_from_demo,
    validate_request,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "artifacts/showcase/demo.json").read_text(encoding="utf-8-sig"))


@pytest.fixture
def payload():
    return copy.deepcopy(request_from_demo(DEMO))


@pytest.fixture
def inspector():
    return RecoveryInspector.from_repository(ROOT)


def synthetic_filter(threshold=0.4, constraints=CONSTRAINTS):
    return SafetyFilter(
        rules={name: ConstraintRule(name, threshold, 0.8) for name in constraints},
        retract_distance_m=0.0,
    )


def run_cli(*arguments, stdin=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/inspect_recovery.py"), *map(str, arguments)],
        input=stdin, capture_output=True, text=True, cwd=ROOT, timeout=30,
    )


@pytest.mark.parametrize(
    ("level", "filtered_index", "allowed_indices"),
    [("E0", 9, [0, 1, 2, 5, 7, 8, 9, 11]),
     ("E2", 9, [0, 1, 2, 5, 7, 8, 9, 11]),
     ("E4", 5, [0, 1, 2, 5, 7, 8])],
)
def test_recorded_estimates_preserve_policy_choices_and_all_constraint_scores(
    inspector, level, filtered_index, allowed_indices,
):
    """Pinned indices were measured independently with the unchanged v4 filter."""
    report = inspector.inspect(request_from_demo(DEMO, level))
    assert report["policies"]["conservative"]["action_index"] == 0
    assert report["policies"]["filtered"]["action_index"] == filtered_index
    assert report["policies"]["unfiltered"]["action_index"] == 4
    assert [c["index"] for c in report["candidates"] if c["rule_status"] == "allowed"] == allowed_indices
    historical = SafetyFilter.from_evidence(*(ROOT / path for path in SOURCE_PATHS[:3]))
    block = DEMO["levels"][level]
    for candidate in report["candidates"]:
        arguments = (block["decision"], DEMO["candidate_actions"][candidate["index"]],
                     block["run_direction_xy"], block["declared_error"])
        expected = historical.verdict(*arguments)
        assert candidate["constraints"] == expected["constraints"]
        assert candidate["budget"] == historical.budget(*arguments)
        assert candidate["refused_by"] == expected["refused_by"]
        assert candidate["binding_constraint"] == expected["binding_constraint"]
    assert report["selected"] == report["candidates"][0]
    assert report["scope"]["candidate_set"] == "registered_v6"
    assert report["scope"]["fit_geometry"] == "outside_fit_geometry"


@pytest.mark.parametrize("missing", ERROR_FIELDS)
def test_missing_uncertainty_is_rejected_instead_of_assumed_zero(payload, inspector, missing):
    del payload["declared_error"][missing]
    with pytest.raises(InvalidRequest, match=missing):
        inspector.inspect(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "0.01", None, 1_000_001])
@pytest.mark.parametrize("section", ["declared_error", "position", "candidate_action"])
def test_invalid_numeric_inputs_cannot_reach_geometry(payload, inspector, value, section):
    if section == "declared_error":
        payload["declared_error"]["socket_bias_m"] = value
    elif section == "position":
        payload["decision"]["boot_position_m"][0] = value
    else:
        payload["candidate_actions"][0]["speed_m_per_s"] = value
    with pytest.raises(InvalidRequest):
        inspector.inspect(payload)


@pytest.mark.parametrize("field", ERROR_FIELDS)
def test_uncertainty_cannot_be_negative(payload, field):
    payload["declared_error"][field] = -0.001
    with pytest.raises(InvalidRequest, match=field):
        validate_request(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("retreat_m", -0.001), ("excursion_m", -0.001),
     ("speed_m_per_s", -0.001), ("speed_m_per_s", 0.0)],
)
def test_nonphysical_action_values_are_rejected(payload, field, value):
    payload["candidate_actions"][0][field] = value
    with pytest.raises(InvalidRequest, match=field):
        validate_request(payload)


@pytest.mark.parametrize("units", ["mm_deg_s", "m", "", None])
def test_ambiguous_units_are_rejected(payload, units):
    payload["units"] = units
    with pytest.raises(InvalidRequest, match="units"):
        validate_request(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("boot_position_m", [0.0, 0.0]), ("anchor_site_m", [0.0, 0.0, 0.0, 0.0]),
     ("boot_position_m", (0.0, 0.0, 0.0)), ("insertion_axis", [0.0, 0.0, 0.0]),
     ("insertion_axis", [0.0, 0.0, -2.0]), ("insertion_axis", [0.0, 0.0, -1.0001])],
)
def test_position_dimensions_and_axis_length_are_explicit(payload, field, value):
    payload["decision"][field] = value
    with pytest.raises(InvalidRequest, match=field):
        validate_request(payload)


@pytest.mark.parametrize("value", [[0, 0], [2, 0], [1, 0, 0], "x"])
def test_run_direction_requires_a_two_dimensional_unit_vector(payload, value):
    payload["run_direction_xy"] = value
    with pytest.raises(InvalidRequest, match="run_direction_xy"):
        validate_request(payload)


def test_inconsistent_distance_is_rejected_but_omitted_distance_is_derived(payload):
    payload["decision"]["boot_to_anchor_m"] += 0.001
    with pytest.raises(InvalidRequest, match="disagrees"):
        validate_request(payload)
    del payload["decision"]["boot_to_anchor_m"]
    checked = validate_request(payload)
    assert checked["decision"]["boot_to_anchor_m"] == math.dist(
        payload["decision"]["boot_position_m"], payload["decision"]["anchor_site_m"],
    )
    assert "boot_to_anchor_m" not in payload["decision"]


@pytest.mark.parametrize("actions", [[], None, {}, "actions"])
def test_no_candidate_list_is_invalid(payload, actions):
    payload["candidate_actions"] = actions
    with pytest.raises(InvalidRequest, match="candidate_actions"):
        validate_request(payload)


def test_unrecognised_fields_cannot_hide_a_typo_or_outcome_data(payload):
    payload["decision"]["actual_clip_retained"] = True
    with pytest.raises(InvalidRequest, match="actual_clip_retained"):
        validate_request(payload)


@pytest.mark.parametrize("constraints", [("C1_clip", "C3_anchor"), ()])
def test_missing_constraint_rules_force_abstention_even_when_scored_rules_pass(payload, constraints):
    report = RecoveryInspector(synthetic_filter(1.0, constraints)).inspect(payload)
    assert report["status"] == "unscored"
    assert report["selected"] is None
    for policy in ("conservative", "filtered"):
        assert report["policies"][policy] == {
            "action_index": None, "abstained": True, "reason": "missing_constraint_rule",
        }
    assert all(c["rule_status"] == "unscored" for c in report["candidates"])
    assert all("C2_bend" in c["unscored"] for c in report["candidates"])
    if not constraints:
        assert all(c["headroom_m"] is None for c in report["candidates"])


def test_valid_request_with_no_allowed_candidate_abstains(payload, inspector):
    payload["declared_error"]["socket_bias_m"] = 0.5
    report = inspector.inspect(payload)
    assert report["status"] == "abstained"
    assert report["selected"] is None
    assert all(c["rule_status"] == "refused" for c in report["candidates"])
    for policy in ("conservative", "filtered"):
        assert report["policies"][policy]["reason"] == "no_candidate_allowed"
        assert report["policies"][policy]["action_index"] is None
    assert report["policies"]["unfiltered"]["action_index"] == 4


def test_equal_geometric_choices_preserve_input_order_despite_speed_difference(payload, inspector):
    first = copy.deepcopy(payload["candidate_actions"][0])
    second = {**first, "speed_m_per_s": 0.5}
    payload["candidate_actions"] = [first, second]
    report = inspector.inspect(payload)
    assert all(policy["action_index"] == 0 for policy in report["policies"].values())
    assert report["selected"]["action"]["speed_m_per_s"] == 0.02
    assert report["scope"]["candidate_set"] == "custom_unvalidated"
    payload["candidate_actions"].reverse()
    assert inspector.inspect(payload)["selected"]["action"]["speed_m_per_s"] == 0.5


def test_zero_headroom_serialises_as_null_without_a_nonfinite_budget(payload):
    payload["decision"] = {
        "boot_position_m": [0.0, 0.0, 0.0], "anchor_site_m": [0.4, 0.0, 0.0],
        "insertion_axis": [0.0, 0.0, -1.0], "boot_to_anchor_m": 0.4,
    }
    payload["candidate_actions"] = payload["candidate_actions"][:1]
    report = RecoveryInspector(synthetic_filter()).inspect(payload)
    assert report["status"] == "ranked"
    assert report["selected"]["headroom_m"] == 0.0
    for budget in report["selected"]["budget"].values():
        assert budget["spent_fraction"] is None
        assert budget["headroom_left_m"] == 0.0
    assert json.loads(json.dumps(report, allow_nan=False)) == report


def test_call_and_validation_leave_the_original_request_untouched(payload, inspector):
    original = copy.deepcopy(payload)
    detached = validate_request(payload)
    report = inspector.inspect(payload)
    detached["decision"]["boot_position_m"][0] = 999
    report["selected"]["action"]["speed_m_per_s"] = 999
    assert payload == original


def test_constructor_snapshots_model_actions_and_provenance(payload):
    filter_ = synthetic_filter()
    provenance = {"sources": {"example": "original"}}
    actions = copy.deepcopy(payload["candidate_actions"])
    inspector = RecoveryInspector(filter_, provenance=provenance, registered_actions=actions)
    before = inspector.inspect(payload)
    filter_.rules["C1_clip"] = ConstraintRule("C1_clip", 0.01, 0.8)
    provenance["sources"]["example"] = "changed"
    actions.clear()
    assert inspector.inspect(payload) == before


def test_returned_provenance_cannot_modify_future_reports(payload, inspector):
    before = copy.deepcopy(inspector.inspect(payload))
    returned = inspector.inspect(payload)
    returned["provenance"]["sources"].clear()
    assert inspector.inspect(payload) == before


def test_provenance_matches_normalised_source_content_and_request(payload, inspector):
    report = inspector.inspect(payload)
    sources = report["provenance"]["sources"]
    assert sources == {path: content_sha256(ROOT / path) for path in SOURCE_PATHS}
    normalised = json.dumps(validate_request(payload), sort_keys=True, allow_nan=False).encode()
    assert report["provenance"]["request_sha256"] == hashlib.sha256(normalised).hexdigest()
    reordered = dict(reversed(list(payload.items())))
    assert inspector.inspect(reordered)["provenance"]["request_sha256"] == report["provenance"]["request_sha256"]
    payload["declared_error"]["socket_bias_m"] += 0.001
    assert inspector.inspect(payload)["provenance"]["request_sha256"] != report["provenance"]["request_sha256"]


@pytest.mark.parametrize("stale", [True, False])
def test_installed_runtime_must_match_checkout_source(tmp_path, monkeypatch, stale):
    import assembly_recovery.recovery_inspector as module

    installed = tmp_path / "recovery_inspector.py"
    source = (ROOT / "src/assembly_recovery/recovery_inspector.py").read_text(encoding="utf-8")
    installed.write_text(source + ("\n# older installed build\n" if stale else ""),
                         encoding="utf-8", newline="\r\n")
    monkeypatch.setattr(module, "__file__", str(installed))
    if stale:
        with pytest.raises(InvalidRequest, match="Reinstall this checkout"):
            RecoveryInspector.from_repository(ROOT)
    else:
        loaded = RecoveryInspector.from_repository(ROOT)
        assert loaded.provenance["runtime_matches_repository"] is True
        runtime = loaded.provenance["runtime_sources"]
        assert runtime == {key: value for key, value in loaded.provenance["sources"].items()
                           if key.startswith("src/")}


def test_geometry_labels_never_serve_as_proof_of_calibration(payload, inspector):
    payload["context"].update(required_clips=1, geometry_id="looks_registered", cable_segments=46, physics_hz=8000)
    report = inspector.inspect(payload)
    assert report["scope"]["fit_geometry"] == "geometry_not_verified"
    assert report["scope"]["discretisation"] == "outside_measured_discretisation"
    assert report["scope"]["context_is_caller_declared"] is True


def test_demo_adapter_excludes_recorded_outcomes_and_unused_truth():
    payload = request_from_demo(DEMO, "E4")
    assert "recorded_job_outcome" not in payload
    assert "anchor_reaction_n" not in payload["decision"]
    assert "min_bend_radius_m" not in payload["decision"]
    assert "centreline_dropout_p" not in payload["declared_error"]
    validate_request(payload)


def test_cli_stdin_matches_api_report(payload, inspector):
    finished = run_cli("--input", "-", "--json", stdin=json.dumps(payload))
    assert finished.returncode == 0, finished.stderr
    assert finished.stderr == ""
    assert json.loads(finished.stdout) == inspector.inspect(payload)


def test_cli_returns_three_for_valid_abstention(payload):
    payload["declared_error"]["socket_bias_m"] = 0.5
    finished = run_cli("--input", "-", "--json", stdin=json.dumps(payload))
    assert finished.returncode == 3, finished.stderr
    assert json.loads(finished.stdout)["status"] == "abstained"
    assert finished.stderr == ""


@pytest.mark.parametrize("text", ['{"bad":', '{"schema": 1, "schema": 1}',
                                 '{"uncertainty": NaN}', '{"uncertainty": Infinity}', "[]", "null"])
def test_cli_bad_json_or_contract_returns_structured_error_on_stderr(text):
    finished = run_cli("--input", "-", "--json", stdin=text)
    assert finished.returncode == 2
    assert finished.stdout == ""
    assert json.loads(finished.stderr)["status"] == "invalid_request"
    assert "Traceback" not in finished.stderr


def test_cli_missing_file_returns_readable_error(tmp_path):
    finished = run_cli("--input", tmp_path / "missing.json")
    assert finished.returncode == 2
    assert finished.stdout == ""
    assert "Cannot inspect:" in finished.stderr
    assert "Traceback" not in finished.stderr


def test_cli_writes_a_reusable_example_and_never_overwrites_it(tmp_path):
    example = tmp_path / "payload.json"
    written = run_cli("--write-example", example, "--level", "E4")
    assert written.returncode == 0, written.stderr
    payload = json.loads(example.read_text(encoding="utf-8"))
    assert payload == request_from_demo(DEMO, "E4")
    inspected = run_cli("--input", example, "--json")
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["policies"]["filtered"]["action_index"] == 5
    original = example.read_bytes()
    refused = run_cli("--write-example", example, "--json")
    assert refused.returncode == 2
    assert json.loads(refused.stderr)["status"] == "invalid_request"
    assert example.read_bytes() == original


def test_cli_example_write_failure_is_an_error(tmp_path):
    finished = run_cli("--write-example", tmp_path / "missing" / "payload.json", "--json")
    assert finished.returncode == 2
    assert finished.stdout == ""
    assert json.loads(finished.stderr)["status"] == "invalid_request"


@pytest.mark.parametrize("axis", [[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [1.0, 0.0, 1e-9]])
def test_degenerate_repair_basis_fails_before_filter_arithmetic(payload, inspector, axis):
    payload["decision"]["insertion_axis"] = axis
    payload["run_direction_xy"] = [1.0, 0.0]
    with pytest.raises(InvalidRequest, match="must not be parallel"):
        inspector.inspect(payload)
    finished = run_cli("--input", "-", "--json", stdin=json.dumps(payload))
    assert finished.returncode == 2
    assert finished.stdout == ""
    assert json.loads(finished.stderr)["status"] == "invalid_request"


def test_cli_exposes_candidate_table_and_selection():
    finished = run_cli("--demo")
    assert finished.returncode == 0, finished.stderr
    assert "conservative: candidate 0" in finished.stdout
    assert "filtered: candidate 9" in finished.stdout
    assert "unfiltered: candidate 4" in finished.stdout
    assert "outside_fit_geometry" in finished.stdout
