"""Explain the registered recovery policies from an estimate, without a simulator.

This is an advisory interface to the unchanged B0plus filter. A predicted pass
is not a physical safety guarantee. In particular, the five-clip study measured
failure of the threshold's transfer from its single-clip fitting geometry.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from assembly_recovery.cable_constraints_v4 import CONSTRAINTS
from assembly_recovery.cable_safety_filter_v4 import SafetyFilter
from assembly_recovery.cable_study_v3 import action_displacement, content_sha256

ERROR_FIELDS = ("socket_bias_m", "socket_jitter_m", "centreline_occluded_m")
ACTION_FIELDS = ("retreat_m", "bearing_rad", "excursion_m", "speed_m_per_s")
DECISION_FIELDS = ("boot_position_m", "anchor_site_m", "insertion_axis", "boot_to_anchor_m")
SOURCE_PATHS = (
    "evidence/cable_perception_v4.json", "configs/cable_perception_v4.json",
    "configs/cable_recovery_task_v2.json", "configs/cable_routing_v6.json",
    "src/assembly_recovery/cable_safety_filter_v4.py",
    "src/assembly_recovery/cable_study_v3.py", "src/assembly_recovery/cable_study_v4.py",
    "src/assembly_recovery/cable_constraints_v4.py",
    "src/assembly_recovery/recovery_inspector.py",
)


class InvalidRequest(ValueError):
    """An external request cannot be interpreted without making assumptions."""


def _object(value, required, optional=(), *, name):
    if not isinstance(value, dict):
        raise InvalidRequest(f"{name} must be an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise InvalidRequest(f"{name}: missing {sorted(missing)}, unknown {sorted(extra)}")


def _number(value, name, *, minimum=None, positive=False):
    # The broad numerical bound prevents overflow in geometry calculations. It
    # is an input-domain limit, not a physical limit or fitted safety threshold.
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or abs(value) > 1e6 or not math.isfinite(value)):
        raise InvalidRequest(f"{name} must be a finite number with magnitude <= 1e6")
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise InvalidRequest(f"{name} must be {'positive' if positive else f'>= {minimum}'}")
    return float(value)


def _vector(value, size, name, *, unit=False):
    if not isinstance(value, list) or len(value) != size:
        raise InvalidRequest(f"{name} must be an array of {size} numbers")
    result = [_number(v, name) for v in value]
    if unit and not math.isclose(math.hypot(*result), 1.0, abs_tol=1e-6):
        raise InvalidRequest(f"{name} must be a unit vector (tolerance 1e-6)")
    return result


def validate_request(request: dict) -> dict:
    """Return a detached, normalised request; never invent missing uncertainty.

    Positions and distances are metres, angles radians, times seconds. Unit
    vectors are required rather than silently normalised. Candidate order is
    significant: the registered policies break ties by the original index.
    """
    _object(request, ("schema", "request_id", "units", "context", "decision",
                      "run_direction_xy", "declared_error", "candidate_actions"), name="request")
    result = copy.deepcopy(request)
    if type(result["schema"]) is not int or result["schema"] != 1:
        raise InvalidRequest("schema must be the integer 1")
    if result["units"] != "m_rad_s":
        raise InvalidRequest("units must be 'm_rad_s' (metres, radians, seconds)")
    if not isinstance(result["request_id"], str) or not result["request_id"].strip():
        raise InvalidRequest("request_id must be a nonempty string")
    context = result["context"]
    _object(context, ("geometry_id", "required_clips", "cable_segments", "physics_hz", "task"),
            name="context")
    if not isinstance(context["geometry_id"], str) or not context["geometry_id"].strip():
        raise InvalidRequest("context.geometry_id must be a nonempty string")
    if context["task"] != "held_clip_preserving_seating":
        raise InvalidRequest("context.task must be 'held_clip_preserving_seating'")
    for field in ("required_clips", "cable_segments", "physics_hz"):
        if type(context[field]) is not int or not 1 <= context[field] <= 1000000:
            raise InvalidRequest(f"context.{field} must be a positive integer <= 1000000")
    decision = result["decision"]
    _object(decision, DECISION_FIELDS[:3], DECISION_FIELDS[3:], name="decision")
    for field in DECISION_FIELDS[:3]:
        decision[field] = _vector(decision[field], 3, f"decision.{field}", unit=field == "insertion_axis")
    distance = math.dist(decision["boot_position_m"], decision["anchor_site_m"])
    if "boot_to_anchor_m" in decision:
        declared = _number(decision["boot_to_anchor_m"], "decision.boot_to_anchor_m", minimum=0)
        if not math.isclose(declared, distance, rel_tol=0, abs_tol=1e-8):
            raise InvalidRequest("decision.boot_to_anchor_m disagrees with the supplied positions")
    decision["boot_to_anchor_m"] = distance
    result["run_direction_xy"] = _vector(result["run_direction_xy"], 2, "run_direction_xy", unit=True)
    _object(result["declared_error"], ERROR_FIELDS, name="declared_error")
    for field in ERROR_FIELDS:
        result["declared_error"][field] = _number(result["declared_error"][field],
                                                 f"declared_error.{field}", minimum=0)
    actions = result["candidate_actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 4096:
        raise InvalidRequest("candidate_actions must contain 1 to 4096 actions")
    for index, action in enumerate(actions):
        _object(action, ACTION_FIELDS, name=f"candidate_actions[{index}]")
        for field in ACTION_FIELDS:
            action[field] = _number(action[field], f"candidate_actions[{index}].{field}",
                                    minimum=None if field == "bearing_rad" else 0,
                                    positive=field == "speed_m_per_s")
    return result


def request_from_demo(demo: dict, level: str = "E0") -> dict:
    """Adapt a committed estimate; outcome data is deliberately excluded."""
    block = demo["levels"][level]
    return {
        "schema": 1, "request_id": block["case"], "units": "m_rad_s",
        "context": {"geometry_id": "RC1", "required_clips": 5, "cable_segments": 23,
                    "physics_hz": 4000, "task": "held_clip_preserving_seating"},
        "decision": {key: block["decision"][key] for key in DECISION_FIELDS},
        "run_direction_xy": block["run_direction_xy"],
        "declared_error": {key: block["declared_error"][key] for key in ERROR_FIELDS},
        "candidate_actions": demo["candidate_actions"],
    }


class RecoveryInspector:
    """Rank candidate repairs and expose the assumptions behind each choice.

    The conservative and filtered selections call the historical policy directly.
    Partial models abstain here even though the historical aggregate allowed a
    pass on its scored subset. No action is executed by this interface.
    """

    def __init__(self, filter_: SafetyFilter, *, provenance=None, registered_actions=None):
        self.filter = copy.deepcopy(filter_)
        self.provenance = copy.deepcopy(provenance or {})
        self.registered_actions = copy.deepcopy(registered_actions or [])

    @classmethod
    def from_repository(cls, root: str | Path) -> RecoveryInspector:
        root = Path(root)
        fitted = SafetyFilter.from_evidence(*(root / path for path in SOURCE_PATHS[:3]))
        contract = json.loads((root / "configs/cable_routing_v6.json").read_text(encoding="utf-8-sig"))
        return cls(fitted, provenance={"sources": {path: content_sha256(root / path) for path in SOURCE_PATHS},
                                       "hash_convention": "BOM-stripped, LF-normalised UTF-8 content"},
                   registered_actions=contract["route"]["candidate_actions"])

    def inspect(self, request: dict) -> dict:
        request = validate_request(request)
        decision, actions = request["decision"], request["candidate_actions"]
        run, error = request["run_direction_xy"], request["declared_error"]
        missing = [name for name in CONSTRAINTS if name not in self.filter.rules]
        for rule in self.filter.rules.values():
            if rule.shape:
                raise InvalidRequest("The inspector supports the registered B0plus model only")
            _number(rule.threshold_m, "model.threshold_m", positive=True)
            _number(rule.coverage_sigma, "model.coverage_sigma", minimum=0)
        _number(self.filter.retract_distance_m, "model.retract_distance_m", minimum=0)
        candidates = []
        for index, action in enumerate(actions):
            verdict = self.filter.verdict(decision, action, run, error)
            budget = self.filter.budget(decision, action, run, error)
            for entry in budget.values():
                if not math.isfinite(entry["spent_fraction"]):
                    entry["spent_fraction"] = None
                    entry["fraction_undefined_reason"] = "zero available headroom"
            displacement = action_displacement(action, np.asarray(decision["insertion_axis"]),
                                               np.array([*run, 0.0]), self.filter.retract_distance_m)
            candidates.append({
                "index": index, "action": action, "magnitude_m": float(np.linalg.norm(displacement)),
                "rule_status": "unscored" if missing else "allowed" if verdict["safe"] else "refused",
                "headroom_m": min((v["headroom_m"] for v in verdict["constraints"].values()
                                   if v["state"] != "unscored"), default=None),
                "binding_constraint": verdict["binding_constraint"], "refused_by": verdict["refused_by"],
                "unscored": verdict["unscored"], "constraints": verdict["constraints"], "budget": budget,
            })
        policies = {}
        for name, prefer in (("conservative", "safest"), ("filtered", "largest")):
            chosen = None if missing else self.filter.best_action(decision, actions, run, error, prefer=prefer)
            policies[name] = {"action_index": None if chosen is None else chosen["index"],
                              "abstained": chosen is None,
                              "reason": ("missing_constraint_rule" if missing else "no_candidate_allowed")
                              if chosen is None else "maximum_headroom" if name == "conservative"
                              else "largest_allowed_displacement"}
        unfiltered = max(candidates, key=lambda c: (c["magnitude_m"], -c["index"]))
        policies["unfiltered"] = {"action_index": unfiltered["index"], "abstained": False,
                                  "reason": "largest_displacement_without_consulting_filter"}
        chosen_index = policies["conservative"]["action_index"]
        context = request["context"]
        fit_scope = "outside_fit_geometry" if context["required_clips"] != 1 else "geometry_not_verified"
        model_scope = ("matches_declared_discretisation"
                       if context["cable_segments"] == 23 and context["physics_hz"] == 4000
                       else "outside_measured_discretisation")
        report = {
            "schema": 1, "request_id": request["request_id"], "units": request["units"],
            "request": copy.deepcopy(request),
            "status": "unscored" if missing else "abstained" if chosen_index is None else "ranked",
            "selected_policy": "conservative", "selected": None if chosen_index is None else candidates[chosen_index],
            "policies": policies, "candidates": candidates,
            "scope": {"mode": "advisory_only", "fit_geometry": fit_scope, "discretisation": model_scope,
                      "context_is_caller_declared": True,
                      "candidate_set": "registered_v6" if actions == self.registered_actions else "custom_unvalidated",
                      "interpretation": "Allowed means the fitted rule passes. It does not mean the move is physically safe.",
                      "transfer_evidence": "evidence/cable_routing_v6.json",
                      "limitations": ["Thresholds were fitted on single-clip layouts; five-clip transfer failed.",
                                      "Ranking alternatives at this estimate does not predict their later trajectories.",
                                      "C2 is scoped to the 23-segment cable at 4 kHz.",
                                      "Simulation only; held seating before release; no force-certified safety claim."]},
            "provenance": {**copy.deepcopy(self.provenance),
                           "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True,
                                                                       allow_nan=False).encode()).hexdigest(),
                           "model": self.filter.report()["rules"], "arm": "B0plus",
                           "retract_distance_m": self.filter.retract_distance_m},
        }
        # The API promises strict JSON, including at zero remaining headroom.
        json.dumps(report, allow_nan=False)
        return report
