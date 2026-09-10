"""Complete-job bookkeeping for the separately versioned cable extension.

The caller supplies actual native measurements and audited mutation counters.
This does not implement contact sensing, perception, a clip model, or control.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CableJobLimits:
    deadline_s: float = 30.0
    dwell_s: float = 0.5
    position_tolerance_m: float = 0.001
    orientation_tolerance_rad: float = 0.03
    wrist_force_n: float = 20.0
    plug_force_n: float = 20.0
    anchor_force_n: float = 15.0
    contact_witness_n: float = 0.05
    stall_window_s: float = 0.5
    minimum_commanded_progress_m: float = 0.001
    maximum_new_progress_m: float = 0.0001

    def __post_init__(self):
        if any(not math.isfinite(v) or v <= 0 for v in vars(self).values()):
            raise ValueError("All job limits must be finite and positive")
        if self.dwell_s > self.deadline_s:
            raise ValueError("Dwell exceeds the job deadline")


@dataclass(frozen=True)
class CableSample:
    time_s: float
    dt_s: float
    seating_error_m: float
    seating_angle_rad: float
    insertion_depth_m: float
    commanded_depth_m: float
    wrist_force_n: float
    plug_force_n: float
    anchor_force_n: float
    connector_contact_n: float
    post_contact_n: float
    clip_retained: bool
    grasp_retained: bool
    engagement_valid: bool
    forbidden_events: int = 0


@dataclass
class CableJob:
    limits: CableJobLimits = field(default_factory=CableJobLimits)
    elapsed_s: float = 0.0
    dwell_s: float = 0.0
    status: str = "active"
    failure_reason: str | None = None
    first_witness_s: float | None = None
    witness_type: str | None = None
    samples: int = 0
    _window: list[CableSample] = field(default_factory=list, repr=False)

    def update(self, sample: CableSample) -> str:
        if self.status != "active":
            return self.status
        values = [
            v
            for k, v in vars(sample).items()
            if k not in ("clip_retained", "grasp_retained", "engagement_valid", "forbidden_events")
        ]
        if not all(math.isfinite(v) for v in values) or sample.dt_s <= 0:
            return self.fail("invalid_native_sample")
        if sample.forbidden_events < 0 or type(sample.forbidden_events) is not int:
            return self.fail("invalid_mutation_counter")
        if any(
            getattr(sample, k) < 0
            for k in (
                "seating_error_m",
                "seating_angle_rad",
                "wrist_force_n",
                "plug_force_n",
                "anchor_force_n",
                "connector_contact_n",
                "post_contact_n",
            )
        ):
            return self.fail("invalid_native_sample")
        if not math.isclose(sample.time_s, self.elapsed_s + sample.dt_s, rel_tol=1e-8, abs_tol=1e-8):
            return self.fail("missing_or_repeated_native_sample")
        self.elapsed_s = sample.time_s
        self.samples += 1
        # Safety/retention take precedence over simultaneous seating and deadline.
        checks = (
            (sample.forbidden_events > 0, "forbidden_state_change"),
            (not sample.grasp_retained, "lost_grasp"),
            (not sample.clip_retained, "lost_required_clip"),
            (sample.anchor_force_n > self.limits.anchor_force_n, "prior_connection_load_abort"),
            (
                sample.wrist_force_n > self.limits.wrist_force_n or sample.plug_force_n > self.limits.plug_force_n,
                "force_abort",
            ),
        )
        for failed, reason in checks:
            if failed:
                return self.fail(reason)
        seated = (
            sample.engagement_valid
            and sample.seating_error_m <= self.limits.position_tolerance_m
            and sample.seating_angle_rad <= self.limits.orientation_tolerance_rad
        )
        self.dwell_s = self.dwell_s + sample.dt_s if seated else 0.0
        if self.dwell_s + 1e-10 >= self.limits.dwell_s:
            self.status = "completed"
            return self.status
        if self.elapsed_s + 1e-10 >= self.limits.deadline_s:
            return self.fail("deadline")
        self._window.append(sample)
        while len(self._window) > 1 and self._window[1].time_s <= sample.time_s - self.limits.stall_window_s:
            self._window.pop(0)
        if (
            self.first_witness_s is None
            and sample.time_s - self._window[0].time_s + sample.dt_s >= self.limits.stall_window_s
        ):
            first = self._window[0]
            command = sample.commanded_depth_m - first.commanded_depth_m
            progress = max(s.insertion_depth_m for s in self._window) - first.insertion_depth_m
            sustained_connector = all(s.connector_contact_n > self.limits.contact_witness_n for s in self._window)
            sustained_post = all(s.post_contact_n > self.limits.contact_witness_n for s in self._window)
            if (
                command >= self.limits.minimum_commanded_progress_m
                and progress <= self.limits.maximum_new_progress_m
                and (sustained_connector or sustained_post)
            ):
                self.first_witness_s = sample.time_s
                self.witness_type = "connector_contact_stall" if sustained_connector else "distal_post_motion_stall"
        return self.status

    def fail(self, reason: str) -> str:
        if self.status == "active":
            self.status = "failed"
            self.failure_reason = reason
        return self.status

    def report(self) -> dict:
        return {k: v for k, v in vars(self).items() if k not in ("limits", "_window")}
