"""Score the composition study and apply its registered prediction.

Reads the executed sequence block and answers one question per constraint: does
the per-step violation rate rise as motions are chained? The denominator at step
k is the sequences that *reached* step k with that constraint still intact - a
sequence that already broke it cannot break it again, and a sequence nobody
issued a motion for at step k cannot break anything, so both are removed from
that step's denominator and reported beside it.

It applies the same resolution rule the perception study applies: a rate computed
over too few surviving sequences cannot resolve the registered margin, and is
reported as unresolvable rather than as a number.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_constraints_v4 import CENSORED, CONSTRAINTS, VIOLATED  # noqa: E402
from assembly_recovery.cable_study_v4 import check_margin_resolution, content_sha256  # noqa: E402


def collect(run_dir: Path) -> list[dict]:
    rows = []
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
            "supervisor": case["supervisor"],
            "reason": result["job"]["failure_reason"] or "completed",
            "steps_offered": result.get("steps_offered", 0),
            "steps_issued": result.get("steps_issued", 0),
            "steps_completed": result.get("steps_completed", 0),
            "abstentions": result.get("abstentions", 0),
            "issued": result.get("issued", []),
            "constraints": result.get("constraints", {}),
            "attribution": result.get("attribution", {}),
            "terminal_clip_retained": result.get("terminal_clip_retained"),
            "privilege_events": result.get("privilege_guard", {}).get("events", 0),
            "mutation_events": result.get("mutation_guard", {}).get("forbidden_events", 0),
            "native_steps": result["accounting"]["native_steps"],
            "wall_seconds": result["accounting"]["wall_seconds"],
        })
    return rows


def per_step_rates(rows, constraint: str, steps: int, margin: float) -> dict:
    """Violation rate at each step, over the sequences that reached it intact.

    A sequence that already broke this constraint cannot break it again, so it
    leaves the denominator at the step after it broke. A sequence that issued no
    motion at this step - because the supervisor abstained, or because the job had
    already ended - cannot break anything either, and is counted beside the rate
    rather than inside it. What is left is the honest question: of the motions
    actually issued at step k with the constraint still intact, how many broke it.
    """
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
                # The job ended during this motion, so this step never got to
                # test the constraint. Counting it as respecting one would be the
                # same error the single-motion study censors against.
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
    return {"sequences": len(states),
            "observed": len(observed),
            "censored": sum(1 for s in states if s == CENSORED),
            "violated": sum(1 for s in observed if s == VIOLATED),
            "rate": (sum(1 for s in observed if s == VIOLATED)/len(observed)
                     if observed else None)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_sequence_v5.json"))
    parser.add_argument("--out", type=Path, default=Path("evidence/cable_sequence_v5.json"))
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    rows = collect(ROOT / args.run_dir)
    if not rows:
        parser.error("No sequence requests found")
    margin = float(contract["decision_rule"]["margin"])
    steps = len(contract["sequence"]["decision_times_s"])
    levels = contract["registered_support"]["error_levels"]
    supervisors = [s["id"] for s in contract["sequence"]["supervisors"]]

    results: dict = {}
    for supervisor in supervisors:
        for level in levels:
            subset = [r for r in rows if r["supervisor"] == supervisor and r["level"] == level]
            if not subset:
                continue
            block = {"requests": len(subset),
                     "motions_issued": sum(r["steps_issued"] for r in subset),
                     "motions_completed": sum(r.get("steps_completed", 0) for r in subset),
                     "abstentions": sum(r["abstentions"] for r in subset),
                     "by_reason": dict(sorted(
                         defaultdict(int, {k: sum(1 for r in subset if r["reason"] == k)
                                           for k in {r["reason"] for r in subset}}).items()))}
            for constraint in CONSTRAINTS:
                block[constraint] = {"per_step": per_step_rates(subset, constraint, steps, margin),
                                     "cumulative": cumulative(subset, constraint)}
            results[f"{supervisor}:{level}"] = block

    # The registered predictions, each answered on its own.
    def rise(supervisor, level, constraint):
        block = results.get(f"{supervisor}:{level}")
        if not block:
            return None
        return block[constraint]["per_step"]

    verdicts = {}
    for constraint in CONSTRAINTS:
        per_level = {}
        for level in levels:
            block = rise("filtered", level, constraint)
            per_level[level] = (None if block is None else
                                {"rise": block["rise_first_to_last"],
                                 "rises_by_more_than_margin": block["rises_by_more_than_margin"],
                                 "readable": block["readable"]})
        readable = [v for v in per_level.values() if v and v["readable"]]
        verdicts[constraint] = {
            "per_level": per_level,
            "composes": (None if not readable else
                         not any(v["rises_by_more_than_margin"] for v in readable)),
            "levels_readable": len(readable), "levels": len(levels),
        }

    worth_it = {}
    for level in levels:
        filtered = results.get(f"filtered:{level}", {}).get("C1_clip", {}).get("cumulative", {})
        unfiltered = results.get(f"unfiltered:{level}", {}).get("C1_clip", {}).get("cumulative", {})
        a, b = filtered.get("rate"), unfiltered.get("rate")
        worth_it[level] = {"filtered_rate": a, "unfiltered_rate": b,
                           "gap": (None if a is None or b is None else float(b-a)),
                           "beats_by_more_than_margin": (None if a is None or b is None
                                                         else bool(b-a > margin))}

    # POST-HOC, and labelled as such. Two supervisors read the same filter and
    # differ only in how greedily they spend what it allows. Nothing predicted
    # this comparison, so it is reported as exploratory and carries no verdict.
    appetite = {}
    for level in levels:
        row = {}
        for supervisor in ("filtered", "conservative"):
            block = results.get(f"{supervisor}:{level}")
            if not block:
                continue
            done = block["by_reason"].get("completed", 0)
            row[supervisor] = {
                "clip_violation_rate": block["C1_clip"]["cumulative"]["rate"],
                "clip_violated": block["C1_clip"]["cumulative"]["violated"],
                "sequences": block["requests"],
                "completed": done,
                "completion_rate": round(done / block["requests"], 4) if block["requests"] else None,
                "motions_issued": block["motions_issued"],
            }
        if len(row) == 2:
            a = row["filtered"]["clip_violation_rate"]
            b = row["conservative"]["clip_violation_rate"]
            row["conservative_minus_filtered"] = (None if a is None or b is None
                                                  else round(float(b - a), 4))
        appetite[level] = row

    report = {
        "schema": 1, "id": "cable_sequence_v5", "created_on": contract["created_on"],
        "status": "fitted_composition_study",
        "scope": contract["scope"], "question": contract["question"],
        "contract": {"path": args.contract.as_posix(),
                     "content_sha256": content_sha256(ROOT / args.contract)},
        "run_dir": args.run_dir.as_posix(),
        "denominator": {
            "requests": len(rows),
            "decisions_offered": len(rows)*steps,
            "motions_issued": sum(r["steps_issued"] for r in rows),
            "motions_completed": sum(r.get("steps_completed", 0) for r in rows),
            "abstentions": sum(r["abstentions"] for r in rows),
            "by_reason": {k: sum(1 for r in rows if r["reason"] == k)
                          for k in sorted({r["reason"] for r in rows})},
            "note": "Every registered sequence counts. A sequence cut short is censored on every "
                    "constraint it had not already violated, never counted as respecting one.",
        },
        "guards": {"privilege_guard_events": sum(r["privilege_events"] for r in rows),
                   "mutation_guard_events": sum(r["mutation_events"] for r in rows)},
        "cost": {"native_steps": sum(r["native_steps"] for r in rows),
                 "summed_worker_wall_seconds": round(sum(r["wall_seconds"] for r in rows), 1)},
        "prediction": contract["decision_rule"]["prediction"],
        "verdicts": verdicts,
        "is_the_filter_worth_it_over_a_sequence": worth_it,
        "how_greedily_the_supervisor_spends": {
            "status": "exploratory, post-hoc, not pre-registered and carrying no verdict",
            "what_differs": "Both supervisors read the same filter and the same estimate. "
                            "`filtered` issues the largest motion the filter calls safe; "
                            "`conservative` issues the one with the most headroom.",
            "per_level": appetite,
            "reading": "The filter says what is permitted. How much of the permitted range a "
                       "supervisor takes is a separate choice, and this study cannot say which "
                       "appetite is right - only that the two differ enough to matter and that "
                       "the difference is not a property of the safety check.",
        },
        "results": results,
        "reading": "A constraint that composes is one a planner may chain: the per-step violation "
                   "rate does not rise by more than the margin from the first decision to the "
                   "last. A constraint that does not compose is a design consequence, not a score - "
                   "it says a safety layer fitted on one quantity cannot be reused for a different "
                   "constraint shape, and must be fitted per shape.",
        "scope_and_limitations": contract["scope_and_limitations"],
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"out": args.out.as_posix(), "requests": len(rows),
                      "composes": {k: v["composes"] for k, v in verdicts.items()},
                      "filter_worth_it": {k: v["beats_by_more_than_margin"]
                                          for k, v in worth_it.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
