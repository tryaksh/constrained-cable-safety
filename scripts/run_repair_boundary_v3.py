"""Generate and launch the registered safe-repair boundary block.

The frozen contract in ``configs/cable_repair_boundary_v3.json`` names the
support, the action design, the held-out group split and the pre-registered
decision rule. This script expands it into a runnable case list, checks that the
base task it merges onto is the one the contract declares, and hands the result
to the ordinary cable launcher so the run gets the usual prelaunch provenance.

It runs no physics itself and makes no decision. A pilot run is labelled as a
pilot and uses its own run id, so it can never be mistaken for the registered
block.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_run import execute_run  # noqa: E402
from assembly_recovery.cable_study_v3 import (  # noqa: E402
    build_contexts,
    content_sha256,
    merge_runtime,
    raw_sha256,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_repair_boundary_v3.json"))
    parser.add_argument("--max-minutes", type=float, default=180)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--pilot-contexts", type=int, default=0,
                        help="Run only the first N registered contexts. A pilot, not the block.")
    parser.add_argument("--dry-run", action="store_true", help="Write the runtime config and stop.")
    parser.add_argument("--python", type=Path, default=ROOT / ".deps/cable-venv/Scripts/python.exe")
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    base_path = ROOT / contract["base_config"]["path"]
    measured = content_sha256(base_path)
    if measured != contract["base_config"]["content_sha256"]:
        parser.error(f"Base task content hash is {measured}, contract declares "
                     f"{contract['base_config']['content_sha256']}")

    runtime = merge_runtime(json.loads(base_path.read_text(encoding="utf-8-sig")), contract)
    if args.pilot_contexts:
        keep = {c["id"] for c in build_contexts(contract)[:args.pilot_contexts]}
        runtime["cases"] = [c for c in runtime["cases"] if c["study_context"] in keep]
        runtime["id"] = contract["id"] + "_pilot"
        runtime["pilot"] = {"contexts": sorted(keep),
                            "note": "Pilot subset for timing and outcome spread. Not the registered block."}
    expected = contract["expected_requests"]
    if not args.pilot_contexts and len(runtime["cases"]) != expected:
        parser.error(f"Expanded {len(runtime['cases'])} requests, contract declares {expected}")

    runtime_path = ROOT / "artifacts/cable" / f"{args.run_id}__runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime, indent=1), encoding="utf-8")
    summary = {
        "run_id": args.run_id, "contract": args.contract.as_posix(),
        "contract_content_sha256": content_sha256(ROOT / args.contract),
        "base_content_sha256": measured, "base_raw_sha256": raw_sha256(base_path),
        "runtime_config": runtime_path.relative_to(ROOT).as_posix(),
        "runtime_content_sha256": content_sha256(runtime_path),
        "requests": len(runtime["cases"]),
        "contexts": len({c["study_context"] for c in runtime["cases"]}),
        "pilot": bool(args.pilot_contexts),
    }
    if args.dry_run:
        print(json.dumps({**summary, "status": "dry_run"}, indent=1))
        return 0

    manifest = execute_run(
        root=ROOT, run_id=args.run_id, worker=ROOT / "scripts/evaluate_cable_recovery_v2.py",
        config=runtime_path, python=ROOT / args.python, max_minutes=args.max_minutes,
        worker_args=["--workers", str(args.workers)],
    )
    print(json.dumps({**summary, "status": manifest["status"],
                      "manifest": (ROOT / "artifacts/cable" / args.run_id / "manifest.json").as_posix()}, indent=1))
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
