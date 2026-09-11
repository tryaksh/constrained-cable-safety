"""Registered support, action design and features for the safe-repair boundary study.

The study asks one question: when a supervisor must choose a clearance repair,
is the boundary between a repair that keeps the required clip and one that
overdraws the cable a simple analytic function of the observable state, or does
it need a learned action-outcome model?

This module holds everything that must be identical between data collection and
model fitting: the merge of the frozen task onto the study contract, the
deterministic action design, the analytic endpoint every predictor may compute,
and the named feature set. It runs no physics and fits no model.

Provenance note. The v2 block recorded a config hash that no committed file
reproduces: the archived copy was CRLF and git stored LF, so identical content
hashed differently. Hashes here are taken on content-normalised bytes, and the
raw hash is recorded beside them so both are checkable.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

#: Halton bases for the three action coordinates, registered before collection.
HALTON_BASES = (2, 3, 5)

#: Named features offered to the calibrated feature model. The analytic budget
#: baseline sees only ``endpoint_boot_to_anchor_m``; the learned model sees the
#: whole centreline as well. Order is fixed so a fitted model is reproducible.
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
)


def normalised_bytes(raw: bytes) -> bytes:
    """Content bytes: byte-order mark removed and line endings made LF.

    Two checkouts of the same file differ in these and nothing else, so a hash
    over them identifies content rather than a working-tree encoding.
    """
    return raw.lstrip(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")


def content_sha256(path) -> str:
    return hashlib.sha256(normalised_bytes(Path(path).read_bytes())).hexdigest()


def raw_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def halton(count: int, skip: int = 0) -> np.ndarray:
    """Deterministic three-dimensional Halton points in the unit cube."""
    out = np.empty((count, len(HALTON_BASES)))
    for column, base in enumerate(HALTON_BASES):
        for row in range(count):
            index, value, denominator = row+skip+1, 0.0, 1.0
            while index > 0:
                index, remainder = divmod(index, base)
                denominator *= base
                value += remainder/denominator
            out[row, column] = value
    return out


def action_from_unit(unit, bounds: dict, speed: float) -> dict:
    """Map one unit-cube point onto a registered clearance action."""
    low, high = bounds["retreat_m"]
    retreat = low+(high-low)*float(unit[0])
    low, high = bounds["excursion_m"]
    excursion = low+(high-low)*float(unit[2])
    return {"retreat_m": round(retreat, 6), "bearing_rad": round(2*math.pi*float(unit[1]), 6),
            "excursion_m": round(excursion, 6), "speed_m_per_s": speed}


def core_actions(design: dict) -> list[dict]:
    """The shared action set issued in every context.

    A common set makes contexts comparable and makes per-context action ranking
    well defined; the sampled set beside it broadens coverage of the space.
    """
    speed = design["clearance_speed_m_per_s"]
    return [{"retreat_m": retreat, "bearing_rad": round(math.radians(bearing_deg), 6),
             "excursion_m": excursion, "speed_m_per_s": speed}
            for retreat, bearing_deg, excursion in design["core_grid"]]


def sampled_actions(design: dict, context_index: int) -> list[dict]:
    """Context-specific quasi-random actions from one registered Halton stream."""
    count = design["sampled_actions"]
    points = halton(count, skip=design["halton_skip"]+context_index*count)
    return [action_from_unit(p, design["bounds"], design["clearance_speed_m_per_s"]) for p in points]


def repair_basis(axis, run) -> np.ndarray:
    """The (run, lateral, axis) frame a repair offset is expressed in.

    Identical construction to ``RepairMacro.waypoints``, so a predictor's
    analytic endpoint and the executed motion cannot drift apart.
    """
    axis = np.asarray(axis, dtype=float)
    run = np.asarray(run, dtype=float)
    run = run-axis*(run @ axis)
    run = run/np.linalg.norm(run)
    return np.column_stack([run, np.cross(axis, run), axis])


def action_displacement(action: dict, axis, run, retract_distance_m: float) -> np.ndarray:
    """World displacement of the plug from the decision pose to the detour endpoint.

    The plug is rigid and its commanded orientation is held, so the boot moves by
    the same vector as the tip. This is what a predictor may compute without
    simulating, and it is what the analytic budget baseline is built on.
    """
    basis = repair_basis(axis, run)
    bearing, excursion = float(action["bearing_rad"]), float(action["excursion_m"])
    offset = np.array([excursion*math.cos(bearing), excursion*math.sin(bearing),
                       -float(action["retreat_m"])])
    return -np.asarray(axis, dtype=float)*retract_distance_m+basis @ offset


def feature_row(decision: dict, action: dict, context: dict, retract_distance_m: float) -> dict:
    """Named observable features for one (decision state, action) pair."""
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
    }


def outcome_label(result: dict) -> str:
    """One of the registered repair outcomes, read from a worker result."""
    job = result["job"]
    if job["status"] == "completed":
        return "completed_clip_retained" if result["terminal_clip_retained"] else "completed_clip_lost"
    reason = job["failure_reason"]
    if reason == "lost_required_clip":
        return "clip_lost"
    if reason in ("force_abort", "prior_connection_load_abort"):
        return "load_abort"
    if reason == "deadline":
        return "deadline"
    if reason == "construction_infeasible":
        return "construction_infeasible"
    if reason is not None and reason.startswith("settle_"):
        return "settling_rejected"
    return "failed_other"


def build_contexts(contract: dict) -> list[dict]:
    """Every registered context, in a fixed order, with its held-out group."""
    support = contract["registered_support"]
    groups = contract["groups"]
    contexts = []
    for layout in support["layouts"]:
        for loop in support["installed_loop_m"]:
            group = f"{layout['id']}_l{int(round(loop*1000))}"
            split = next(k for k in ("train", "dev", "test") if group in groups[k])
            for mount in support["port_mount"]:
                for pose in support["decision_pose"]:
                    contexts.append({
                        "id": f"{group}_{mount['id']}_{pose['id']}",
                        "group": group, "split": split,
                        "layout_id": layout["id"], "run_direction_xy": layout["run_direction_xy"],
                        "outward_xy": layout["outward_xy"],
                        "route_waypoints_along_across_m": layout["route_waypoints_along_across_m"],
                        "clip_along_m": layout["clip_along_m"],
                        "installed_loop_m": loop,
                        "mount_id": mount["id"], "port_compliance": mount.get("compliance"),
                        "decision_pose_id": pose["id"], "decision_at_s": pose["at_s"],
                    })
    return contexts


def build_cases(contract: dict) -> list[dict]:
    """The full registered request list: every context crossed with its actions."""
    design = contract["action_design"]
    shared = core_actions(design)
    cases, seed = [], contract["first_calibration_seed"]
    for index, context in enumerate(build_contexts(contract)):
        actions = ([("core", i, a) for i, a in enumerate(shared)]
                   + [("halton", i, a) for i, a in enumerate(sampled_actions(design, index))])
        for kind, position, action in actions:
            case = {
                "id": f"{context['id']}_{kind}{position:02d}",
                "controller": "force_guided_insertion",
                "calibration_seed": seed,
                "run_direction_xy": context["run_direction_xy"],
                "outward_xy": context["outward_xy"],
                "route_waypoints_along_across_m": context["route_waypoints_along_across_m"],
                "fixture_overrides": {"clip": {"along_m": context["clip_along_m"]}},
                "installed_loop_m": context["installed_loop_m"],
                "fixture_offset_m": [0.0, 0.0],
                "forced_macro": "parametric",
                "forced_macro_at_s": context["decision_at_s"],
                "repair_action": action,
                "study_context": context["id"], "study_group": context["group"],
                "study_split": context["split"], "action_kind": kind, "action_index": position,
                "gate": "S1", "purpose": "safe-repair boundary: one action from one decision state",
            }
            if context["port_compliance"]:
                case["port_compliance"] = context["port_compliance"]
            cases.append(case)
            seed += 1
    return cases


def merge_runtime(base: dict, contract: dict) -> dict:
    """The runnable configuration: the frozen task with the study's declared deltas."""
    runtime = json.loads(json.dumps(base))
    for key, value in contract["runtime_overrides"].items():
        if isinstance(value, dict) and isinstance(runtime.get(key), dict):
            runtime[key] = {**runtime[key], **value}
        else:
            runtime[key] = value
    runtime["id"] = contract["id"]
    runtime["scope"] = contract["scope"]
    runtime["cases"] = build_cases(contract)
    return runtime


