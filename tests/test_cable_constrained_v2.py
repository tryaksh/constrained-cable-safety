"""CPU tests for the constrained-cable task construction, guards and controllers.

These cover geometry, accounting and control logic only. They do not compile a
simulator scene, run physics or establish any recovery result.
"""

from __future__ import annotations

import math
import types

import numpy as np
import pytest

from assembly_recovery.cable_constrained_v2 import (
    MutationGuard,
    capsule_chain_density,
    capsule_segment_mass,
    chain_turn_angles_deg,
    fit_chain,
    matched_guide,
    rounded_path,
)
from assembly_recovery.cable_recovery_control_v2 import (
    PHASE_CODE,
    CableAwareRules,
    ForceGuidedInsertion,
    RecoveryObservation,
    RepairMacro,
    ScriptedProgram,
    SlewReference,
    repair_library,
)
from assembly_recovery.cable_routes import route_length

CONTROLLER = {
    "speed_m_per_s": 0.004, "deadline_s": 40.0, "alignment_standoff_m": 0.018,
    "position_tolerance_m": 0.0003, "retract_distance_m": 0.006, "insertion_overtravel_m": 0.0003,
    "slowdown_force_n": 4.0, "retract_force_n": 15.0, "max_retries": 2,
}
AXIS = np.array([0.0, 0.0, -1.0])
RUN = np.array([1.0, 0.0, 0.0])


def observation(time_s, tip, seated, force=(0.0, 0.0, 0.0), **kwargs):
    fields = {
        "connector_contact_n": 0.0, "clip_contact_n": 0.0, "post_contact_n": 0.0,
        "anchor_reaction_world": np.zeros(3), "cable_centerline": np.zeros((3, 3)),
        "clip_retained": True, "clip_margin_m": 0.01, "witnessed": False,
    }
    fields.update(kwargs)
    return RecoveryObservation(time_s, np.asarray(tip, float), np.eye(3), np.asarray(seated, float),
                               AXIS, np.asarray(force, float), np.zeros(3), **fields)


def test_capsule_density_reaches_the_declared_total_mass():
    density = capsule_chain_density(0.05, 0.002, 0.02, 23)
    total = 23 * capsule_segment_mass(0.002, 0.02, density)
    assert total == pytest.approx(0.05, abs=1e-15)


def test_capsule_density_differs_from_the_plain_cylinder_formula():
    cylinder = 0.05 / (23 * 0.02) / (math.pi * 0.002**2)
    assert capsule_chain_density(0.05, 0.002, 0.02, 23) < cylinder


def test_capsule_density_rejects_impossible_requests():
    for args in ((0.0, 0.002, 0.02, 23), (0.05, 0.002, 0.02, 0), (0.05, 0.0, 0.02, 23)):
        with pytest.raises(ValueError):
            capsule_chain_density(*args)


def test_rounded_path_keeps_endpoints_and_shortens_a_corner():
    corner = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
    dense = rounded_path(corner, 0.2)
    assert dense[0] == [0, 0, 0] and dense[-1] == [1, 1, 0]
    assert route_length(dense) < route_length(corner)


def test_rounded_path_rejects_a_single_waypoint():
    with pytest.raises(ValueError):
        rounded_path([[0, 0, 0]], 0.1)


def test_fit_chain_gives_exact_chords_with_pinned_ends():
    guide = rounded_path([[0, 0, 0], [0.3, 0, 0], [0.3, 0.2, 0]], 0.05)
    points = fit_chain(guide, 20, 0.026)
    chords = np.linalg.norm(np.diff(points, axis=0), axis=1)
    assert np.allclose(chords, 0.026, atol=1e-9)
    assert np.allclose(points[0], guide[0]) and np.allclose(points[-1], guide[-1])


def test_fit_chain_rejects_an_unreachable_anchor():
    with pytest.raises(ValueError):
        fit_chain([[0, 0, 0], [1, 0, 0]], 4, 0.1)


def test_fit_chain_floor_clamp_keeps_the_chain_above_the_support():
    guide = rounded_path([[0, 0, 0.05], [0.2, 0, 0.0], [0.4, 0, 0.0]], 0.05)
    points = fit_chain(guide, 24, 0.02, floor_z=0.0)
    assert points[1:-1, 2].min() >= -1e-6


