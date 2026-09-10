"""Launch one native cable worker with prelaunch provenance and a wall deadline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_run import execute_run  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--worker", type=Path, default=Path("scripts/probe_cable_task.py"))
    parser.add_argument("--config", type=Path, default=Path("configs/cable_task_v2.json"))
    parser.add_argument("--max-minutes", type=float, default=10)
    parser.add_argument("--python", type=Path, default=ROOT / ".deps/cable-venv/Scripts/python.exe")
    parser.add_argument("worker_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    worker_args = args.worker_args[1:] if args.worker_args[:1] == ["--"] else args.worker_args
    try:
        manifest = execute_run(
            root=ROOT,
            run_id=args.run_id,
            worker=ROOT / args.worker,
            config=ROOT / args.config,
            python=ROOT / args.python,
            max_minutes=args.max_minutes,
            worker_args=worker_args,
        )
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {"status": manifest["status"], "manifest": str(ROOT / "artifacts/cable" / args.run_id / "manifest.json")}
        )
    )
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
