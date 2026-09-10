"""Audit four frozen native UR5e cable blocks and plot recorded diagnostics only.

Run with .deps/cable-venv/Scripts/python.exe scripts/review_cable_robot.py.
No simulator package, dynamics, rendering, or worker source is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN_IDS = ("cable-robot-v1-r01", "cable-robot-v1-r02", "cable-robot-v2-r01", "cable-robot-v3-r01")
LOADS = ("plug_port_contact_n", "port_detector_contact_n", "other_contact_n", "raw_wrist_load_n", "raw_plug_load_n")
AIC_COMMIT = "e9145480c945f2afc3741f355233f44082cc3b06"


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read(path):
    def reject(value):
        raise ValueError(f"Nonfinite JSON value {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=reject)


def close(a, b):
    return bool(np.allclose(a, b, rtol=1e-10, atol=1e-9))


class Audit:
    def __init__(self):
        self.count = 0
        self.failures = []

    def check(self, name, condition):
        self.count += 1
        if not condition:
            self.failures.append(name)

    def summary(self):
        return {"status": "passed" if not self.failures else "failed", "checks": self.count,
                "failed_checks": self.failures}


def verify_provenance(run, audit, external_cache):
    manifest = read(run / "manifest.json")
    prelaunch = read(run / "prelaunch.json")
    audit.check("run_completed_without_timeout", manifest["status"] == "completed" and not manifest["timed_out"])
    audit.check("prelaunch_hash", digest(run / "prelaunch.json") == manifest["prelaunch_sha256"])
    audit.check("prelaunch_fields_preserved", all(manifest.get(k) == v for k, v in prelaunch.items() if k != "status"))
    audit.check("source_archive_hash", digest(run / "source.zip") == prelaunch["source_archive"]["sha256"])
    with zipfile.ZipFile(run / "source.zip") as archive:
        audit.check("source_archive_inventory", set(archive.namelist()) == set(prelaunch["source_hashes"]))
        for name, expected in prelaunch["source_hashes"].items():
            audit.check(f"snapshot:{name}", hashlib.sha256(archive.read(name)).hexdigest() == expected)
        config_path = prelaunch["config"]["path"]
        config_bytes = archive.read(config_path)
        audit.check("archived_config_hash", hashlib.sha256(config_bytes).hexdigest() == prelaunch["config"]["sha256"])
        config = json.loads(config_bytes)
        declared = {item["path"] for item in prelaunch["external_files"]}
        audit.check("all_config_external_files_recorded", declared == set(config.get("external_files", [])))
        for item in prelaunch["external_files"]:
            name = item["path"]
            audit.check(f"external_archive:{name}", hashlib.sha256(archive.read(item["archive_path"])).hexdigest() == item["sha256"])
            audit.check(f"external_current:{name}", (ROOT / name).is_file() and digest(ROOT / name) == item["sha256"])
    upstream_files = 0
    for name, upstream in prelaunch["upstream"].items():
        audit.check(f"upstream_clean_record:{name}", upstream["dirty"] is False)
        if name == "aic":
            audit.check("aic_pinned", upstream["commit"] == AIC_COMMIT)
        for path, expected in upstream["files_sha256"].items():
            source = Path(upstream["path"]) / path
            if source not in external_cache:
                external_cache[source] = digest(source) if source.is_file() else None
            audit.check(f"upstream_bytes:{name}/{path}", external_cache[source] == expected)
            upstream_files += 1
    audit.check("native_runtime_pin", prelaunch["native_environment"]["packages"]["mujoco"] == "3.3.7")
    for artifact in manifest["artifacts"]:
        path = (run / artifact["path"]).resolve()
        valid = path.is_relative_to(run.resolve()) and path.is_file()
        audit.check(f"artifact:{artifact['path']}", valid and path.stat().st_size == artifact["bytes"] and digest(path) == artifact["sha256"])
    return manifest, config, {"manifest_sha256": digest(run / "manifest.json"),
        "prelaunch_sha256": manifest["prelaunch_sha256"], "source_archive_sha256": prelaunch["source_archive"]["sha256"],
        "source_commit_at_start": prelaunch["source_commit_at_start"], "source_dirty_at_start": prelaunch["source_dirty_at_start"],
        "archived_project_and_external_files": len(prelaunch["source_hashes"]), "external_meshes_archived": len(prelaunch["external_files"]),
        "upstream_source_and_asset_hashes_checked": upstream_files, "run_artifacts_checked": len(manifest["artifacts"]),
        "configuration_path": config_path, "configuration_sha256": prelaunch["config"]["sha256"]}


def verify_case(directory, report, config):
    audit = Audit()
    audit.check("case_report_matches_parent", read(directory / "result.json") == report)
    dt, steps = report["case"]["dt"], report["native_steps"]
    init_expected = round(config["initialization_seconds"] / dt)
    initialization_complete = report["initialization_native_steps"] >= init_expected
    audit.check("poststep_forward_work_recorded", report["poststep_forward_calls"] == steps)
    trajectory = np.load(directory / "trajectory.npz", allow_pickle=False)
    samples, columns = trajectory["samples"], list(trajectory["columns"])
    audit.check("trajectory_finite", all(np.isfinite(trajectory[k]).all() for k in trajectory.files if k != "columns"))
    audit.check("trajectory_monotone", bool(np.all(np.diff(samples[:, 0]) > 0)))
    audit.check("trajectory_before_terminal", float(samples[-1, 0]) <= steps * dt + 1e-8)
    stream_path = directory / "native_force_stream.npz"
    force_review = {"full_stream_available": stream_path.is_file()}
    if stream_path.is_file():
        stream = np.load(stream_path, allow_pickle=False)
        force, force_columns = stream["samples"], list(stream["columns"])
        expected_columns = ["native_time_s", "forward_time_s", *("native_" + k for k in LOADS), *("forward_" + k for k in LOADS)]
        audit.check("force_stream_columns", force_columns == expected_columns)
        audit.check("force_stream_steps", force.shape == (steps, 12))
        audit.check("force_stream_finite_nonnegative", bool(np.isfinite(force).all() and (force[:, 2:] >= 0).all()))
        audit.check("native_time_grid", close(force[:, 0], np.arange(steps) * dt))
        audit.check("forward_time_grid", close(force[:, 1], (np.arange(steps) + 1) * dt))
        native, forward = force[:, 2:7], force[:, 7:12]
        maximum = np.maximum(native, forward)
        for i, key in enumerate(LOADS):
            audit.check(f"native_peak:{key}", close(native[:, i].max(), report["native_solve_peak_loads"][key]))
            audit.check(f"forward_peak:{key}", close(forward[:, i].max(), report["postforward_peak_loads"][key]))
            audit.check(f"combined_peak:{key}", close(maximum[:, i].max(), report["peak_loads"][key]))
        contact = maximum[:, 0] > .05
        audit.check("contact_step_count", int(contact.sum()) == report["contact_native_steps"])
        observed_first = float(force[np.flatnonzero(contact)[0], 1]) if contact.any() else None
        audit.check("first_contact_time", observed_first == report["first_contact_s"])
        initialization = force[:, 0] < config["initialization_seconds"]
        insertion = (force[:, 0] >= config["initialization_seconds"]) & (force[:, 0] < config["initialization_seconds"] + config["attempt_seconds"])
        for phase, mask in (("initialization", initialization), ("insertion", insertion), ("retraction", ~(initialization | insertion))):
            actual = maximum[mask].max(0) if mask.any() else np.zeros(5)
            audit.check(f"phase_peak:{phase}", close(actual, [report["phase_peak_loads"][phase][key] for key in LOADS]))
        audit.check("initialization_step_count", int(initialization.sum()) == report["initialization_native_steps"])
        limits = config["acceptance"]
        violations = (maximum[:, 3] > limits["raw_wrist_load_abort_n"]) | (maximum[:, 4] > limits["raw_plug_load_abort_n"])
        audit.check("abort_matches_stream", bool(violations.any()) == report["raw_load_abort"])
        audit.check("stop_at_first_raw_violation", not violations.any() or np.flatnonzero(violations)[0] == steps - 1)
        stride = max(1, round(.01 / dt))
        saved = np.arange(0, steps, stride)
        audit.check("trajectory_force_times", close(samples[:, 0], force[saved, 1]))
        audit.check("trajectory_force_values", close(samples[:, 9:], force[saved, 2:]))
        with np.load(directory / "terminal_state.npz", allow_pickle=False) as terminal:
            audit.check("terminal_time", close(float(terminal["time_s"]), steps * dt))
            audit.check("terminal_state_finite", all(np.isfinite(terminal[k]).all() for k in terminal.files))
            sensor_names = [s.get("name") for s in ET.parse(directory / "scene.xml").getroot().find("sensor")]
            audit.check("sensor_channel_layout", sensor_names == ["AtiForceTorqueSensor_force", "AtiForceTorqueSensor_torque", "plug_load_force", "plug_load_torque"])
            for label, array, stored in (("native", terminal["native_sensors"], native), ("forward", terminal["postforward_sensors"], forward)):
                audit.check(f"terminal_{label}_wrist_force", close(np.linalg.norm(array[:3]), stored[-1, 3]))
                audit.check(f"terminal_{label}_plug_force", close(np.linalg.norm(array[6:9]), stored[-1, 4]))
        force_review.update(native_steps_independently_checked=steps, contact_steps_recomputed=int(contact.sum()),
                            raw_violation_steps=int(violations.sum()), first_contact_s=observed_first,
                            maximum_native_forward_load_difference_n={key: float(np.abs(native[:, i] - forward[:, i]).max()) for i, key in enumerate(LOADS)})
    else:
        for key in LOADS:
            available = [samples[:, columns.index(prefix + key)] for prefix in ("native_", "forward_", "") if prefix + key in columns]
            audit.check(f"sparse_sample_peak_within_report:{key}", max(float(a.max()) for a in available) <= report["peak_loads"][key] + 1e-9)
        force_review.update(native_steps_independently_checked=0,
                            limitation="Only sparse 10 ms trajectories; unsaved native maxima, terminal forces and contact counts cannot be independently reconstructed.")
    if "initial_tracking_samples" in report:
        expected_samples = int(sum(i * dt > config["initialization_seconds"] - .5 for i in range(report["initialization_native_steps"])))
        audit.check("tracking_window_sample_count", report["initial_tracking_samples"] == expected_samples)
        audit.check("initialization_complete_flag", report["initialization_completed"] == initialization_complete)
        justified = initialization_complete and expected_samples > 0 and report["initial_tracking_error_m"] <= config["acceptance"]["tracking_tolerance_m"]
        audit.check("tracking_gate_has_observations", report["acceptance_checks"]["initial_tracking"] == justified)
    summary_keys = ("controller", "attempt_outcome", "native_steps", "initialization_native_steps", "poststep_forward_calls",
                    "initial_tracking_error_m", "seating_dwell_reached", "raw_load_abort", "first_contact_s", "seating_time_s",
                    "minimum_tip_error_m", "final_seating_error_m", "peak_loads", "cable_max_displacement_m", "joint_torque_saturation_steps")
    result = {"case_id": report["case"]["id"], "dt_s": dt, "with_cable": report["case"]["with_cable"],
              **{key: report[key] for key in summary_keys}, "initialization_completed_derived": initialization_complete,
              "recorded_acceptance_checks": report["acceptance_checks"], "force_review": force_review, "verification": audit.summary()}
    result["held_seating_and_retraction_check"] = bool(initialization_complete and all(report["acceptance_checks"].values()))
    if not initialization_complete and report["acceptance_checks"]["initial_tracking"]:
        result["interpretation_correction"] = {"superseded": "Recorded initial_tracking=True", "corrected": False,
            "reason": "Aborted before the last-half-second initialization tracking window; initialized zero is not a tracking measurement."}
    return result


def canonical_scene(path):
    root = ET.parse(path).getroot()
    root.find("option").attrib.pop("timestep")
    for mesh in root.findall(".//asset/mesh"):
        if "file" in mesh.attrib:
            mesh.set("file", Path(mesh.get("file")).name)
    return ET.tostring(root)


def render_figure(output_stem):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    selections = (("cable-robot-v2-r01", "robot_cable_1ms", "1 ms: initialization abort"),
                  ("cable-robot-v3-r01", "robot_cable_05ms", "0.5 ms: held seat + retract"),
                  ("cable-robot-v3-r01", "robot_cable_025ms", "0.25 ms: held seat + retract"))
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "font.family": "DejaVu Sans", "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 3, figsize=(11.4, 6.1), gridspec_kw={"height_ratios": [1.3, 1]}, layout="constrained")
    colors = {"raw_wrist_load_n": "#714ca0", "raw_plug_load_n": "#167baa", "other_contact_n": "#db8431"}
    labels = {"raw_wrist_load_n": "Raw wrist", "raw_plug_load_n": "Raw plug", "other_contact_n": "Other contact"}
    for col, (run_id, case_id, title) in enumerate(selections):
        directory = ROOT / "artifacts/cable" / run_id / case_id
        report = read(directory / "result.json")
        stream = np.load(directory / "native_force_stream.npz")
        values, columns = stream["samples"], list(stream["columns"])
        for key, color in colors.items():
            y = np.maximum(values[:, columns.index("native_" + key)], values[:, columns.index("forward_" + key)])
            axes[0, col].plot(values[:, 1], y, color=color, lw=.85, label=labels[key], rasterized=True)
        axes[0, col].axhline(20, color="#6a6a6a", ls="--", lw=.8)
        axes[0, col].set(title=title, ylim=(0, 22.5), ylabel="Load (N)" if col == 0 else "")
        trajectory = np.load(directory / "trajectory.npz")
        x = trajectory["samples"]
        time = np.r_[x[:, 0], report["native_steps"] * report["case"]["dt"]]
        error = np.r_[x[:, 7], report["final_seating_error_m"]] * 1000
        axes[1, col].plot(time, error, color="#31566f", lw=1.4)
        axes[1, col].axhspan(0, 1, color="#8ebf9f", alpha=.3)
        axes[1, col].set(ylim=(0, 25), xlabel="Elapsed time (s)", ylabel="Tip-to-seat error (mm)" if col == 0 else "")
        for ax in axes[:, col]:
            ax.grid(alpha=.15)
            ax.set_xlim(0, report["native_steps"] * report["case"]["dt"])
        if report["raw_load_abort"]:
            axes[0, col].annotate("Plug abort: 20.06 N\nat 28 ms", xy=(.028, 20.063), xytext=(.008, 15),
                                  arrowprops={"arrowstyle": "->", "color": "#555"}, fontsize=8)
            axes[1, col].text(.0015, 4.5, "Initialization never completed", fontsize=8)
        else:
            for ax in axes[:, col]:
                ax.axvline(3, color="#999", ls=":", lw=.7)
                ax.axvline(12, color="#999", ls=":", lw=.7)
            axes[1, col].axvline(report["seating_time_s"], color="#4c8c65", ls="--", lw=.8)
            axes[1, col].text(8.9, 5, "Dwell reached", color="#39704f", fontsize=8)
            axes[0, col].text(.04, .94, f"Other-contact peak: {report['peak_loads']['other_contact_n']:.2f} N",
                              transform=axes[0, col].transAxes, va="top", fontsize=8)
    axes[0, 0].legend(loc="upper left", frameon=False, fontsize=8)
    fig.suptitle("Native UR5e cable insertion: feasibility with remaining timestep sensitivity\n"
                 "One layout • fixed preset grasp • straight-rest cable • recorded scripted diagnostics", fontsize=12)
    fig.supxlabel("Loads show the native/forward maximum at each right endpoint; dashed horizontal line is the raw abort limit.\n"
                  "Held seating and retraction do not establish released retention, official benchmark success, or learned recovery.", fontsize=8)
    for extension in ("png", "pdf"):
        fig.savefig(output_stem.with_suffix("." + extension), dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/cable_robot_validation_v1.json")
    args = parser.parse_args()
    evidence = {"schema": 1, "version": "cable_robot_validation_v1", "generated_at_utc": datetime.now(UTC).isoformat(),
                "scope": "Independent artifact and force-stream review of four frozen native UR5e scripted engineering blocks; not a learned recovery comparison or official AIC evaluation.",
                "review_source_sha256": digest(__file__), "runs": []}
    external_cache = {}
    for run_id in RUN_IDS:
        run = ROOT / "artifacts/cable" / run_id
        audit = Audit()
        manifest, config, provenance = verify_provenance(run, audit, external_cache)
        result = read(run / "result.json")
        cases = [verify_case(run / case["case"]["id"], case, config) for case in result["cases"]]
        audit.check("requested_case_ids_match", [c["case_id"] for c in cases] == result["expected_case_ids"])
        audit.check("run_native_steps_sum", sum(c["native_steps"] for c in cases) == result["accounting"]["native_steps"])
        audit.check("run_initialization_steps_sum", sum(c["initialization_native_steps"] for c in cases) == result["accounting"]["initialization_native_steps"])
        audit.check("manifest_accounting_matches", manifest["accounting"] == result["accounting"] and manifest["accounting_complete"])
        evidence["runs"].append({"run_id": run_id, "manifest": (run / "manifest.json").relative_to(ROOT).as_posix(),
                                 "provenance": provenance, "verification": audit.summary(), "cases": cases,
                                 "accounting": result["accounting"], "launcher_wall_seconds": manifest["elapsed_seconds"]})
    pair_root = ROOT / "artifacts/cable/cable-robot-v3-r01"
    coarse, fine = (read(pair_root / name / "result.json") for name in ("robot_cable_05ms", "robot_cable_025ms"))
    pair_audit = Audit()
    pair_audit.check("scene_only_timestep_and_asset_locations_differ", canonical_scene(pair_root / "robot_cable_05ms/scene.xml") == canonical_scene(pair_root / "robot_cable_025ms/scene.xml"))
    repeated = ROOT / "artifacts/cable/cable-robot-v2-r01/robot_cable_05ms"
    for name in ("native_force_stream.npz", "trajectory.npz", "terminal_state.npz"):
        with np.load(repeated / name) as old, np.load(pair_root / "robot_cable_05ms" / name) as new:
            pair_audit.check(f"repeated_05ms_arrays_identical:{name}", old.files == new.files and all(np.array_equal(old[k], new[k]) for k in old.files))
    totals = {key: sum(r["accounting"][key] for r in evidence["runs"]) for key in ("native_steps", "initialization_native_steps")}
    totals["launcher_wall_seconds"] = sum(r["launcher_wall_seconds"] for r in evidence["runs"])
    pair_audit.check("block_budget", totals["native_steps"] == 177637 and totals["initialization_native_steps"] == 34637)
    pair_audit.check("block_launcher_wall", math.isclose(totals["launcher_wall_seconds"], 89.547, abs_tol=1e-6))
    totals.update(poststep_forward_calls=sum(c["poststep_forward_calls"] for r in evidence["runs"] for c in r["cases"]),
                  force_stream_verified_native_steps=sum(c["force_review"]["native_steps_independently_checked"] for r in evidence["runs"] for c in r["cases"]),
                  prior_zero_step_geometry_review={"native_steps": 0, "mj_forward_calls": 99, "render_calls": 0,
                      "scope": "Separate read-only reconstruction of saved v1-r02 poses; no exact terminal force replay."},
                  this_artifact_review={"native_steps": 0, "mj_forward_calls": 0, "simulator_render_calls": 0},
                  additional_build_compile_forward_work="Not fully instrumented; native steps and poststep forwards are separate measured counters.",
                  ordinary_learned_training_native_steps=0, recovery_focused_learned_training_native_steps=0,
                  scripted_recovery_native_steps=0, scripted_continuation_native_steps=0,
                  controller_cost_scope="All 177637 steps belong to scripted initialization, first insertion and diagnostic retraction. No recovery or failed-attempt continuation arm ran in these four blocks.")
    evidence["accounting"] = totals
    evidence["latest_pair"] = {"verification": pair_audit.summary(), "time_steps_s": [coarse["case"]["dt"], fine["case"]["dt"]],
        "held_seating_and_retraction": [bool(c["valid_seating_attempt"] and c["acceptance_checks"]["retracted"]) for c in (coarse, fine)],
        "seating_time_s": [c["seating_time_s"] for c in (coarse, fine)],
        "peak_other_contact_n": [c["peak_loads"]["other_contact_n"] for c in (coarse, fine)],
        "peak_plug_port_contact_n": [c["peak_loads"]["plug_port_contact_n"] for c in (coarse, fine)],
        "cable_max_displacement_m": [c["cable_max_displacement_m"] for c in (coarse, fine)],
        "other_contact_peak_ratio_05_over_025": coarse["peak_loads"]["other_contact_n"] / fine["peak_loads"]["other_contact_n"],
        "fine_other_contact_peak_pairs": fine.get("phase_other_contact_peak_pairs"),
        "interpretation": "Outcome agreement supports a runnable engineering baseline on this layout. Large cable/contact differences retain numerical sensitivity; two timesteps do not establish convergence."}
    evidence["corrections_preserved"] = [
        {"run_id": "cable-robot-v1-r01", "superseded_force_statistics": "Postforward-only maxima and abort checking are superseded for scientific interpretation by the repeated no-cable case in v1-r02, which retains native-solve and postforward values. Original artifacts and all 16000 steps remain counted.", "full_native_force_stream_available": False},
        {"run_id": "cable-robot-v1-r02", "superseded_initial_tracking_pass_for_cases": ["robot_cable_1ms", "robot_cable_05ms"],
         "reason": "Both aborted before the tracking window. Zero initialized error was not a measurement. v2/v3 require completed initialization and nonzero tracking samples."}]
    evidence["demonstrated_findings"] = [
        "Native six-joint UR5e finite-torque control seats and retracts the public rigid SC plug with a gravity-loaded elastic cable at 0.5 and 0.25 ms on one aligned layout.",
        "Straight horizontal cable initialization in v1 collapses into the gripper/connector region and aborts before insertion. An outboard hanging initial curve with unchanged straight material rest shape enables finer-step trials.",
        "The corrected 1 ms hanging-curve trial still aborts at 28 native steps. The 0.5/0.25 ms pair agrees on held seating/retraction but differs materially in cable contact and motion."]
    evidence["scope_and_limitations"] = [
        "SC collision geometry is rigid and has no latch model: pose/contact dwell under a held plug is not released mechanical retention or electrical/optical function.",
        "Fixed preset grasp precludes claims of learned pickup, drop reliability, or a complete autonomous cable assembly job.",
        "One aligned layout, no required clip or retained earlier connection, and no balanced misalignment-by-snag failure assay in these four blocks.",
        "No ordinary learned training, recovery-focused training, scripted recovery comparison or scripted continuation comparison ran in this native validation block.",
        "Earlier force streams and terminal states were not saved at native rate; their reported peaks retain the stated verification limitation.",
        "The prior 99-forward reconstruction identifies contact geometry only: missing terminal qvel/ctrl prevents exact causal reconstruction of the original force spikes.",
        "Wrist force contains tool/gripper weight and inertia, with roughly 10.24 N no-cable initial load; raw force and torque are separate channels. No hardware force certification or simulator equivalence claim.",
        "The 0.25 ms setting is the preferred engineering setting for subsequent bounded diagnostics, not a converged physical truth or permission for a full learned comparison."]
    evidence["decision"] = {"status": "continue_engineering_baseline_with_numerical_limitations", "preferred_dt_s": .00025,
        "full_comparison_gate_passed": False, "physics_convergence_established": False, "algorithmic_benefit_tested": False,
        "next_action": "At 0.25 ms, establish a reproducible competent first attempt and balanced misalignment/cable-fault diagnostics, preserving force limits and validating seating/retention scope before learned comparisons."}
    all_reviews = [r["verification"] for r in evidence["runs"]] + [c["verification"] for r in evidence["runs"] for c in r["cases"]] + [pair_audit.summary()]
    evidence["verification"] = {"status": "passed" if all(r["status"] == "passed" for r in all_reviews) else "failed",
                                "checks": sum(r["checks"] for r in all_reviews),
                                "failed_checks": [check for r in all_reviews for check in r["failed_checks"]]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if evidence["verification"]["status"] == "passed":
        render_figure(args.output.with_suffix(""))
        evidence["figures"] = [{"path": args.output.with_suffix("." + extension).relative_to(ROOT).as_posix(),
                                "sha256": digest(args.output.with_suffix("." + extension))} for extension in ("png", "pdf")]
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf8")
    print(json.dumps({"verification": evidence["verification"], "accounting": totals,
                      "evidence": str(args.output), "decision": evidence["decision"]}, indent=2))
    return 0 if evidence["verification"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
