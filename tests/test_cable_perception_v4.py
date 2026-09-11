"""CPU tests for the estimated observation interface and the privilege guard.

These check the parts that must agree between data collection and model fitting,
and the two properties the contract rests on: that the zero level reproduces the
privileged v3 interface exactly, and that a control-side read of a scoring-only
channel is detected. They compile no scene, run no physics and establish no study
result.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from assembly_recovery.cable_perception_v4 import (
    EpisodePerception,
    PerceptionLevel,
    PrivilegeGuard,
    occlusion_weights,
    rotation_about,
)

FIXTURE = {
    "clip_origin_world": [0.5, 0.0, 1.0],
    "clip_rotation_world": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    "clip_predicate": {"half_width_m": 0.006, "floor_height_m": -0.001,
                       "lip_height_m": 0.0125, "cable_radius_m": 0.002},
    "fixture_origin_world": [0.33, 0.0, 1.0],
}
CAMERA = {"eye_world_m": [0.0, -0.55, 1.55], "clip_length_m": 0.03,
          "bracket_half_m": [0.032, 0.045, 0.02], "sight_line_samples": 24,
          "sight_line_length_m": 0.15}


def straight_cable(n=24):
    return np.stack([np.linspace(0.33, 0.62, n), np.zeros(n), np.full(n, 1.002)], axis=1)


def test_zero_level_reproduces_the_privileged_interface_exactly():
    level = PerceptionLevel(id="E0")
    assert level.is_anchor
    perception = EpisodePerception(level, FIXTURE, CAMERA, seed=3, servo_dt=0.002, node_count=24)
    truth_socket = np.array([0.5, 0.01, 1.2])
    truth_axis = np.array([0.0, 0.0, -1.0])
    truth_line = straight_cable()
    for _ in range(20):
        perception.advance()
    assert np.array_equal(perception.socket_position(truth_socket), truth_socket)
    assert np.allclose(perception.insertion_axis(truth_axis), truth_axis, atol=0, rtol=0)
    estimate, weights = perception.centreline(truth_line)
    assert np.array_equal(estimate, truth_line)
    assert not weights.any()
    assert perception.scalar_force(3.25) == 3.25
    assert np.array_equal(perception.force(np.array([1.0, 2.0, 3.0])), [1.0, 2.0, 3.0])
    assert not perception.process_force_world_n.any()


def test_socket_bias_is_systematic_and_jitter_is_correlated():
    level = PerceptionLevel(id="E4", socket_bias_m=0.005, socket_jitter_m=0.001,
                            socket_correlation_s=0.25)
    perception = EpisodePerception(level, FIXTURE, CAMERA, seed=7, servo_dt=0.002, node_count=24)
    truth = np.zeros(3)
    assert math.isclose(float(np.linalg.norm(perception.socket_bias)), 0.005, rel_tol=1e-12)
    samples = []
    for _ in range(400):
        perception.advance()
        samples.append(perception.socket_position(truth))
    samples = np.asarray(samples)
    # The bias does not average away: the mean estimate stays a bias length from truth.
    assert 0.003 < float(np.linalg.norm(samples.mean(0))) < 0.007
    # The jitter is correlated in time, so consecutive samples are much closer to
    # each other than two independent draws of the same standard deviation.
    steps = np.linalg.norm(np.diff(samples, axis=0), axis=1)
    assert float(steps.mean()) < 0.001


def test_orientation_error_rotates_the_axis_by_the_declared_angle():
    level = PerceptionLevel(id="E", socket_orientation_deg=2.0)
    perception = EpisodePerception(level, FIXTURE, CAMERA, seed=1, servo_dt=0.002, node_count=24)
    truth = np.array([0.0, 0.0, -1.0])
    estimate = perception.insertion_axis(truth)
    angle = math.degrees(math.acos(float(np.clip(estimate @ truth, -1, 1))))
    assert 0.0 < angle <= 2.0 + 1e-9
    assert math.isclose(float(np.linalg.norm(estimate)), 1.0, rel_tol=1e-12)


def test_rotation_about_is_a_rotation():
    matrix = rotation_about([0.3, -0.4, 0.87], 0.31)
    assert np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-12)
    assert math.isclose(float(np.linalg.det(matrix)), 1.0, rel_tol=1e-12)


def test_occlusion_is_structured_by_geometry_not_uniform():
    line = straight_cable(40)
    # Push the middle of the cable down into the clip channel, which is the region
    # the fixture actually hides.
    inside = (np.abs(line[:, 0]-0.5) < 0.012)
    line[inside, 2] = 1.0 + 0.002
    weights = occlusion_weights(line, FIXTURE, CAMERA)
    assert weights.shape == (40,)
    assert weights.max() > 0.5, "the cable inside the clip must be occluded"
    assert weights.min() < 0.5, "the cable outside every blocker must be visible"
    assert weights[inside].mean() > weights[~inside].mean()


def test_occluded_nodes_get_the_larger_error_and_dropout_is_interpolated():
    line = straight_cable(40)
    inside = (np.abs(line[:, 0]-0.5) < 0.012)
    line[inside, 2] = 1.0 + 0.002
    level = PerceptionLevel(id="E4", centreline_visible_m=0.0002, centreline_occluded_m=0.01,
                            centreline_dropout_p=0.5)
    perception = EpisodePerception(level, FIXTURE, CAMERA, seed=11, servo_dt=0.002, node_count=40)
    estimate, weights = perception.centreline(line)
    error = np.linalg.norm(estimate-line, axis=1)
    hidden = weights > 0.5
    assert hidden.any() and (~hidden).any()
    assert error[hidden].mean() > 5*error[~hidden].mean()
    assert np.isfinite(estimate).all()


def test_process_force_is_not_an_estimate_and_is_correlated():
    level = PerceptionLevel(id="E", process_force_n=0.1, process_correlation_s=0.2)
    perception = EpisodePerception(level, FIXTURE, CAMERA, seed=5, servo_dt=0.002, node_count=24)
    trace = []
    for _ in range(500):
        perception.advance()
        trace.append(perception.process_force_world_n)
    trace = np.asarray(trace)
    assert float(np.linalg.norm(trace, axis=1).mean()) > 0.0
    steps = np.linalg.norm(np.diff(trace, axis=0), axis=1)
    assert float(steps.mean()) < float(np.linalg.norm(trace, axis=1).mean())


def test_privilege_guard_is_silent_outside_control_and_fires_inside_it():
    guard = PrivilegeGuard()
    channel = guard.channel("true_port_site", np.array([1.0, 2.0, 3.0]))
    assert np.array_equal(channel.read(), [1.0, 2.0, 3.0])
    assert guard.report() == {"events": 0, "reasons": [], "verdict": "clean"}
    guard.arm()
    channel.read()
    channel.read()
    guard.disarm()
    report = guard.report()
    assert report["events"] == 2
    assert report["reasons"] == ["true_port_site"]
    assert report["verdict"] == "privilege_violation"
    # Scoring after control is legitimate and must not add an event.
    channel.read()
    assert guard.report()["events"] == 2


def test_unregistered_level_fields_are_refused():
    with pytest.raises(ValueError, match="Unregistered perception level fields"):
        PerceptionLevel.from_dict({"id": "E", "socket_bias_m": 0.001, "made_up": 1.0})


def test_level_from_dict_round_trips_the_registered_fields():
    payload = {"id": "E2", "socket_bias_m": 0.002, "socket_jitter_m": 0.0004,
               "socket_orientation_deg": 1.0, "centreline_visible_m": 0.0006,
               "centreline_occluded_m": 0.004, "centreline_dropout_p": 0.1,
               "process_force_n": 0.04, "force_noise_fraction": 0.04,
               "force_noise_floor_n": 0.01}
    level = PerceptionLevel.from_dict(payload)
    assert not level.is_anchor
    for key, value in payload.items():
        assert getattr(level, key) == value
