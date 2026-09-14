"""The two commands the README offers a stranger must actually work.

Both run on a plain Python environment with numpy and nothing else: no
simulator, no GPU, no network. If either stops working, someone arriving from a
link finds a dead end in the first screenful, so both are run here rather than
trusted.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *arguments],
        capture_output=True, text=True, cwd=ROOT, timeout=180,
    )


def test_the_findings_verifier_re_derives_every_verdict():
    """Exit zero means all four verdicts came back out of the records."""
    finished = run("verify_findings.py")
    assert finished.returncode == 0, finished.stdout + finished.stderr
    for study in ("v3", "v4", "v5", "v6"):
        assert f"  {study}  " in finished.stdout, f"{study} is missing from the table"
    assert "FAIL" not in finished.stdout
    assert finished.stdout.count("  ok   ") >= 12


def test_the_findings_verifier_names_the_record_behind_each_verdict():
    finished = run("verify_findings.py")
    for record in ("cable_repair_boundary_v3.json", "cable_perception_v4.json",
                   "cable_sequence_v5.json", "cable_routing_v6.json"):
        assert record in finished.stdout, f"the table does not name {record}"
        assert (ROOT / "evidence" / record).is_file()


def test_the_safety_check_runs_and_agrees_with_the_job_the_study_ran():
    """Exit zero means the headroom it computes equals the one the block recorded."""
    finished = run("try_the_safety_check.py")
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert "They agree." in finished.stdout
    for eyesight in ("perfect information", "small error", "large error"):
        assert eyesight in finished.stdout, f"the table is missing the {eyesight} row"
    for constraint in ("C1_clip", "C2_bend", "C3_anchor"):
        assert constraint in finished.stdout, f"{constraint} is not broken down"


def test_the_safety_check_stays_short_enough_to_read():
    """Its whole point is being small. A demonstration nobody reads is not one."""
    lines = [line for line in run("try_the_safety_check.py").stdout.splitlines() if line.strip()]
    assert 10 <= len(lines) <= 25, f"{len(lines)} lines of output is not a demonstration"


def test_the_committed_estimates_are_internally_consistent():
    """The stored distance has to be the distance between the two stored points."""
    demo = json.loads((ROOT / "artifacts/showcase/demo.json").read_text(encoding="utf-8-sig"))
    assert set(demo["levels"]) == {"E0", "E2", "E4"}
    for level, block in demo["levels"].items():
        decision = block["decision"]
        measured = math.dist(decision["boot_position_m"], decision["anchor_site_m"])
        assert abs(measured - decision["boot_to_anchor_m"]) < 1e-12, level
        assert abs(math.dist(decision["insertion_axis"], (0, 0, 0)) - 1.0) < 1e-9, level
        assert block["case"].endswith(f"_{level}_conservative_r0"), level
    assert len(demo["candidate_actions"]) == 12


def test_the_declared_error_grows_with_the_eyesight_level():
    """The margin the check takes is built from these three numbers and nothing else."""
    demo = json.loads((ROOT / "artifacts/showcase/demo.json").read_text(encoding="utf-8-sig"))
    reported = [demo["levels"][level]["declared_error"] for level in ("E0", "E2", "E4")]
    for field in ("socket_bias_m", "socket_jitter_m", "centreline_occluded_m"):
        values = [level[field] for level in reported]
        assert values == sorted(values) and values[0] == 0.0 and values[-1] > 0.0, field
