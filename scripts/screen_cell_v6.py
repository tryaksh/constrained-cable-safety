"""Screen candidate multi-clip routing cells before spending block compute.

A five-clip route is a bigger object than a clip position, and most of the ways
it can fail are visible in one settle: the strain relief cannot be placed, the
construction folds, the route installs below the bend-radius spec, or the cable
simply does not end up inside all five channels. Every candidate declared in
configs/cable_cell_v6_candidates.json is built and settled once at every
registered service loop, and every rejection is kept here with its reason, so the
cell the routing block registers is a measured subset of a declared list.

This is the v4 layout screen (scripts/screen_layouts_v4.py) applied to a cell
rather than a clip: same settle, same acceptance discipline, same withdrawn
lateral-clearance floor reported as a diagnostic instead of applied. It runs no
supervisor, issues no motion and decides nothing about safety.
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
from assembly_recovery.cable_cell_v6 import cell_case, group_id  # noqa: E402
from assembly_recovery.cable_constrained_v2 import build_scene, cable_centerline, clip_state  # noqa: E402
from assembly_recovery.cable_constraints_v4 import min_bend_radius  # noqa: E402
from assembly_recovery.cable_routes import plane_crossings  # noqa: E402
from scripts.evaluate_cable_recovery_v2 import settle  # noqa: E402


def candidate_case(layout: dict, loop_m: float, base: dict, candidates: dict) -> tuple[dict, dict]:
    case = cell_case(layout, loop_m, candidates, base,
                     id=f"screen_{group_id(layout['id'], loop_m)}",
                     controller="force_guided_insertion", calibration_seed=76000,
                     gate="screen",
                     purpose="Routing-cell settling screen for the v6 block contract.")
    return case, {**base, "render_visuals": False}


def lateral_wall_gaps(scene, centreline) -> list[dict]:
    """Per clip, how far the installed crossing sits inside its own lateral wall.

    The same diagnostic evidence/cable_layout_screen_v4.json reports, evaluated at
    every clip. The predicate retains a crossing when |lateral| <= half_width -
    radius, which is exactly where the cable surface touches the wall, so a clip
    that installs close to that line starts every request next to the boundary of
    its own label. The 1 mm floor the v4 candidate file declared was WITHDRAWN
    there because it rejects the reference layout; it stays withdrawn here and
    this is reported, not applied.
    """
    points = np.asarray(centreline, dtype=float)
    gaps = []
    for clip in scene.clips:
        origin = np.asarray(clip["origin_world"], dtype=float)
        rotation = np.asarray(clip["rotation_world"], dtype=float)
        crossings = plane_crossings(((points-origin) @ rotation).tolist())
        wall = float(clip["predicate"]["half_width_m"]-clip["predicate"]["cable_radius_m"])
        worst = (None if not crossings else
                 max((c for c in crossings), key=lambda c: abs(float(c["point"][1]))))
        gaps.append({
            "clip": clip["id"],
            "crossings": len(crossings),
            # Signed, so a cell can be re-centred on where the cable actually lies
            # rather than on where the route was drawn.
            "lateral_m": None if worst is None else float(worst["point"][1]),
            "height_m": None if worst is None else float(worst["point"][2]),
            "lateral_wall_gap_m": (float("-inf") if worst is None else
                                   wall-abs(float(worst["point"][1]))),
        })
    return gaps


def screen_one(layout: dict, loop_m: float, base: dict, candidates: dict) -> dict:
    case, runtime = candidate_case(layout, loop_m, base, candidates)
    started = time.monotonic()
    entry = {"layout": layout["id"], "installed_loop_m": loop_m,
             "clips": len(layout["clips"])}
    with tempfile.TemporaryDirectory() as directory:
        try:
            scene = build_scene(ROOT, runtime, case, Path(directory))
        except (ValueError, KeyError) as exc:
            return {**entry, "built": False, "settled": False,
                    "reason": "construction_infeasible",
                    "error": f"{type(exc).__name__}: {exc}"[:240],
                    "wall_s": round(time.monotonic()-started, 1)}
        steps, settled, reason = settle(scene, runtime)
        centreline = cable_centerline(scene)
        state = clip_state(scene, centreline)
        report = scene.report["cable"]
        gaps = lateral_wall_gaps(scene, centreline)
        return {
            **entry, "built": True, "settled": bool(settled), "reason": reason,
            "per_clip": state["per_clip"], "summary": state["summary"],
            "lateral_wall_gaps": gaps,
            "worst_lateral_wall_gap_m": min(g["lateral_wall_gap_m"] for g in gaps),
            "installed_min_bend_radius_m": float(min_bend_radius(centreline)),
            "max_initial_turn_deg": float(report["max_initial_turn_deg"]),
            "routed_direct_length_m": float(report["direct_length_m"]),
            "geometric_service_loop_m": float(report["rest_length_m"]-report["direct_length_m"]),
            "solved_anchor_along_m": float(scene.fixture["solved_anchor_along_m"]),
            "boot_to_anchor_m": float(np.linalg.norm(
                np.asarray(centreline)[0]-np.asarray(scene.fixture["anchor_site_world"]))),
            "settle_native_steps": int(steps),
            "wall_s": round(time.monotonic()-started, 1),
        }


def _screen(item):
    return screen_one(*item)


def cell_fails(record: dict, spec: float):
    """Why this (cell, installed loop) cannot be registered, or None."""
    if not record.get("built"):
        return record.get("reason") or "construction_infeasible"
    if not record.get("settled"):
        return record.get("reason") or "not_settled"
    summary = record.get("summary") or {}
    if not summary.get("all_required_retained"):
        return "required_clip_not_retained:" + ",".join(summary.get("lost_required_ids", []))
    if any(c["ambiguous_multiple_passages"] for c in record.get("per_clip", [])):
        return "ambiguous_multiple_passages"
    if record.get("installed_min_bend_radius_m", 0.0) <= spec:
        return "installed_bend_below_c2_spec"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path,
                        default=ROOT / "configs/cable_cell_v6_candidates.json")
    parser.add_argument("--out", type=Path, default=ROOT / "evidence/cable_cell_screen_v6.json")
    parser.add_argument("--base", type=Path, default=ROOT / "configs/cable_recovery_task_v2.json")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
    base = json.loads(args.base.read_text(encoding="utf-8-sig"))
    spec = float(candidates["c2_spec_m"])
    cells = [(layout, loop) for layout in candidates["layouts"]
             for loop in candidates["installed_loop_m"]]
    items = [(layout, loop, base, candidates) for layout, loop in cells]
    if args.workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            runs = list(pool.map(_screen, items))
        for record in runs:
            print(json.dumps({k: v for k, v in record.items()
                              if k not in ("per_clip", "lateral_wall_gaps")}), flush=True)
    else:
        runs = []
        for item in items:
            record = screen_one(*item)
            runs.append(record)
            print(json.dumps({k: v for k, v in record.items()
                              if k not in ("per_clip", "lateral_wall_gaps")}), flush=True)

    accepted, rejected = [], []
    for record in runs:
        group = group_id(record["layout"], record["installed_loop_m"])
        reason = cell_fails(record, spec)
        entry = {"group": group, "layout": record["layout"],
                 "installed_loop_m": record["installed_loop_m"], "clips": record["clips"]}
        if reason:
            rejected.append({**entry, "reason": reason})
        else:
            accepted.append({**entry,
                             "worst_lateral_wall_gap_m": record["worst_lateral_wall_gap_m"],
                             "installed_min_bend_radius_m": record["installed_min_bend_radius_m"],
                             "boot_to_anchor_m": record["boot_to_anchor_m"],
                             "solved_anchor_along_m": record["solved_anchor_along_m"]})
    report = {
        "schema": 1, "id": "cable_cell_screen_v6", "created_on": candidates["created_on"],
        "status": "executed_cell_screen",
        "scope": "Settling and installed-geometry screen for the v6 routing cell. Not a study "
                 "result, not a safety claim and not a hardware claim.",
        "candidates": args.candidates.name,
        "c2_spec_m": spec,
        "unit": "One screened unit is one (cell, installed service loop), which is also the "
                "routing block's registered group. A cell whose loops do not all survive is not "
                "discarded whole: the surviving ones are registered and the rest are recorded "
                "here and never run.",
        "rule": candidates["rule"],
        "selection_rule": candidates["selection_rule"],
        "pilot": candidates["pilot"],
        "withdrawn_lateral_floor": "The 1 mm installed lateral-clearance floor that "
                                   "evidence/cable_layout_screen_v4.json withdrew, because it "
                                   "rejects the validated reference layout, stays withdrawn. The "
                                   "clearance is reported per clip as a diagnostic.",
        "accepted_groups": [a["group"] for a in accepted],
        "accepted_cell_detail": accepted,
        "rejected_groups": rejected,
        "accepted_cells": len(accepted), "rejected_cells": len(rejected),
        "screened_cells": len(runs), "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float),
                        encoding="utf-8")
    print(json.dumps({"accepted_groups": report["accepted_groups"],
                      "rejected_cells": report["rejected_cells"],
                      "out": args.out.as_posix()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
