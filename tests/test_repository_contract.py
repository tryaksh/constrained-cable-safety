import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def maintained_documents():
    """Every document a reader is expected to read, and that we therefore maintain.

    The three at the root plus everything in `docs/`, except `docs/handover/`,
    which is history: a handover describes the repository as it was on the day it
    was written and is deliberately not updated afterwards.
    """
    documents = [ROOT / name for name in ("README.md", "ROADMAP.md", "AGENTS.md")]
    documents += sorted(p for p in (ROOT / "docs").glob("*.md"))
    return documents


def local_links(path: Path):
    """Every link in one document that should resolve to a file in this repository."""
    text = path.read_text(encoding="utf-8-sig")
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        yield target, (path.parent / target.split("#")[0]).resolve()


def test_maintained_documents_link_to_real_files():
    for path in maintained_documents():
        for target, resolved in local_links(path):
            assert resolved.is_file() or resolved.is_dir(), (path.name, target)


def test_maintained_documents_link_only_to_files_a_clone_would_have():
    """Existing on this machine is not the same as being in the repository.

    The README linked to five records under `artifacts/showcase/` for weeks. They
    were on disk, so a check for existence passed, and they were git-ignored, so
    anyone who cloned got five dead links and the only copy of those records
    stayed on one workstation. The root cause was a `.gitignore` line reading
    `artifacts/` rather than `artifacts/*`: git cannot re-include anything inside
    an excluded directory, so every exception below it was silently dead.

    This asks git, not the filesystem.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout.split("\n")
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available, so tracked-ness cannot be checked here")

    known = {ROOT.joinpath(line).resolve() for line in tracked if line}
    directories = {parent for path in known for parent in path.parents}
    untracked = []
    for path in maintained_documents():
        for target, resolved in local_links(path):
            if resolved in known or resolved in directories:
                continue
            untracked.append(f"  {path.name} -> {target}")
    assert not untracked, (
        "these links point at files that are not in the repository, so they are dead "
        "in a fresh clone:\n" + "\n".join(untracked)
    )


#: The pre-registered studies. Every one of these must carry its own scope and
#: the hash of the contract it was frozen against. Exactly one surviving record
#: predates that discipline and says what it is in a decision instead; it is
#: named here rather than quietly exempted.
REGISTERED = ("cable_repair_boundary_v3.json", "cable_perception_v4.json",
              "cable_sequence_v5.json")
PRE_SCOPE_ERA = ("cable_cycle_decision_v1.json",)


#: The record itself is what must declare its limits, not the generated index.
#: Two spellings are in use: newer records carry `scope`, a few older ones a
#: `scope_and_limitations` list.
DECLARES_SCOPE = ("scope", "scope_and_limitations")

#: Three files under `evidence/` are not measurements and have nothing to scope.
#: They are named here rather than quietly exempted, and each must still say what
#: it is. If you are tempted to add a fourth, check first that the new file really
#: is not reporting a number.
NOT_A_MEASUREMENT = {
    # A session handover: what one working session passed to the next.
    "claude_handover_v1.json": ("handover", "next_action"),
    # A snapshot of the machine and package versions a run happened on.
    "environment.json": ("platform", "python"),
    # A pre-launch check that ran before any measurement did.
    "learned_physics_preflight_v1.json": ("status", "required_acceptance"),
}


def test_every_evidence_record_says_what_it_is():
    index = json.loads((ROOT / "evidence/INDEX.json").read_text(encoding="utf-8-sig"))
    assert index["records"], "the evidence index is empty"
    for listed in index["records"]:
        name = listed["file"]
        record = json.loads((ROOT / "evidence" / name).read_text(encoding="utf-8-sig"))
        if name in PRE_SCOPE_ERA:
            assert record.get("decision") or record.get("summary"), name
            continue
        if name in NOT_A_MEASUREMENT:
            for key in NOT_A_MEASUREMENT[name]:
                assert record.get(key), (name, key)
            continue
        assert any(record.get(key) for key in DECLARES_SCOPE), name


def test_registered_studies_carry_their_contract_hash():
    """A frozen contract that cannot be checked is not a pre-registration."""
    for name in REGISTERED:
        record = json.loads((ROOT / "evidence" / name).read_text(encoding="utf-8-sig"))
        assert record["scope"], name
        assert record["contract"]["content_sha256"], name


def test_the_running_code_is_only_the_cable_work():
    """The peg study's code stayed behind; only its records came here.

    The peg-insertion campaign was closed and its 66 evidence records now live in
    `evidence/` next to the cable ones, because it is recovery work and this is
    the recovery repository. Its reinforcement-learning training stack did not
    come with them: it is code for a campaign nobody is continuing, it needs a GPU
    and a simulator that is not installed here, and it is preserved whole under
    the tag `archive/assembly-recovery-training` in the repository it ran in. See
    docs/PEG_INSERTION.md and docs/REPO_MAP.md.
    """
    modules = {path.name for path in (ROOT / "src/assembly_recovery").glob("*.py")}
    for retired in ("study_ppo.py", "tensor_jobs.py", "peg_env.py", "refinement_env.py"):
        assert retired not in modules, retired
    assert "cable_safety_filter_v4.py" in modules


def test_the_peg_records_are_here_and_are_labelled_as_peg():
    """A peg number must never be mistakable for a cable number."""
    index = json.loads((ROOT / "evidence/INDEX.json").read_text(encoding="utf-8-sig"))
    campaigns = {listed["file"]: listed["campaign"] for listed in index["records"]}
    assert campaigns.get("research_cycle_decision_v1.json") == "peg"
    assert campaigns.get("cable_perception_v4.json") == "cable"
    assert set(campaigns.values()) <= {"cable", "peg", "shared"}
    assert sum(1 for value in campaigns.values() if value == "peg") > 50


def test_the_shipped_filter_reads_its_thresholds_from_evidence():
    """The published number and the running check must not be able to drift apart."""
    source = (ROOT / "src/assembly_recovery/cable_safety_filter_v4.py").read_text(encoding="utf8")
    assert "from_evidence" in source
