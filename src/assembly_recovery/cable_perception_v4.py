"""Estimated observation interface and the fail-closed privilege guard.

The v3 study handed every arm the socket's exact pose at 500 Hz and the cable's
exact centreline. Nothing failed that a moving target could explain, because a
moving target that is measured exactly is simply tracked. This module removes
that: a controller and every predictor read an *estimate*, ground truth is
scoring-only, and a guard fails the request if control-side code touches a truth
channel.

Three declared error sources, swept independently by the v4 contract:

``socket``     a per-episode systematic bias plus temporally correlated jitter on
               the port position, and a per-episode rotation error on the
               insertion axis. Anchored to reported 6-DoF industrial pose
               estimation (about 2 mm and 0.6-1 deg) with the ladder reaching
               well past it.
``centreline`` node error structured by occlusion, derived geometrically from a
               declared camera pose and the fixture, plus whole-segment dropout.
               The occluded region is the cable inside the clip and behind the
               bracket, which is exactly the region every constraint depends on.
               This is not uniform noise and must not be replaced by it.
``process``    a stochastic disturbance force on the cable, so the shape moves
               for reasons no estimator can attribute.

Scope: this models how a perception system fails. It is not a perception system,
it renders no camera, and it makes no hardware claim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

#: Error channels a level may scale. A level of zero on every channel reproduces
#: the v3 privileged interface exactly and is the registered anchor.
ERROR_CHANNELS = ("socket", "centreline", "process")


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(vector))
    if norm < 1e-12:
        raise ValueError("Cannot normalise a zero-length direction")
    return vector/norm


def rotation_about(axis, angle_rad: float) -> np.ndarray:
    """Rodrigues rotation matrix about a unit axis."""
    axis = _unit(axis)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    cross = np.array([[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]])
    return c*np.eye(3)+s*cross+(1-c)*np.outer(axis, axis)


@dataclass(frozen=True)
class PerceptionLevel:
    """One registered point on the error ladder.

    Every field is a declared magnitude, not a fitted one. ``socket_bias_m`` and
    ``socket_orientation_deg`` are per-episode systematic errors; the jitter terms
    are the standard deviation of a stationary first-order autoregressive process
    whose correlation time is declared beside them.
    """

    id: str
    socket_bias_m: float = 0.0
    socket_jitter_m: float = 0.0
    socket_orientation_deg: float = 0.0
    socket_correlation_s: float = 0.25
    centreline_visible_m: float = 0.0
    centreline_occluded_m: float = 0.0
    centreline_dropout_p: float = 0.0
    process_force_n: float = 0.0
    process_correlation_s: float = 0.2
    force_noise_fraction: float = 0.0
    force_noise_floor_n: float = 0.0

    @property
    def is_anchor(self) -> bool:
        """True when this level reproduces the v3 privileged interface exactly."""
        return not any((self.socket_bias_m, self.socket_jitter_m, self.socket_orientation_deg,
                        self.centreline_visible_m, self.centreline_occluded_m,
                        self.centreline_dropout_p, self.process_force_n,
                        self.force_noise_fraction, self.force_noise_floor_n))

    @classmethod
    def from_dict(cls, payload: dict) -> PerceptionLevel:
        unknown = set(payload)-set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unregistered perception level fields: {sorted(unknown)}")
        return cls(**payload)


def occlusion_weights(centreline, fixture: dict, camera: dict) -> np.ndarray:
    """Per-node occlusion fraction in [0, 1], derived from geometry.

    A node is occluded when the straight line from it to the declared camera eye
    is blocked. Two blockers are modelled, both real parts of this fixture: the
    clip channel, whose walls and lip enclose the cable over the clip length, and
    the mount bracket, whose plate and riser stand between the camera and the
    cable near the port. The returned weight is a smooth occlusion fraction, so a
    node at the edge of a blocker is partly seen, which is how an estimator
    degrades rather than switching off at a boundary.

    Geometry only: a pinhole eye point and two box blockers, no rendering.
    """
    points = np.asarray(centreline, dtype=float)
    eye = np.asarray(camera["eye_world_m"], dtype=float)
    origin = np.asarray(fixture["clip_origin_world"], dtype=float)
    rotation = np.asarray(fixture["clip_rotation_world"], dtype=float)
    predicate = fixture["clip_predicate"]
    local = (points-origin) @ rotation

    ramp = max(float(predicate["cable_radius_m"]), 1e-6)
    half_length = 0.5*float(camera["clip_length_m"])
    half_width = float(predicate["half_width_m"])
    lip = float(predicate["lip_height_m"])
    # Inside the clip channel the walls and the lip enclose the cable, so a node
    # there is hidden from any eye above the shelf. The fraction ramps over one
    # cable radius at each boundary instead of switching.
    along = np.clip((half_length-np.abs(local[:, 0]))/ramp, 0.0, 1.0)
    across = np.clip((half_width-np.abs(local[:, 1]))/ramp, 0.0, 1.0)
    below = np.clip((lip-local[:, 2])/ramp, 0.0, 1.0)
    inside_clip = along*across*below

    # Behind the bracket: the mount plate and riser stand between a camera placed
    # off to the side of the shelf and the cable close to the port. A node is
    # shadowed when its sight line passes through the plate footprint.
    plate = np.asarray(fixture["fixture_origin_world"], dtype=float)
    half = np.asarray(camera["bracket_half_m"], dtype=float)
    direction = eye-points
    span = np.linalg.norm(direction, axis=1, keepdims=True)
    direction = direction/np.maximum(span, 1e-12)
    shadow = np.zeros(len(points))
    # Probe the sight line at fixed distances, not at fractions of the distance to
    # the eye. The blockers are centimetres from the cable and the eye is most of
    # a metre away, so a fractional first step leaves the fixture entirely and the
    # shadow silently never fires.
    for step in np.linspace(0.0, float(camera["sight_line_length_m"]),
                            int(camera["sight_line_samples"]))[1:]:
        delta = np.abs(points+direction*step-plate)
        inside = np.clip((half-delta)/ramp, 0.0, 1.0)
        shadow = np.maximum(shadow, inside[:, 0]*inside[:, 1]*inside[:, 2])
    return np.clip(np.maximum(inside_clip, shadow), 0.0, 1.0)


class EpisodePerception:
    """The estimate a controller and every predictor read, for one request.

    One instance owns one request's random draws. The per-episode systematic
    terms are drawn once at construction, so they are a bias and not a noise that
    averages away over the move; the jitter terms are advanced at each
    observation tick with a declared correlation time.
    """

    def __init__(self, level: PerceptionLevel, fixture: dict, camera: dict, seed: int,
                 servo_dt: float, node_count: int):
        self.level = level
        self.fixture = fixture
        self.camera = camera
        self.servo_dt = float(servo_dt)
        self.generator = np.random.default_rng(seed)
        self.node_count = int(node_count)

        self.socket_bias = (_unit(self.generator.normal(size=3))*level.socket_bias_m
                            if level.socket_bias_m else np.zeros(3))
        self.axis_rotation = (rotation_about(self.generator.normal(size=3),
                                             math.radians(level.socket_orientation_deg))
                              if level.socket_orientation_deg else np.eye(3))
        self._jitter = np.zeros(3)
        self._process = np.zeros(3)
        # An estimator's error on a hidden node is persistent, not resampled every
        # frame, because the same occlusion is there every frame. Visible nodes
        # get the same treatment at their own much smaller magnitude.
        self._node_bias = self.generator.normal(size=(self.node_count, 3))
        self.dropout_mask = self.generator.random(self.node_count) < level.centreline_dropout_p
        self._weights = None
        self.ticks = 0

    @staticmethod
    def _retain(correlation_s: float, dt: float) -> float:
        return math.exp(-dt/correlation_s) if correlation_s > 0 else 0.0

    def advance(self):
        """Step the temporally correlated terms by one observation tick."""
        level = self.level
        if level.socket_jitter_m:
            keep = self._retain(level.socket_correlation_s, self.servo_dt)
            innovation = math.sqrt(max(1.0-keep*keep, 0.0))*level.socket_jitter_m
            self._jitter = keep*self._jitter+innovation*self.generator.normal(size=3)
        if level.process_force_n:
            keep = self._retain(level.process_correlation_s, self.servo_dt)
            innovation = math.sqrt(max(1.0-keep*keep, 0.0))*level.process_force_n
            self._process = keep*self._process+innovation*self.generator.normal(size=3)
        self.ticks += 1

    @property
    def process_force_world_n(self) -> np.ndarray:
        """The disturbance force applied to the cable this tick. Not an estimate."""
        return self._process.copy()

    def socket_position(self, truth) -> np.ndarray:
        return np.asarray(truth, dtype=float)+self.socket_bias+self._jitter

    def insertion_axis(self, truth) -> np.ndarray:
        return _unit(self.axis_rotation @ np.asarray(truth, dtype=float))

    def centreline(self, truth) -> tuple[np.ndarray, np.ndarray]:
        """Estimated node positions and the per-node occlusion weight.

        A dropped node is not deleted: it is reported at the position a simple
        estimator would infer for it, the straight-line interpolation between its
        surviving neighbours. The weights are returned beside the estimate so a
        model that wants to know which nodes were guessed can be given that too.
        """
        points = np.asarray(truth, dtype=float)
        level = self.level
        if level.is_anchor:
            return points.copy(), np.zeros(len(points))
        if self._weights is None or len(self._weights) != len(points):
            self._weights = occlusion_weights(points, self.fixture, self.camera)
        weights = self._weights
        scale = (level.centreline_visible_m
                 + (level.centreline_occluded_m-level.centreline_visible_m)*weights)
        estimate = points+self._node_bias[:len(points)]*scale[:, None]
        mask = self.dropout_mask[:len(points)] & (weights > 0.5)
        if mask.any() and not mask.all():
            index = np.arange(len(points))
            keep = ~mask
            for column in range(3):
                estimate[mask, column] = np.interp(index[mask], index[keep], estimate[keep, column])
        return estimate, weights

    def force(self, truth) -> np.ndarray:
        """A force channel with declared sensor noise. Force is measured, not seen."""
        truth = np.asarray(truth, dtype=float)
        level = self.level
        if not level.force_noise_fraction and not level.force_noise_floor_n:
            return truth.copy()
        scale = level.force_noise_floor_n+level.force_noise_fraction*float(np.linalg.norm(truth))
        return truth+self.generator.normal(size=truth.shape)*scale

    def scalar_force(self, truth: float) -> float:
        level = self.level
        if not level.force_noise_fraction and not level.force_noise_floor_n:
            return float(truth)
        scale = level.force_noise_floor_n+level.force_noise_fraction*abs(float(truth))
        return float(max(0.0, float(truth)+self.generator.normal()*scale))


class PrivilegeViolation(RuntimeError):
    """Raised when control-side code reads a scoring-only truth channel."""


@dataclass
class PrivilegeGuard:
    """Fail-closed detector for control-side reads of a scoring-only channel.

    Built the same way as ``MutationGuard``: fail closed, count the event and
    prove it fires with a positive control. A truth value stays reachable for
    scoring at any time; what is forbidden is reading it from inside a controller
    or predictor call, and that window is exactly when the guard is armed.
    """

    armed: bool = False
    events: int = 0
    reasons: list = field(default_factory=list)

    def arm(self):
        self.armed = True

    def disarm(self):
        self.armed = False

    def record(self, name: str):
        self.events += 1
        if name not in self.reasons:
            self.reasons.append(name)

    def channel(self, name: str, value) -> TruthChannel:
        return TruthChannel(name, value, self)

    def report(self) -> dict:
        return {"events": self.events, "reasons": list(self.reasons),
                "verdict": "clean" if self.events == 0 else "privilege_violation"}


@dataclass
class TruthChannel:
    """A scoring-only value that records any read taken while control is armed."""

    name: str
    value: object
    guard: PrivilegeGuard | None = None

    def read(self):
        if self.guard is not None and self.guard.armed:
            self.guard.record(self.name)
        return self.value