def test_chain_turn_angles_are_zero_on_a_straight_chain():
    straight = np.stack([np.linspace(0, 1, 6), np.zeros(6), np.zeros(6)], axis=1)
    assert np.allclose(chain_turn_angles_deg(straight), 0.0, atol=1e-9)


def test_chain_turn_angles_detect_a_right_angle():
    bent = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]], dtype=float)
    assert chain_turn_angles_deg(bent)[0] == pytest.approx(90.0)


def test_matched_guide_absorbs_surplus_length_into_the_chosen_leg():
    waypoints = [[0, 0, 0], [0.2, 0, 0], [0.5, 0, 0]]
    guide = matched_guide(waypoints, 0.03, 0.60, np.array([0.0, 1.0, 0.0]), 0.3, 1)
    assert route_length(guide) == pytest.approx(0.60, abs=1e-6)
    assert max(abs(p[1]) for p in guide) > 0.0


def test_matched_guide_rejects_a_route_longer_than_the_cable():
    with pytest.raises(ValueError):
        matched_guide([[0, 0, 0], [1, 0, 0]], 0.01, 0.5, np.array([0.0, 1.0, 0.0]), 0.3, 0)


def test_matched_guide_rejects_surplus_beyond_the_bow_limit():
    with pytest.raises(ValueError):
        matched_guide([[0, 0, 0], [0.1, 0, 0], [0.2, 0, 0]], 0.01, 5.0, np.array([0.0, 1.0, 0.0]), 0.01, 1)


def fake_scene():
    model = types.SimpleNamespace(
        eq_active0=np.ones(2), eq_obj1id=np.zeros(2), eq_obj2id=np.ones(2), eq_data=np.zeros((2, 11)),
        eq_type=np.zeros(2), actuator_ctrllimited=np.ones(3), actuator_ctrlrange=np.zeros((3, 2)),
        geom_contype=np.ones(4), geom_conaffinity=np.ones(4), body_mass=np.ones(5),
        dof_damping=np.zeros(6), opt=types.SimpleNamespace(gravity=np.array([0.0, 0.0, -9.81])))
    data = types.SimpleNamespace(time=0.0, qpos=np.zeros(7), qvel=np.zeros(6))
    return types.SimpleNamespace(model=model, data=data)


def test_mutation_guard_passes_a_clean_controller_call():
    scene = fake_scene()
    guard = MutationGuard(scene)
    guard.before_control()
    guard.after_control()
    assert guard.events == 0 and guard.report()["forbidden_events"] == 0


def test_mutation_guard_detects_a_controller_pose_write():
    scene = fake_scene()
    guard = MutationGuard(scene)
    guard.before_control()
    scene.data.qpos[0] = 1e-6
    guard.after_control()
    assert guard.events == 1 and "controller_wrote_qpos" in guard.reasons


def test_mutation_guard_detects_a_velocity_write_and_a_clock_move():
    scene = fake_scene()
    guard = MutationGuard(scene)
    guard.before_control()
    scene.data.qvel[2] = 0.5
    scene.data.time = 0.01
    guard.after_control()
    assert {"controller_wrote_qvel", "controller_moved_native_clock"} <= set(guard.reasons)


def test_mutation_guard_detects_an_attachment_and_a_gravity_change():
    scene = fake_scene()
    guard = MutationGuard(scene)
    scene.model.eq_active0[1] = 0
    scene.model.opt.gravity[2] = 0.0
    guard.before_control()
    guard.after_control()
    assert any(r.startswith("model_field_changed:eq_active0") for r in guard.reasons)
    assert any(r.endswith("opt.gravity") for r in guard.reasons)


def test_mutation_guard_detects_a_native_clock_rewind():
    scene = fake_scene()
    guard = MutationGuard(scene)
    guard.before_control()
    scene.data.time = -1.0
    guard.before_control()
    assert "native_clock_rewind" in guard.reasons


def test_slew_reference_respects_the_rate_limit():
    reference = SlewReference(np.zeros(3), 0.004)
    position = reference.toward([1.0, 0.0, 0.0], 0.02)
    assert np.linalg.norm(position) == pytest.approx(0.00008)


