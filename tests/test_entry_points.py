"""The two commands the README offers a stranger must actually work.

Both run on a plain Python environment with numpy and nothing else: no
simulator, no GPU, no network. If either stops working, someone arriving from a
link finds a dead end in the first screenful, so both are run here rather than
trusted.
"""

from __future__ import annotations

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
