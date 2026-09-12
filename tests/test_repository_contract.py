import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_three_documents_link_to_real_active_files():
    for name in ("README.md", "ROADMAP.md", "AGENTS.md"):
        text = (ROOT / name).read_text(encoding="utf8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            assert (ROOT / target.split("#")[0]).is_file(), (name, target)


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


def test_every_evidence_record_says_what_it_is():
    index = json.loads((ROOT / "evidence/INDEX.json").read_text(encoding="utf-8-sig"))
    assert index["records"], "the evidence index is empty"
    for listed in index["records"]:
        name = listed["file"]
        record = json.loads((ROOT / "evidence" / name).read_text(encoding="utf-8-sig"))
        if name in PRE_SCOPE_ERA:
            assert record.get("decision") or record.get("summary"), name
            continue
        assert any(record.get(key) for key in DECLARES_SCOPE), name


def test_registered_studies_carry_their_contract_hash():
    """A frozen contract that cannot be checked is not a pre-registration."""
    for name in REGISTERED:
        record = json.loads((ROOT / "evidence" / name).read_text(encoding="utf-8-sig"))
        assert record["scope"], name
        assert record["contract"]["content_sha256"], name


def test_this_tree_carries_only_the_cable_work():
    """The peg study and the training stack stayed in the repository this was cut from."""
    modules = {path.name for path in (ROOT / "src/assembly_recovery").glob("*.py")}
    for retired in ("study_ppo.py", "tensor_jobs.py", "peg_env.py", "refinement_env.py"):
        assert retired not in modules, retired
    assert "cable_safety_filter_v4.py" in modules


def test_the_shipped_filter_reads_its_thresholds_from_evidence():
    """The published number and the running check must not be able to drift apart."""
    source = (ROOT / "src/assembly_recovery/cable_safety_filter_v4.py").read_text(encoding="utf8")
    assert "from_evidence" in source