def test_slew_reference_lands_exactly_on_a_close_goal():
    reference = SlewReference(np.zeros(3), 0.004)
    assert np.allclose(reference.toward([1e-9, 0, 0], 0.02), [1e-9, 0, 0])


def test_repair_macro_offsets_use_the_run_axis_basis():
    macro = RepairMacro("m", ((0.02, 0.0, -0.01),))
    point = macro.waypoints(np.zeros(3), AXIS, RUN)[0]
    assert np.allclose(point, [0.02, 0.0, 0.01])


def test_repair_library_reads_declared_offsets():
    library = repair_library({"a": {"offsets_m": [[0, 0, 0]], "description": "d"}})
    assert library["a"].name == "a" and library["a"].description == "d"


def test_scripted_program_advances_only_after_the_declared_hold():
    program = ScriptedProgram([{"offset_m": [0, 0, 0], "hold_s": 0.1, "speed_m_per_s": 0.004},
                               {"offset_m": [0.01, 0, 0], "speed_m_per_s": 0.004}],
                              np.zeros(3), AXIS, RUN)
    program.step(0.0, np.zeros(3), 0.02)
    assert program.index == 0
    program.step(0.2, np.zeros(3), 0.02)
    assert program.index == 1 and not program.finished


def test_force_guided_insertion_retreats_on_axial_load_and_exhausts_retries():
    controller = ForceGuidedInsertion(CONTROLLER, np.zeros(3), AXIS)
    heavy = observation(0.0, np.zeros(3), [0, 0, -0.02], force=(0.0, 0.0, 20.0))
    for step in range(3):
        controller.step(observation(step * 0.02, np.zeros(3), [0, 0, -0.02]), 0.02)
        controller.step(heavy, 0.02)
        controller.phase = "insert"
    assert controller.retries == 2
    controller.step(heavy, 0.02)
    assert controller.terminal


def test_force_guided_insertion_stops_when_the_clip_is_lost():
    controller = ForceGuidedInsertion(CONTROLLER, np.zeros(3), AXIS)
    controller.step(observation(0.1, np.zeros(3), [0, 0, -0.02], clip_retained=False), 0.02)
    assert controller.terminal and controller.phase == "clip_lost"


def test_cable_aware_rules_pick_the_distal_macro_only_under_distal_load():
    macros = repair_library({"local_realign": {"offsets_m": []},
                             "slacken_arc": {"offsets_m": [[0.02, 0, -0.006]]}})
    rules = {"distal_contact_witness_n": 0.05, "distal_load_witness_n": 0.5,
             "distal_macro": "slacken_arc", "local_macro": "local_realign"}
    loaded = CableAwareRules(CONTROLLER, np.zeros(3), AXIS, macros, rules)
    assert loaded.on_witness(observation(1.0, np.zeros(3), [0, 0, -0.02], post_contact_n=0.2), RUN, 1.0) == "slacken_arc"
    plain = CableAwareRules(CONTROLLER, np.zeros(3), AXIS, macros, rules)
    assert plain.on_witness(observation(1.0, np.zeros(3), [0, 0, -0.02]), RUN, 1.0) == "local_realign"


def test_cable_aware_rules_choose_once_per_job():
    macros = repair_library({"local_realign": {"offsets_m": []}, "slacken_arc": {"offsets_m": [[0.02, 0, -0.006]]}})
    rules = {"distal_contact_witness_n": 0.05, "distal_load_witness_n": 0.5,
             "distal_macro": "slacken_arc", "local_macro": "local_realign"}
    controller = CableAwareRules(CONTROLLER, np.zeros(3), AXIS, macros, rules)
    controller.on_witness(observation(1.0, np.zeros(3), [0, 0, -0.02]), RUN, 1.0)
    assert controller.on_witness(observation(2.0, np.zeros(3), [0, 0, -0.02]), RUN, 2.0) is None
    assert controller.repairs_started == 1


def test_every_controller_phase_has_a_ledger_code():
    controller = ForceGuidedInsertion(CONTROLLER, np.zeros(3), AXIS)
    controller.step(observation(0.0, np.zeros(3), [0, 0, -0.02]), 0.02)
    assert controller.phase in PHASE_CODE
    assert PHASE_CODE["blind_insert"] == len(PHASE_CODE) - 1
