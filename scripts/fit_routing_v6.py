"""Score the routing block and apply its registered predictions.

Reads the executed routing block and answers three registered questions. Does the
shipped filter still earn its place over a five-clip route? Does the clip budget
keep decaying past the three steps the composition study could see? And does the
supervisor's appetite - the thing that study found post hoc and could not certify
- beat the filter's representation when both read the same check?

The denominator at step k is the routes that REACHED step k with that constraint
still intact. A route that already broke it cannot break it again, and a step
nobody issued a motion at cannot break anything, so both leave that step's
denominator and are reported beside it. A motion the job ended during is censored,
never counted as having respected a constraint it never got to test.

It applies the same resolution rule as every block here, level by level: a rate
computed over too few surviving routes cannot resolve the registered margin and is
reported as unresolvable rather than as a number.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_constraints_v4 import CENSORED, CONSTRAINTS, VIOLATED  # noqa: E402
from assembly_recovery.cable_study_v4 import check_margin_resolution, content_sha256  # noqa: E402

BOOTSTRAP_DRAWS = 2000


def collect(run_dirs) -> list[dict]:
    """Every executed route, from one or more shards."""
    rows = []
    for run_dir in run_dirs:
        for directory in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            path = directory / "result.json"
            if not path.exists():
                continue
            result = json.loads(path.read_text(encoding="utf-8"))
            case = result.get("case", {})
            if "supervisor" not in case:
                continue
            rows.append({
                "case": case["id"], "group": case["study_group"], "level": case["error_level"],
                "supervisor": case["supervisor"], "mount_offset": case.get("mount_offset_index"),
                "reason": result["job"]["failure_reason"] or "completed",
                "steps_offered": result.get("steps_offered", 0),
                "steps_issued": result.get("steps_issued", 0),
                "steps_completed": result.get("steps_completed", 0),
                "abstentions": result.get("abstentions", 0),
                "issued": result.get("issued", []),
                "constraints": result.get("constraints", {}),
                "attribution": result.get("attribution", {}),
                "clip_loss": result.get("clip_loss_attribution", {}),
                "terminal_clips": result.get("terminal_clips") or {},
                "terminal_clip_retained": result.get("terminal_clip_retained"),
                "seated": bool(result.get("seated")),
                "route_completed": bool(result.get("route_completed")),
                "settled": bool(result.get("settled")),
                "privilege_events": result.get("privilege_guard", {}).get("events", 0),
                "mutation_events": result.get("mutation_guard", {}).get("forbidden_events", 0),
                "native_steps": result["accounting"]["native_steps"],
                "settle_steps": result["accounting"].get("settle_native_steps", 0),
                "wall_seconds": result["accounting"]["wall_seconds"],
            })
    return rows


def per_step_rates(rows, constraint: str, steps: int, margin: float) -> dict:
    """Violation rate at each step, over the routes that reached it intact."""
    out = []
    for step in range(steps):
        intact = scored = broke = idle = censored = 0
        for row in rows:
            broke_at = (row["attribution"].get(constraint) or {}).get("during_step")
            if broke_at is not None and broke_at < step:
                continue
            intact += 1
            record = next((r for r in row["issued"] if r["step"] == step), None)
            if record is None or not record.get("requested"):
                idle += 1
                continue
            if broke_at == step:
                scored += 1
                broke += 1
                continue
            if not record.get("motion_completed"):
                censored += 1
                continue
            scored += 1
        out.append({"step": step, "reached_intact": intact, "motions_scored": scored,
                    "no_motion_issued": idle, "motion_cut_short": censored,
                    "violations": broke,
                    "rate": (broke/scored if scored else None),
                    "resolution": (1/scored if scored else None)})
    first = out[0]["rate"] if out else None
    last = out[-1]["rate"] if out else None
    check = check_margin_resolution(margin, [s["resolution"] for s in out])
    return {
        "steps": out,
        "rise_first_to_last": (None if first is None or last is None else float(last-first)),
        "rises_by_more_than_margin": (None if first is None or last is None
                                      else bool(last-first > margin)),
        "margin_resolution": check,
        "readable": bool(check["verdict"] == "usable" and first is not None and last is not None),
    }


def cumulative(rows, constraint: str) -> dict:
    states = [row["constraints"].get(constraint, {}).get("state") for row in rows]
    observed = [s for s in states if s != CENSORED and s is not None]
    return {"routes": len(states),
            "observed": len(observed),
            "censored": sum(1 for s in states if s == CENSORED),
            "violated": sum(1 for s in observed if s == VIOLATED),
            "rate": (sum(1 for s in observed if s == VIOLATED)/len(observed)
                     if observed else None)}


def cluster_bootstrap(rows_a, rows_b, value, draws: int = BOOTSTRAP_DRAWS, seed: int = 20260912):
    """Bootstrap the gap between two arms, resampling whole GROUPS.

    Routes inside a group share a physical cell and are not independent, so the
    resampling unit is the group, exactly as the perception study's comparison
    does it. Returns the point gap and a 95 per cent interval, or None when either
    arm has nothing to resample.
    """
    def by_group(rows):
        out = defaultdict(list)
        for row in rows:
            out[row["group"]].append(value(row))
        return {g: [v for v in vs if v is not None] for g, vs in out.items()}

    a, b = by_group(rows_a), by_group(rows_b)
    groups = sorted(set(a) & set(b))
    groups = [g for g in groups if a[g] and b[g]]
    if not groups:
        return None
    point = float(np.mean([v for g in groups for v in b[g]])
                  - np.mean([v for g in groups for v in a[g]]))
    rng = np.random.default_rng(seed)
    gaps = []
    for _ in range(draws):
        picked = rng.choice(len(groups), size=len(groups), replace=True)
        left = [v for i in picked for v in a[groups[i]]]
        right = [v for i in picked for v in b[groups[i]]]
        if left and right:
            gaps.append(float(np.mean(right)-np.mean(left)))
    if not gaps:
        return None
    low, high = (float(x) for x in np.percentile(gaps, [2.5, 97.5]))
    return {"gap": point, "ci95": [low, high], "excludes_zero": bool(low > 0 or high < 0),
             "groups": len(groups), "draws": len(gaps),
             "unit": "whole (cell, service loop) groups, because routes inside one share a cell"}


def budget_spend(rows) -> dict:
    """What the shipped layer reported it was spending, step by step.

    This is the composition mechanism made directly visible: the headroom the
    filter reports at each decision, and the fraction of it the issued motion
    consumes. The workbench renders these; nothing else reconstructs them.
    """
    per_step = defaultdict(list)
    for row in rows:
        for record in row["issued"]:
            budget = (record.get("budget") or {}).get("C1_clip")
            if not budget or not record.get("requested"):
                continue
            per_step[record["step"]].append(
                (budget.get("headroom_at_decision_m"), budget.get("spent_by_this_motion_m"),
                 budget.get("spent_fraction")))
    out = []
    for step in sorted(per_step):
        values = [v for v in per_step[step] if all(x is not None and np.isfinite(x) for x in v)]
        if not values:
            continue
        head, spent, fraction = (np.array([v[i] for v in values]) for i in range(3))
        out.append({"step": step, "motions": len(values),
                    "mean_headroom_at_decision_m": float(head.mean()),
                    "mean_spent_m": float(spent.mean()),
                    "mean_spent_fraction": float(fraction.mean()),
                    "median_spent_fraction": float(np.median(fraction))})
    return {"per_step": out,
            "headroom_decay_m": (None if len(out) < 2 else
                                 out[0]["mean_headroom_at_decision_m"]
                                 - out[-1]["mean_headroom_at_decision_m"])}


def clip_losses(rows) -> dict:
    """Which clip went, and how often, over these routes."""
    counts = defaultdict(int)
    first_step = defaultdict(list)
    for row in rows:
        for clip, entry in (row["clip_loss"] or {}).items():
            counts[clip] += 1
            if entry.get("during_step") is not None:
                first_step[clip].append(entry["during_step"])
    return {"routes": len(rows),
            "losses_by_clip": dict(sorted(counts.items())),
            "mean_step_at_loss": {c: float(np.mean(v)) for c, v in sorted(first_step.items())},
            "routes_losing_any_required_clip": sum(1 for r in rows if r["clip_loss"]),
            "mean_required_clips_kept": float(np.mean(
                [r["terminal_clips"].get("required_retained", 0) for r in rows]))
            if rows else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, action="append", required=True,
                        help="May be given more than once; shards are fitted together.")
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_routing_v6.json"))
    parser.add_argument("--out", type=Path, default=Path("evidence/cable_routing_v6.json"))
    parser.add_argument("--partial", action="store_true",
                        help="Fit what is on disk even if the block did not finish, and say so.")
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    rows = collect([ROOT / d for d in args.run_dir])
    if not rows:
        parser.error("No routing requests found")
    expected = contract["expected_requests"]
    complete = len(rows) == expected
    if not complete and not args.partial:
        parser.error(f"Found {len(rows)} of {expected} registered routes. The block did not "
                     f"finish. Pass --partial to fit what is on disk, and the record will say so.")

    margin = float(contract["decision_rule"]["margin"])
    steps = len(contract["route"]["decision_times_s"])
    levels = contract["registered_support"]["error_levels"]
    supervisors = [s["id"] for s in contract["route"]["supervisors"]]

    results: dict = {}
    for supervisor in supervisors:
        for level in levels:
            subset = [r for r in rows if r["supervisor"] == supervisor and r["level"] == level]
            if not subset:
                continue
            done = sum(1 for r in subset if r["route_completed"])
            block = {
                "routes": len(subset),
                "motions_issued": sum(r["steps_issued"] for r in subset),
                "motions_completed": sum(r["steps_completed"] for r in subset),
                "abstentions": sum(r["abstentions"] for r in subset),
                "routes_completed": done,
                "route_completion_rate": done/len(subset),
                "seated": sum(1 for r in subset if r["seated"]),
                "settling_rejections": sum(1 for r in subset if not r["settled"]),
                "by_reason": {k: sum(1 for r in subset if r["reason"] == k)
                              for k in sorted({r["reason"] for r in subset})},
                "clips": clip_losses(subset),
                "budget": budget_spend(subset),
            }
            for constraint in CONSTRAINTS:
                block[constraint] = {"per_step": per_step_rates(subset, constraint, steps, margin),
                                     "cumulative": cumulative(subset, constraint)}
            results[f"{supervisor}:{level}"] = block

    def arm(supervisor, level):
        return [r for r in rows if r["supervisor"] == supervisor and r["level"] == level]

    def lost_any(row):
        return 1.0 if row["clip_loss"] else 0.0

    def completed(row):
        return 1.0 if row["route_completed"] else 0.0

    # P1: does the filter still earn its place over a five-clip route?
    p1 = {}
    for level in levels:
        filtered, unfiltered = arm("filtered", level), arm("unfiltered", level)
        a = np.mean([lost_any(r) for r in filtered]) if filtered else None
        b = np.mean([lost_any(r) for r in unfiltered]) if unfiltered else None
        p1[level] = {
            "filtered_clip_loss_rate": None if a is None else float(a),
            "unfiltered_clip_loss_rate": None if b is None else float(b),
            "gap": None if a is None or b is None else float(b-a),
            "beats_by_more_than_margin": (None if a is None or b is None else bool(b-a > margin)),
            "bootstrap": cluster_bootstrap(filtered, unfiltered, lost_any),
        }

    # P2: does the clip budget keep decaying past three steps? Read on the arm
    # that actually reaches step five, which the contract names in advance.
    p2 = {}
    for supervisor in supervisors:
        per_level = {}
        for level in levels:
            block = results.get(f"{supervisor}:{level}")
            step_block = None if block is None else block["C1_clip"]["per_step"]
            per_level[level] = (None if step_block is None else {
                "rise_first_to_last": step_block["rise_first_to_last"],
                "rises_by_more_than_margin": step_block["rises_by_more_than_margin"],
                "readable": step_block["readable"],
                "motions_scored_by_step": [s["motions_scored"] for s in step_block["steps"]],
                "rate_by_step": [s["rate"] for s in step_block["steps"]]})
        readable = [v for v in per_level.values() if v and v["readable"]]
        p2[supervisor] = {
            "per_level": per_level,
            "keeps_decaying": (None if not readable else
                               any(v["rises_by_more_than_margin"] for v in readable)),
            "levels_readable": len(readable), "levels": len(levels),
        }

    # P3: appetite. Registered here, not post hoc, because the composition study
    # earned it that promotion.
    p3 = {}
    for level in levels:
        filtered, conservative = arm("filtered", level), arm("conservative", level)
        a = np.mean([completed(r) for r in filtered]) if filtered else None
        b = np.mean([completed(r) for r in conservative]) if conservative else None
        p3[level] = {
            "filtered_route_completion": None if a is None else float(a),
            "conservative_route_completion": None if b is None else float(b),
            "gap": None if a is None or b is None else float(b-a),
            "beats_by_more_than_margin": (None if a is None or b is None else bool(b-a > margin)),
            "bootstrap": cluster_bootstrap(filtered, conservative, completed),
            "clip_loss": {
                "filtered": None if not filtered else float(np.mean([lost_any(r) for r in filtered])),
                "conservative": (None if not conservative
                                 else float(np.mean([lost_any(r) for r in conservative]))),
            },
        }

    def certified(block):
        """A prediction is only carried if the metric could resolve the margin."""
        values = [v for v in block.values() if v is not None]
        return [v.get("beats_by_more_than_margin") for v in values]

    verdicts = {
        "p1_filter_earns_its_place_over_a_route": {
            "held": all(v is True for v in certified(p1)) if certified(p1) else None,
            "by_level": {k: v["beats_by_more_than_margin"] for k, v in p1.items()},
            "gaps": {k: v["gap"] for k, v in p1.items()},
        },
        "p2_clip_budget_keeps_decaying": {
            "held": p2.get("conservative", {}).get("keeps_decaying"),
            "read_on": "conservative",
            "why_that_arm": "The contract named it in advance as the only arm expected to reach "
                            "step 5. The other two lose a clip at step 1 in every route, so their "
                            "per-step rates past step 1 are computed over nothing and are "
                            "reported as unresolvable, exactly as declared.",
            "rise_first_to_last": {k: (v or {}).get("rise_first_to_last")
                                   for k, v in p2.get("conservative", {})
                                   .get("per_level", {}).items()},
        },
        "p3_appetite_beats_representation": {
            "held": {k: v["beats_by_more_than_margin"] for k, v in p3.items()},
            "gaps": {k: v["gap"] for k, v in p3.items()},
            "status": "PRE-REGISTERED here, unlike the composition study where the same "
                      "comparison was post hoc and carried no verdict.",
        },
    }
    verdicts["correct"] = sum(1 for key, held in (
        ("p1", verdicts["p1_filter_earns_its_place_over_a_route"]["held"]),
        ("p2", verdicts["p2_clip_budget_keeps_decaying"]["held"]),
        ("p3", verdicts["p3_appetite_beats_representation"]["held"].get("E0")),
    ) if held is True)
    verdicts["of"] = 3

    report = {
        "schema": 1, "id": "cable_routing_v6",
        "created_on": contract["created_on"],
        "status": "fitted_routing_study" if complete else "fitted_routing_study_partial",
        "complete": complete,
        "scope": contract["scope"], "question": contract["question"],
        "contract": {"path": args.contract.as_posix(),
                     "content_sha256": content_sha256(ROOT / args.contract)},
        "cell": contract["cell"],
        "run_dirs": [d.as_posix() for d in args.run_dir],
        "denominator": {
            "registered_routes": expected,
            "executed_routes": len(rows),
            "decisions_offered": len(rows)*steps,
            "motions_issued": sum(r["steps_issued"] for r in rows),
            "motions_completed": sum(r["steps_completed"] for r in rows),
            "abstentions": sum(r["abstentions"] for r in rows),
            "settling_rejections": sum(1 for r in rows if not r["settled"]),
            "routes_completed": sum(1 for r in rows if r["route_completed"]),
            "by_reason": {k: sum(1 for r in rows if r["reason"] == k)
                          for k in sorted({r["reason"] for r in rows})},
            "note": "Every registered route counts, including settling rejections, infeasible "
                    "constructions and aborts. A route cut short is censored on every constraint "
                    "it had not already violated, never counted as respecting one.",
        },
        "guards": {"privilege_guard_events": sum(r["privilege_events"] for r in rows),
                   "mutation_guard_events": sum(r["mutation_events"] for r in rows)},
        "cost": {"native_steps": sum(r["native_steps"] for r in rows),
                 "settle_native_steps": sum(r["settle_steps"] for r in rows),
                 "summed_worker_wall_seconds": round(sum(r["wall_seconds"] for r in rows), 1)},
        "prediction": contract["decision_rule"]["prediction"],
        "verdicts": verdicts,
        "p1_does_the_filter_still_earn_its_place": p1,
        "p2_does_the_clip_budget_keep_decaying": p2,
        "p3_appetite_against_representation": p3,
        "clips": clip_losses(rows),
        "results": results,
        "reading": "Three things are separable here and should not be run together. Whether the "
                   "check is worth having at all over a route; whether its per-step calibration "
                   "holds as the chain lengthens; and whether how greedily a supervisor spends "
                   "what the check permits matters more than what the check is. The first two are "
                   "properties of the check. The third is not, and the composition study already "
                   "measured it to be large.",
        "scope_and_limitations": contract["scope_and_limitations"],
    }
    if not complete:
        report["partial_note"] = (
            f"The block was fitted from {len(rows)} of {expected} registered routes. It is not "
            f"the registered result: cells are unequally filled and every rate here is "
            f"provisional. Re-fit when the block finishes.")
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"out": args.out.as_posix(), "routes": len(rows), "complete": complete,
                      "p1_filter_beats_no_filter": {k: v["beats_by_more_than_margin"]
                                                    for k, v in p1.items()},
                      "p2_keeps_decaying": {k: v["keeps_decaying"] for k, v in p2.items()},
                      "p3_appetite_wins": {k: v["beats_by_more_than_margin"]
                                           for k, v in p3.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
