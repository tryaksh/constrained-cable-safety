"""Registered support, error ladder, arms and metrics for the perception study.

The v3 study answered one question and left one corner: every arm was handed the
socket's exact pose at 500 Hz and the cable's exact shape, so a scalar over that
state tied everything richer. This module holds everything that must be identical
between collection and fitting for the question that corner poses:

  HOW MUCH MUST A SAFETY CHECK SEE?

  As the state estimate degrades the way real perception degrades, where does a
  predicate over richer observations start to beat a scalar over estimated state,
  and does that crossover move with the SHAPE of the constraint?

It runs no physics and fits no model. The v3 support is preserved verbatim as the
first five layouts, so the zero-error level of this study reproduces the v3 block
on those cells and is a checkable anchor rather than a claim.

Prior work this study positions against, credited and not re-derived:
measurement-robust control barrier functions bound worst-case safety under a
bounded state-estimation error for known dynamics, and the B0+ arm below is an
application of that idea to this predicate, not a contribution. Hand-chosen
reduced states for deformable objects are standard practice and assume their
sufficiency; what is measured here is that assumption, against a safety
constraint rather than a task reward.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from assembly_recovery.cable_constraints_v4 import CENSORED, CONSTRAINTS, VIOLATED
from assembly_recovery.cable_study_v3 import (  # re-exported: identical construction on purpose
    HALTON_BASES,
    action_displacement,
    content_sha256,
    finite,
    halton,
    raw_sha256,
    repair_basis,
)

#: Features offered to the calibrated feature model, computed from the ESTIMATE.
#: The v3 fourteen are kept in their v3 order so the two blocks are comparable,
#: and four perception-aware channels are appended.
FEATURE_NAMES = (
    "endpoint_boot_to_anchor_m",
    "decision_boot_to_anchor_m",
    "retreat_m",
    "excursion_m",
    "bearing_sin",
    "bearing_cos",
    "installed_loop_m",
    "clip_margin_m",
    "routed_length_m",
    "depth_along_axis_m",
    "anchor_reaction_n",
    "cable_boot_load_n",
    "connector_contact_n",
    "shelf_contact_n",
    "min_bend_radius_m",
    "occluded_node_fraction",
    "declared_socket_sigma_m",
    "declared_centreline_sigma_m",
)

#: Features the force-only arm may see. No vision channel appears here. "Feel the
#: Tension" proposes force as the fallback when vision fails under occlusion; this
#: arm is what measures whether and when that fallback is the right answer.
FORCE_FEATURE_NAMES = (
    "anchor_reaction_n",
    "cable_boot_load_n",
    "wrist_force_n",
    "connector_contact_n",
    "shelf_contact_n",
    "retreat_m",
    "excursion_m",
    "bearing_sin",
    "bearing_cos",
)

#: Arms, with the sensing each one requires. The cost axis is reported beside
#: accuracy so "which is worth it" is answerable and not only "which is best".
ARMS = ("B0", "B0plus", "B2", "B1", "M", "Mh")

ARM_COST = {
    "B0": {"sensing": "estimated socket pose only", "parameters": 1,
           "inference": "one distance and one comparison"},
    "B0plus": {"sensing": "estimated socket pose plus the declared estimator covariance",
               "parameters": 1, "inference": "one distance, one margin and one comparison"},
    "B2": {"sensing": "force only: anchor reaction, boot load, wrist force. No vision.",
           "parameters": len(FORCE_FEATURE_NAMES)+1, "inference": "one linear form"},
    "B1": {"sensing": "estimated pose, estimated centreline summary and force",
           "parameters": len(FEATURE_NAMES)+1, "inference": "one linear form"},
    "M": {"sensing": "the whole estimated centreline, pose and action",
          "parameters": "MLP over 3N+10 inputs", "inference": "one forward pass"},
    "Mh": {"sensing": "the whole estimated centreline over a short history, pose and action",
           "parameters": "MLP over H*(3N)+10 inputs", "inference": "one forward pass"},
}


def perception_levels(contract: dict) -> list[dict]:
    return list(contract["error_model"]["levels"])


def level_by_id(contract: dict, level_id: str) -> dict:
    return next(level for level in contract["error_model"]["levels"] if level["id"] == level_id)


def build_contexts(contract: dict) -> list[dict]:
    """Every registered context, in a fixed order, with its held-out group.

    A context is one (layout, installed loop, port mount, decision pose, error
    level). Whole (layout, loop) families are held out; the error level is not a
    held-out factor, because the crossover is measured *along* it and every level
    must appear in train, dev and test. A (layout, loop) cell the screen rejected
    appears in ``excluded_groups`` and is never expanded into a request: it stays
    a recorded settling rejection in evidence/cable_layout_screen_v4.json.
    """
    support = contract["registered_support"]
    groups = contract["groups"]
    excluded = set(support.get("excluded_groups") or [])
    contexts = []
    for layout in support["layouts"]:
        for loop in support["installed_loop_m"]:
            group = f"{layout['id']}_l{int(round(loop*1000))}"
            if group in excluded:
                continue
            split = next(k for k in ("train", "dev", "test") if group in groups[k])
            for mount in support["port_mount"]:
                for pose in support["decision_pose"]:
                    for level in contract["error_model"]["levels"]:
                        contexts.append({
                            "id": f"{group}_{mount['id']}_{pose['id']}_{level['id']}",
                            "group": group, "split": split,
                            "layout_id": layout["id"],
                            "run_direction_xy": layout["run_direction_xy"],
                            "outward_xy": layout["outward_xy"],
                            "route_waypoints_along_across_m": layout["route_waypoints_along_across_m"],
                            "clip_along_m": layout["clip_along_m"],
                            "fixture_overrides": layout.get("fixture_overrides", {}),
                            "cable_overrides": layout.get("cable_overrides", {}),
                            "installed_loop_m": loop,
                            "mount_id": mount["id"], "port_compliance": mount.get("compliance"),
                            "decision_pose_id": pose["id"], "decision_at_s": pose["at_s"],
                            "error_level": level["id"],
                            "isolation": "all",
                        })
    return contexts


def isolation_contexts(contract: dict) -> list[dict]:
    """Single-factor cells: one error channel on at a time, at the top level.

    The ladder moves all three channels together, which measures the crossover.
    These cells attribute it. They are run on the held-out groups only, because
    attribution is read off the test split and adding them to training would mix
    a different error model into the fit.
    """
    isolation = contract["error_model"].get("isolation")
    if not isolation:
        return []
    out = []
    for context in build_contexts(contract):
        if context["split"] != "test" or context["error_level"] != isolation["at_level"]:
            continue
        for channel in isolation["channels"]:
            copy = dict(context)
            copy["id"] = f"{context['id']}_only{channel}"
            copy["isolation"] = channel
            out.append(copy)
    return out


def core_actions(design: dict) -> list[dict]:
    speed = design["clearance_speed_m_per_s"]
    return [{"retreat_m": retreat, "bearing_rad": round(math.radians(bearing_deg), 6),
             "excursion_m": excursion, "speed_m_per_s": speed}
            for retreat, bearing_deg, excursion in design["core_grid"]]


def action_from_unit(unit, bounds: dict, speed: float) -> dict:
    low, high = bounds["retreat_m"]
    retreat = low+(high-low)*float(unit[0])
    low, high = bounds["excursion_m"]
    excursion = low+(high-low)*float(unit[2])
    return {"retreat_m": round(retreat, 6), "bearing_rad": round(2*math.pi*float(unit[1]), 6),
            "excursion_m": round(excursion, 6), "speed_m_per_s": speed}


def sampled_actions(design: dict, context_index: int) -> list[dict]:
    count = design["sampled_actions"]
    points = halton(count, skip=design["halton_skip"]+context_index*count)
    return [action_from_unit(p, design["bounds"], design["clearance_speed_m_per_s"]) for p in points]


def build_cases(contract: dict) -> list[dict]:
    """The full registered request list: every context crossed with its actions."""
    design = contract["action_design"]
    shared = core_actions(design)
    cases, seed = [], contract["first_calibration_seed"]
    contexts = build_contexts(contract)+isolation_contexts(contract)
    for index, context in enumerate(contexts):
        actions = [("core", i, a) for i, a in enumerate(shared)]
        if context["isolation"] == "all":
            actions += [("halton", i, a) for i, a in enumerate(sampled_actions(design, index))]
        for kind, position, action in actions:
            case = {
                "id": f"{context['id']}_{kind}{position:02d}",
                "controller": "force_guided_insertion",
                "calibration_seed": seed,
                "perception_seed": seed+contract["perception_seed_offset"],
                "run_direction_xy": context["run_direction_xy"],
                "outward_xy": context["outward_xy"],
                "route_waypoints_along_across_m": context["route_waypoints_along_across_m"],
                "fixture_overrides": {**context["fixture_overrides"],
                                      "clip": {**context["fixture_overrides"].get("clip", {}),
                                               "along_m": context["clip_along_m"]}},
                "installed_loop_m": context["installed_loop_m"],
                "fixture_offset_m": [0.0, 0.0],
                "forced_macro": "parametric",
                "forced_macro_at_s": context["decision_at_s"],
                "repair_action": action,
                "error_level": context["error_level"],
                "error_isolation": context["isolation"],
                "study_context": context["id"], "study_group": context["group"],
                "study_split": context["split"], "action_kind": kind, "action_index": position,
                "gate": "S1",
                "purpose": "perception study: one action from one decision state at one error level",
            }
            if context["cable_overrides"]:
                case["cable_overrides"] = dict(context["cable_overrides"])
            if context["port_compliance"]:
                case["port_compliance"] = context["port_compliance"]
            cases.append(case)
            seed += 1
    return cases


def effective_level(contract: dict, level_id: str, isolation: str) -> dict:
    """The perception level actually applied, after single-factor isolation.

    ``isolation`` is ``all`` for the ladder, or the name of the one channel left
    on. Zeroing the others is done here and nowhere else, so collection and
    fitting cannot disagree about what a cell means.
    """
    level = dict(level_by_id(contract, level_id))
    if isolation == "all":
        return level
    channel_fields = {
        "socket": ("socket_bias_m", "socket_jitter_m", "socket_orientation_deg"),
        "centreline": ("centreline_visible_m", "centreline_occluded_m", "centreline_dropout_p"),
        "process": ("process_force_n",),
    }
    if isolation not in channel_fields:
        raise ValueError(f"Unregistered isolation channel {isolation!r}")
    for channel, fields in channel_fields.items():
        if channel == isolation:
            continue
        for field in fields:
            if field in level:
                level[field] = 0.0
    return level


def merge_runtime(base: dict, contract: dict) -> dict:
    runtime = json.loads(json.dumps(base))
    for key, value in contract["runtime_overrides"].items():
        if isinstance(value, dict) and isinstance(runtime.get(key), dict):
            runtime[key] = {**runtime[key], **value}
        else:
            runtime[key] = value
    runtime["id"] = contract["id"]
    runtime["scope"] = contract["scope"]
    runtime["perception"] = {"camera": contract["error_model"]["camera"],
                             "levels": contract["error_model"]["levels"],
                             "isolation": contract["error_model"].get("isolation"),
                             "history": contract["error_model"]["history"]}
    runtime["constraints"] = contract["constraints"]
    runtime["cases"] = build_cases(contract)
    return runtime


def feature_row(decision: dict, action: dict, context: dict, retract_distance_m: float,
                level: dict) -> dict:
    """Named observable features for one (estimated decision state, action) pair.

    Every geometric channel here is computed from the ESTIMATE. The two declared
    sigma channels are not measurements: they are what the estimator says about
    itself, which a deployed safety check would also have.
    """
    axis = np.asarray(decision["insertion_axis"], dtype=float)
    run = np.array([*context["run_direction_xy"], 0.0])
    boot = np.asarray(decision["boot_position_m"], dtype=float)
    anchor = np.asarray(decision["anchor_site_m"], dtype=float)
    endpoint_boot = boot+action_displacement(action, axis, run, retract_distance_m)
    bearing = float(action["bearing_rad"])
    return {
        "endpoint_boot_to_anchor_m": float(np.linalg.norm(endpoint_boot-anchor)),
        "decision_boot_to_anchor_m": float(decision["boot_to_anchor_m"]),
        "retreat_m": float(action["retreat_m"]),
        "excursion_m": float(action["excursion_m"]),
        "bearing_sin": math.sin(bearing),
        "bearing_cos": math.cos(bearing),
        "installed_loop_m": float(context["installed_loop_m"]),
        "clip_margin_m": float(decision["clip_margin_m"]),
        "routed_length_m": float(decision["routed_length_m"]),
        "depth_along_axis_m": float(decision["depth_along_axis_m"]),
        "anchor_reaction_n": float(decision["anchor_reaction_n"]),
        "cable_boot_load_n": float(decision["cable_boot_load_n"]),
        "connector_contact_n": float(decision["connector_contact_n"]),
        "shelf_contact_n": float(decision["shelf_contact_n"]),
        "min_bend_radius_m": float(decision["min_bend_radius_m"]),
        "occluded_node_fraction": float(decision["occluded_node_fraction"]),
        "declared_socket_sigma_m": float(level.get("socket_bias_m", 0.0)
                                         + level.get("socket_jitter_m", 0.0)),
        "declared_centreline_sigma_m": float(level.get("centreline_occluded_m", 0.0)),
        "wrist_force_n": float(decision["wrist_force_n"]),
    }


def b0plus_margin_m(level: dict, coverage_sigma: float) -> float:
    """The measurement-robust margin B0+ subtracts from the fitted threshold.

    Worst-case shift of the endpoint boot-to-anchor distance under the declared
    estimator error: the socket bias enters the estimated boot position directly,
    the jitter enters at a declared coverage factor, and the node error on the
    anchor-side estimate enters once. This is the engineering answer -
    measurement-robust CBF thinking applied to this predicate - and it is
    computed from the DECLARED covariance, never fitted on outcomes.
    """
    return float(level.get("socket_bias_m", 0.0)
                 + coverage_sigma*level.get("socket_jitter_m", 0.0)
                 + level.get("centreline_occluded_m", 0.0))


def commanded_magnitude(row, retract_distance_m: float) -> float:
    axis = np.asarray(row["decision"]["insertion_axis"], dtype=float)
    run = np.array([*row["run_direction_xy"], 0.0])
    return float(np.linalg.norm(action_displacement(row["action"], axis, run, retract_distance_m)))


def core_by_context(rows) -> dict[str, list[int]]:
    contexts: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        if row["action_kind"] == "core":
            contexts.setdefault(row["context"], []).append(i)
    return contexts


def constraint_truth(rows, constraint: str) -> tuple[np.ndarray, np.ndarray]:
    """(violated, observed) for one constraint. Censored rows are not observed."""
    states = [row["constraints"][constraint]["state"] for row in rows]
    violated = np.asarray([s == VIOLATED for s in states])
    observed = np.asarray([s != CENSORED for s in states])
    return violated, observed


def false_safe_at_coverage(scores, violated, observed, coverage: int) -> dict:
    """Of the `coverage` actions a predictor is most confident are safe, how many went.

    Censored actions are counted in the coverage - a predictor does not get to
    pick actions whose outcome nobody observed and be scored only on the rest -
    but they are excluded from the numerator, because their constraint was never
    tested. Both the rate and the censored share are returned, so a predictor
    that hides behind censoring is visible.
    """
    scores, violated, observed = np.asarray(scores), np.asarray(violated), np.asarray(observed)
    if coverage <= 0 or scores.size == 0:
        return {"rate": float("nan"), "coverage": int(coverage), "observed": 0, "censored": 0}
    order = np.argsort(scores, kind="stable")[:coverage]
    seen = observed[order]
    return {"rate": float(violated[order][seen].mean()) if seen.any() else float("nan"),
            "coverage": int(coverage), "observed": int(seen.sum()),
            "censored": int((~seen).sum())}


def per_context_regret(rows, safe: np.ndarray, constraint: str, retract_distance_m: float) -> dict:
    """The registered supervisor procedure, resolved per context.

    The supervisor keeps the actions its predictor calls safe and issues the one
    with the largest commanded displacement, because a larger clearance is the
    more useful repair. ``None`` means the predictor abstained: it called no
    action safe. An issued action whose constraint was censored is returned as
    ``"censored"`` and scored separately, never silently as a success.
    """
    out = {}
    for context, indices in core_by_context(rows).items():
        allowed = [i for i in indices if safe[i]]
        if not allowed:
            out[context] = None
            continue
        chosen = max(allowed, key=lambda i: (commanded_magnitude(rows[i], retract_distance_m),
                                             -rows[i]["action_index"]))
        state = rows[chosen]["constraints"][constraint]["state"]
        out[context] = "censored" if state == CENSORED else int(state == VIOLATED)
    return out


def ranking_regret(rows, safe: np.ndarray, constraint: str, retract_distance_m: float) -> dict:
    """The registered metric, with its own resolution reported beside it.

    ``resolution`` is one scored context: the smallest difference this metric can
    express. The contract's margin must be at least twice it, and
    ``check_margin_resolution`` refuses the block otherwise. The v3 block
    registered a margin exactly equal to its resolution and returned a verdict
    that was unresolvable by construction.
    """
    per_context = per_context_regret(rows, safe, constraint, retract_distance_m)
    scored = [v for v in per_context.values() if isinstance(v, int)]
    censored = sum(1 for v in per_context.values() if v == "censored")
    return {"contexts": len(per_context), "scored": len(scored),
            "abstentions": sum(1 for v in per_context.values() if v is None),
            "censored_choices": censored,
            "regret": sum(scored)/len(scored) if scored else float("nan"),
            "resolution": 1/len(scored) if scored else float("nan")}


def per_context_regret_matched(rows, scores, coverage_by_context: dict, constraint: str,
                              retract_distance_m: float) -> dict:
    """The supervisor procedure at matched coverage, per context.

    Declared in configs/cable_perception_v4_amendment_01.json, beside the
    registered metric and never instead of it. An arm's safe set here is its K
    lowest-risk actions in that context, where K is the number the analytic
    baseline calls safe there, floored at one. That makes the comparison a
    question about the ORDER an arm puts actions in rather than about where it
    happens to put its probability threshold - which is what the study is asking,
    and which the registered metric cannot answer for an arm that calls nothing
    safe.

    It is harsher than the registered metric on a cautious arm: an arm that
    correctly refuses every action in a dangerous context is made to issue one
    anyway. Read the two together.
    """
    scores = np.asarray(scores, dtype=float)
    out = {}
    for context, indices in core_by_context(rows).items():
        coverage = max(1, int(coverage_by_context.get(context, 0)))
        allowed = sorted(indices, key=lambda i: (scores[i], rows[i]["action_index"]))[:coverage]
        chosen = max(allowed, key=lambda i: (commanded_magnitude(rows[i], retract_distance_m),
                                             -rows[i]["action_index"]))
        state = rows[chosen]["constraints"][constraint]["state"]
        out[context] = "censored" if state == CENSORED else int(state == VIOLATED)
    return out


def ranking_regret_matched(rows, scores, coverage_by_context: dict, constraint: str,
                           retract_distance_m: float) -> dict:
    per_context = per_context_regret_matched(rows, scores, coverage_by_context, constraint,
                                             retract_distance_m)
    scored = [v for v in per_context.values() if isinstance(v, int)]
    return {"contexts": len(per_context), "scored": len(scored),
            "abstentions": 0,
            "censored_choices": sum(1 for v in per_context.values() if v == "censored"),
            "regret": sum(scored)/len(scored) if scored else float("nan"),
            "resolution": 1/len(scored) if scored else float("nan"),
            "status": "companion metric declared in "
                      "configs/cable_perception_v4_amendment_01.json; the registered decision rule "
                      "does not read it"}


def coverage_by_context(rows, safe) -> dict:
    """How many actions the baseline calls safe in each context."""
    safe = np.asarray(safe)
    return {context: int(safe[indices].sum())
            for context, indices in core_by_context(rows).items()}


def check_margin_resolution(margin: float, resolutions, required_ratio: float = 2.0) -> dict:
    """Refuse a margin the finest metric cannot resolve.

    This is the v3 defect, fixed in code rather than in prose: a margin equal to
    one context in twenty cannot separate a real difference from a single context
    changing hands. The block refuses to report a verdict unless the margin is at
    least ``required_ratio`` times the coarsest resolution in play.
    """
    finite_resolutions = [float(r) for r in resolutions if r is not None and np.isfinite(r)]
    worst = max(finite_resolutions) if finite_resolutions else float("inf")
    ok = bool(margin >= required_ratio*worst)
    return {"margin": float(margin), "coarsest_resolution": worst,
            "required_ratio": required_ratio, "required_margin": required_ratio*worst,
            "verdict": "usable" if ok else "refused_margin_below_resolution",
            "note": ("A margin below twice the coarsest metric resolution cannot separate signal "
                     "from one context changing hands. v3 registered a margin exactly equal to its "
                     "resolution and returned an unresolvable verdict; this check is why that "
                     "cannot happen again.")}


def cluster_bootstrap_difference(rows, scores_a, scores_b, safe_a, constraint: str,
                                 draws: int = 4000, seed: int = 0) -> dict:
    """Exploratory: a confidence interval on the false-safe gap between two arms."""
    contexts: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        contexts.setdefault(row["context"], []).append(i)
    keys = list(contexts)
    violated, observed = constraint_truth(rows, constraint)
    scores_a, scores_b, safe_a = np.asarray(scores_a), np.asarray(scores_b), np.asarray(safe_a)
    generator = np.random.default_rng(seed)
    differences = []
    for _ in range(draws):
        picked = np.concatenate([contexts[keys[k]]
                                 for k in generator.integers(0, len(keys), len(keys))])
        coverage = int(safe_a[picked].sum())
        if coverage == 0:
            continue
        a = false_safe_at_coverage(scores_a[picked], violated[picked], observed[picked], coverage)
        b = false_safe_at_coverage(scores_b[picked], violated[picked], observed[picked], coverage)
        if np.isfinite(a["rate"]) and np.isfinite(b["rate"]):
            differences.append(a["rate"]-b["rate"])
    differences = np.asarray(differences)
    if differences.size == 0:
        return {"draws": 0, "resampled_unit": "context", "mean_difference": None,
                "percentile_95_interval": None, "fraction_favouring_b": None,
                "status": "exploratory_post_hoc_not_part_of_the_decision_rule"}
    return {"draws": int(differences.size), "resampled_unit": "context",
            "mean_difference": float(differences.mean()),
            "percentile_95_interval": [float(np.percentile(differences, 2.5)),
                                       float(np.percentile(differences, 97.5))],
            "fraction_favouring_b": float((differences > 0).mean()),
            "status": "exploratory_post_hoc_not_part_of_the_decision_rule"}


def sign_test(wins: int, losses: int) -> float:
    total = wins+losses
    if total == 0:
        return 1.0
    lower = min(wins, losses)
    tail = sum(math.comb(total, k) for k in range(lower+1))/2**total
    return min(1.0, 2*tail)


def kaplan_meier(progress, violated, observed) -> dict:
    """Right-censored survival of the constraint against commanded detour distance.

    L4 in one function: a request whose move was cut short by the force abort is
    right-censored, not a success. This is reported beside the conditional
    analysis, and the contract declares which one is primary before collection.
    """
    progress = np.asarray(progress, dtype=float)
    violated = np.asarray(violated, dtype=bool)
    observed = np.asarray(observed, dtype=bool)
    events = violated
    times = np.where(events, progress, progress)
    order = np.argsort(times, kind="stable")
    at_risk = len(times)
    survival, curve = 1.0, []
    for i in order:
        if at_risk <= 0:
            break
        if events[i]:
            survival *= 1.0-1.0/at_risk
            curve.append({"progress_m": float(times[i]), "survival": float(survival)})
        at_risk -= 1
    return {"events": int(events.sum()), "censored": int((~events & ~observed).sum()),
            "final_survival": float(survival), "curve": curve[-20:],
            "note": "Survival of the constraint against commanded detour distance travelled."}


def fit_threshold(values: np.ndarray, labels: np.ndarray) -> dict:
    """One scalar threshold, chosen by balanced accuracy. Identical to v3's fit."""
    values, labels = np.asarray(values, dtype=float), np.asarray(labels)
    order = np.unique(values)
    if order.size == 0:
        return {"threshold_m": float("nan"), "train_balanced_accuracy": float("nan")}
    midpoints = np.concatenate([[order[0]-1e-6], (order[:-1]+order[1:])/2, [order[-1]+1e-6]])
    positive, negative = labels == 1, labels == 0
    best = None
    for threshold in midpoints:
        if not positive.any() or not negative.any():
            continue
        predicted = values > threshold
        score = 0.5*(predicted[positive].mean()+(~predicted[negative]).mean())
        if best is None or score > best[1]:
            best = (float(threshold), float(score))
    if best is None:
        return {"threshold_m": float("nan"), "train_balanced_accuracy": float("nan")}
    return {"threshold_m": best[0], "train_balanced_accuracy": best[1]}


def balanced_accuracy(truth: np.ndarray, predicted: np.ndarray) -> float:
    positive, negative = truth == 1, truth == 0
    if not positive.any() or not negative.any():
        return float("nan")
    return float(0.5*(predicted[positive].mean()+(~predicted[negative]).mean()))


def load_contract(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


__all__ = [
    "ARMS", "ARM_COST", "CONSTRAINTS", "FEATURE_NAMES", "FORCE_FEATURE_NAMES", "HALTON_BASES",
    "b0plus_margin_m", "balanced_accuracy", "build_cases", "build_contexts",
    "check_margin_resolution", "cluster_bootstrap_difference", "commanded_magnitude",
    "coverage_by_context",
    "constraint_truth", "content_sha256", "core_actions", "core_by_context", "effective_level",
    "false_safe_at_coverage", "feature_row", "finite", "fit_threshold", "isolation_contexts",
    "kaplan_meier", "level_by_id", "load_contract", "merge_runtime", "per_context_regret",
    "per_context_regret_matched", "ranking_regret_matched",
    "perception_levels", "ranking_regret", "raw_sha256", "repair_basis", "sampled_actions",
    "sign_test",
]
