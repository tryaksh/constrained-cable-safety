"""Simulator-independent provenance and bounded execution for cable diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from assembly_recovery.protocol import assess_completion, sha256, validate_run_id, write_json
from scripts.run_experiment import git, run_bounded

AIC_COMMIT = "e9145480c945f2afc3741f355233f44082cc3b06"
MUJOCO_VERSION = "3.3.7"


def snapshot_source(root: Path, output: Path, extra_paths=()) -> dict:
    """Archive and hash identical bytes, including newly written untracked source."""
    suffixes = {".py", ".ps1", ".json", ".xml", ".mjcf", ".yaml", ".yml", ".toml"}
    paths = {
        p
        for folder in ("src", "scripts", "configs", "tests")
        for p in (root / folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix.lower() in suffixes
    }
    paths.update(
        root / name
        for name in ("README.md", "ROADMAP.md", "AGENTS.md", "pyproject.toml", "environment-lock.example.json")
        if (root / name).is_file()
    )
    paths.update(Path(p).resolve() for p in extra_paths)
    hashes = {}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            name = path.resolve().relative_to(root.resolve()).as_posix()
            content = path.read_bytes()
            hashes[name] = hashlib.sha256(content).hexdigest()
            archive.writestr(name, content)
    return hashes


def configured_external_files(root: Path, config: Path) -> list[Path]:
    """Resolve explicitly listed assets; their bytes enter the prelaunch archive."""
    configuration = json.loads(config.read_text(encoding="utf-8-sig"), parse_constant=_invalid_constant)
    values = configuration.get("external_files", [])
    if not isinstance(values, list):
        raise ValueError("Config external_files must be a list of project-relative file paths")
    paths = set()
    for value in values:
        if (
            not isinstance(value, str)
            or not value.strip()
            or Path(value).is_absolute()
            or PureWindowsPath(value).drive
            or PureWindowsPath(value).root
        ):
            raise ValueError("Every external_files entry must be a project-relative file path")
        candidate = (root / value).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise ValueError(f"External asset leaves the project root: {value}")
        if not candidate.is_file():
            raise ValueError(f"External asset is missing: {value}")
        paths.add(candidate)
    return sorted(paths)


def external_provenance(root: Path) -> dict:
    """Record clean pinned assets without duplicating upstream mesh repositories."""
    result = {}
    repositories = (("aic", AIC_COMMIT, ("aic_assets/models", "aic_utils/aic_mujoco")), ("ur_description", None, ()))
    for name, expected, prefixes in repositories:
        repository = root / ".deps" / name
        if not repository.exists() and expected is None:
            continue
        commit = git(repository, "rev-parse", "HEAD")
        dirty = git(repository, "status", "--porcelain", "--untracked-files=all")
        if dirty or (expected is not None and commit != expected):
            raise ValueError(f"External repository {name} must be clean" + (f" at {expected}" if expected else ""))
        paths = git(repository, "ls-files", "-z", "--", *prefixes).split("\0")
        hashes = {p: sha256(repository / p) for p in paths if p}
        if not hashes:
            raise ValueError(f"External repository {name} has no recorded dependencies")
        result[name] = {
            "path": str(repository),
            "commit": commit,
            "dirty": False,
            "files_sha256": hashes,
            "hash_scope": list(prefixes) or ["all tracked files"],
        }
    return result


def native_environment(python: Path) -> dict:
    """Ask the actual worker interpreter; importing MuJoCo is unnecessary."""
    code = (
        "import importlib.metadata as m,json,platform,sys; "
        "print(json.dumps({'executable':sys.executable,'python':sys.version,'prefix':sys.prefix,"
        "'base_prefix':sys.base_prefix,'platform':platform.platform(),"
        "'packages':{d.metadata['Name'].lower():d.version for d in m.distributions()}}))"
    )
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    completed = subprocess.run(
        [str(python), "-c", code], capture_output=True, text=True, check=True, timeout=30, **options
    )
    result = json.loads(completed.stdout)
    result["launcher_executable_sha256"] = sha256(python)
    if result["packages"].get("mujoco") != MUJOCO_VERSION:
        raise ValueError(f"Native cable runtime requires mujoco=={MUJOCO_VERSION}")
    return result


def _invalid_constant(value):
    raise ValueError(f"Nonfinite JSON constant: {value}")


def check_result(run_dir: Path) -> tuple[dict, dict]:
    """Completion requires a valid report; checkpoint presence cannot establish it."""
    path = run_dir / "result.json"
    if not path.is_file():
        return {}, {"result_present": False}
    try:
        report = json.loads(path.read_text(encoding="utf8"), parse_constant=_invalid_constant)
        steps = report.get("accounting", {}).get("native_steps")
        checks = {
            "result_present": True,
            "worker_completed": report.get("status") == "completed",
            "native_steps_recorded": type(steps) is int and steps >= 0,
        }
        checkpoints = report.get("checkpoints", [])
        checks["declared_checkpoints_valid"] = isinstance(checkpoints, list)
        for item in checkpoints if isinstance(checkpoints, list) else []:
            checkpoint = (run_dir / item["path"]).resolve()
            valid = checkpoint.is_relative_to(run_dir.resolve()) and checkpoint.is_file()
            valid = valid and sha256(checkpoint) == item["sha256"]
            if "bytes" in item:
                valid = valid and checkpoint.stat().st_size == item["bytes"]
            checks["declared_checkpoints_valid"] &= valid
        return report, checks
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {}, {"result_present": True, "result_readable_and_valid": False, "error": str(exc)}


def artifact_inventory(run_dir: Path) -> list[dict]:
    return [
        {"path": p.relative_to(run_dir).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)}
        for p in sorted(run_dir.rglob("*"))
        if p.is_file() and p != run_dir / "manifest.json"
    ]


def progress_artifacts(run_dir: Path) -> list[dict]:
    """Preserve individual durable counters, without assuming their work is disjoint."""
    records = []
    for path in sorted(run_dir.rglob("progress.json")):
        if not path.is_file():
            continue
        record = {"path": path.relative_to(run_dir).as_posix()}
        try:
            content = path.read_bytes()
            record.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
            value = json.loads(content.decode("utf8"), parse_constant=_invalid_constant)
            record.update(parsed=True, contents=value)
            steps = value.get("native_steps") if isinstance(value, dict) else None
            record["worker_reported_native_steps_lower_bound"] = steps if type(steps) is int and steps >= 0 else None
        except (OSError, ValueError, UnicodeError) as exc:
            record.update(parsed=False, error=f"{type(exc).__name__}: {exc}")
        records.append(record)
    return records


def execute_run(
    *, root: Path, run_id: str, worker: Path, config: Path, python: Path, max_minutes: float, worker_args=()
) -> dict:
    """Reserve an immutable run ID and execute one owned, deadline-bounded worker."""
    validate_run_id(run_id)
    if not 0 < max_minutes <= 300:
        raise ValueError("A cable job deadline must be greater than zero and at most 300 minutes")
    root, worker, config, python = (p.resolve() for p in (root, worker, config, python))
    for path in (worker, config, python):
        if not path.is_file():
            raise ValueError(f"Required input does not exist: {path}")
    if any(arg.split("=", 1)[0] in {"--run-dir", "--config"} for arg in worker_args):
        raise ValueError("Worker arguments cannot override --run-dir or --config")
    run_dir = root / "artifacts/cable" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    command = [str(python), str(worker), "--run-dir", str(run_dir), "--config", str(config), *worker_args]
    started = time.monotonic()
    manifest = {
        "schema": 1,
        "version": "cable_run_v1",
        "run_id": run_id,
        "status": "starting",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "command": command,
        "max_minutes": max_minutes,
        "run_directory": str(run_dir),
        "research_result": False,
        "environment_overrides": {"PYTHONUNBUFFERED": "1"},
        "scope_and_limitations": [
            "Native cable diagnostic; separate from official benchmark scores.",
            "A completed process and hashed checkpoint do not establish learning or checkpoint reload.",
            "Partial work is retained; worker-reported native steps are a lower bound after interruption.",
        ],
    }
    lock = run_dir.parent / ".active-job.json"
    locked = False
    try:
        with lock.open("x", encoding="utf8") as handle:
            json.dump({"run_id": run_id, "launcher_pid": os.getpid()}, handle)
        locked = True
        external_files = configured_external_files(root, config)
        manifest.update(
            source_commit_at_start=git(root, "rev-parse", "HEAD"),
            source_dirty_at_start=bool(git(root, "status", "--porcelain")),
            source_hashes=snapshot_source(root, run_dir / "source.zip", (worker, config, *external_files)),
            upstream=external_provenance(root),
            native_environment=native_environment(python),
            config={"path": config.relative_to(root).as_posix(), "sha256": sha256(config)},
        )
        manifest["external_files"] = [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": manifest["source_hashes"][path.relative_to(root).as_posix()],
                "archive": "source.zip",
                "archive_path": path.relative_to(root).as_posix(),
            }
            for path in external_files
        ]
        manifest["source_archive"] = {"path": "source.zip", "sha256": sha256(run_dir / "source.zip")}
        prelaunch = run_dir / "prelaunch.json"
        with prelaunch.open("x", encoding="utf8") as handle:
            json.dump(manifest, handle, indent=2, allow_nan=False)
            handle.write("\n")
        manifest["prelaunch_sha256"] = sha256(prelaunch)
        write_json(run_dir / "manifest.json", manifest)
        code, timed_out = run_bounded(
            command,
            run_dir / "process.log",
            started + 60 * max_minutes,
            {**os.environ, **manifest["environment_overrides"]},
        )
        report, checks = check_result(run_dir)
        boolean_checks = {key: value for key, value in checks.items() if type(value) is bool}
        manifest.update(
            status=assess_completion(code, timed_out, boolean_checks),
            returncode=code,
            timed_out=timed_out,
            artifact_checks=checks,
            accounting=report.get("accounting"),
            accounting_complete=code == 0 and not timed_out and all(boolean_checks.values()),
        )
    except BaseException as exc:
        manifest.update(status="launcher_failed", error=f"{type(exc).__name__}: {exc}", accounting_complete=False)
        if not isinstance(exc, Exception):
            raise
    finally:
        if locked:
            lock.unlink()
        manifest.update(
            finished_at_utc=datetime.now(UTC).isoformat(),
            elapsed_seconds=time.monotonic() - started,
            artifacts=artifact_inventory(run_dir),
            progress_artifacts=progress_artifacts(run_dir),
            progress_aggregation="Not summed: artifact counters may overlap each other or result.json. No disjoint-work aggregation schema is registered.",
        )
        write_json(run_dir / "manifest.json", manifest)
    return manifest
