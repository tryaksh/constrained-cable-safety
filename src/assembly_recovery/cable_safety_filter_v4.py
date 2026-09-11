"""A loadable safety layer for constrained-cable motion, and the envelope it implies.

The study measures which representation a safety check needs. This is the check
itself, packaged so something other than the study can call it: a planner, a
supervisor choosing among candidate motions, or a second study asking whether the
check still holds when motions are chained.

It is deliberately the cheap arm. The analytic budget plus a margin sized from
the estimator's declared covariance is what the measurement-robust control
barrier function literature prescribes, it costs one distance and one comparison,
and if the study finds it sufficient then this is the artefact worth shipping. The
learned arms are not packaged here: they need torch, their weights are not part of
the evidence record, and packaging a model this project may find unnecessary would
be the wrong thing to hand somebody.

Three things it does that a per-action yes/no cannot:

  ``verdict``    scores ALL THREE registered constraints, not just clip
                 retention, and says which one a motion would break.
  ``envelope``   maps the whole action space in one call, so a planner can see
                 the shape of what is allowed rather than probing it action by
                 action.
  ``budget``     reports how much of each constraint's headroom a motion spends,
                 which is what a multi-step plan actually needs: a step that is
                 individually safe can still leave nothing for the next one.

Using it with a real estimator. Every call takes a ``level``: a dict of what the
estimator says about its OWN error, not about the world. Three numbers are read
from it - ``socket_bias_m``, ``socket_jitter_m`` and ``centreline_occluded_m`` -
so any pose estimator that reports a systematic bias, a jitter standard deviation
and a worst-case node error can drive this directly. ``declared_error`` builds
one from those three numbers without needing the study's registered ladder. An
estimator that reports nothing gets a zero margin, which is the unsafe default and
is why it has to be passed explicitly rather than defaulted.

Scope. Fitted on one task, one connector, one cable model, in simulation. The
thresholds are properties of that; the interface is not. Read
``evidence/cable_perception_v4.json`` before quoting a number from it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from assembly_recovery.cable_constraints_v4 import CONSTRAINTS
from assembly_recovery.cable_study_v4 import action_displacement, b0plus_margin_m

#: What each constraint's headroom is measured in, and which way is safer.
HEADROOM_UNITS = {
    "C1_clip": ("metres of budget left before the fitted boot-to-anchor threshold",
                "larger is safer"),
    "C2_bend": ("metres of bend radius above the declared spec", "larger is safer"),
    "C3_anchor": ("newtons below the declared anchor limit", "larger is safer"),
}


def declared_error(socket_bias_m: float = 0.0, socket_jitter_m: float = 0.0,
                   centreline_occluded_m: float = 0.0, **extra) -> dict:
    """What an estimator says about its own error, in the form the filter reads.

    Three numbers, all of which a deployed pose or shape estimator can report:
    the systematic offset it believes it carries, the standard deviation of its
    jitter, and the worst-case position error it leaves on a node it cannot see.
    Nothing here is measured from the world; it is the estimator's own account of
    itself, which is exactly what a measurement-robust margin is built on.
    """
    return {"socket_bias_m": float(socket_bias_m), "socket_jitter_m": float(socket_jitter_m),
            "centreline_occluded_m": float(centreline_occluded_m), **extra}


@dataclass(frozen=True)
class ConstraintRule:
    """One fitted scalar rule, with the margin a declared covariance implies.

    ``shape`` is optional and off by default. When present the rule carries one
    extra state channel matched to the constraint's shape - the estimated minimum
    bend radius for a curvature limit, the estimated anchor reaction for a load
    limit - standardised and weighted as the fit chose. It is still one weighted
    sum and one comparison. The registered baseline has no shape term, and a
    filter built with ``shape_matched=False`` is exactly that baseline.
    """

    constraint: str
    threshold_m: float
    train_balanced_accuracy: float
    coverage_sigma: float = 2.0
    shape: dict | None = None

    def margin(self, level: dict) -> float:
        return b0plus_margin_m(level, self.coverage_sigma)

    def effective_threshold(self, level: dict) -> float:
        """The threshold a measurement-robust supervisor actually applies."""
        return self.threshold_m-self.margin(level)

    def shape_term(self, decision: dict) -> float:
        """The shape-matched channel's contribution, in metres of budget."""
        if not self.shape or not self.shape.get("weight_m"):
            return 0.0
        raw = float(decision.get(self.shape["channel"], 0.0))
        reference = self.shape["standardisation"]
        return float(self.shape["weight_m"]*self.shape["sign"]
                     * (raw-reference["mean"])/reference["scale"])


