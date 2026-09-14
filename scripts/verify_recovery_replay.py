"""Check the decision inspector against the portable registered-run replay.

No simulator or raw run directory is required. Each original policy's action,
chosen magnitude, verdict and all three budgets must match its recorded result.
The check does not estimate success rates or score alternative trajectories.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.recovery_inspector import RecoveryInspector  # noqa: E402
from scripts.export_recovery_replay import (  # noqa: E402
    BUDGET_FIELDS,
    differences,
    read_json,
    request_from_replay,
)


def compare_decision(report: dict, supervisor: str, expected: dict) -> list[str]:
    """Compare only the policy that acted on this historical trajectory."""
    pick = report["policies"][supervisor]
    compared = {key: pick[key] for key in ("abstained", "action_index")}
    wanted = {key: expected[key] for key in compared}
    mismatch = differences(compared, wanted, "policy")
    if expected["action_index"] is None or mismatch:
        return mismatch
    candidate = report["candidates"][pick["action_index"]]
    compared = {key: candidate[key] for key in ("action", "magnitude_m")}
    wanted = {key: expected[key] for key in compared}
    if supervisor != "unfiltered":
        compared["headroom_m"] = candidate["headroom_m"]
        wanted["headroom_m"] = expected["headroom_m"]
        compared["verdict"] = {
            "safe": candidate["rule_status"] == "allowed",
            "refused_by": candidate["refused_by"],
            "unscored": candidate["unscored"],
            "binding_constraint": candidate["binding_constraint"],
            "constraints": copy.deepcopy(candidate["constraints"]),
        }
        wanted["verdict"] = expected["verdict"]
    compared["budget"] = {
        name: {key: budget[key] for key in BUDGET_FIELDS}
        for name, budget in candidate["budget"].items()}
    wanted["budget"] = expected["budget"]
    # Unfiltered decisions also record geometric budgets, but their verdict is
    # explicitly "no filter was consulted". Never retrofit a filtered verdict.
    compared["endpoint_boot_to_anchor_m"] = next(
        row["endpoint_distance_m"] for row in candidate["constraints"].values()
        if row["state"] != "unscored")
    wanted["endpoint_boot_to_anchor_m"] = expected["endpoint_boot_to_anchor_m"]
    return mismatch + differences(compared, wanted, "chosen_candidate")


def verify_replay(replay: dict, inspector: RecoveryInspector) -> dict:
    """Return a JSON-safe software verification record for every stored decision."""
    checks = []
    for case in replay["cases"]:
        for step in case["decisions"]:
            request = request_from_replay(replay, case, step)
            report = inspector.inspect(request)
            mismatch = compare_decision(report, case["supervisor"], step["expected"])
            checks.append({"request": case["request"], "step": step["step"],
                           "supervisor": case["supervisor"], "passes": not mismatch,
                           "mismatches": mismatch})
    source_verified = bool(replay["verification"]["reproduces_original"])
    return {
        "schema": 1,
        "status": "verified" if source_verified and checks and all(row["passes"] for row in checks)
                  else "FAILED",
        "cases": len(replay["cases"]),
        "decisions": len(checks),
        "mismatched_decisions": sum(not row["passes"] for row in checks),
        "source_replays_verified": source_verified,
        "absolute_numerical_tolerance": 1e-12,
        "checks": checks,
        "scope": "Software parity on a fixed nine-request replay selection. The original "
                 "supervisor's action and budget are checked at its own estimates. No new "
                 "controller, performance rate, rescoring, or counterfactual outcome claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--replay", type=Path, default=Path("artifacts/showcase/recovery_replay.json"))
    parser.add_argument("--json", action="store_true", help="Print the full verification record.")
    args = parser.parse_args()
    try:
        replay = read_json(args.root / args.replay)
        result = verify_replay(replay, RecoveryInspector.from_repository(args.root))
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        print(f"{result['status']}: {result['decisions']} recorded decisions from "
              f"{result['cases']} registered requests; "
              f"{result['mismatched_decisions']} mismatches.")
        print("Checks the original policy's action, magnitude, verdict and all three budgets.")
        print("Software replay only; the four historical studies are unchanged.")
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
