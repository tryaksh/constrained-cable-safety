"""The three safety constraints scored on one rollout.

The v3 study scored one constraint, clip retention, which is a global length
budget. One constraint cannot carry a claim about which representation a safety
check needs, because the answer plainly depends on what the constraint is made
of. Three are scored here on the same trajectory, chosen so that their shapes
differ as much as the task allows:

``C1`` clip retention      a GLOBAL LENGTH budget. Violated when the required
                           open clip is no longer retained. Computable in closed
                           form from a pose, which is why one scalar sufficed in
                           v3.
``C2`` minimum bend radius a LOCAL CURVATURE limit. Violated when the discrete
                           curvature of the centreline anywhere exceeds the
                           declared spec at any instant of the move. Published
                           industrial practice for a jacketed cable is 4-6x the
                           outer diameter static and 10-15x dynamic; this cable
                           is 4 mm OD, so 16-24 mm and 40-60 mm. No pose alone
                           determines it: it is a property of the whole shape.
``C3`` anchor load limit   a RATE-DEPENDENT dynamic limit. Violated when the peak
                           reaction at the strain relief exceeds the declared
                           limit. It depends on how the shape got where it is,
                           not only on where it is.

Every constraint is scored from the same rollout, so the factorial is contexts x
error level x actions and is not multiplied by three. None of them stops the job:
they are scored, and the job's own force abort is a separate, declared event that
censors them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: The three registered constraint ids, in contract order.
CONSTRAINTS = ("C1_clip", "C2_bend", "C3_anchor")

#: A constraint outcome on one request.
RESPECTED, VIOLATED, CENSORED = "respected", "violated", "censored"


def discrete_bend_radius(points) -> np.ndarray:
    """Circumradius through each interior triple of a polyline, in metres.

    The bend radius of a discretised rod is only defined up to its segment
    length: three points spaced ``L`` apart with turn angle ``theta`` lie on a
    circle of radius ``L/(2 sin(theta/2))``, so a discretisation cannot express a
    radius tighter than about ``L/2``. The caller must check the declared spec
    against ``representable_radius_m`` before quoting a violation rate.
    """
    p = np.asarray(points, dtype=float)
    if len(p) < 3:
        return np.array([np.inf])
    a = np.linalg.norm(p[1:-1]-p[:-2], axis=1)
    b = np.linalg.norm(p[2:]-p[1:-1], axis=1)
    c = np.linalg.norm(p[2:]-p[:-2], axis=1)
    s = 0.5*(a+b+c)
    area = np.sqrt(np.maximum(s*(s-a)*(s-b)*(s-c), 0.0))
    return np.where(area > 1e-14, a*b*c/(4*np.maximum(area, 1e-14)), np.inf)


def min_bend_radius(points) -> float:
    radii = discrete_bend_radius(points)
    finite = radii[np.isfinite(radii)]
    return float(finite.min()) if finite.size else float("inf")


def representable_radius_m(segment_length_m: float, max_turn_deg: float) -> float:
    """The tightest bend radius this discretisation can express at all.

    At the construction cap on the per-joint turn angle, the circumradius through
    three equally spaced nodes. A spec below this number is not a statement about
    a cable, it is a statement about a polyline.
    """
    turn = np.radians(float(max_turn_deg))
    return float(segment_length_m/(2*np.sin(turn/2))) if turn > 0 else float("inf")


@dataclass
class ConstraintScorer:
    """Running score of all three constraints over one rollout.

    Updated at every servo tick from the *true* state, never from the estimate.
    This is scoring, and the privilege guard is disarmed while it runs.
    """

    bend_radius_spec_m: float
    anchor_limit_n: float
    bend_radius_secondary_m: float = 0.0
    anchor_secondary_n: float = 0.0
    segment_length_m: float = 0.02
    max_turn_deg: float = 70.0

    min_bend_radius_m: float = float("inf")
    peak_anchor_n: float = 0.0
    clip_retained: bool = True
    ticks: int = 0
    #: Commanded detour distance travelled when each constraint first went, so a
    #: censored request still carries a right-censoring time for the survival view.
    first_violation_progress_m: dict = field(default_factory=dict)
    progress_m: float = 0.0

    def update(self, centreline, anchor_reaction_n: float, clip_retained: bool, progress_m: float):
        self.ticks += 1
        self.progress_m = float(progress_m)
        radius = min_bend_radius(centreline)
        if radius < self.min_bend_radius_m:
            self.min_bend_radius_m = radius
        self.peak_anchor_n = max(self.peak_anchor_n, float(anchor_reaction_n))
        self.clip_retained = bool(clip_retained)
        for name, violated in (("C1_clip", not clip_retained),
                               ("C2_bend", radius < self.bend_radius_spec_m),
                               ("C3_anchor", float(anchor_reaction_n) > self.anchor_limit_n)):
            if violated and name not in self.first_violation_progress_m:
                self.first_violation_progress_m[name] = float(progress_m)

    def labels(self, move_completed: bool, terminal_clip_retained: bool) -> dict:
        """The registered outcome of each constraint on this request.

        A request whose commanded detour was cut short by the job's force abort is
        CENSORED on any constraint it had not already violated: the action never
        got to test that constraint, and scoring it as respected is not true. The
        censoring progress is carried so a right-censored survival view is
        available without re-running anything.
        """
        violated = {
            "C1_clip": (not terminal_clip_retained) or ("C1_clip" in self.first_violation_progress_m),
            "C2_bend": self.min_bend_radius_m < self.bend_radius_spec_m,
            "C3_anchor": self.peak_anchor_n > self.anchor_limit_n,
        }
        out = {}
        for name in CONSTRAINTS:
            if violated[name]:
                state = VIOLATED
            elif move_completed:
                state = RESPECTED
            else:
                state = CENSORED
            out[name] = {
                "state": state,
                "violation_progress_m": self.first_violation_progress_m.get(name),
                "censoring_progress_m": None if state != CENSORED else self.progress_m,
            }
        return out

    def report(self) -> dict:
        return {
            "min_bend_radius_m": None if not np.isfinite(self.min_bend_radius_m) else self.min_bend_radius_m,
            "peak_anchor_reaction_n": self.peak_anchor_n,
            "terminal_clip_retained": self.clip_retained,
            "scored_ticks": self.ticks,
            "bend_radius_spec_m": self.bend_radius_spec_m,
            "bend_radius_secondary_m": self.bend_radius_secondary_m,
            "anchor_limit_n": self.anchor_limit_n,
            "anchor_secondary_n": self.anchor_secondary_n,
            "min_bend_radius_below_secondary": (np.isfinite(self.min_bend_radius_m)
                                                and self.min_bend_radius_m < self.bend_radius_secondary_m),
            "peak_anchor_above_secondary": self.peak_anchor_n > self.anchor_secondary_n,
            "representable_radius_m": representable_radius_m(self.segment_length_m, self.max_turn_deg),
        }