def finite(value):
    """Replace non-finite floats with null so the record is valid JSON.

    A metric that is undefined - a rate over an empty set - is recorded as null
    rather than as NaN, which no strict JSON reader accepts.
    """
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value

def commanded_magnitude(row, retract_distance_m: float) -> float:
    """Magnitude of the commanded detour displacement, as the contract words it."""
    axis = np.asarray(row["decision"]["insertion_axis"], dtype=float)
    run = np.array([*row["run_direction_xy"], 0.0])
    return float(np.linalg.norm(action_displacement(row["action"], axis, run, retract_distance_m)))

def core_by_context(rows) -> dict[str, list[int]]:
    contexts: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        if row["action_kind"] == "core":
            contexts.setdefault(row["context"], []).append(i)
    return contexts

def per_context_regret(rows, safe: np.ndarray, key: str, retract_distance_m: float) -> dict:
    """The registered supervisor procedure, resolved per context.

    The supervisor keeps the actions its predictor calls safe and issues the one
    with the largest commanded displacement, because a larger clearance is the
    more useful repair. A predictor whose safe set is too generous is punished
    exactly where it matters. ``None`` means the predictor abstained: it called
    no action safe, which is not scored as regret.
    """
    out = {}
    for context, indices in core_by_context(rows).items():
        allowed = [i for i in indices if safe[i]]
        if not allowed:
            out[context] = None
            continue
        chosen = max(allowed, key=lambda i: (commanded_magnitude(rows[i], retract_distance_m),
                                             -rows[i]["action_index"]))
        out[context] = int(rows[chosen]["clip_lost"] if key == "clip_lost"
                           else 1-rows[chosen]["completed"])
    return out


