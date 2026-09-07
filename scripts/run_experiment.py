"""Plan or run a bounded, provenance-recorded upstream FORGE infrastructure check."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assembly_recovery.protocol import (  # noqa: E402
    LAB_COMMIT,
    RunSpec,
    assess_completion,
    sha256,
    training_command,
    validate_run_id,
    validate_study,
    write_json,
)


def git(directory: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-c", f"safe.directory={directory.as_posix()}", "-C", str(directory),
                                    *arguments], text=True, stderr=subprocess.PIPE).strip()


def snapshot_source(output: Path) -> dict:
    paths = set()
    for folder in ("src/assembly_recovery", "scripts", "configs"):
        paths.update(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".ps1", ".json"})
    paths.update(ROOT / name for name in ("README.md", "ROADMAP.md", "AGENTS.md", "pyproject.toml", "environment-lock.example.json"))
    result = {}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            relative = path.relative_to(ROOT).as_posix()
            # Use the exact same bytes for the snapshot and hash.
            content = path.read_bytes()
            result[relative] = hashlib.sha256(content).hexdigest()
            archive.writestr(relative, content)
    return result


def stop_owned_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)


def run_bounded(command: list[str], log_path: Path, deadline: float, env: dict) -> tuple[int, bool]:
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with log_path.open("w", encoding="utf8") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        try:
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stop_owned_process(process)
                    return process.returncode, True
                try:
                    process.wait(timeout=min(30, remaining))
                except subprocess.TimeoutExpired:
                    print(f"Running PID {process.pid}; deadline in {max(0, int(deadline - time.monotonic()))}s; log: {log_path}", flush=True)
            return process.returncode, False
        except BaseException:
            if process.poll() is None:
                stop_owned_process(process)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "smoke", "train"))
    parser.add_argument("--task", choices=("peg", "gear"), default="peg")
    parser.add_argument("--run-id")
    parser.add_argument("--seed", type=int, default=170)
    parser.add_argument("--num-envs", type=int)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--max-minutes", type=int, default=15)
    parser.add_argument("--sim-python", type=Path, default=Path("C:/isaac-sim/python.bat"))
    args = parser.parse_args()
    try:
        num_envs = args.num_envs if args.num_envs is not None else (4 if args.mode == "smoke" else 64)
        spec = RunSpec(args.task, args.seed, num_envs, args.epochs, args.max_minutes)
        if args.mode == "smoke" and spec.num_envs > 16:
            raise ValueError("Smoke checks permit at most 16 environments")
        study = json.loads((ROOT / "configs/study.json").read_text(encoding="utf8"))
        missing = validate_study(study)
        run_id = validate_run_id(args.run_id or "preview")
    except ValueError as exc:
        parser.error(str(exc))
    command = training_command(ROOT, args.sim_python, spec, run_id)
    if args.mode == "plan":
        print(json.dumps({**spec.summary(), "command": command, "environment": {"TORCHDYNAMO_DISABLE": "1"},
                          "unmet_study_gates": missing}, indent=2))
        return 0
    if not args.run_id:
        parser.error("--run-id is required when creating a run")
    if not args.sim_python.is_file():
        parser.error(f"Simulator launcher not found: {args.sim_python}")
    lab = ROOT / ".deps/IsaacLab"
    upstream_commit = git(lab, "rev-parse", "HEAD")
    upstream_dirty = git(lab, "status", "--porcelain", "--untracked-files=no")
    if upstream_commit != LAB_COMMIT or upstream_dirty:
        parser.error("Pinned upstream source must match the declared commit and have no tracked modifications")
    run_dir = ROOT / "artifacts/assembly" / run_id
    weights_dir = ROOT / "logs/rl_games/Forge" / run_id
    if run_dir.exists() or weights_dir.exists():
        parser.error("Run ID already exists in artifacts or training logs; choose a new ID")
    run_dir.mkdir(parents=True, exist_ok=False)
    if args.mode == "smoke":
        command = [str(args.sim_python), str(ROOT / "scripts/assembly_smoke.py"), "--headless", "--task", args.task,
                   "--report", str(run_dir / "smoke.json"), "--num_envs", str(spec.num_envs), "--steps", "16", "--seed", str(spec.seed)]
    started = time.monotonic()
    deadline = started + 60 * spec.max_minutes
    manifest = {
        "schema": 1, "run_id": run_id, "mode": args.mode, "status": "starting",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "spec": spec.summary() if args.mode == "train" else {"task": spec.task, "seed": spec.seed, "num_envs": spec.num_envs, "control_steps": 16},
        "source_commit_at_start": git(ROOT, "rev-parse", "HEAD"),
        "source_dirty_at_start": bool(git(ROOT, "status", "--porcelain")),
        "source_hashes": snapshot_source(run_dir / "source.zip"),
        "upstream_commit": upstream_commit, "upstream_dirty": False,
        "command": command, "environment_overrides": {"TORCHDYNAMO_DISABLE": "1", "PYTHONUNBUFFERED": "1"},
        "unmet_study_gates": missing,
        "scope": ["Upstream infrastructure check only.", "Upstream held-part gravity disabled; preset grasp and synthetic pose observations.",
                  "Snapshot preserves exact project files for this development run; no new-method evidence."]}
    write_json(run_dir / "manifest.json", manifest)
    env = os.environ.copy()
    env.update(manifest["environment_overrides"])
    try:
        code, timeout = run_bounded(command, run_dir / "process.log", deadline, env)
        checks = {}
        if args.mode == "smoke":
            report = run_dir / "smoke.json"
            checks["smoke_passed"] = report.exists() and json.loads(report.read_text(encoding="utf8")).get("status") == "passed"
        else:
            checkpoints = sorted(weights_dir.glob("nn/*.pth"))
            checks["checkpoint_saved"] = bool(checkpoints)
            checks["environment_config_saved"] = (weights_dir / "params/env.yaml").is_file()
            checks["agent_config_saved"] = (weights_dir / "params/agent.yaml").is_file()
            manifest["checkpoints"] = [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in checkpoints]
            if code == 0 and not timeout and checkpoints:
                verify_command = [str(args.sim_python), str(ROOT / "scripts/verify_checkpoint.py"), "--checkpoint", str(checkpoints[-1]),
                                  "--report", str(run_dir / "checkpoint_check.json"), "--expected-epoch", str(spec.epochs)]
                vcode, vtimeout = run_bounded(verify_command, run_dir / "checkpoint_check.log", deadline, env)
                timeout |= vtimeout
                verification = run_dir / "checkpoint_check.json"
                checks["checkpoint_loadable_and_epoch_matches"] = vcode == 0 and verification.exists() and json.loads(verification.read_text(encoding="utf8")).get("status") == "passed"
            else:
                checks["checkpoint_loadable_and_epoch_matches"] = False
        manifest.update(status=assess_completion(code, timeout, checks), process_exit_code=code, timed_out=timeout, artifact_checks=checks)
    except BaseException as exc:
        manifest.update(status="launcher_failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        manifest.update(finished_at_utc=datetime.now(UTC).isoformat(), elapsed_seconds=time.monotonic() - started)
        write_json(run_dir / "manifest.json", manifest)
        print(json.dumps({"status": manifest["status"], "manifest": str(run_dir / "manifest.json")}), flush=True)
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
