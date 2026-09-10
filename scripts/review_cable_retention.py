"""Verify and plot the completed isolated SC retention study without simulation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN_IDS = ("cable-retention-v1-r01", "cable-retention-v1-r02", "cable-retention-v2-r01")
CASE_IDS = ("zero_net_extraction", "half_newton_net_extraction", "two_newton_net_extraction")
AIC_COMMIT = "e9145480c945f2afc3741f355233f44082cc3b06"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha256(path):
    return digest(Path(path).read_bytes())


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Checks:
    def __init__(self):
        self.count = 0

    def require(self, condition, message):
        self.count += 1
        if not condition:
            raise ValueError(message)


def safe_path(directory, relative):
    path = (directory/relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError(f"Recorded artifact escapes run directory: {relative}")
    return path


def verify_provenance(root, run_id, checks):
    directory = root/"artifacts/cable"/run_id
    manifest = read_json(directory/"manifest.json")
    checks.require(manifest["run_id"] == run_id, "Manifest run identifier mismatch")
    if run_id == RUN_IDS[0]:
        checks.require(manifest["status"] == "launcher_failed", "BOM failure status changed")
        checks.require("JSONDecodeError" in manifest["error"] and "BOM" in manifest["error"], "BOM failure cause changed")
        checks.require({p.name for p in directory.iterdir()} == {"manifest.json"}, "Unexpected worker artifacts for prelaunch failure")
        checks.require(not manifest["artifacts"] and not manifest["progress_artifacts"], "Prelaunch failure has work artifacts")
        return {"run_id": run_id, "status": "failed_before_worker_launch", "native_steps": 0,
                "launcher_wall_s": manifest["elapsed_seconds"], "manifest_sha256": sha256(directory/"manifest.json"),
                "source_provenance": None, "prelaunch_present": False, "source_archive_present": False,
                "basis": "Saved launcher reports config JSON BOM failure before worker launch; directory contains only its manifest. No source hash or source commit is assigned retrospectively."}, None, None
    checks.require(manifest["status"] == "completed" and manifest["returncode"] == 0 and not manifest["timed_out"], "Unsuccessful worker execution")
    checks.require(manifest["accounting_complete"], "Incomplete launcher accounting")
    prelaunch = read_json(directory/"prelaunch.json")
    checks.require(sha256(directory/"prelaunch.json") == manifest["prelaunch_sha256"], "Prelaunch bytes differ")
    for key, value in prelaunch.items():
        if key != "status":
            checks.require(manifest.get(key) == value, f"Manifest changed prelaunch field {key}")
    archive_path = safe_path(directory, prelaunch["source_archive"]["path"])
    checks.require(sha256(archive_path) == prelaunch["source_archive"]["sha256"], "Source archive hash differs")
    with zipfile.ZipFile(archive_path) as archive:
        checks.require(set(archive.namelist()) == set(prelaunch["source_hashes"]), "Archived source inventory differs")
        for name, expected in prelaunch["source_hashes"].items():
            checks.require(digest(archive.read(name)) == expected, f"Archived source differs: {name}")
        config_path = prelaunch["config"]["path"]
        config_bytes = archive.read(config_path)
        checks.require(digest(config_bytes) == prelaunch["config"]["sha256"], "Archived config hash differs")
        config = json.loads(config_bytes)
    upstream = prelaunch["upstream"]["aic"]
    checks.require(upstream["commit"] == AIC_COMMIT and not upstream["dirty"], "Unexpected upstream source provenance")
    upstream_path = root/".deps/aic"
    actual_commit = subprocess.check_output(["git", "-C", str(upstream_path), "rev-parse", "HEAD"], text=True).strip()
    checks.require(actual_commit == AIC_COMMIT, "Installed AIC commit changed")
    for name, expected in upstream["files_sha256"].items():
        checks.require(sha256(safe_path(upstream_path, name)) == expected, f"Pinned upstream bytes differ: {name}")
    artifact_names = []
    for artifact in manifest["artifacts"]:
        path = safe_path(directory, artifact["path"])
        artifact_names.append(artifact["path"])
        checks.require(path.stat().st_size == artifact["bytes"], f"Artifact length differs: {path.name}")
        checks.require(sha256(path) == artifact["sha256"], f"Artifact bytes differ: {path.name}")
    actual_names = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() and p.name != "manifest.json"}
    checks.require(actual_names == set(artifact_names), "Artifact inventory is incomplete or has unrecorded additions")
    selected = ["scripts/probe_cable_retention.py", "src/assembly_recovery/cable_assets.py", config_path]
    report = {"run_id": run_id, "status": "completed", "manifest_sha256": sha256(directory/"manifest.json"),
              "prelaunch_sha256": manifest["prelaunch_sha256"], "source_archive_sha256": prelaunch["source_archive"]["sha256"],
              "source_commit_at_launch": prelaunch["source_commit_at_start"], "source_dirty_at_launch": prelaunch["source_dirty_at_start"],
              "source_entries_verified": len(prelaunch["source_hashes"]), "artifact_entries_verified": len(manifest["artifacts"]),
              "upstream_entries_verified": len(upstream["files_sha256"]),
              "selected_archived_source_sha256": {name: prelaunch["source_hashes"][name] for name in selected},
              "upstream_commit": upstream["commit"], "upstream_archive_scope": "Upstream files were hashed before launch, not included in source.zip; all recorded hashes rechecked against the pinned local checkout.",
              "environment": {"python": prelaunch["native_environment"]["python"],
                              "mujoco": prelaunch["native_environment"]["packages"]["mujoco"],
                              "numpy": prelaunch["native_environment"]["packages"]["numpy"]},
              "config_path": config_path, "command": prelaunch["command"], "launcher_wall_s": manifest["elapsed_seconds"]}
    return report, config, manifest


def physical_scene_signature(path):
    tree = ET.parse(path).getroot()
    option = tree.find("option")
    option.attrib.pop("timestep")
    return [ET.tostring(tree.find(name), encoding="unicode") for name in
            ["compiler", "option", "default", "worldbody", "actuator", "sensor"]]


def longest_true(values):
    longest = current = 0
    for value in values:
        current = current+1 if value else 0
        longest = max(longest, current)
    return longest


def verify_case(directory, result, config, checks):
    case_id = result["case"]["id"]
    saved = read_json(directory/"result.json")
    checks.require(saved == result, f"Root/per-case result mismatch: {case_id}")
    with np.load(directory/"samples.npz", allow_pickle=False) as data:
        rows, columns = data["samples"].copy(), data["columns"].tolist()
    index = {name: i for i, name in enumerate(columns)}
    def field(name):
        return rows[:, index[name]]
    checks.require(np.isfinite(rows).all(), "Nonfinite retention stream")
    checks.require(len(rows) == result["native_steps"], "Native sample count differs from explicit step count")
    dt = config["dt"]
    checks.require(np.allclose(field("native_time_s"), np.arange(len(rows))*dt, rtol=0, atol=1e-8), "Native clock has gaps or duplicate steps")
    checks.require(np.allclose(field("forward_time_s")-field("native_time_s"), dt, rtol=0, atol=1e-12), "Native/forward force timestamps are not separated by one timestep")
    approach = field("phase_0_approach_1_load") == 0
    loading = field("phase_0_approach_1_load") == 1
    checks.require(np.all(approach | loading), "Unexpected trial phase")
    approach_count = int(approach.sum())
    load_count = int(loading.sum())
    checks.require(approach_count == result["approach_native_steps"] == round(config["approach_seconds"]/dt), "Incomplete approach phase")
    checks.require(load_count == result["load_native_steps"] and approach_count+load_count == result["native_steps"], "Disjoint phase accounting mismatch")
    checks.require(np.all(approach[:approach_count]) and np.all(loading[approach_count:]), "Phases interleaved")
    checks.require(load_count > 0 and result["retention_assessable"], "No assessable load phase")
    checks.require(np.allclose(field("measured_actuator_force_n"), field("motor_command_n"), rtol=0, atol=1e-12), "Actuator failed to apply its declared force")
    checks.require(np.max(np.abs(field("motor_command_n"))) <= config["motor_force_limit_n"], "Motor force limit exceeded")
    checks.require(np.allclose(field("motor_command_n")+field("gravity_axis_force_n"), field("declared_net_force_n"), rtol=0, atol=1e-12), "Gravity/net external force mismatch")
    checks.require(np.allclose(field("declared_net_force_n")[loading], result["case"]["net_extraction_load_n"], rtol=0, atol=1e-12), "Wrong extraction load or residual insertion/damping force")
    previous_velocity = np.r_[0.0, field("qvel_m_per_s")[:-1]]
    expected_approach_force = np.clip(-config["net_insertion_force_n"]-config["approach_velocity_damping_ns_per_m"]*previous_velocity,
                                      -config["net_insertion_force_n"], config["net_insertion_force_n"])
    checks.require(np.allclose(field("declared_net_force_n")[approach], expected_approach_force[approach], rtol=0, atol=1e-12), "Recorded force-driven approach differs from declared controller")
    mass = result["adaptation"]["plug_mass_kg"]
    balance = mass*field("native_qacc_m_per_s2")-field("declared_net_force_n")-field("native_contact_axial_on_plug_n")
    balance_max = float(np.abs(balance).max())
    checks.require(balance_max < 1e-8, "Native axial Newton balance failed")
    for kind in ["native", "forward"]:
        checks.require(np.all(field(f"{kind}_contact_sum_n") >= 0), "Negative contact norm")
        checks.require(np.all(field(f"{kind}_contact_resultant_n") <= field(f"{kind}_contact_sum_n")+1e-10), "Contact resultant exceeds sum of component norms")
        checks.require(np.all(np.abs(field(f"{kind}_contact_axial_on_plug_n")) <= field(f"{kind}_contact_resultant_n")+1e-10), "Axial force exceeds resultant norm")
    acceptance = config["acceptance"]
    seated = (field("tip_error_m") <= acceptance["seating_position_tolerance_m"]) & (field("tip_angle_rad") <= acceptance["seating_orientation_tolerance_rad"])
    approach_dwell = longest_true(seated[approach])*dt
    checks.require(approach_dwell >= acceptance["seating_dwell_s"] and seated[approach_count-1], "Seating dwell or seated load handoff failed")
    checks.require(result["seated_before_load"] and result["seating_dwell_reached"] and result["initial_contact_clear"], "Reported seating/initialization gates failed")
    checks.require(field("native_contact_sum_n")[0] == 0 and field("forward_contact_sum_n")[0] == 0, "Initial sample is not contact-free")
    checks.require(field("native_contact_sum_n")[approach].max() > acceptance["positive_contact_threshold_n"], "No native contact positive control")
    bad_load = np.flatnonzero(loading & ~seated)
    loss_time = float(field("forward_time_s")[bad_load[0]]-config["approach_seconds"]) if len(bad_load) else None
    checks.require(loss_time == result["first_loss_after_load_s"], "First seating-loss time differs from recorded samples")
    checks.require(bool(len(bad_load)) == result["lost_seating"], "Seating-loss flag differs")
    retained = not len(bad_load) and load_count == round(config["load_seconds"]/dt)
    checks.require(retained == result["retained_in_axial_fixture"], "Retention outcome differs from recomputed criterion")
    positive_load = result["case"]["net_extraction_load_n"] > 0
    zero_contact = bool(np.all(field("native_contact_sum_n")[loading] == 0) and np.all(field("forward_contact_sum_n")[loading] == 0))
    if positive_load:
        checks.require(zero_contact, "Positive-load extraction has nonzero contact")
        checks.require(not retained and result["early_extraction_stop"], "Expected loaded extraction failure absent")
        checks.require(field("extraction_since_load_start_m")[-1] >= acceptance["early_extraction_stop_m"], "Early stop occurred before prescribed displacement")
        checks.require(field("extraction_since_load_start_m")[-2] < acceptance["early_extraction_stop_m"], "Early extraction stop delayed")
    else:
        checks.require(retained, "Zero-net-load control did not remain in seating region")
    maximum_contact = max(field("native_contact_sum_n").max(), field("forward_contact_sum_n").max())
    checks.require(maximum_contact < acceptance["raw_contact_abort_n"] and not result["raw_contact_abort"], "Contact force abort occurred")
    checks.require(np.allclose(field("extraction_since_load_start_m")[loading], field("qpos_m")[loading]-field("qpos_m")[approach_count-1], rtol=0, atol=1e-11), "Extraction displacement inconsistent with actual prismatic coordinate")
    with np.load(directory/"terminal_state.npz", allow_pickle=False) as terminal:
        checks.require(np.isclose(terminal["time_s"], field("forward_time_s")[-1], rtol=0, atol=1e-12), "Terminal time missing")
        checks.require(np.isclose(terminal["qpos"][0], field("qpos_m")[-1], rtol=0, atol=1e-12), "Terminal position missing")
        checks.require(np.isclose(terminal["qvel"][0], field("qvel_m_per_s")[-1], rtol=0, atol=1e-12), "Terminal velocity missing")
        checks.require(np.isclose(terminal["ctrl"][0], field("motor_command_n")[-1], rtol=0, atol=1e-12), "Terminal control missing")
    scene = ET.parse(directory/"scene.xml").getroot()
    checks.require(float(scene.find("option").get("timestep")) == dt, "Scene timestep differs from registration")
    checks.require(len(scene.findall(".//joint")) == 1 and scene.find(".//joint").get("type") == "slide", "Fixture constraints changed")
    checks.require(not scene.findall(".//equality") and not scene.findall(".//freejoint"), "Unexpected attachment or free-body constraints")
    checks.require(abs(float(scene.find("worldbody/body[@name='plug']/inertial").get("mass"))-mass) < 1e-12, "Recorded mass differs from physical scene")
    for prefix in ["plug", "port"]:
        geoms = scene.findall(f"worldbody/body[@name='{prefix}']/geom")
        collision_count = sum(g.get("contype") != "0" or g.get("conaffinity") != "0" for g in geoms)
        checks.require(collision_count == 15, f"{prefix} collision count changed")
    return {"case_id": case_id, "net_extraction_load_n": result["case"]["net_extraction_load_n"], "dt_s": dt,
            "seating_dwell_verified_s": approach_dwell, "seated_before_load": True,
            "retained_within_axial_fixture": retained, "first_seating_loss_after_load_s": loss_time,
            "final_tip_error_m": float(field("tip_error_m")[-1]),
            "native_extraction_contact_peak_n": float(field("native_contact_sum_n")[loading].max()),
            "forward_extraction_contact_peak_n": float(field("forward_contact_sum_n")[loading].max()),
            "positive_load_extraction_contact_exactly_zero": zero_contact if positive_load else None,
            "native_approach_contact_peak_n": float(field("native_contact_sum_n")[approach].max()),
            "native_force_balance_max_residual_n": balance_max,
            "native_steps": len(rows), "approach_native_steps": approach_count, "load_native_steps": load_count,
            "gravity_axis_force_n": float(field("gravity_axis_force_n")[0]),
            "extraction_actuator_force_n": float(field("motor_command_n")[loading][0]),
            "samples_sha256": sha256(directory/"samples.npz"), "terminal_state_sha256": sha256(directory/"terminal_state.npz")}, rows, columns, physical_scene_signature(directory/"scene.xml")


def make_figure(output, arrays):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "savefig.facecolor": "white"})
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.3), gridspec_kw={"width_ratios": [1, 1.2, 1]})
    colors = {0.0: "#4c6b8a", .5: "#008a91", 2.0: "#cf6336"}
    for run_number, run_id in enumerate(RUN_IDS[1:]):
        style = "-" if run_number == 0 else "--"
        dt_label = "0.25 ms" if run_number == 0 else "0.125 ms"
        for case_id in CASE_IDS:
            rows, columns, summary = arrays[(run_id, case_id)]
            idx = {name: i for i, name in enumerate(columns)}
            load = summary["net_extraction_load_n"]
            phase = rows[:, idx["phase_0_approach_1_load"]]
            approach = phase == 0
            loading = phase == 1
            if load == 0:
                axes[0].plot(rows[approach, idx["native_time_s"]], rows[approach, idx["native_contact_sum_n"]],
                             style, color=colors[load], lw=1.8, label=dt_label)
                axes[2].plot(rows[loading, idx["forward_time_s"]]-2, rows[loading, idx["tip_error_m"]]*1000,
                             style, color=colors[load], lw=1.8, label=dt_label)
            else:
                axes[1].plot((rows[loading, idx["forward_time_s"]]-2)*1000, rows[loading, idx["tip_axial_error_m"]]*1000,
                             style, color=colors[load], lw=1.8, label=f"{load:g} N, {dt_label}")
    axes[0].set(title="Force-driven seating", xlabel="Approach time (s)", ylabel="Native contact force (N)", xlim=(0, 2), ylim=(0, 2.25))
    axes[0].legend(frameon=False, loc="upper right", fontsize=9)
    axes[0].text(.12, 1.5, "All six trials seated\nwith at least 0.5 s dwell", fontsize=10)
    axes[1].axhline(1, color="#5b6570", lw=1, ls=":")
    axes[1].text(16, 1.16, "Seating limit", color="#5b6570", fontsize=9)
    axes[1].set(title="Positive pull releases the plug", xlabel="Time after load begins (ms)", ylabel="Axial tip distance from seat (mm)", xlim=(0, 32), ylim=(0, 5.6))
    axes[1].legend(frameon=False, loc="upper left", fontsize=8)
    axes[2].axhline(1, color="#5b6570", lw=1, ls=":")
    axes[2].set(title="Zero net pull control", xlabel="Time after load begins (s)", ylabel="Tip distance from seat (mm)", xlim=(0, 2), ylim=(0, 1.12))
    axes[2].legend(frameon=False, loc="lower right", fontsize=9)
    axes[2].text(.6, .74, "Near-seat persistence\nis not latch retention", color="#4c6b8a", fontsize=9)
    for axis in axes:
        axis.grid(axis="y", color="#e6e9ed", linewidth=.6)
    fig.suptitle("Rigid SC assets provide no measured axial resistance under 0.5 N or 2 N pull", fontsize=13, fontweight="bold", y=1.01)
    fig.text(.5, .005, "Recorded simulation only · Axial fixture with fixed lateral position/orientation · Gravity compensated · No actual gripper release\nPositive-load extraction contact is exactly zero at every recorded native and refreshed sample at both timesteps.", ha="center", fontsize=9, color="#4c5560")
    fig.tight_layout(rect=(0, .13, 1, .97))
    png, pdf = output.with_suffix(".png"), output.with_suffix(".pdf")
    fig.savefig(png, dpi=180, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight", metadata={"CreationDate": None, "ModDate": None})
    plt.close(fig)
    return [{"path": p.as_posix(), "sha256": sha256(p)} for p in [png, pdf]]


def review(root, output):
    checks = Checks()
    provenance, scientific, arrays, config_list, signatures = [], [], {}, [], []
    totals = {"native_steps": 0, "approach_native_steps": 0, "load_native_steps": 0,
              "initialization_native_steps": 0, "launcher_wall_s": 0.0, "worker_wall_s": 0.0}
    for run_id in RUN_IDS:
        record, config, manifest = verify_provenance(root, run_id, checks)
        provenance.append(record)
        totals["launcher_wall_s"] += record["launcher_wall_s"]
        if manifest is None:
            continue
        config_list.append(config)
        directory = root/"artifacts/cable"/run_id
        result = read_json(directory/"result.json")
        checks.require(result["status"] == "completed", "Aggregate worker did not complete")
        checks.require(result["expected_case_ids"] == list(CASE_IDS), "Expected trial denominator differs")
        checks.require([case["case"]["id"] for case in result["cases"]] == list(CASE_IDS), "Missing, extra, or reordered trials")
        summaries, approaches = [], []
        for case in result["cases"]:
            summary, rows, columns, signature = verify_case(directory/case["case"]["id"], case, config, checks)
            summaries.append(summary)
            arrays[(run_id, case["case"]["id"])] = (rows, columns, summary)
            phase_index = columns.index("phase_0_approach_1_load")
            approaches.append(rows[rows[:, phase_index] == 0])
            signatures.append(signature)
        checks.require(all(np.array_equal(approaches[0], prefix) for prefix in approaches[1:]), "Load cases lack identical physical approach prefixes")
        counts = {key: sum(case[key] for case in summaries) for key in ["native_steps", "approach_native_steps", "load_native_steps"]}
        for key, value in counts.items():
            checks.require(result["accounting"][key] == value, f"Aggregate {key} differs from complete arrays")
            totals[key] += value
        checks.require(result["accounting"]["initialization_native_steps"] == 0, "Uncounted initialization steps")
        checks.require(manifest["accounting"] == result["accounting"], "Launcher/worker accounting differs")
        totals["worker_wall_s"] += result["elapsed_s"]
        record.update(counts, worker_wall_s=result["elapsed_s"])
        scientific.append({"run_id": run_id, "dt_s": config["dt"], "cases": summaries, "approach_prefixes_bitwise_identical": True})
    left, right = [{key: value for key, value in config.items() if key not in ["task_id", "dt", "refines"]} for config in config_list]
    checks.require(left == right, "Refinement changed a parameter besides timestep and metadata")
    checks.require(config_list[0]["dt"] == 2*config_list[1]["dt"], "Not a matched half-timestep refinement")
    checks.require(all(signature == signatures[0] for signature in signatures[1:]), "Physical scene differs across cases/resolutions beyond timestep")
    for name in ["scripts/probe_cable_retention.py", "src/assembly_recovery/cable_assets.py"]:
        checks.require(provenance[1]["selected_archived_source_sha256"][name] == provenance[2]["selected_archived_source_sha256"][name], "Worker/asset adapter changed across refinement")
    loss_deltas = {}
    for case_id in CASE_IDS:
        coarse, fine = [arrays[(run_id, case_id)][2] for run_id in RUN_IDS[1:]]
        checks.require(coarse["retained_within_axial_fixture"] == fine["retained_within_axial_fixture"], "Retention outcome changed under refinement")
        if coarse["net_extraction_load_n"] > 0:
            delta = fine["first_seating_loss_after_load_s"]-coarse["first_seating_loss_after_load_s"]
            loss_deltas[case_id] = delta
            checks.require(abs(delta) <= config_list[0]["dt"]+1e-10, "Loss time differs by more than one coarse sample")
    checks.require(totals["native_steps"] == 96516 and totals["approach_native_steps"] == 72000 and totals["load_native_steps"] == 24516, "Cost ledger differs from executed retention block")
    output.parent.mkdir(parents=True, exist_ok=True)
    figures = make_figure(output, arrays)
    for figure in figures:
        figure["path"] = Path(figure["path"]).relative_to(root).as_posix()
    evidence = {"schema": 1, "study": "isolated_sc_axial_retention", "verification_status": "passed",
        "verification_checks_passed": checks.count, "review_script": "scripts/review_cable_retention.py",
        "review_script_sha256": sha256(Path(__file__)), "review_uses_recorded_arrays_only": True,
        "new_simulator_steps": 0, "new_gpu_jobs": 0,
        "scope_and_limitations": ["Isolated one-axis force-actuated fixture with fixed lateral position and rotation; not a robot or recovery evaluation.",
            "The plug is initialized aligned2mm above the seated pose, then physically force-driven to contact/dwell. No attachment or constraint changes occur.",
            "There is no gripper in these trials and therefore no actual gripper-release event.",
            "Gravity is compensated explicitly. Zero net extraction load is a zero-net-force control, not evidence of a mechanical latch.",
            "Results apply to pinned public rigid SC collision geometry and registered solver/friction parameters, not hardware retention or all connector models.",
            "Matched timesteps support the observed missing axial resistance in this fixture; this is not general physics convergence or complete-job validation."],
        "summary": {"force_driven_seating_trials": 6, "seating_passed": 6, "zero_load_controls": 2,
            "zero_load_controls_within_seating_region_for_2s": 2, "positive_load_trials": 4, "positive_load_trials_lost_seating": 4,
            "positive_load_extraction_contact_exactly_zero_in_all_native_and_forward_samples": True,
            "gravity_axis_force_n": scientific[0]["cases"][0]["gravity_axis_force_n"],
            "source_plug_mass_kg": .041, "net_extraction_loads_n": [0, .5, 2], "seating_tolerance_m": .001,
            "maximum_native_force_balance_residual_n": max(c["native_force_balance_max_residual_n"] for run in scientific for c in run["cases"]),
            "loss_time_refinement_deltas_s": loss_deltas},
        "decision": {"retention_gate_passed": False, "action": "revise_and_validate_missing_retention_model",
            "reason": "After verified seating, both positive extraction loads experience exactly zero opposing contact and promptly leave the seating region at both resolutions.",
            "complete_connection_claim_earned": False, "candidate_training_gate_earned": False,
            "clip_or_snag_recovery_comparison_gate_earned": False,
            "next_action": "Introduce an evidence-backed connector-retention model or revise the task claim, then independently validate seating and axial retention before complete-job cable recovery comparisons."},
        "runs": provenance, "scientific_results": scientific, "costs": totals, "figures": figures}
    output.write_text(json.dumps(evidence, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("evidence/cable_retention_v1.json"))
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.root/args.output
    result = review(args.root.resolve(), output.resolve())
    print(json.dumps({"verification": result["verification_status"], "checks": result["verification_checks_passed"],
                      "retention_gate_passed": result["decision"]["retention_gate_passed"], "native_steps": result["costs"]["native_steps"],
                      "evidence": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
