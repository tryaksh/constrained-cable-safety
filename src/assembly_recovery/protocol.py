"""CPU-only run validation and provenance helpers for bounded upstream checks."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

LAB_COMMIT = "37ddf626871758333d6ed89cf64ad702aef127d0"
TASKS = {"peg": "Isaac-Forge-PegInsert-Direct-v0", "gear": "Isaac-Forge-GearMesh-Direct-v0"}


@dataclass(frozen=True)
class RunSpec:
    task: str = "peg"
    seed: int = 170
    num_envs: int = 64
    epochs: int = 2
    max_minutes: int = 15

    def __post_init__(self):
        if self.task not in TASKS:
            raise ValueError("Only the declared peg and gear tasks are supported")
        if not 0 <= self.seed < 2**31:
            raise ValueError("Use an explicit nonnegative seed; random seed -1 is forbidden")
        if not 4 <= self.num_envs <= 128 or self.num_envs % 4:
            raise ValueError("Use 4..128 environments in multiples of four for the pinned PPO minibatch")
        if not 1 <= self.epochs <= 20:
            raise ValueError("This upstream infrastructure launcher permits 1..20 epochs; implement the gated study adapter before campaigns")
        if not 1 <= self.max_minutes <= 300:
            raise ValueError("A run deadline must be 1..300 minutes")

    @property
    def requested_transitions(self) -> int:
        return self.num_envs * 128 * self.epochs

    def summary(self) -> dict:
        return {**asdict(self), "task_id": TASKS[self.task], "requested_transitions": self.requested_transitions,
                "scope": "Upstream infrastructure check; no recovery study implementation or performance claim"}


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
        raise ValueError("Run IDs must be 1..64 letters, digits, underscores or hyphens, starting with a letter or digit")
    return run_id


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    """Replace a manifest atomically; an interrupted write must not truncate the prior state."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf8")
    temporary.replace(path)


def validate_study(study: dict) -> list[str]:
    """Validate basic split integrity and return the still-unmet scientific gates."""
    training = set(study["training"]["seeds"])
    development = set(study["splits"]["development_seeds"])
    test = set(study["splits"]["test_seeds"])
    if not training or not development or not test:
        raise ValueError("All seed splits must be nonempty")
    if training & development or training & test or development & test:
        raise ValueError("Training, development and test seeds overlap")
    budgets = study["training"]["transition_targets"]
    if not budgets or any(x <= 0 for x in budgets) or budgets != sorted(set(budgets)):
        raise ValueError("Training targets must be positive and strictly increasing")
    if not 0 < study["training"]["nominal_fraction"] < 1:
        raise ValueError("Nominal practice must remain a proper fraction of the training budget")
    return [name for name, passed in study["gates"].items() if passed is not True]


def training_command(root: Path, sim_python: Path, spec: RunSpec, run_id: str) -> list[str]:
    validate_run_id(run_id)
    return [str(sim_python), str(root / ".deps/IsaacLab/scripts/reinforcement_learning/rl_games/train.py"),
            "--task", TASKS[spec.task], "--headless", "--num_envs", str(spec.num_envs), "--seed", str(spec.seed),
            "--max_iterations", str(spec.epochs),
            f"agent.params.config.full_experiment_name={run_id}",
            f"agent.params.config.save_frequency={spec.epochs}", "agent.params.config.save_best_after=0"]


def assess_completion(returncode: int, timed_out: bool, artifact_checks: dict[str, bool]) -> str:
    if timed_out:
        return "timed_out"
    if returncode != 0:
        return "process_failed"
    if not artifact_checks or not all(artifact_checks.values()):
        return "artifact_check_failed"
    return "completed"
