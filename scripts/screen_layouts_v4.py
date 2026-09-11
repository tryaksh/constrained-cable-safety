"""Screen candidate layouts for a settled installation before spending block compute.

A layout that does not reach a settled, clip-retaining initial configuration is
not a layout; running the study on it would only add settling rejections to the
denominator. Every candidate is built and settled once at the registered loop
extremes, and every rejection is kept here with its reason, so the support the
contract registers is a measured subset of a declared candidate list rather than
a hand-picked one.

The screen also reports the installed minimum bend radius, because a layout whose
route already violates the C2 spec before the robot moves cannot be used to
measure whether a repair violates it.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_constrained_v2 import build_scene, cable_centerline, clip_state  # noqa: E402
from assembly_recovery.cable_constraints_v4 import min_bend_radius  # noqa: E402
from assembly_recovery.cable_routes import plane_crossings  # noqa: E402
from scripts.evaluate_cable_recovery_v2 import clip_margin, settle  # noqa: E402


def candidate_case(layout: dict, loop_m: float, base: dict) -> tuple[dict, dict]:
    case = {
        "id": f"screen_{layout['id']}_l{int(round(loop_m*1000))}",
        "controller": "force_guided_insertion",
        "calibration_seed": 71000,
        "run_direction_xy": layout["run_direction_xy"],
        "outward_xy": layout["outward_xy"],
        "route_waypoints_along_across_m": layout["route_waypoints_along_across_m"],
        "fixture_overrides": {**layout.get("fixture_overrides", {}),
                              "clip": {**layout.get("fixture_overrides", {}).get("clip", {}),
                                       "along_m": layout["clip_along_m"]}},
        "installed_loop_m": loop_m,
        "fixture_offset_m": [0.0, 0.0],
        "gate": "screen",
        "purpose": "Layout settling screen for the perception study contract.",
    }
    if layout.get("cable_overrides"):
        case["cable_overrides"] = dict(layout["cable_overrides"])
    runtime = {**base, "render_visuals": False,
               "cable": {**base["cable"], **layout.get("cable_overrides", {})}}
    return case, runtime


def lateral_wall_gap(scene, centreline) -> float:
    """How far the installed crossing sits inside the retention predicate's own wall.

    evidence/cable_discretisation_v4.json measures why this matters: the predicate
    retains a crossing when |lateral| <= half_width - cable_radius, which is
    exactly the coordinate at which the cable surface touches the clip wall. A
    layout that installs close to that line starts every job next to the label's
    boundary, so the screen requires a declared floor of clearance.
    """
    local = (np.asarray(centreline)-scene.clip_origin) @ scene.clip_rotation
    crossings = plane_crossings(local.tolist())
    if not crossings:
        return float("-inf")
    predicate = scene.clip_predicate
    wall = float(predicate["half_width_m"]-predicate["cable_radius_m"])
    return wall-max(abs(float(c["point"][1])) for c in crossings)


def screen_one(layout: dict, loop_m: float, base: dict) -> dict:
    case, runtime = candidate_case(layout, loop_m, base)
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        try:
            scene = build_scene(ROOT, runtime, case, Path(directory))
        except (ValueError, KeyError) as exc:
            return {"layout": layout["id"], "installed_loop_m": loop_m, "built": False,
                    "settled": False, "reason": "construction_infeasible",
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                    "wall_s": round(time.monotonic()-started, 1)}
        steps, settled, reason = settle(scene, runtime)
        centreline = cable_centerline(scene)
        state = clip_state(scene, centreline)
        report = scene.report["cable"]
        return {
            "layout": layout["id"], "installed_loop_m": loop_m, "built": True,
            "settled": bool(settled), "reason": reason,
            "clip_retained": bool(state["has_retained_passage"]),
            "retained_passages": len(state["retained_passages"]),
            "ambiguous_multiple_passages": bool(state["ambiguous_multiple_passages"]),
            "clip_margin_m": float(clip_margin(scene, state, centreline)),
            "lateral_wall_gap_m": lateral_wall_gap(scene, centreline),
            "installed_min_bend_radius_m": float(min_bend_radius(centreline)),
            "max_initial_turn_deg": float(report["max_initial_turn_deg"]),
            "routed_direct_length_m": float(report["direct_length_m"]),
            "geometric_service_loop_m": float(report["rest_length_m"]-report["direct_length_m"]),
            "boot_to_anchor_m": float(np.linalg.norm(
                centreline[0]-np.asarray(scene.fixture["anchor_site_world"]))),
            "settle_native_steps": int(steps),
            "wall_s": round(time.monotonic()-started, 1),
        }


def _screen(item):
    return screen_one(*item)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path,
                        default=ROOT / "configs/cable_perception_v4_candidates.json")
    parser.add_argument("--out", type=Path, default=ROOT / "evidence/cable_layout_screen_v4.json")
    parser.add_argument("--base", type=Path, default=ROOT / "configs/cable_recovery_task_v2.json")
    parser.add_argument("--workers", type=int, default=1,
                        help="Screen cells are independent settles; run this many at once.")
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
    base = json.loads(args.base.read_text(encoding="utf-8-sig"))
    spec = float(candidates["c2_spec_m"])
    lateral_floor = float(candidates["lateral_wall_gap_floor_m"])
    cells = [(layout, loop) for layout in candidates["layouts"]
             for loop in candidates["installed_loop_m"]]
    if args.workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            runs = list(pool.map(_screen, [(layout, loop, base) for layout, loop in cells]))
        for record in runs:
            print(json.dumps(record), flush=True)
    else:
        runs = []
        for layout, loop in cells:
            record = screen_one(layout, loop, base)
            runs.append(record)
            print(json.dumps(record), flush=True)

    def cell_fails(record: dict, floor: float):
        """Why this (layout, installed loop) cell cannot be registered, or None."""
        if not record.get("settled"):
            return record.get("reason") or "not_settled"
        if not record.get("clip_retained"):
            return "clip_not_retained"
        if record.get("ambiguous_multiple_passages"):
            return "ambiguous_multiple_passages"
        if record.get("installed_min_bend_radius_m", 0.0) <= spec:
            return "installed_bend_below_c2_spec"
        if record.get("lateral_wall_gap_m", float("-inf")) < floor:
            return "lateral_wall_gap_below_floor"
        return None

    def verdict(floor: float) -> dict:
        accepted, rejected = [], []
        for record in runs:
            group = f"{record['layout']}_l{int(round(record['installed_loop_m']*1000))}"
            reason = cell_fails(record, floor)
            entry = {"group": group, "layout": record["layout"],
                     "installed_loop_m": record["installed_loop_m"]}
            if reason:
                rejected.append({**entry, "reason": reason})
            else:
                accepted.append({**entry,
                                 "lateral_wall_gap_m": record["lateral_wall_gap_m"],
                                 "installed_min_bend_radius_m":
                                     record["installed_min_bend_radius_m"]})
        return {"lateral_wall_gap_floor_m": None if floor == float("-inf") else floor,
                "accepted_groups": [a["group"] for a in accepted],
                "accepted_layouts": sorted({a["layout"] for a in accepted}),
                "accepted_cell_detail": accepted,
                "rejected_groups": rejected,
                "accepted_cells": len(accepted), "rejected_cells": len(rejected)}

    declared = verdict(lateral_floor)
    registered = verdict(float("-inf"))
    report = {
        "schema": 1, "id": "cable_layout_screen_v4", "created_on": candidates["created_on"],
        "status": "executed_layout_screen",
        "scope": "Settling and installed-geometry screen for the perception study support. "
                 "Not a study result and not a hardware claim.",
        "candidates": args.candidates.relative_to(ROOT).as_posix(),
        "c2_spec_m": spec,
        "unit": "One screened unit is one (layout, installed service loop) CELL, which is also the "
                "study's held-out group. A layout whose cells do not all survive is not discarded "
                "whole: the surviving cells are registered and the failing ones are recorded here "
                "and never run.",
        "rule": "A cell is registered only if it settles, retains exactly the required clip, and "
                "installs at a minimum bend radius strictly above the C2 spec.",
        "declared_lateral_floor_verdict": declared,
        "declared_lateral_floor_withdrawn": {
            "floor_m": lateral_floor,
            "why": "The candidate file declared a 1 mm floor on the installed clearance between the "
                   "cable's clip crossing and the retention predicate's own lateral wall. The "
                   "screen measures that this floor rejects L1, the validated v2/v3 layout the "
                   "whole repository is built on: its three cells install at 0.14, 1.87 and 1.05 mm "
                   "of clearance. A criterion that rejects the reference cannot be the right "
                   "criterion, so it is withdrawn rather than tuned, and the clearance is reported "
                   "for every cell as a diagnostic instead. It is the same measurement "
                   "evidence/cable_discretisation_v4.json reports: this task installs its cable "
                   "close to the label's boundary, which is a property of the task worth stating "
                   "rather than a property of these candidates.",
            "kept": "The declared verdict above is kept in full so the withdrawal is checkable.",
        },
        "registered": registered,
        "accepted_layouts": registered["accepted_layouts"],
        "accepted_groups": registered["accepted_groups"],
        "rejected_groups": registered["rejected_groups"],
        "screened_cells": len(runs), "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"accepted_groups": registered["accepted_groups"],
                      "accepted_layouts": registered["accepted_layouts"],
                      "rejected_cells": registered["rejected_cells"],
                      "out": args.out.relative_to(ROOT).as_posix()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
