"""Prepare/check pinned native cable dependencies without changing the peg runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command(args, *, timeout=300):
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run(
        [str(a) for a in args], cwd=ROOT, capture_output=True, text=True, check=True, timeout=timeout, **kwargs
    ).stdout.strip()


def prepare(install=False):
    lock = json.loads((ROOT / "configs/cable_dependencies_v1.json").read_text())
    source = ROOT / lock["aic"]["path"]
    if not source.exists() and install:
        command(["git", "clone", "--no-checkout", lock["aic"]["url"], source])
        command(["git", "-C", source, "checkout", "--detach", lock["aic"]["commit"]])
    if not source.exists():
        raise FileNotFoundError(source)
    actual = command(["git", "-C", source, "rev-parse", "HEAD"])
    if actual != lock["aic"]["commit"] or command(["git", "-C", source, "status", "--porcelain"]):
        raise ValueError(
            "Existing AIC dependency is not clean at the pinned revision; preserve it and resolve explicitly"
        )
    meshdir = ROOT / lock["robot_meshes"]["directory"]
    if install:
        meshdir.mkdir(parents=True, exist_ok=True)
    checked = []
    for item in lock["robot_meshes"]["files"]:
        target = meshdir / item["name"]
        if not target.exists() and install:
            with urllib.request.urlopen(item["url"], timeout=60) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Downloaded mesh hash mismatch")
            with target.open("xb") as f:
                f.write(content)
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Missing or changed pinned mesh: {target}")
        checked.append(item["name"])
    env = ROOT / lock["environment"]
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if install:
        if not python.exists():
            command(["uv", "venv", env, "--python", lock["python"]])
        command(["uv", "pip", "install", "--python", python, *lock["packages"]])
    if not python.exists():
        raise FileNotFoundError(python)
    actual_packages = command(["uv", "pip", "freeze", "--python", python]).splitlines()
    missing = set(lock["packages"]) - set(actual_packages)
    if missing:
        raise ValueError(f"Runtime differs from pin: {sorted(missing)}")
    version = command([python, "-c", "import sys,mujoco;print(sys.version.split()[0],mujoco.__version__)"])
    if version.split()[0] != lock["python"]:
        raise ValueError(f"Python version differs from pin: {version}")
    return {
        "status": "verified",
        "aic_commit": actual,
        "robot_meshes_verified": checked,
        "runtime": version,
        "python": str(python),
        "all_registered_packages_match": not missing,
        "extra_packages": sorted(set(actual_packages) - set(lock["packages"])),
        "scope": "Native dependencies only; no simulator trajectories or official benchmark evaluation executed by setup",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.install), indent=2))
    except (ValueError, FileNotFoundError, subprocess.SubprocessError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
