"""Behavioral checks for the simulator-independent scripted cable controller."""
from dataclasses import replace

import numpy as np
import pytest

from assembly_recovery.cable_control import (
    CableControllerConfig,
    CableInsertionController,
    CableObservation,
)


def observation(time_s=0.0, **changes):
    default = CableObservation(
        time_s, (0.0, 0.0, 0.022), (0.0, 0.0, 0.0),
        (0.0, 0.0, -1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
    )
    return replace(default, **changes)


def test_visible_lateral_error_is_corrected_before_insertion():
    controller = CableInsertionController()
    obs = observation(tip_position=(0.003, 0.0, 0.022))
    first = controller.step(obs)
    next_command = controller.step(replace(obs, time_s=0.25))
    assert first.target_tip_position == obs.tip_position
    assert next_command.phase == "align"
    assert 0.0 < next_command.target_tip_position[0] < 0.003
    assert next_command.target_tip_position[2] == pytest.approx(0.022)
    assert np.linalg.norm(np.subtract(next_command.target_tip_position, first.target_tip_position)) <= 0.001 + 1e-12


def test_insertion_uses_declared_axis_instead_of_world_z():
    controller = CableInsertionController()
    obs = observation(
        tip_position=(0.978, 2.0, 3.0), seated_position=(1.0, 2.0, 3.0),
        insertion_axis=(2.0, 0.0, 0.0),
    )
    controller.step(obs)
    command = controller.step(replace(obs, time_s=0.25))
    assert command.target_tip_position == pytest.approx((0.979, 2.0, 3.0))
    assert command.phase == "insert"


def test_compensated_force_slows_motion_and_raw_force_remains_available():
    low = CableInsertionController()
    high = CableInsertionController()
    obs = observation()
    low.step(obs)
    high.step(obs)
    low_command = low.step(replace(obs, time_s=0.25))
    high_command = high.step(replace(obs, time_s=0.25, wrist_force_world=(0.0, 0.0, 6.0)))
    assert high_command.phase == "insert"
    assert high_command.target_tip_position[2] > low_command.target_tip_position[2]

    compensated = CableInsertionController()
    biased = replace(obs, wrist_force_world=(0.0, 0.0, 100.0), precontact_bias_world=(0.0, 0.0, 100.0))
    compensated.step(biased)
    command = compensated.step(replace(biased, time_s=0.25))
    assert command.compensated_axial_force_n == 0.0
    assert command.raw_force_norm_n == 100.0
    assert command.target_tip_position == low_command.target_tip_position
    # The independent runtime raw-load guard still rejects this observation.
    assert command.raw_force_norm_n > 20.0
    assert not command.terminal


def test_persistent_load_uses_at_most_two_retries_then_holds():
    controller = CableInsertionController()
    tip = np.array((0.0, 0.0, 0.022))
    history = []
    for i in range(80):
        command = controller.step(observation(i * 0.25, tip_position=tip, wrist_force_world=(0.0, 0.0, 9.0)))
        tip = np.asarray(command.target_tip_position)
        history.append(command)
        if command.terminal:
            break
    assert command.phase == "retries_exhausted"
    assert command.retries_started == 2
    assert any(c.phase == "retract" for c in history)
    stopped = controller.step(observation(25.0, tip_position=tip))
    assert stopped.target_tip_position == command.target_tip_position
    assert stopped.terminal


def test_deadline_uses_elapsed_time_and_is_terminal():
    controller = CableInsertionController()
    first = controller.step(observation(100.0))
    timed_out = controller.step(observation(130.0))
    assert timed_out.phase == "deadline"
    assert timed_out.terminal
    assert timed_out.target_tip_position == first.target_tip_position


def test_cannot_rewind_time_and_rejected_call_does_not_advance_target():
    controller = CableInsertionController()
    controller.step(observation(1.0))
    before = controller.step(observation(1.25))
    with pytest.raises(ValueError, match="rewind"):
        controller.step(observation(1.1))
    after = controller.step(observation(1.5))
    assert np.linalg.norm(np.subtract(after.target_tip_position, before.target_tip_position)) <= 0.001 + 1e-12


def test_clip_loss_is_terminal_and_is_not_automatically_repaired():
    controller = CableInsertionController(repair_waypoints=[(0.0, 0.0, 0.03)])
    first = controller.step(observation())
    failed = controller.step(observation(0.25, clip_retained=False, snag_visible=True))
    assert failed.phase == "clip_lost"
    assert failed.terminal
    assert failed.retries_started == 0
    assert failed.target_tip_position == first.target_tip_position


def test_verified_repair_waypoints_and_variable_tick_slew():
    waypoints = [(0.0, 0.0, 0.031), (0.003, 0.0, 0.031)]
    controller = CableInsertionController(repair_waypoints=waypoints)
    tip = np.array((0.0, 0.0, 0.022))
    t = 0.0
    previous = controller.step(observation(t, tip_position=tip, snag_visible=True))
    visited = [False, False]
    phases = {previous.phase}
    for i in range(160):
        dt = (0.07, 0.13, 0.2)[i % 3]
        t += dt
        command = controller.step(observation(t, tip_position=tip, snag_visible=True))
        target = np.asarray(command.target_tip_position)
        assert np.linalg.norm(target - np.asarray(previous.target_tip_position)) <= 0.004 * dt + 1e-12
        for k, point in enumerate(waypoints):
            visited[k] |= np.linalg.norm(target - point) < 0.0004
        tip = target
        previous = command
        phases.add(command.phase)
        if command.phase == "insert":
            break
    assert all(visited)
    assert {"retract", "repair", "align", "insert"} <= phases
    assert command.retries_started == 1
    assert not command.terminal


@pytest.mark.parametrize(
    "changes",
    [{"insertion_axis": (0.0, 0.0, 0.0)}, {"wrist_force_world": (0.0, np.nan, 0.0)}, {"time_s": np.inf}],
)
def test_invalid_observation_is_rejected(changes):
    with pytest.raises(ValueError):
        CableInsertionController().step(observation(**changes))


def test_invalid_waypoint_or_retry_budget_is_rejected():
    with pytest.raises(ValueError):
        CableInsertionController(repair_waypoints=[(0.0, np.nan, 0.0)])
    with pytest.raises(ValueError):
        CableControllerConfig(max_retries=3)


def test_duplicate_timestamp_preserves_motion_but_refreshes_raw_load():
    controller = CableInsertionController()
    first = controller.step(observation())
    duplicate = controller.step(observation(wrist_force_world=(0.0, 0.0, 100.0)))
    assert duplicate.target_tip_position == first.target_tip_position
    assert duplicate.retries_started == first.retries_started
    assert duplicate.raw_force_norm_n == 100.0


def test_target_speed_cannot_exceed_registered_four_mm_per_second():
    with pytest.raises(ValueError, match="4 mm/s"):
        CableControllerConfig(speed_m_per_s=0.0041)
