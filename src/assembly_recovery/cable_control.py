"""Scripted cable insertion targets; no simulator writes or physical success claim.

The runtime enforces raw load limits and validates seating, grasp and retention.
Compensated force controls motion only; target slew is not a hard force ceiling.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np


def _vector(value: Sequence[float], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must contain three finite values")
    return result.copy()


@dataclass(frozen=True)
class CableControllerConfig:
    speed_m_per_s: float = 0.004
    deadline_s: float = 30.0
    alignment_standoff_m: float = 0.018
    position_tolerance_m: float = 0.0003
    retract_distance_m: float = 0.006
    insertion_overtravel_m: float = 0.0003
    slowdown_force_n: float = 2.0
    retract_force_n: float = 8.0
    max_retries: int = 2

    def __post_init__(self):
        positive = (
            self.speed_m_per_s, self.deadline_s, self.alignment_standoff_m,
            self.position_tolerance_m, self.retract_distance_m, self.retract_force_n,
        )
        if not all(np.isfinite(x) and x > 0 for x in positive):
            raise ValueError("Controller distances, speed, deadline and retract force must be positive")
        if self.speed_m_per_s > 0.004:
            raise ValueError("Target slew cannot exceed 4 mm/s")
        if not np.isfinite(self.insertion_overtravel_m) or self.insertion_overtravel_m < 0:
            raise ValueError("Insertion overtravel must be finite and nonnegative")
        if not np.isfinite(self.slowdown_force_n) or not 0 <= self.slowdown_force_n < self.retract_force_n:
            raise ValueError("Slowdown force must be below retract force")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 2:
            raise ValueError("At most two retries are supported")


@dataclass(frozen=True)
class CableObservation:
    time_s: float
    tip_position: Sequence[float]
    seated_position: Sequence[float]
    insertion_axis: Sequence[float]
    wrist_force_world: Sequence[float]
    precontact_bias_world: Sequence[float]
    snag_visible: bool = False
    clip_retained: bool = True


@dataclass(frozen=True)
class CableCommand:
    target_tip_position: tuple[float, float, float]
    phase: str
    retries_started: int
    raw_force_norm_n: float
    compensated_axial_force_n: float
    terminal: bool


class CableInsertionController:
    """Align observed poses, insert, and withdraw on axial load or a visible snag.

    The insertion axis points from entrance toward the seated tip position.
    Parameters are engineering defaults, to be registered for the actual task.
    Fixed-orientation motion is assumed; runtime owns tool orientation control.
    Repair waypoints are world-frame tip positions whose reach, slack, clearance
    and retention have already been verified externally. A visible snag triggers
    withdrawal followed by these waypoints, never an invented lift trajectory.
    Each corrective cycle consumes one retry, including preventive snag repair.
    """

    def __init__(
        self, config: CableControllerConfig | None = None,
        *, repair_waypoints: Sequence[Sequence[float]] = (),
    ):
        self.config = config or CableControllerConfig()
        self.waypoints = tuple(_vector(p, "repair waypoint") for p in repair_waypoints)
        self.phase = "align"
        self.retries_started = 0
        self._start_time: float | None = None
        self._last_time: float | None = None
        self._target: np.ndarray | None = None
        self._retract_goal: np.ndarray | None = None
        self._repair_pending = False
        self._waypoint_index = 0
        self._last_snag = False
        self._terminal = False
        self._last_command: CableCommand | None = None

    def _retry(self, tip, axis, use_repair):
        if self.retries_started >= self.config.max_retries:
            self.phase, self._terminal = "retries_exhausted", True
            return
        self.retries_started += 1
        self.phase = "retract"
        self._retract_goal = tip - axis * self.config.retract_distance_m
        self._repair_pending = use_repair
        self._waypoint_index = 0

    def step(self, observation: CableObservation) -> CableCommand:
        """Duplicate timestamps hold motion state while refreshing force telemetry."""
        t = observation.time_s
        if not np.isfinite(t):
            raise ValueError("time_s must be finite")
        tip = _vector(observation.tip_position, "tip position")
        seated = _vector(observation.seated_position, "seated position")
        axis = _vector(observation.insertion_axis, "insertion axis")
        length = np.linalg.norm(axis)
        if length < 1e-12:
            raise ValueError("Insertion axis must be nonzero")
        axis /= length
        raw = _vector(observation.wrist_force_world, "wrist force")
        bias = _vector(observation.precontact_bias_world, "precontact bias")
        axial = float(abs(np.dot(raw - bias, axis)))
        if self._last_time is not None:
            if t < self._last_time:
                raise ValueError("Controller time cannot rewind")
            if t == self._last_time:
                return replace(
                    self._last_command, raw_force_norm_n=float(np.linalg.norm(raw)),
                    compensated_axial_force_n=axial,
                )
        if self._start_time is None:
            self._start_time = t
            self._target = tip.copy()
        dt = 0.0 if self._last_time is None else t - self._last_time
        self._last_time = t
        cfg = self.config
        if not self._terminal:
            if not observation.clip_retained:
                self.phase, self._terminal = "clip_lost", True
            elif t - self._start_time >= cfg.deadline_s:
                self.phase, self._terminal = "deadline", True

        new_snag = observation.snag_visible and not self._last_snag and bool(self.waypoints)
        self._last_snag = observation.snag_visible
        if (
            not self._terminal and self.phase in ("align", "insert")
            and (axial >= cfg.retract_force_n or new_snag)
        ):
            self._retry(tip, axis, observation.snag_visible and bool(self.waypoints))

        goal = self._target.copy()
        speed = cfg.speed_m_per_s
        if not self._terminal:
            if self.phase == "retract":
                goal = self._retract_goal
                if np.linalg.norm(tip - goal) <= cfg.position_tolerance_m:
                    self.phase = "repair" if self._repair_pending else "align"
            elif self.phase == "repair":
                goal = self.waypoints[self._waypoint_index]
                if np.linalg.norm(tip - goal) <= cfg.position_tolerance_m:
                    self._waypoint_index += 1
                    if self._waypoint_index == len(self.waypoints):
                        self.phase = "align"
            elif self.phase == "align":
                distance = float(np.dot(seated - tip, axis))
                goal = seated - axis * max(distance, cfg.alignment_standoff_m)
                if np.linalg.norm(tip - goal) <= cfg.position_tolerance_m:
                    self.phase = "insert"
            elif self.phase == "insert":
                goal = seated + axis * cfg.insertion_overtravel_m
                fraction = (cfg.retract_force_n - axial) / (cfg.retract_force_n - cfg.slowdown_force_n)
                speed *= float(np.clip(fraction, 0.0, 1.0))
            delta = goal - self._target
            distance = float(np.linalg.norm(delta))
            if distance > 0:
                self._target += delta * min(1.0, speed * dt / distance)
        command = CableCommand(
            tuple(float(v) for v in self._target), self.phase, self.retries_started,
            float(np.linalg.norm(raw)), axial, self._terminal,
        )
        self._last_command = command
        return command
