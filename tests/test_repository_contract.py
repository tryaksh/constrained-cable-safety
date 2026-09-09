import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_three_documents_link_to_real_active_files():
    documents = ("README.md", "ROADMAP.md", "AGENTS.md")
    for name in documents:
        text = (ROOT / name).read_text(encoding="utf8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            assert (ROOT / target.split("#")[0]).is_file(), (name, target)


def test_legacy_archive_is_separate_from_new_evidence():
    archive = json.loads((ROOT / "maintenance/archive_index.json").read_text())
    assert archive["original_commit"] == "1b969f6db01aeac226667db4759b7603b3f663a0"
    assert len(archive["retired_files"]) == 629
    for name in ("smoke.json", "training_pilot.json"):
        evidence = json.loads((ROOT / "evidence" / name).read_text())
        assert evidence["scope"]
        assert evidence["research_result"] is False


def test_cpu_imports_resolve_to_this_source_tree():
    from assembly_recovery import evaluation, study_ppo, tensor_jobs

    for module in (evaluation, study_ppo, tensor_jobs):
        assert Path(module.__file__).resolve().is_relative_to(ROOT / "src")