@dataclass
class SafetyFilter:
    """The analytic budget with a measurement-robust margin, per constraint.

    ``rules`` maps a constraint id to the scalar rule fitted for it. A constraint
    with no fitted rule is reported as ``unscored`` rather than silently passed:
    a filter that quietly approves what it cannot judge is worse than one that
    says so.
    """

    rules: dict[str, ConstraintRule]
    retract_distance_m: float
    source: dict = field(default_factory=dict)
    spec: dict = field(default_factory=dict)

    @classmethod
    def from_evidence(cls, fit_path, contract_path, base_path=None,
                      shape_matched: bool = False) -> SafetyFilter:
        """Load the fitted thresholds straight out of the study's evidence record.

        Nothing is recomputed here. If a number in the record changes, the filter
        changes with it, which is the only way a shipped filter and a published
        result can be kept from drifting apart.
        """
        fit = json.loads(Path(fit_path).read_text(encoding="utf-8"))
        contract = json.loads(Path(contract_path).read_text(encoding="utf-8-sig"))
        if base_path is None:
            base_path = Path(contract_path).parent/Path(contract["base_config"]["path"]).name
        base = json.loads(Path(base_path).read_text(encoding="utf-8-sig"))
        coverage = float(contract["predictors"]["B0plus"]["coverage_sigma"])
        rules = {}
        for constraint in CONSTRAINTS:
            block = fit["results"].get(constraint) or {}
            selection = block.get("selection") or {}
            key = "B0shape" if shape_matched and selection.get("B0shape") else "B0"
            fitted = selection.get(key)
            if not fitted or fitted.get("threshold_m") is None:
                continue
            shape = None
            if key == "B0shape" and fitted.get("shape_channel") and fitted.get("weight_m"):
                shape = {"channel": fitted["shape_channel"], "sign": float(fitted["shape_sign"]),
                         "weight_m": float(fitted["weight_m"]),
                         "standardisation": fitted["standardisation"]}
            rules[constraint] = ConstraintRule(
                constraint=constraint, threshold_m=float(fitted["threshold_m"]),
                train_balanced_accuracy=float(fitted["train_balanced_accuracy"]),
                coverage_sigma=coverage, shape=shape)
        return cls(
            rules=rules,
            retract_distance_m=float(base["force_guided_controller"]["retract_distance_m"]),
            source={"fit": Path(fit_path).as_posix(), "contract": Path(contract_path).as_posix(),
                    "fit_id": fit.get("id"), "created_on": fit.get("created_on"),
                    "arm": "B0shape (EXPLORATORY, post hoc)" if shape_matched else "B0plus",
                    "shape_matched": bool(shape_matched)},
            spec={name: contract["constraints"][name] for name in CONSTRAINTS
                  if name in contract["constraints"]})

    # -- the one geometric quantity every rule is built on ---------------------

    def endpoint_distance_m(self, decision: dict, action: dict, run_direction_xy) -> float:
        """Straight-line boot-to-anchor distance at the endpoint the motion reaches.

        Computed from the ESTIMATE the supervisor holds, exactly as the study
        computes it, so a filter call and a study row cannot disagree.
        """
        axis = np.asarray(decision["insertion_axis"], dtype=float)
        run = np.array([*run_direction_xy, 0.0], dtype=float)
        boot = np.asarray(decision["boot_position_m"], dtype=float)
        anchor = np.asarray(decision["anchor_site_m"], dtype=float)
        endpoint = boot+action_displacement(action, axis, run, self.retract_distance_m)
        return float(np.linalg.norm(endpoint-anchor))

    # -- the three things this exists to do ------------------------------------

    def verdict(self, decision: dict, action: dict, run_direction_xy, level: dict) -> dict:
        """Per-constraint judgement on one candidate motion, and the aggregate."""
        distance = self.endpoint_distance_m(decision, action, run_direction_xy)
        per_constraint = {}
        for name in CONSTRAINTS:
            rule = self.rules.get(name)
            if rule is None:
                per_constraint[name] = {"state": "unscored", "headroom_m": None,
                                        "why": "no rule was fitted for this constraint"}
                continue
            limit = rule.effective_threshold(level)
            shift = rule.shape_term(decision)
            score = distance+shift
            per_constraint[name] = {
                "state": "safe" if score <= limit else "refused",
                "endpoint_distance_m": distance,
                "shape_term_m": shift,
                "score_m": score,
                "effective_threshold_m": limit,
                "fitted_threshold_m": rule.threshold_m,
                "margin_m": rule.margin(level),
                "headroom_m": limit-score,
            }
        scored = [v for v in per_constraint.values() if v["state"] != "unscored"]
        refused = [name for name, v in per_constraint.items() if v["state"] == "refused"]
        return {
            "safe": bool(scored) and not refused,
            "refused_by": refused,
            "unscored": [name for name, v in per_constraint.items() if v["state"] == "unscored"],
            "binding_constraint": (min((v["headroom_m"], name)
                                       for name, v in per_constraint.items()
                                       if v["state"] != "unscored")[1] if scored else None),
            "constraints": per_constraint,
        }

    def is_safe(self, decision: dict, action: dict, run_direction_xy, level: dict) -> bool:
        return bool(self.verdict(decision, action, run_direction_xy, level)["safe"])

    def budget(self, decision: dict, action: dict, run_direction_xy, level: dict) -> dict:
        """How much of each constraint's headroom this motion would spend.

        A single-step filter answers "is this allowed". A plan needs "and what is
        left afterwards", because a step that is individually safe can still
        leave the next one nothing. ``spent_fraction`` is the share of the
        headroom available at the decision that this motion consumes; above 1.0
        the motion is refused.
        """
        here = self.endpoint_distance_m(decision, action, run_direction_xy)
        at_rest = float(decision["boot_to_anchor_m"])
        out = {}
        for name, rule in self.rules.items():
            limit = rule.effective_threshold(level)
            available = limit-at_rest
            spent = here-at_rest
            out[name] = {
                "headroom_at_decision_m": available,
                "spent_by_this_motion_m": spent,
                "spent_fraction": (spent/available) if abs(available) > 1e-12 else float("inf"),
                "headroom_left_m": limit-here,
                "units": HEADROOM_UNITS[name][0],
            }
        return out

    def envelope(self, decision: dict, run_direction_xy, level: dict, bounds: dict,
                 resolution: int = 24, constraint: str = "C1_clip") -> dict:
        """Map the safe region over the whole action space in one call.

        Returns the retreat and excursion axes, the bearing the slice is taken
        at, and a boolean grid. A planner that wants the shape of what is allowed
        should not have to discover it by probing one action at a time, and a
        reader who wants to know whether the rule is a sensible shape should be
        able to look at it.
        """
        rule = self.rules.get(constraint)
        if rule is None:
            raise ValueError(f"No fitted rule for {constraint!r}")
        low, high = bounds["retreat_m"]
        retreats = np.linspace(low, high, resolution)
        low, high = bounds["excursion_m"]
        excursions = np.linspace(low, high, resolution)
        bearings = np.linspace(0.0, 2*math.pi, resolution, endpoint=False)
        limit = rule.effective_threshold(level)
        grid = np.zeros((len(bearings), len(retreats), len(excursions)), dtype=bool)
        distance = np.zeros_like(grid, dtype=float)
        for b, bearing in enumerate(bearings):
            for r, retreat in enumerate(retreats):
                for e, excursion in enumerate(excursions):
                    action = {"retreat_m": float(retreat), "bearing_rad": float(bearing),
                              "excursion_m": float(excursion)}
                    value = self.endpoint_distance_m(decision, action, run_direction_xy)
                    distance[b, r, e] = value
                    grid[b, r, e] = value <= limit
        return {
            "constraint": constraint,
            "retreat_m": retreats.tolist(), "excursion_m": excursions.tolist(),
            "bearing_rad": bearings.tolist(),
            "safe": grid.tolist(), "endpoint_distance_m": distance.tolist(),
            "effective_threshold_m": limit,
            "safe_fraction": float(grid.mean()),
            "largest_safe_retreat_m": (float(retreats[np.flatnonzero(grid.any(axis=(0, 2)))[-1]])
                                       if grid.any() else None),
            "largest_safe_excursion_m": (float(excursions[np.flatnonzero(grid.any(axis=(0, 1)))[-1]])
                                         if grid.any() else None),
            "note": "Geometry only. The envelope is what the fitted rule allows, not what the "
                    "physics permits; the study's held-out false-safe rate is the measure of how "
                    "often those differ.",
        }

    def best_action(self, decision: dict, actions, run_direction_xy, level: dict,
                    prefer: str = "largest") -> dict | None:
        """The motion a supervisor should issue from the candidates it was given.

        ``largest`` takes the biggest commanded displacement among the safe ones,
        because a larger clearance is the more useful repair - the study's own
        registered supervisor procedure. ``safest`` takes the one with the most
        headroom instead. Returns None when nothing is safe, which is a real
        answer and not a failure.
        """
        axis = np.asarray(decision["insertion_axis"], dtype=float)
        run = np.array([*run_direction_xy, 0.0], dtype=float)
        safe = []
        for index, action in enumerate(actions):
            verdict = self.verdict(decision, action, run_direction_xy, level)
            if not verdict["safe"]:
                continue
            magnitude = float(np.linalg.norm(
                action_displacement(action, axis, run, self.retract_distance_m)))
            headroom = min(v["headroom_m"] for v in verdict["constraints"].values()
                           if v["state"] != "unscored")
            safe.append({"index": index, "action": action, "magnitude_m": magnitude,
                         "headroom_m": headroom, "verdict": verdict})
        if not safe:
            return None
        key = (lambda c: (c["magnitude_m"], -c["index"])) if prefer == "largest" \
            else (lambda c: (c["headroom_m"], -c["index"]))
        return max(safe, key=key)

    def report(self) -> dict:
        shaped = any(rule.shape for rule in self.rules.values())
        return {
            "kind": ("analytic budget with a measurement-robust margin and a shape-matched term"
                     if shaped else "analytic budget with a measurement-robust margin"),
            "shape_matched": shaped,
            "shape_matched_status": (
                "EXPLORATORY. The shape term is post hoc and is not one of the study's registered "
                "arms; a filter built without it is the registered baseline exactly."
                if shaped else "off; this is the registered baseline"),
            "rules": {name: {"threshold_m": rule.threshold_m,
                             "train_balanced_accuracy": rule.train_balanced_accuracy,
                             "coverage_sigma": rule.coverage_sigma,
                             "shape_channel": (rule.shape or {}).get("channel"),
                             "shape_weight_m": (rule.shape or {}).get("weight_m")}
                      for name, rule in self.rules.items()},
            "unscored": [name for name in CONSTRAINTS if name not in self.rules],
            "retract_distance_m": self.retract_distance_m,
            "source": self.source,
            "scope": "Fitted on one task, one connector and one cable model, in simulation. The "
                     "thresholds are properties of that. No hardware, no force-certified safety "
                     "claim, and no guarantee outside the registered action space.",
        }
