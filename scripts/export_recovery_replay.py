"""Export exact decision inputs from a fixed set of existing routing requests.

The historical result files keep the chosen action but omit the full estimated
geometry. This exporter replays nine registered requests and copies the estimate
on each decision tick through the worker's existing observer. It performs no
additional perception draws and never changes the worker or its controller.

The resulting small JSON can exercise the inspector without MuJoCo or raw runs.
This is a software reproduction check, not another measurement study.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import platform
import subprocess
import sys
import time
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_study_v3 import content_sha256  # noqa: E402

ERROR_FIELDS = ("socket_bias_m", "socket_jitter_m", "centreline_occluded_m")
BUDGET_FIELDS = ("headroom_at_decision_m", "spent_by_this_motion_m", "spent_fraction",
                 "headroom_left_m")
POLICY_FIELDS = ("abstained", "action_index", "action", "magnitude_m", "headroom_m",
                 "decision_boot_to_anchor_m", "endpoint_boot_to_anchor_m",
                 "motion_completed", "requested")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def request_from_replay(replay: dict, case: dict, step: dict) -> dict:
    """Adapt a portable snapshot to the inspector's public JSON input schema.

    Expected outcomes are deliberately omitted: the inspector gets the original
    estimate and declared uncertainty, while the caller keeps scoring separate.
    """
    return {
        "schema": 1,
        "request_id": f"{case['request']}:step{step['step']}",
        "units": "m_rad_s",
        "context": copy.deepcopy(case["context"]),
        "decision": {key: copy.deepcopy(value) for key, value in step["decision"].items()
                     if key != "time_s"},
        "run_direction_xy": list(case["run_direction_xy"]),
        "declared_error": dict(case["declared_error"]),
        "candidate_actions": copy.deepcopy(replay["candidate_actions"]),
    }


def decision_snapshot(tick: dict) -> dict:
    """Copy only estimated geometry, without requesting another random draw."""
    estimate = tick["estimate"]
    boot = [float(value) for value in estimate.cable_centerline[0]]
    anchor = [float(value) for value in tick["scene"].fixture["anchor_site_world"]]
    return {
        "time_s": float(estimate.time_s),
        "insertion_axis": [float(value) for value in estimate.insertion_axis],
        "boot_position_m": boot,
        "anchor_site_m": anchor,
        "boot_to_anchor_m": math.sqrt(sum((a-b)**2 for a, b in zip(boot, anchor, strict=True))),
    }


def comparable_issued(row: dict) -> dict:
    """Keep every decision value; historical budget-unit prose is not arithmetic."""
    return {
        **{key: copy.deepcopy(row.get(key)) for key in POLICY_FIELDS},
        "step": row["step"],
        "time_s": row["time_s"],
        "verdict": copy.deepcopy(row["verdict"]),
        "budget": ({name: {key: budget[key] for key in BUDGET_FIELDS}
                    for name, budget in row["budget"].items()}
                   if row.get("budget") else None),
        "state_before": copy.deepcopy(row["state_before"]),
        "state_after": copy.deepcopy(row.get("state_after")),
    }


def stable_outcome(result: dict) -> dict:
    """The existing outcome, including censoring and guard counters."""
    return {
        "case": result["case"],
        "supervisor": result["supervisor"],
        "job": {key: result["job"][key]
                for key in ("failure_reason", "elapsed_s", "status")},
        "route_completed": result["route_completed"],
        "seated": result["seated"],
        "installed_clips": result["installed_clips"],
        "terminal_clips": result["terminal_clips"],
        "clip_loss_attribution": result["clip_loss_attribution"],
        "constraints": {name: row["state"] for name, row in result["constraints"].items()},
        "steps_offered": result["steps_offered"],
        "steps_issued": result["steps_issued"],
        "abstentions": result["abstentions"],
        "guards": {
            "privilege": result["privilege_guard"]["events"],
            "mutation": result["mutation_guard"]["forbidden_events"],
        },
        "issued": [comparable_issued(row) for row in result["issued"]],
    }


def differences(actual, expected, path: str = "", tolerance: float = 1e-12) -> list[str]:
    """Compare nested records with an explicit absolute numerical tolerance."""
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        return [] if type(actual) is type(expected) and actual == expected else [path]
    if isinstance(expected, (int, float)):
        valid = isinstance(actual, (int, float)) and not isinstance(actual, bool)
        return [] if valid and math.isclose(actual, expected, rel_tol=0, abs_tol=tolerance) else [path]
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            return [path + ":keys"]
        return [item for key in expected
                for item in differences(actual[key], expected[key], f"{path}.{key}", tolerance)]
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [path + ":length"]
        return [item for index, value in enumerate(expected)
                for item in differences(actual[index], value, f"{path}[{index}]", tolerance)]
    raise TypeError(f"Unsupported comparison value at {path}: {type(expected).__name__}")


def source_provenance(root: Path, paths: list[Path]) -> dict:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                            capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"],
                            cwd=root, check=True, capture_output=True, text=True).stdout
    return {
        "commit": commit,
        "dirty": bool(status.strip()),
        "working_tree_status": status.splitlines(),
        "source_sha256": {path.relative_to(root).as_posix(): content_sha256(path)
                          for path in paths},
        "hashing": "cable_study_v3.content_sha256 (normalised text line endings)",
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "packages": {distribution.metadata["Name"]: distribution.version
                         for distribution in sorted(distributions(),
                                                    key=lambda item: item.metadata["Name"].lower())},
        },
    }


def capture_case(runtime: dict, case_id: str, reference_dir: Path, output_dir: Path,
                 tolerance: float) -> tuple[dict, dict]:
    # Lazy imports keep this module and the portable adapter simulator-free.
    from scripts.evaluate_cable_routing_v6 import run_case

    case = next((row for row in runtime["cases"] if row["id"] == case_id), None)
    if case is None:
        raise ValueError(f"Not a registered case in the runtime: {case_id}")
    reference_path = reference_dir / case_id / "result.json"
    reference = read_json(reference_path)
    snapshots: list[dict] = []

    def observe(tick: dict) -> None:
        count = len(tick["issued"])
        if count == len(snapshots):
            return
        if count != len(snapshots)+1:
            raise RuntimeError("The observer skipped a repair decision")
        row = tick["issued"][-1]
        snapshot = decision_snapshot(tick)
        if not math.isclose(snapshot["boot_to_anchor_m"], row["decision_boot_to_anchor_m"],
                            rel_tol=0, abs_tol=tolerance):
            raise RuntimeError("Captured estimate differs from the decision the worker used")
        snapshots.append({"step": row["step"], "decision": snapshot})

    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    measured = run_case(runtime, case, output_dir, observe)
    elapsed = time.monotonic()-started
    expected = stable_outcome(reference)
    mismatches = differences(stable_outcome(measured), expected, tolerance=tolerance)
    if len(snapshots) != len(reference["issued"]):
        mismatches.append("captured_decisions:length")
    guard_events = measured["privilege_guard"]["events"] + measured["mutation_guard"]["forbidden_events"]
    if guard_events:
        mismatches.append("guard_events")
    verification = {
        "request": case_id,
        "reproduces_original": not mismatches,
        "mismatches": mismatches,
        "decisions": len(snapshots),
        "wall_seconds": round(elapsed, 3),
        "reference": reference_path.as_posix(),
        "reference_sha256": content_sha256(reference_path),
    }
    write_json(output_dir / "replay_check.json", verification)
    if mismatches:
        raise RuntimeError(f"Replay mismatch for {case_id}: {mismatches[:12]}")
    for snapshot, row in zip(snapshots, reference["issued"], strict=True):
        snapshot["expected"] = comparable_issued(row)
    level_id = measured["error_level"]
    levels = runtime["perception"]["levels"]
    level = next(row for row in levels if row["id"] == level_id)
    compact = {
        "request": case_id,
        "supervisor": case["supervisor"],
        "error_level": level_id,
        "seeds": {key: case[key] for key in ("calibration_seed", "perception_seed") if key in case},
        "context": {
            "geometry_id": measured["cell"]["id"],
            "required_clips": len(measured["cell"]["required"]),
            "cable_segments": int(runtime["cable"]["segments"]),
            "physics_hz": int(runtime["clocks"]["physics_hz"]),
            "task": "held_clip_preserving_seating",
        },
        "run_direction_xy": case["run_direction_xy"],
        "declared_error": {name: level[name] for name in ERROR_FIELDS},
        "recorded_outcome": {key: value for key, value in expected.items()
                             if key not in ("case", "issued")},
        "decisions": snapshots,
        "source": {"result": f"artifacts/cable/routing-v6-s1/{case_id}/result.json",
                   "sha256": content_sha256(reference_path)},
    }
    return compact, verification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=Path("configs/recovery_inspector_demo.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    config_path = root / args.config
    config = read_json(config_path)
    runtime_path = root / config["source_runtime"]
    runtime = read_json(runtime_path)
    output_dir = root / config["outputs"]["raw_capture"]
    output_dir.mkdir(parents=True, exist_ok=True)
    source_paths = sorted({
        config_path, runtime_path,
        *(root / "src/assembly_recovery").rglob("*.py"),
        *(root / "scripts").glob("*.py"),
        *(root / "configs").glob("*.json"),
        *(root / "assets/cell_v6").glob("*.stl"),
        root / "evidence/cable_perception_v4.json",
        root / "evidence/cable_cell_cad_v6.json",
        root / "evidence/cable_cell_screen_v6.json",
    })
    provenance = source_provenance(root, source_paths)
    provenance["selected_cases"] = config["cases"]
    write_json(output_dir / "prelaunch.json", provenance)
    if provenance["dirty"]:
        raise RuntimeError("Commit the implementation and fixed replay config before capture; "
                           "the working tree is dirty. No simulation was launched.")
    cases, checks = [], []
    for case_id in config["cases"]:
        compact, check = capture_case(
            runtime, case_id, root / config["source_results"], output_dir / case_id,
            float(config["verification"]["decision_tolerance_m"]))
        cases.append(compact)
        checks.append(check)
        print(json.dumps({"request": case_id, "reproduces_original": True,
                          "decisions": check["decisions"]}), flush=True)
    record = {
        "schema": 1,
        "id": "recovery_inspector_replay_v1",
        "created_on": config["created_on"],
        "scope": config["scope"],
        "selection_rule": config["selection_rule"],
        "capture_method": config["capture"],
        "claims": config["claims"],
        "budget_units": "All three budgets are metres of boot-to-anchor distance. Historical "
                        "budget unit labels were incorrect; the numerical values are unchanged.",
        "safety_filter": runtime["safety_filter"],
        "candidate_actions": runtime["route"]["candidate_actions"],
        "cases": cases,
        "verification": {
            "status": "verified",
            "cases": len(cases),
            "decisions": sum(len(case["decisions"]) for case in cases),
            "reproduces_original": all(check["reproduces_original"] for check in checks),
            "comparison_tolerance": config["verification"],
            "checks": checks,
        },
        "provenance": provenance,
    }
    destination = root / config["outputs"]["portable_replay"]
    write_json(destination, record)
    print(json.dumps({"wrote": str(destination), "cases": len(cases),
                      "decisions": record["verification"]["decisions"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
