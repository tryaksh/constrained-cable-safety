"""CPU tests for the workbench session: loading, mutating, screening, reporting.

These compile no scene and run no physics. They cover the part of the tool that
decides WHAT is run - which cell, which loop, which request, and whether it is
allowed to run at all - because that is the part that can silently show an
engineer a different jig from the one it names.

The end-to-end check that the tool reproduces a committed result needs the
simulator and lives in ``scripts/workbench.py --self-check``, whose record is
``artifacts/showcase/tool.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assembly_recovery.cable_workbench_v7 import MOVABLE, WorkbenchSession

ROOT = Path(__file__).resolve().parents[1]

#: One registered request whose committed result is on disk in a full working
#: tree. The tests that need it skip when the run directory has been pruned.
REGISTERED = "RC1_l15_compliant4000_m0_E0_conservative_r0"
REGISTERED_LOOP = 0.0015


@pytest.fixture
def session():
    return WorkbenchSession.open(ROOT, loop_m=REGISTERED_LOOP, error_level="E0",
                                 supervisor="conservative")


def test_open_loads_the_registered_cell_at_an_accepted_loop(session):
    described = session.describe()
    assert described["cell"] == described["registered_cell"] == "RC1"
    assert described["installed_loop_m"] == REGISTERED_LOOP
    assert REGISTERED_LOOP in described["accepted_loops_m"]
    assert [clip["id"] for clip in described["clips"]] == ["c1", "c2", "c3", "c4", "c5"]
    assert described["mutated"] is False
    assert described["needs_screening"] is False
    assert described["screen"]["source"].endswith("cable_cell_screen_v6.json")


def test_open_defaults_to_a_loop_the_screen_accepted():
    loaded = WorkbenchSession.open(ROOT)
    assert loaded.loop_m in loaded._accepted_loops(loaded.screen, loaded.cell_id)
    assert loaded.needs_screening is False


def test_an_unaccepted_loop_loads_but_counts_as_a_mutation():
    loaded = WorkbenchSession.open(ROOT, loop_m=0.0075)
    assert loaded.mutated is True
    assert loaded.needs_screening is True
    assert "not one of the loops the screen accepted" in loaded.mutations[0]["note"]


def test_the_expanded_request_is_the_registered_one(session):
    case = session.case()
    assert case["id"] == REGISTERED
    assert case["supervisor"] == "conservative"
    assert case["error_level"] == "E0"
    assert case["installed_loop_m"] == REGISTERED_LOOP
    assert len(case["fixture_overrides"]["clips"]) == 5


@pytest.mark.skipif(not (ROOT / "artifacts/cable/routing-v6-s1" / REGISTERED
                         / "result.json").is_file(),
                    reason="the executed run directory is not in this working tree")
def test_the_expanded_request_matches_the_one_the_block_committed(session):
    committed = json.loads((ROOT / "artifacts/cable/routing-v6-s1" / REGISTERED / "result.json")
                           .read_text(encoding="utf-8"))["case"]
    case = session.case()
    assert {key: case.get(key) for key in committed} == committed


def test_settings_are_checked_against_what_was_declared(session):
    with pytest.raises(ValueError, match="not a declared error level"):
        session.set_level("E9")
    with pytest.raises(ValueError, match="not a registered supervisor"):
        session.set_supervisor("greedy")
    assert session.set_level("E4") == "E4"
    assert session.set_supervisor("unfiltered") == "unfiltered"
    assert session.case()["id"].endswith("_E4_unfiltered_r0")


def test_moving_a_clip_changes_the_cell_and_invalidates_the_screen(session):
    before = next(c for c in session.layout["clips"] if c["id"] == "c3")["up_m"]
    change = session.move_clip("c3", up_m=before+0.003)
    assert change["from"]["up_m"] == before
    assert change["to"]["up_m"] == pytest.approx(before+0.003)
    assert session.mutated is True
    assert session.needs_screening is True
    moved = next(c for c in session.layout["clips"] if c["id"] == "c3")
    assert moved["up_m"] == pytest.approx(before+0.003)
    # The candidate file the expansion reads has to move with it, or the request
    # would carry the cell that was NOT changed.
    candidate = next(e for e in session.candidates["layouts"] if e["id"] == "RC1")
    assert next(c for c in candidate["clips"] if c["id"] == "c3")["up_m"] == moved["up_m"]


def test_moving_a_clip_refuses_unknown_fields_and_unknown_clips(session):
    with pytest.raises(ValueError, match="movable fields"):
        session.move_clip("c3", colour=1.0)
    with pytest.raises(ValueError, match="not a clip"):
        session.move_clip("c9", up_m=0.001)
    assert session.mutated is False
    assert set(MOVABLE) == {"along_m", "across_m", "up_m", "bearing_rad"}


def test_changing_the_loop_invalidates_the_screen(session):
    change = session.set_loop(0.0045)
    assert change == {"what": "service loop", "from_m": REGISTERED_LOOP, "to_m": 0.0045}
    assert session.needs_screening is True


def test_a_cell_that_has_not_been_screened_cannot_be_routed(session):
    session.move_clip("c3", up_m=0.009)
    with pytest.raises(RuntimeError, match="has not passed a screen"):
        session.case()
    with pytest.raises(RuntimeError, match="has not passed a screen"):
        session.runtime()


def test_a_screened_mutated_cell_expands_again_and_says_it_is_mutated(session):
    session.move_clip("c3", up_m=0.009)
    # Stand in for the six-second settle the real screen runs; this test is about
    # what the session does with a pass, not about whether that cell installs.
    session.screen_result = {"passes": True, "source": "stub", "rerun_here": True}
    case = session.case()
    assert next(c for c in case["fixture_overrides"]["clips"]
                if c["id"] == "c3")["up_m"] == pytest.approx(0.009)
    assert session.describe()["mutated"] is True
    assert "MUTATED" in session.scope_line()


def test_the_report_carries_every_constraint_and_says_what_cell_it_came_from(session):
    outcome = json.loads((ROOT / "tests/data/workbench_outcome.json").read_text(encoding="utf-8")) \
        if (ROOT / "tests/data/workbench_outcome.json").is_file() else _stub_outcome()
    report = session.summarise(outcome, Path("nowhere"))
    assert report["request"] == REGISTERED
    assert report["cell"] == "RC1"
    assert report["mutated"] is False
    assert "not a hardware claim" in report["scope"]
    assert set(report["per_constraint"]) == {"C1_clip", "C2_bend", "C3_anchor"}
    assert report["per_constraint"]["C1_clip"]["motions_scored"] == 2
    assert report["per_constraint"]["C1_clip"]["total_spent_m"] == pytest.approx(0.009)
    assert report["per_constraint"]["C1_clip"]["largest_single_spend_fraction"] == pytest.approx(0.1)
    assert [step["step"] for step in report["per_step"]] == [0, 1]
    assert report["guards"] == {"privilege": 0, "mutation": 0}


def test_the_report_of_a_mutated_cell_refuses_to_look_registered(session):
    session.move_clip("c1", along_m=0.11)
    report = session.summarise(_stub_outcome(), Path("nowhere"))
    assert report["mutated"] is True
    assert report["mutations"][0]["clip"] == "c1"
    assert "no number from it belongs beside a published one" in report["scope"]


def _budget(headroom, spent):
    return {name: {"headroom_at_decision_m": headroom, "spent_by_this_motion_m": spent,
                   "spent_fraction": spent/headroom, "headroom_left_m": headroom-spent,
                   "units": "metres"}
            for name in ("C1_clip", "C2_bend", "C3_anchor")}


def _stub_outcome():
    """The shape ``run_case`` returns, with two decisions and nothing else."""
    step = {"abstained": False, "action_index": 0, "magnitude_m": 0.006, "headroom_m": 0.05,
            "motion_completed": True,
            "state_before": {"clips": {"required_retained": 5}}}
    return {
        "case": {"id": REGISTERED},
        "job": {"failure_reason": None, "elapsed_s": 21.7},
        "route_completed": True, "seated": True,
        "installed_clips": {"required_retained": 5},
        "terminal_clips": {"required_retained": 5, "lost": []},
        "clip_loss_attribution": {},
        "steps_offered": 5, "steps_issued": 2, "abstentions": 0,
        "issued": [{**step, "step": 0, "time_s": 2.0, "budget": _budget(0.05, 0.005)},
                   {**step, "step": 1, "time_s": 4.0, "budget": _budget(0.04, 0.004)}],
        "constraints": {name: {"state": "respected"}
                        for name in ("C1_clip", "C2_bend", "C3_anchor")},
        "privilege_guard": {"events": 0}, "mutation_guard": {"forbidden_events": 0},
    }
