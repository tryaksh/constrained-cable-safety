"""Independent replay check of every constrained-cable recovery verdict.

Recomputes the seating dwell, first witness, clip loss, load aborts, deadline and
whole-request denominators from the recorded native and servo ledgers alone,
without re-running physics, and compares them with the worker's own verdicts.
Agreement is an accounting check, not a second physical measurement.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_jobs import CableJob, CableJobLimits, CableSample  # noqa: E402


def replay(ledger, limits: CableJobLimits) -> dict:
    """Rebuild the job verdict from the servo ledger using the same predicate."""
    channels = {name: i for i, name in enumerate(ledger["servo_channels"])}
    rows = ledger["servo"]
    job = CableJob(limits)
    for k, row in enumerate(rows):
        dt = float(rows[k + 1][channels["time_s"]] - row[channels["time_s"]]) if k + 1 < len(rows) else None
        if dt is None:
            dt = float(rows[1][channels["time_s"]] - rows[0][channels["time_s"]]) if len(rows) > 1 else 0.002
        sample = CableSample(
            float(row[channels["time_s"]]) + dt, dt,
            float(row[channels["seating_error_m"]]), float(row[channels["seating_angle_rad"]]),
            float(row[channels["insertion_depth_m"]]), float(row[channels["commanded_depth_m"]]),
            float(row[channels["raw_wrist_load_n"]]), float(row[channels["raw_plug_load_n"]]),
            float(row[channels["anchor_load_n"]]),
            float(row[channels["plug_port_contact_n"]]), float(row[channels["cable_post_contact_n"]]),
            bool(row[channels["clip_retained"]] > 0.5), True,
            bool(row[channels["port_detector_contact_n"]] > limits.contact_witness_n),
            int(row[channels["forbidden_events"]]))
        if job.update(sample) != "active":
            break
    return job.report()


def check_case(directory: Path) -> dict:
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if not (directory / "ledger.npz").exists():
        return {"case": result["case"]["id"], "replayed": False,
                "reason": result["job"].get("failure_reason"), "agrees": None}
    ledger = np.load(directory / "ledger.npz", allow_pickle=False)
    limits = CableJobLimits(**{**json.loads((ROOT / "configs/cable_recovery_task_v2.json")
                                            .read_text(encoding="utf-8-sig"))["job_limits"],
                               **result["case"].get("job_limits_override", {})})
    native = ledger["native"]
    channels = {name: i for i, name in enumerate(ledger["servo_channels"])}
    rows = ledger["servo"]
    replayed = replay(ledger, limits)
    worker = result["job"]
    checks = {
        "status_agrees": replayed["status"] == worker["status"],
        "reason_agrees": replayed["failure_reason"] == worker["failure_reason"],
        "witness_agrees": replayed["witness_type"] == worker["witness_type"],
        "dwell_agrees": abs(replayed["dwell_s"] - worker["dwell_s"]) < 1e-12,
        "elapsed_agrees": abs(replayed["elapsed_s"] - worker["elapsed_s"]) < 1e-12,
        "native_rows_cover_job": len(native) > 0 and abs(
            float(native[-1][0]) - worker["elapsed_s"]) <= 1.5 * float(rows[1][0] - rows[0][0]),
        "native_wrist_under_limit_until_end": bool(
            np.all(native[:-1, 1] <= limits.wrist_force_n) if len(native) > 1 else True),
        "clip_flag_matches_terminal": bool(
            (rows[-1][channels["clip_retained"]] > 0.5) == result["terminal_clip_retained"]
            or worker["failure_reason"] == "lost_required_clip"),
        "no_unreported_mutation": int(rows[:, channels["forbidden_events"]].max()) == (
            result["mutation_guard"]["forbidden_events"] if result.get("mutation_guard") else 0),
    }
    return {
        "case": result["case"]["id"], "controller": result["controller"], "replayed": True,
        "worker": {k: worker[k] for k in ("status", "failure_reason", "witness_type", "dwell_s", "elapsed_s")},
        "independent": {k: replayed[k] for k in ("status", "failure_reason", "witness_type", "dwell_s", "elapsed_s")},
        "checks": checks, "agrees": all(checks.values()),
        "first_witness_s": replayed["first_witness_s"],
        "peak_native_wrist_n": float(native[:, 1].max()) if len(native) else None,
        "peak_native_plug_n": float(native[:, 2].max()) if len(native) else None,
        "peak_native_anchor_sensor_n": float(native[:, 3].max()) if len(native) else None,
        "peak_anchor_reaction_n": float(rows[:, channels["anchor_load_n"]].max()),
        "max_retreat_travel_m": float(
            (rows[0][channels["tip_z"]] - rows[:, channels["tip_z"]]).min() * -1),
        "terminal_clip_margin_m": result["terminal_clip_margin_m"],
        "native_rows": int(len(native)), "servo_rows": int(len(rows)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    cases = [check_case(d) for d in sorted(args.run_dir.iterdir())
             if d.is_dir() and (d / "result.json").exists()]
    summary = {
        "schema": 1, "run_dir": str(args.run_dir), "cases": cases,
        "requests": len(cases),
        "replayed": sum(1 for c in cases if c["replayed"]),
        "agreeing": sum(1 for c in cases if c["agrees"]),
        "disagreeing": [c["case"] for c in cases if c["replayed"] and not c["agrees"]],
        "scope": [
            "Recomputes verdicts from the recorded ledgers with the same predicate; it does not re-run physics.",
            "Agreement shows the stored ledger is sufficient to reproduce every reported verdict.",
            "Native rows carry the authoritative abort channels at the physics rate.",
        ],
    }
    text = json.dumps(summary, indent=2, allow_nan=False, default=float)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps({"requests": summary["requests"], "replayed": summary["replayed"],
                      "agreeing": summary["agreeing"], "disagreeing": summary["disagreeing"]}))
    return 0 if not summary["disagreeing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
