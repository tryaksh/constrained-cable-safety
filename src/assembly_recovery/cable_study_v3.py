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
