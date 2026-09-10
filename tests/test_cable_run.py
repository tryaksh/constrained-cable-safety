"""Cable launch contracts use fake workers and temporary assets, never a simulator."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from assembly_recovery import cable_run


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    for directory in ("scripts", "configs", "tests", "src/assembly_recovery"):
        (tmp_path / directory).mkdir(parents=True)
    for name in ("README.md", "ROADMAP.md", "AGENTS.md"):
        (tmp_path / name).write_text("fixture")
    config = tmp_path / "configs/cable.json"
    config.write_text('{"seed": 7}')
    worker = tmp_path / "scripts/fake_worker.py"
    worker.write_text(
        "import argparse,json\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser(); p.add_argument('--run-dir'); p.add_argument('--config'); a=p.parse_args()\n"
        "Path(a.run_dir,'result.json').write_text(json.dumps({'status':'completed','accounting':{'native_steps':12}}))\n"
    )
    monkeypatch.setattr(cable_run, "git", lambda root, *args: "fixture-commit" if args[0] == "rev-parse" else "")
    monkeypatch.setattr(cable_run, "external_provenance", lambda root: {"aic": {"commit": cable_run.AIC_COMMIT}})
    monkeypatch.setattr(
        cable_run, "native_environment", lambda python: {"packages": {"mujoco": cable_run.MUJOCO_VERSION}}
    )
    return {
        "root": tmp_path,
        "worker": worker,
        "config": config,
        "python": Path(sys.executable),
        "run_id": "fake-001",
        "max_minutes": 1,
    }


def test_snapshot_archives_exact_xml_and_untracked_test_bytes(tmp_path):
    sources = {"configs/cable.xml": b"<mujoco/>\n", "tests/test_new.py": b"x = 7\n"}
    for name, content in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    snapshot = tmp_path / "source.zip"
    hashes = cable_run.snapshot_source(tmp_path, snapshot)
    (tmp_path / "configs/cable.xml").write_text("changed later")
    with zipfile.ZipFile(snapshot) as archive:
        for name, content in sources.items():
            assert archive.read(name) == content
            assert hashes[name] == hashlib.sha256(content).hexdigest()


def test_fake_worker_completes_with_immutable_prelaunch_and_collision_rejection(workspace):
    manifest = cable_run.execute_run(**workspace)
    assert manifest["status"] == "completed"
    assert manifest["accounting"] == {"native_steps": 12}
    assert manifest["accounting_complete"]
    run_dir = Path(manifest["run_directory"])
    original = (run_dir / "prelaunch.json").read_bytes()
    assert json.loads(original)["status"] == "starting"
    assert hashlib.sha256(original).hexdigest() == manifest["prelaunch_sha256"]
    assert {"source.zip", "prelaunch.json", "result.json", "process.log"} <= {a["path"] for a in manifest["artifacts"]}
    with pytest.raises(FileExistsError):
        cable_run.execute_run(**workspace)
    assert (run_dir / "prelaunch.json").read_bytes() == original
    assert not (run_dir.parent / ".active-job.json").exists()


def test_timeout_preserves_partial_weights_without_calling_run_complete(workspace):
    workspace["worker"].write_text(
        "import argparse,time\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser(); p.add_argument('--run-dir'); p.add_argument('--config'); a=p.parse_args()\n"
        "Path(a.run_dir,'partial.pth').write_bytes(b'partial'); time.sleep(60)\n"
    )
    manifest = cable_run.execute_run(**{**workspace, "max_minutes": 0.02})
    assert manifest["status"] == "timed_out"
    assert not manifest["accounting_complete"]
    assert "partial.pth" in {a["path"] for a in manifest["artifacts"]}
    assert not (Path(manifest["run_directory"]).parent / ".active-job.json").exists()


def test_nonzero_process_exit_wins_over_completed_report(workspace):
    with workspace["worker"].open("a") as handle:
        handle.write("raise SystemExit(9)\n")
    manifest = cable_run.execute_run(**workspace)
    assert manifest["status"] == "process_failed"
    assert manifest["returncode"] == 9
    assert manifest["accounting"]["native_steps"] == 12
    assert not manifest["accounting_complete"]


@pytest.mark.parametrize(
    "report",
    [
        {"status": "completed", "accounting": {"native_steps": -1}},
        {"status": "completed", "accounting": {"native_steps": True}},
        {"status": "completed", "accounting": {"native_steps": 0.5}},
        {"status": "failed", "accounting": {"native_steps": 12}},
        {"status": "completed"},
    ],
)
def test_result_requires_explicit_completed_native_accounting(tmp_path, report):
    (tmp_path / "result.json").write_text(json.dumps(report))
    _, checks = cable_run.check_result(tmp_path)
    assert not all(value for value in checks.values() if type(value) is bool)


def test_nonfinite_result_is_rejected(tmp_path):
    (tmp_path / "result.json").write_text('{"status":"completed","accounting":{"native_steps":1},"load":NaN}')
    _, checks = cable_run.check_result(tmp_path)
    assert not checks["result_readable_and_valid"]


def test_checkpoint_hash_and_path_are_checked_without_inventing_reload(tmp_path):
    checkpoint = tmp_path / "weights.bin"
    checkpoint.write_bytes(b"model")
    report = {
        "status": "completed",
        "accounting": {"native_steps": 1},
        "checkpoints": [{"path": "weights.bin", "sha256": cable_run.sha256(checkpoint)}],
    }
    result = tmp_path / "result.json"
    result.write_text(json.dumps(report))
    assert cable_run.check_result(tmp_path)[1]["declared_checkpoints_valid"]
    checkpoint.write_bytes(b"corrupt")
    assert not cable_run.check_result(tmp_path)[1]["declared_checkpoints_valid"]
    report["checkpoints"][0] = {"path": "../outside.pth", "sha256": "anything"}
    result.write_text(json.dumps(report))
    assert not cable_run.check_result(tmp_path)[1]["declared_checkpoints_valid"]


def test_existing_job_lock_blocks_worker_and_keeps_owner_lock(workspace):
    parent = workspace["root"] / "artifacts/cable"
    parent.mkdir(parents=True)
    lock = parent / ".active-job.json"
    lock.write_text('{"launcher_pid":123}')
    manifest = cable_run.execute_run(**workspace)
    assert manifest["status"] == "launcher_failed"
    assert lock.read_text() == '{"launcher_pid":123}'
    assert not (Path(manifest["run_directory"]) / "process.log").exists()


def test_worker_cannot_override_provenance_paths(workspace):
    with pytest.raises(ValueError, match="cannot override"):
        cable_run.execute_run(**workspace, worker_args=["--config=other.json"])


@pytest.mark.parametrize("dirty,revision", [(" M model.xml", cable_run.AIC_COMMIT), ("", "wrong-revision")])
def test_external_repository_rejects_changed_or_unpinned_assets(tmp_path, monkeypatch, dirty, revision):
    (tmp_path / ".deps/aic").mkdir(parents=True)
    monkeypatch.setattr(cable_run, "git", lambda root, *args: revision if args[0] == "rev-parse" else dirty)
    with pytest.raises(ValueError, match="must be clean"):
        cable_run.external_provenance(tmp_path)


def test_external_dependency_hashes_cover_actual_asset_bytes(tmp_path, monkeypatch):
    model = tmp_path / ".deps/aic/aic_assets/models/plug/model.sdf"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"physical asset")

    def fake_git(root, *args):
        if args[0] == "rev-parse":
            return cable_run.AIC_COMMIT
        return "aic_assets/models/plug/model.sdf\0" if args[0] == "ls-files" else ""

    monkeypatch.setattr(cable_run, "git", fake_git)
    upstream = cable_run.external_provenance(tmp_path)
    assert upstream["aic"]["files_sha256"]["aic_assets/models/plug/model.sdf"] == cable_run.sha256(model)
    assert "ur_description" not in upstream


def test_configured_external_mesh_bytes_are_archived_before_worker_launch(workspace):
    mesh = workspace["root"] / "artifacts/assets/upperarm.stl"
    mesh.parent.mkdir(parents=True)
    content = b"mesh bytes present before launch"
    mesh.write_bytes(content)
    relative = mesh.relative_to(workspace["root"]).as_posix()
    workspace["config"].write_text(json.dumps({"external_files": [relative]}))
    manifest = cable_run.execute_run(**workspace)
    assert manifest["status"] == "completed"
    run_dir = Path(manifest["run_directory"])
    prelaunch = json.loads((run_dir / "prelaunch.json").read_text())
    digest = hashlib.sha256(content).hexdigest()
    assert prelaunch["external_files"] == [
        {"path": relative, "sha256": digest, "archive": "source.zip", "archive_path": relative}
    ]
    mesh.write_bytes(b"changed after run")
    with zipfile.ZipFile(run_dir / "source.zip") as archive:
        assert archive.read(relative) == content
    assert prelaunch["source_hashes"][relative] == digest


@pytest.mark.parametrize(
    "external_files",
    [
        ["artifacts/missing.stl"],
        ["../outside.stl"],
        ["C:/outside.stl"],
        ["/outside.stl"],
        ["C:relative.stl"],
        [123],
        "not-a-list",
    ],
)
def test_invalid_external_asset_configuration_blocks_worker(workspace, external_files):
    workspace["config"].write_text(json.dumps({"external_files": external_files}))
    manifest = cable_run.execute_run(**workspace)
    assert manifest["status"] == "launcher_failed"
    assert not (Path(manifest["run_directory"]) / "process.log").exists()


def test_worker_crash_keeps_separate_progress_lower_bounds_without_summing(workspace):
    workspace["worker"].write_text(
        "import argparse,json\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser(); p.add_argument('--run-dir'); p.add_argument('--config'); a=p.parse_args()\n"
        "r=Path(a.run_dir); (r/'case').mkdir()\n"
        "(r/'progress.json').write_text(json.dumps({'native_steps':10}))\n"
        "(r/'case'/'progress.json').write_text(json.dumps({'native_steps':8,'initialization_native_steps':3}))\n"
        "raise SystemExit(9)\n"
    )
    manifest = cable_run.execute_run(**workspace)
    assert manifest["status"] == "process_failed"
    assert manifest["accounting"] is None
    assert not manifest["accounting_complete"]
    records = {record["path"]: record for record in manifest["progress_artifacts"]}
    assert records["progress.json"]["worker_reported_native_steps_lower_bound"] == 10
    assert records["case/progress.json"]["worker_reported_native_steps_lower_bound"] == 8
    assert records["case/progress.json"]["contents"]["initialization_native_steps"] == 3
    assert "Not summed" in manifest["progress_aggregation"]
    assert {"progress.json", "case/progress.json"} <= {a["path"] for a in manifest["artifacts"]}


def test_truncated_progress_json_remains_hashed_without_a_counter(tmp_path):
    content = b'{"native_steps": '
    (tmp_path / "progress.json").write_bytes(content)
    (record,) = cable_run.progress_artifacts(tmp_path)
    assert not record["parsed"]
    assert record["sha256"] == hashlib.sha256(content).hexdigest()
    assert "worker_reported_native_steps_lower_bound" not in record


def test_windows_bom_config_keeps_exact_source_bytes(workspace):
    config = workspace["config"]
    content = b"\xef\xbb\xbf" + b'{"seed":7}'
    config.write_bytes(content)
    result = cable_run.execute_run(**workspace)
    assert result["status"] == "completed"
    run_dir = workspace["root"] / "artifacts/cable" / workspace["run_id"]
    with zipfile.ZipFile(run_dir / "source.zip") as archive:
        assert archive.read("configs/cable.json") == content
    assert result["config"]["sha256"] == hashlib.sha256(content).hexdigest()