def ranking_regret(rows, safe: np.ndarray, key: str, retract_distance_m: float) -> dict:
    """The registered metric: the rate at which the issued repair was the wrong one."""
    per_context = per_context_regret(rows, safe, key, retract_distance_m)
    scored = [v for v in per_context.values() if v is not None]
    return {"contexts": len(per_context), "scored": len(scored),
            "abstentions": len(per_context)-len(scored),
            "regret": sum(scored)/len(scored) if scored else float("nan"),
            "resolution": 1/len(scored) if scored else float("nan")}


def cluster_bootstrap_difference(rows, scores_a, scores_b, safe_a, draws: int = 4000,
                                 seed: int = 0) -> dict:
    """Exploratory: a confidence interval on the false-safe gap between two predictors.

    Requests inside one context share a decision state and are not independent,
    so contexts and not requests are the resampled unit. Coverage is rematched
    inside every resample, exactly as the registered metric matches it.
    """
    contexts = {}
    for i, row in enumerate(rows):
        contexts.setdefault(row["context"], []).append(i)
    keys = list(contexts)
    truth = np.asarray([row["clip_lost"] for row in rows])
    scores_a, scores_b, safe_a = np.asarray(scores_a), np.asarray(scores_b), np.asarray(safe_a)
    generator = np.random.default_rng(seed)
    differences = []
    for _ in range(draws):
        picked = np.concatenate([contexts[keys[k]]
                                 for k in generator.integers(0, len(keys), len(keys))])
        coverage = int(safe_a[picked].sum())
        if coverage == 0:
            continue
        differences.append(false_safe_at_coverage(scores_a[picked], truth[picked], coverage)
                           - false_safe_at_coverage(scores_b[picked], truth[picked], coverage))
    differences = np.asarray(differences)
    return {"draws": int(differences.size), "resampled_unit": "context",
            "mean_difference": float(differences.mean()),
            "percentile_95_interval": [float(np.percentile(differences, 2.5)),
                                       float(np.percentile(differences, 97.5))],
            "fraction_favouring_b": float((differences > 0).mean()),
            "status": "exploratory_post_hoc_not_part_of_the_decision_rule"}


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact sign-test p-value for a paired win/loss count."""
    total = wins+losses
    if total == 0:
        return 1.0
    lower = min(wins, losses)
    tail = sum(math.comb(total, k) for k in range(lower+1))/2**total
    return min(1.0, 2*tail)


def paired_context_comparison(rows, safe_a, safe_b, key: str, retract_distance_m: float) -> dict:
    """Post-hoc, exploratory: is one predictor's advantage bigger than one context?

    Contexts are the unit both predictors are scored on, so they can be paired.
    Reported because the registered margin happens to equal the metric's own
    resolution, and a difference of one or two contexts cannot be read as a win.
    """
    a = per_context_regret(rows, safe_a, key, retract_distance_m)
    b = per_context_regret(rows, safe_b, key, retract_distance_m)
    shared = [c for c in a if a[c] is not None and b[c] is not None]
    a_only = sum(1 for c in shared if a[c] == 1 and b[c] == 0)
    b_only = sum(1 for c in shared if a[c] == 0 and b[c] == 1)
    return {"paired_contexts": len(shared),
            "a_regrets_b_does_not": a_only, "b_regrets_a_does_not": b_only,
            "agree": len(shared)-a_only-b_only,
            "sign_test_p": sign_test(a_only, b_only),
            "status": "exploratory_post_hoc_not_part_of_the_decision_rule"}

def lowest_risk_choice(rows, scores: np.ndarray, retract_distance_m: float) -> dict:
    """Exploratory, not pre-registered: issue the action the predictor likes most.

    Reported beside the registered metric because the largest safe clearance is a
    deliberately stressful choice, and a supervisor that simply takes the action
    it believes is safest is the other obvious policy.
    """
    lost = incomplete = 0
    contexts = core_by_context(rows)
    for indices in contexts.values():
        chosen = min(indices, key=lambda i: (float(scores[i]), rows[i]["action_index"]))
        lost += rows[chosen]["clip_lost"]
        incomplete += 1-rows[chosen]["completed"]
    total = max(len(contexts), 1)
    return {"contexts": len(contexts), "clip_loss_rate": lost/total,
            "incompletion_rate": incomplete/total,
            "mean_commanded_magnitude_m": float(np.mean([
                commanded_magnitude(rows[min(indices, key=lambda i: (float(scores[i]),
                                                                     rows[i]["action_index"]))],
                                    retract_distance_m)
                for indices in contexts.values()])) if contexts else float("nan"),
            "status": "exploratory_diagnostic_not_part_of_the_decision_rule"}

def fit_b0(values: np.ndarray, labels: np.ndarray) -> dict:
    """One scalar threshold on the analytic endpoint distance, by balanced accuracy."""
    order = np.unique(values)
    midpoints = np.concatenate([[order[0]-1e-6], (order[:-1]+order[1:])/2, [order[-1]+1e-6]])
    positive, negative = labels == 1, labels == 0
    best = None
    for threshold in midpoints:
        predicted = values > threshold
        if not positive.any() or not negative.any():
            continue
        score = 0.5*(predicted[positive].mean()+(~predicted[negative]).mean())
        if best is None or score > best[1]:
            best = (float(threshold), float(score))
    return {"threshold_m": best[0], "train_balanced_accuracy": best[1]}

def false_safe_at_coverage(scores: np.ndarray, truth: np.ndarray, coverage: int) -> float:
    """Of the `coverage` actions a predictor is most confident are safe, how many lost the clip."""
    if coverage <= 0:
        return float("nan")
    order = np.argsort(scores, kind="stable")[:coverage]
    return float(truth[order].mean())

def balanced_accuracy(truth: np.ndarray, predicted: np.ndarray) -> float:
    positive, negative = truth == 1, truth == 0
    if not positive.any() or not negative.any():
        return float("nan")
    return float(0.5*(predicted[positive].mean()+(~predicted[negative]).mean()))
