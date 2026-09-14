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


def test_the_documents_agree_with_the_record_about_where_the_page_went():
    """README.md and ROADMAP.md said the generated page "is not published anywhere".

    The record they both link to says it was published as a private page and
    gives the URL, so a reader who followed the link found the document
    contradicted one click later. The documents now say what the record says.
    This keeps them from drifting apart again in either direction.
    """
    page = json.loads((ROOT / "artifacts/showcase/page.json").read_text(encoding="utf-8-sig"))
    published = bool(page.get("published", {}).get("url"))
    documents = {name: " ".join((ROOT / name).read_text(encoding="utf-8-sig").split())
                 for name in ("README.md", "ROADMAP.md", "AGENTS.md")}
    for name, text in documents.items():
        denies = "not published anywhere" in text or "not published, and not served" in text
        assert denies is not published, (
            f"{name} and artifacts/showcase/page.json disagree about whether the generated "
            f"page was ever published")
    if published:
        # ROADMAP.md owns what was built, so it is the one that has to say it.
        assert "private" in documents["ROADMAP.md"], (
            "ROADMAP.md does not say the page was published privately, which the record says")


def test_every_open_item_says_what_it_would_cost():
    """Deferred extensions retain concrete work and costs in the status table."""
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8-sig")
    section = roadmap.split("## Remaining limitations", 1)
    assert len(section) == 2, "ROADMAP.md must identify its deferred extensions"
    body = section[1].split("\n## ", 1)[0]
    rows = [line.removeprefix("| ").removesuffix(" |").split(" | ") for line in body.splitlines()
            if line.startswith("| ") and not line.startswith(("| ---", "| Open question"))]
    assert rows and all(len(row) == 2 and all(row) for row in rows)
    costs = dict(rows)
    required = {
        "Force-only sensing may merit a larger study": ("200 held-out contexts", "16,080-run"),
        "A supervisor could cap the fraction of headroom spent": ("new candidate set", "780 routes"),
        "Five-clip findings cover one rig": ("second geometry", "2,340 routes", "87 minutes"),
        "v3 remains inconclusive": ("new registered block",),
        "The workbench window is untested": ("--run --view", "display"),
        "v5/v6 lack standalone study figures": ("two figures", "committed evidence"),
        "One old figure has damaged text encoding": ("Re-render", "JSON record"),
    }
    assert required.keys() <= costs.keys(), "a deferred extension disappeared without an explanation"
    for label, terms in required.items():
        for term in terms:
            assert term in costs[label], f"{label} no longer explains {term}"
    assert "none are scheduled" in body


def test_every_committed_figure_is_pointed_at_by_something():
    """A figure nobody links to is a figure nobody will ever see.

    Twenty figures are committed under `evidence/`. Each one has to be reachable:
    either a maintained document shows it or links to it, or a record names it as
    something it produced. A file that is neither is either orphaned or was
    superseded and should say so.
    """
    text = "\n".join(path.read_text(encoding="utf-8-sig") for path in maintained_documents())
    text += "\n".join(path.read_text(encoding="utf-8-sig")
                      for path in sorted((ROOT / "evidence").glob("*.json")))
    figures = sorted(path for path in (ROOT / "evidence").iterdir()
                     if path.suffix in {".png", ".pdf", ".svg", ".jpg"})
    assert figures, "no figures are committed, which is not what this repository looks like"
    orphans = [path.name for path in figures if path.stem not in text]
    assert not orphans, (
        "these figures are in the repository and nothing points at them:\n  "
        + "\n  ".join(orphans))


def test_the_readme_scene_and_findings_link_to_their_evidence():
    """The overview uses one scene image and direct evidence links for the studies."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
    shown = set(re.findall(r"!\[[^\]]*\]\((evidence/[^)]+)\)", readme))
    assert "evidence/cable_cell_v6_clips_cad.png" in shown
    for target in shown:
        assert (ROOT / target).is_file(), target
        after = readme.split(f"]({target})", 1)[1][:600]
        evidence_links = re.findall(r"\]\((evidence/[^)]+\.json)\)", after)
        assert evidence_links, f"{target} is shown without its evidence record"
        assert all((ROOT / link).is_file() for link in evidence_links)
    for record_name in ("cable_repair_boundary_v3", "cable_perception_v4",
                        "cable_sequence_v5", "cable_routing_v6"):
        assert f"](evidence/{record_name}.json)" in readme, record_name


def test_the_documents_report_the_campaign_counts_the_index_actually_has():
    """REPO_MAP owns counts; the README points to the index and distinguishes campaigns."""
    index = json.loads((ROOT / "evidence/INDEX.json").read_text(encoding="utf-8-sig"))
    counts = index["count_by_campaign"]
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8-sig").split())
    repo_map = " ".join((ROOT / "docs/REPO_MAP.md").read_text(encoding="utf-8-sig").split())
    assert "](evidence/INDEX.json)" in readme
    assert "cable and peg campaigns" in readme
    assert "scope before quoting" in readme
    for campaign, number in counts.items():
        assert f"{number} `{campaign}`" in repo_map, (
            f"docs/REPO_MAP.md no longer associates {campaign} with {number} records")
    assert index["count"] == sum(counts.values())
    assert f"{index['count']} records" in repo_map
