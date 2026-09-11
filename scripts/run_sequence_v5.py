"""Freeze and launch the composition study: does the safety check chain?

Expands the frozen contract into one request per (held-out group, error level,
supervisor), checks that the base task it merges onto is the one the contract
declares, checks that the safety filter it will load actually exists, and hands
the list to the ordinary cable launcher so the run gets the usual prelaunch
provenance.

It runs no physics and makes no decision. It refuses to expand if the perception
study has not been fitted yet, because the filter under test is that study's
output and there is nothing to chain without it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_run import execute_run  # noqa: E402
from assembly_recovery.cable_safety_filter_v4 import SafetyFilter  # noqa: E402
from assembly_recovery.cable_study_v4 import content_sha256, raw_sha256  # noqa: E402


def build_cases(contract: dict, perception: dict) -> list[dict]:
    """One request per held-out group, error level and supervisor."""
    support = perception["registered_support"]
    registered = contract["registered_support"]
    layouts = {layout["id"]: layout for layout in support["layouts"]}
    mounts = [m for m in support["port_mount"] if m["id"] in registered["port_mount"]]
    levels = registered["error_levels"]
    repeats = int(registered.get("repeats", 1))
    supervisors = [s["id"] for s in contract["sequence"]["supervisors"]]
    cases, seed = [], contract["first_calibration_seed"]
    for group in perception["groups"]["test"]:
        layout_id, loop_tag = group.rsplit("_l", 1)
        layout = layouts[layout_id]
        loop = int(loop_tag)/1000.0
        for mount in mounts:
            for level in levels:
                for supervisor in supervisors:
                    for repeat in range(repeats):
                        cases.append(one_case(contract, group, layout, loop, mount, level,
                                              supervisor, repeat, seed))
                        seed += 1
    return cases


def one_case(contract, group, layout, loop, mount, level, supervisor, repeat, seed) -> dict:
    """One sequence request. The perception seed is distinct for every repeat."""
    case = {
        "id": f"{group}_{mount['id']}_{level}_{supervisor}_r{repeat}",
        "controller": "sequence_supervisor",
        "calibration_seed": seed,
        "perception_seed": seed+contract["perception_seed_offset"],
        "run_direction_xy": layout["run_direction_xy"],
        "outward_xy": layout["outward_xy"],
        "route_waypoints_along_across_m": layout["route_waypoints_along_across_m"],
        "fixture_overrides": {
            **layout.get("fixture_overrides", {}),
            "clip": {**layout.get("fixture_overrides", {}).get("clip", {}),
                     "along_m": layout["clip_along_m"]}},
        "installed_loop_m": loop,
        "fixture_offset_m": [0.0, 0.0],
        "port_compliance": mount["compliance"],
        "error_level": level, "error_isolation": "all",
        "supervisor": supervisor, "repeat": repeat,
        "study_group": group, "study_split": "sequence_holdout",
        "gate": "S2",
        "purpose": "Composition study: three filtered decisions in one sequence.",
    }
    if layout.get("cable_overrides"):
        case["cable_overrides"] = dict(layout["cable_overrides"])
    return case


def merge_runtime(base: dict, contract: dict, perception: dict) -> dict:
    runtime = json.loads(json.dumps(base))
    for key, value in contract["runtime_overrides"].items():
        if isinstance(value, dict) and isinstance(runtime.get(key), dict):
            runtime[key] = {**runtime[key], **value}
        else:
            runtime[key] = value
    runtime["id"] = contract["id"]
    runtime["scope"] = contract["scope"]
    runtime["perception"] = {"camera": perception["error_model"]["camera"],
                             "levels": perception["error_model"]["levels"],
                             "isolation": perception["error_model"].get("isolation"),
                             "history": perception["error_model"]["history"]}
    runtime["constraints"] = perception["constraints"]
    runtime["safety_filter"] = contract["safety_filter"]
    runtime["sequence"] = contract["sequence"]
    runtime["cases"] = build_cases(contract, perception)
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_sequence_v5.json"))
    parser.add_argument("--perception", type=Path,
                        default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--max-minutes", type=float, default=180)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--python", type=Path, default=ROOT / ".deps/cable-venv/Scripts/python.exe")
    args = parser.parse_args()

    contract_path = ROOT / args.contract
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    perception = json.loads((ROOT / args.perception).read_text(encoding="utf-8-sig"))
    base_path = ROOT / contract["base_config"]["path"]

    fit_path = ROOT / contract["safety_filter"]["fit"]
    if not fit_path.is_file():
        parser.error(f"The filter under test comes from {fit_path.name}, which does not exist yet. "
                     f"Fit the perception block first; there is nothing to chain without it.")
    loaded = SafetyFilter.from_evidence(fit_path, ROOT / contract["safety_filter"]["contract"],
                                        ROOT / contract["safety_filter"]["base"])
    if not loaded.rules:
        parser.error("The perception record carries no fitted threshold for any constraint.")

    if args.freeze:
        contract["base_config"]["content_sha256"] = content_sha256(base_path)
        cases = build_cases(contract, perception)
        contract["expected_requests"] = len(cases)
        registered = contract["registered_support"]
        per_cell = (len(perception["groups"]["test"])*len(registered["port_mount"])
                    * int(registered.get("repeats", 1)))
        contract["frozen_counts"] = {
            "held_out_groups": len(perception["groups"]["test"]),
            "port_mounts": len(registered["port_mount"]),
            "repeats": int(registered.get("repeats", 1)),
            "error_levels": len(registered["error_levels"]),
            "supervisors": len(contract["sequence"]["supervisors"]),
            "steps_per_request": len(contract["sequence"]["decision_times_s"]),
            "sequences_per_level_and_supervisor": per_cell,
            "per_step_metric_resolution": 1/per_cell if per_cell else None,
            "requests": len(cases),
            "decisions": len(cases)*len(contract["sequence"]["decision_times_s"]),
        }
        required = 2*contract["decision_rule"]["margin"]
        if per_cell and 1/per_cell > required:
            raise SystemExit(
                f"A per-step rate over {per_cell} sequences resolves to {1/per_cell:.4f}, which the "
                f"registered margin of {contract['decision_rule']['margin']} cannot beat. Widen the "
                f"support or the repeats; do not lower the margin.")
        contract["safety_filter"]["loaded_at_freeze"] = loaded.report()
        contract_path.write_text(json.dumps(contract, indent=1, ensure_ascii=False)+"\n",
                                 encoding="utf-8")
        print(json.dumps({"status": "frozen", "contract": args.contract.as_posix(),
                          "content_sha256": content_sha256(contract_path),
                          **contract["frozen_counts"]}, indent=1))
        return 0

    if not args.run_id:
        parser.error("--run-id is required unless --freeze is given")
    if contract["expected_requests"] == "PENDING_FREEZE":
        parser.error("Contract is not frozen. Run --freeze first, then commit it, then launch.")
    measured = content_sha256(base_path)
    if measured != contract["base_config"]["content_sha256"]:
        parser.error(f"Base task content hash is {measured}, contract declares "
                     f"{contract['base_config']['content_sha256']}")

    runtime = merge_runtime(json.loads(base_path.read_text(encoding="utf-8-sig")), contract,
                            perception)
    if len(runtime["cases"]) != contract["expected_requests"]:
        parser.error(f"Expanded {len(runtime['cases'])} requests, contract declares "
                     f"{contract['expected_requests']}")

    runtime_path = ROOT / "artifacts/cable" / f"{args.run_id}__runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime, indent=1), encoding="utf-8")
    summary = {
        "run_id": args.run_id, "contract": args.contract.as_posix(),
        "contract_content_sha256": content_sha256(contract_path),
        "perception_fit_sha256": content_sha256(fit_path),
        "base_content_sha256": measured, "base_raw_sha256": raw_sha256(base_path),
        "runtime_config": runtime_path.relative_to(ROOT).as_posix(),
        "requests": len(runtime["cases"]),
        "decisions": len(runtime["cases"])*len(contract["sequence"]["decision_times_s"]),
    }
    if args.dry_run:
        print(json.dumps({**summary, "status": "dry_run"}, indent=1))
        return 0

    manifest = execute_run(
        root=ROOT, run_id=args.run_id,
        worker=ROOT / "scripts/evaluate_cable_sequence_v5.py",
        config=runtime_path, python=ROOT / args.python, max_minutes=args.max_minutes,
        worker_args=["--workers", str(args.workers)],
    )
    print(json.dumps({**summary, "status": manifest["status"]}, indent=1))
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
