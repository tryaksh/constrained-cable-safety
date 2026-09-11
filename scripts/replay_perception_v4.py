"""Re-derive the recorded constraint labels from the stored ledgers alone.

A label is only as trustworthy as the path between the physics and the record. The
v2 block proved that path by replaying 34 requests from their ledgers and
reproducing status, reason, witness, dwell and elapsed time. This does the same
for the two constraints a servo ledger fully determines, over every request in the
block rather than a sample of it:

  ``C1`` clip retention is stored per servo tick and at the terminal state.
  ``C3`` the anchor reaction is stored per servo tick, so its peak is recoverable.

``C2`` is not checkable this way and that is stated rather than glossed: the
minimum bend radius needs the whole centreline at every tick, and storing 16,080
of those was not affordable. The centreline IS stored at the registered events, so
C2 is spot-checked against the terminal state instead, which is a weaker check and
is reported as one.

Reads only artifacts. Runs no physics and fits nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_constraints_v4 import min_bend_radius  # noqa: E402


def replay_one(directory: Path, c3_limit: float, c2_spec: float) -> dict | None:
    result_path = directory / "result.json"
    ledger_path = directory / "ledger.npz"
    if not result_path.is_file() or not ledger_path.is_file():
        return None
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("decision_state") is None and result["job"]["status"] != "failed":
        return None
    ledger = np.load(ledger_path, allow_pickle=False)
    channels = {str(name): i for i, name in enumerate(ledger["servo_channels"])}
    rows = ledger["servo"]
    if rows.size == 0:
        return None

    clip_column = channels.get("clip_retained")
    anchor_columns = [channels[name] for name in ("anchor_cx", "anchor_cy", "anchor_cz")
                      if name in channels]
    if clip_column is None or len(anchor_columns) != 3:
        return {"case": result["case"]["id"], "checkable": False,
                "reason": "ledger does not carry the required channels"}

    clip_went = bool((rows[:, clip_column] < 0.5).any())
    replayed_c1 = clip_went or not result["terminal_clip_retained"]
    peak_anchor = float(np.linalg.norm(rows[:, anchor_columns], axis=1).max())
    replayed_c3 = peak_anchor > c3_limit

    recorded = result["constraints"]
    report = result.get("constraint_report") or {}
    terminal_radius = float(min_bend_radius(ledger["terminal_centerline"]))
    out = {
        "case": result["case"]["id"], "checkable": True,
        "C1_recorded": recorded["C1_clip"]["state"],
        "C1_replayed_violated": bool(replayed_c1),
        "C1_agrees": bool((recorded["C1_clip"]["state"] == "violated") == replayed_c1),
        "C3_recorded": recorded["C3_anchor"]["state"],
        "C3_replayed_violated": bool(replayed_c3),
        "C3_peak_anchor_replayed_n": peak_anchor,
        "C3_peak_anchor_recorded_n": report.get("peak_anchor_reaction_n"),
        "C3_agrees": bool((recorded["C3_anchor"]["state"] == "violated") == replayed_c3),
        "C2_terminal_radius_m": terminal_radius,
        "C2_terminal_below_spec": bool(terminal_radius < c2_spec),
        "C2_recorded": recorded["C2_bend"]["state"],
    }
    # A censored request has no observed label, so an agreement test on it would be
    # a test of the censoring rule rather than of the ledger.
    for name in ("C1", "C3"):
        if out[f"{name}_recorded"] == "censored":
            out[f"{name}_agrees"] = None
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--out", type=Path, default=Path("evidence/cable_perception_replay_v4.json"))
    parser.add_argument("--limit", type=int, default=0, help="Replay only the first N requests.")
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    c3_limit = float(contract["constraints"]["C3_anchor"]["limit_n"])
    c2_spec = float(contract["constraints"]["C2_bend"]["spec_m"])

    rows, skipped = [], 0
    for run_dir in args.run_dir:
        for directory in sorted(p for p in (ROOT / run_dir).iterdir() if p.is_dir()):
            record = replay_one(directory, c3_limit, c2_spec)
            if record is None:
                skipped += 1
                continue
            rows.append(record)
            if args.limit and len(rows) >= args.limit:
                break
        if args.limit and len(rows) >= args.limit:
            break

    def agreement(name):
        tested = [r for r in rows if r.get(f"{name}_agrees") is not None]
        disagreeing = [r for r in tested if not r[f"{name}_agrees"]]
        return {"tested": len(tested), "agree": len(tested)-len(disagreeing),
                "disagree": len(disagreeing),
                "verdict": "pass" if not disagreeing else "fail",
                "first_disagreements": [r["case"] for r in disagreeing[:10]]}

    anchor_error = [abs(r["C3_peak_anchor_replayed_n"]-r["C3_peak_anchor_recorded_n"])
                    for r in rows if r.get("C3_peak_anchor_recorded_n") is not None]
    report = {
        "schema": 1, "id": "cable_perception_replay_v4", "created_on": contract["created_on"],
        "status": "executed_ledger_replay",
        "scope": "Independent re-derivation of the recorded constraint labels from the stored "
                 "servo ledgers. Runs no physics and fits nothing. Not a study result.",
        "run_dirs": [Path(d).as_posix() for d in args.run_dir],
        "requests_replayed": len(rows), "requests_without_a_ledger": skipped,
        "C1_clip": agreement("C1"), "C3_anchor": agreement("C3"),
        "C3_peak_anchor_reconstruction": {
            "max_absolute_error_n": max(anchor_error) if anchor_error else None,
            "note": "The scorer reads the anchor reaction at servo ticks and the ledger stores it "
                    "at servo ticks, so the peak must be recovered exactly. A non-zero error here "
                    "would mean the record and the ledger disagree about what was measured.",
        },
        "C2_bend": {
            "checkable_from_the_ledger": False,
            "why": "The minimum bend radius is a running minimum over the whole centreline at "
                   "every servo tick, and the ledger stores the centreline only at the registered "
                   "events. Storing 16,080 dense centrelines was not affordable.",
            "spot_check": "The terminal centreline IS stored, so the terminal radius is "
                          "recomputed for every request and reported beside the recorded label. "
                          "It is a weaker check than the C1 and C3 replays and must not be read as "
                          "an equivalent one.",
            "terminal_radius_below_spec": sum(1 for r in rows if r.get("C2_terminal_below_spec")),
            "recorded_violated": sum(1 for r in rows if r.get("C2_recorded") == "violated"),
        },
        "reading": "A pass means the label in the record is the label the stored physics supports. "
                   "It does not establish that the physics is right, only that the record is not "
                   "drifting from it.",
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"out": args.out.as_posix(), "replayed": len(rows),
                      "C1": report["C1_clip"]["verdict"], "C3": report["C3_anchor"]["verdict"]},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
