"""Verify frozen cable baseline artifacts and plot recorded force/seating results.

Run with .deps/cable-venv/Scripts/python.exe scripts/review_cable_baseline.py.
No MuJoCo import, simulation, model forward computation, or GPU rendering occurs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.review_cable_robot import Audit, canonical_scene, close, digest, read, verify_provenance  # noqa: E402

RUN_IDS = ("cable-baseline-v1-r01", "cable-baseline-v2-r01")
CONTROLLERS = ("scripted_force_guided_retry", "scripted_continuation")
LOADS = ("plug_port_contact_n", "port_detector_contact_n", "other_contact_n", "raw_wrist_load_n", "raw_plug_load_n")


def case_directory(run, case):
    return run / (case["case"]["id"] + "__" + case["controller"])


def verify_case(run, case, config):
    directory = case_directory(run, case)
    audit = Audit()
    audit.check("case_result_matches_parent", read(directory / "result.json") == case)
    dt, steps, init_steps = case["case"]["dt"], case["native_steps"], case["initialization_native_steps"]
    limits, job = config["job_limits"], case["job"]
    with np.load(directory / "trajectory.npz", allow_pickle=False) as arrays:
        native, samples = arrays["native_forces"], arrays["samples"]
        audit.check("native_force_key_order", list(arrays["native_force_keys"]) == list(LOADS))
        audit.check("native_force_count", native.shape == (steps, 11))
        audit.check("native_force_time_grid", close(native[:, 0], np.arange(1, steps + 1) * dt))
        audit.check("native_forces_finite_and_nonnegative", bool(np.isfinite(native).all() and (native[:, 1:] >= 0).all()))
        maximum = np.maximum(native[:, 1:6], native[:, 6:11])
        for i, key in enumerate(LOADS):
            audit.check(f"full_native_peak:{key}", close(maximum[:, i].max(), case["peak_loads_all_phases"][key]))
        audit.check("poststep_forward_work", case["poststep_forward_calls"] == steps)
        audit.check("job_step_accounting", job["samples"] + init_steps == steps)
        audit.check("job_elapsed_accounting", close(job["elapsed_s"], job["samples"] * dt))
        audit.check("job_deadline", job["elapsed_s"] <= limits["deadline_s"] + 1e-9)
        audit.check("complete_initialization", init_steps == round(config["scene"]["initialization_seconds"] / dt))
        audit.check("initialization_tracking_observed", case["tracking_samples"] == round(.5 / dt) and case["initial_tracking_error_m"] <= .002)
        audit.check("initialization_connector_contact_free", bool((maximum[:init_steps, 0] <= .001).all()))
        violations = (maximum[:, 3] > limits["wrist_force_n"]) | (maximum[:, 4] > limits["plug_force_n"])
        audit.check("no_unreported_raw_force_violation", not violations.any())
        audit.check("sparse_state_arrays_finite", all(np.isfinite(arrays[k]).all() for k in ("samples", "qpos", "qvel", "ctrl", "terminal_qpos", "terminal_qvel", "terminal_ctrl")))
        audit.check("saved_terminal_time", close(samples[-1, 0], job["elapsed_s"]))
        audit.check("saved_terminal_state", all(np.array_equal(arrays[k][-1], arrays["terminal_" + k]) for k in ("qpos", "qvel", "ctrl")))
        native_rows = np.rint(samples[:, 0] / dt).astype(int) - 1 + init_steps
        audit.check("sparse_forces_match_full_stream", close(samples[:, 9:], maximum[native_rows]))
        audit.check("sparse_samples_monotone", bool((np.diff(samples[:, 0]) > 0).all()))
        audit.check("no_retry_phases_in_executed_traces", case["retries_started"] == 0 and not any("retract" in p or "retry" in p for p in arrays["phases"]))
        contact = maximum[init_steps:, 0] > limits["contact_witness_n"]
        detector = maximum[init_steps:, 1] > .05
        witness_review = None
        if job["first_witness_s"] is not None:
            witness_index = round(job["first_witness_s"] / dt) - 1
            first_index = max(0, witness_index - round(limits["stall_window_s"] / dt))
            sustained = bool(contact[first_index:witness_index + 1].all())
            audit.check("witness_sustained_native_connector_contact", sustained)
            audit.check("witness_is_connector_stall", job["witness_type"] == "connector_contact_stall")
            audit.check("witness_precedes_terminal", job["first_witness_s"] < job["elapsed_s"])
            witness_review = {"reported_first_witness_s": job["first_witness_s"],
                              "connector_contact_sustained_at_native_rate": sustained,
                              "native_contact_samples_checked": witness_index - first_index + 1,
                              "pose_progress_replayed_at_native_rate": False,
                              "limitation": "The native worker evaluated commanded/actual progress; saved 10 ms poses cannot replay the exact native progress window."}
        if job["status"] == "completed":
            required = round(limits["dwell_s"] / dt)
            audit.check("reported_dwell_reached", job["dwell_s"] + 1e-10 >= limits["dwell_s"])
            audit.check("final_native_detector_dwell", bool(detector[-required:].all()))
            final_window = samples[samples[:, 0] > job["elapsed_s"] - limits["dwell_s"] + 1e-9]
            audit.check("all_saved_dwell_poses_seated", bool((final_window[:, 7] <= limits["position_tolerance_m"]).all() and (final_window[:, 8] <= limits["orientation_tolerance_rad"]).all()))
        else:
            audit.check("timeout_kept_in_denominator", job["failure_reason"] == "deadline" and close(job["elapsed_s"], limits["deadline_s"]))
            audit.check("failed_offsets_have_no_detector_contact", not detector.any())
        summary = {"case_id": case["case"]["id"], "controller": case["controller"], "task_case": case["case"],
                   "initialization_valid": case["initialization_valid"], "job": job, "retries_started": case["retries_started"],
                   "last_phase": case["last_phase"], "native_steps": steps, "initialization_native_steps": init_steps,
                   "poststep_forward_calls": case["poststep_forward_calls"], "peak_loads_all_phases": case["peak_loads_all_phases"],
                   "native_force_rows_checked": len(native), "native_connector_contact_steps_in_job": int(contact.sum()),
                   "native_detector_contact_steps_in_job": int(detector.sum()), "raw_force_violation_steps_all_phases": int(violations.sum()),
                   "witness_review": witness_review, "precontact_bias_world_n": case["precontact_bias_world_n"],
                   "final_seating_error_m": float(samples[-1, 7]), "worker_wall_seconds": case["resources"]["wall_seconds"],
                   "verification": audit.summary()}
    return summary


def controller_summary(cases, controller):
    selected = [c for c in cases if c["controller"] == controller]
    complete = lambda c: c["initialization_valid"] and c["job"]["status"] == "completed"  # noqa: E731
    return {"controller": controller, "requests": len(selected), "held_seating_dwell_completions": sum(complete(c) for c in selected),
            "initialization_failures": sum(not c["initialization_valid"] for c in selected),
            "deadline_failures": sum(c["job"]["failure_reason"] == "deadline" for c in selected),
            "force_failures": sum(c["job"]["failure_reason"] == "force_abort" for c in selected),
            "witnessed_stalls": sum(c["job"]["first_witness_s"] is not None for c in selected),
            "completions_after_own_witnessed_stall": sum(complete(c) and c["job"]["first_witness_s"] is not None for c in selected),
            "retries_started": sum(c["retries_started"] for c in selected),
            "nominal": {"requests": sum(not any(c["task_case"]["fixture_offset_m"]) for c in selected),
                        "completions": sum(complete(c) and not any(c["task_case"]["fixture_offset_m"]) for c in selected)},
            "offset": {"requests": sum(any(c["task_case"]["fixture_offset_m"]) for c in selected),
                       "completions": sum(complete(c) and any(c["task_case"]["fixture_offset_m"]) for c in selected)},
            "native_steps": sum(c["native_steps"] for c in selected),
            "initialization_native_steps": sum(c["initialization_native_steps"] for c in selected),
            "mean_job_seconds_per_request": sum(c["job"]["elapsed_s"] for c in selected) / len(selected),
            "summed_worker_wall_seconds": sum(c["worker_wall_seconds"] for c in selected)}


def render_figure(output, comparison):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ("Force-guided alignment", "Continued insertion")
    colors = ("#247d91", "#c1774d")
    plt.rcParams.update({"font.size": 9, "font.family": "DejaVu Sans", "axes.spines.top": False,
                         "axes.spines.right": False, "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 6.2), gridspec_kw={"width_ratios": [1, 1.8]}, layout="constrained")
    counts = [s["held_seating_dwell_completions"] for s in comparison["controllers"]]
    for i, (color, count) in enumerate(zip(colors, counts, strict=True)):
        axes[0, 0].barh(1 - i, count, color=color, height=.48)
        axes[0, 0].text(count + .12, 1 - i, f"{count}/6", va="center", fontweight="bold")
    axes[0, 0].set(yticks=[1, 0], yticklabels=labels, xlim=(0, 7), xticks=range(7),
                   xlabel="Held seating with 0.5 s dwell", title="All six requests per controller")
    axes[0, 0].grid(axis="x", alpha=.15)
    axes[1, 0].axis("off")
    table_rows = []
    for layout in range(3):
        for kind in ("nominal", "offset"):
            case_id = f"layout{layout}_{kind}"
            outcomes = [next(c for c in comparison["cases"] if c["case_id"] == case_id and c["controller"] == ctrl)["job"]["status"] for ctrl in CONTROLLERS]
            table_rows.append([f"{layout}: {'2 mm offset' if kind == 'offset' else 'nominal'}", *("seat" if s == "completed" else "timeout" for s in outcomes)])
    table = axes[1, 0].table(cellText=table_rows, colLabels=["Cable layout", "Guided", "Continue"], loc="center", cellLoc="center",
                            colWidths=[.49, .24, .27])
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.6)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("white")
        if row == 0:
            cell.set_facecolor("#e8edf0")
        elif col:
            cell.set_facecolor("#d8e9e2" if cell.get_text().get_text() == "seat" else "#f2ddcf")
    run = ROOT / "artifacts/cable/cable-baseline-v2-r01"
    for controller, label, color in zip(CONTROLLERS, labels, colors, strict=True):
        directory = run / ("layout0_offset__" + controller)
        case = read(directory / "result.json")
        with np.load(directory / "trajectory.npz") as data:
            start = case["initialization_native_steps"]
            native = data["native_forces"][start:]
            time = native[:, 0] - start * case["case"]["dt"]
            force = np.maximum(native[:, 5], native[:, 10])
            axes[0, 1].plot(time, force, color=color, lw=.95, label=label, rasterized=True)
            samples = data["samples"]
            axes[1, 1].plot(samples[:, 0], samples[:, 7] * 1000, color=color, lw=1.4)
        if case["job"]["first_witness_s"] is not None:
            for ax in axes[:, 1]:
                ax.axvline(case["job"]["first_witness_s"], color="#777", ls=":", lw=.8)
    axes[0, 1].axhline(20, color="#777", ls="--", lw=.8)
    axes[0, 1].set(title="Representative 2 mm offset: first registered layout", ylabel="Raw plug load (N)", ylim=(0, 22))
    axes[0, 1].legend(frameon=False, loc="lower right", fontsize=8)
    axes[1, 1].axhspan(0, 1, color="#8db59d", alpha=.25)
    axes[1, 1].set(xlabel="Job time after initialization (s)", ylabel="Tip-to-seat error (mm)", ylim=(0, 25))
    axes[1, 1].text(3.5, 15.1, "Continuation stalls, then times out", color=colors[1], fontsize=8)
    axes[1, 1].text(6.8, 2.1, "Guided job completes at 6.24 s", color=colors[0], fontsize=8)
    for ax in axes[:, 1]:
        ax.set_xlim(0, 30)
        ax.grid(alpha=.15)
    fig.suptitle("Actual-target guidance prevents local insertion failures on six cable cases\n"
                 "Scripted development evidence â€¢ no retries started â€¢ no learned or recovery-effect claim", fontsize=12)
    fig.supxlabel("Three cable directions Ã— nominal / 2 mm local offset; same task, force limits, 30 s deadline and paired initialization.\n"
                  "Free distal cable and fixed preset grasp; held seating is not released retention. Continued insertion is a weak comparator.", fontsize=8)
    for extension in ("png", "pdf"):
        fig.savefig(output.with_suffix("." + extension), dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/cable_baseline_v2.json")
    args = parser.parse_args()
    evidence = {"schema": 1, "version": "cable_baseline_v2", "generated_at_utc": datetime.now(UTC).isoformat(),
                "scope": "Warmup and separate six-case scripted free-cable development baseline. Held seating only; not recovery learning, a cable-snag study, released retention or an official AIC score.",
                "review_sources_sha256": {"scripts/review_cable_baseline.py": digest(__file__),
                                           "scripts/review_cable_robot.py": digest(ROOT / "scripts/review_cable_robot.py")}, "runs": []}
    external_cache = {}
    for run_id in RUN_IDS:
        run = ROOT / "artifacts/cable" / run_id
        audit = Audit()
        manifest, config, provenance = verify_provenance(run, audit, external_cache)
        result = read(run / "result.json")
        cases = [verify_case(run, c, config) for c in result["cases"]]
        requested = [(c["id"], controller) for c in config["cases"] for controller in config["controllers"]]
        audit.check("all_registered_requests", [(c["case_id"], c["controller"]) for c in cases] == requested and len(cases) == result["expected_requests"])
        audit.check("native_step_sum", sum(c["native_steps"] for c in cases) == result["accounting"]["native_steps"])
        audit.check("initialization_step_sum", sum(c["initialization_native_steps"] for c in cases) == result["accounting"]["initialization_native_steps"])
        audit.check("no_training", result["training_runs"] == 0)
        audit.check("no_initialization_failures_hidden", all(c["initialization_valid"] for c in cases))
        pairs = []
        for case in config["cases"]:
            directories = [run / (case["id"] + "__" + c) for c in CONTROLLERS]
            reports = [read(d / "result.json") for d in directories]
            initialization = reports[0]["initialization_native_steps"]
            with np.load(directories[0] / "trajectory.npz") as a, np.load(directories[1] / "trajectory.npz") as b:
                paired = np.array_equal(a["native_forces"][:initialization], b["native_forces"][:initialization])
            same_scene = canonical_scene(directories[0] / "scene.xml") == canonical_scene(directories[1] / "scene.xml")
            same_bias = reports[0]["precontact_bias_world_n"] == reports[1]["precontact_bias_world_n"]
            audit.check(f"paired_initialization:{case['id']}", paired and initialization == reports[1]["initialization_native_steps"] == 12000)
            audit.check(f"same_task_scene:{case['id']}", same_scene)
            audit.check(f"same_precontact_bias:{case['id']}", same_bias)
            pairs.append({"case_id": case["id"], "native_initialization_rows_identical": paired,
                          "initialization_rows_per_arm": initialization, "canonical_scene_identical": same_scene,
                          "recorded_precontact_bias_identical": same_bias})
        evidence["runs"].append({"run_id": run_id, "role": "nominal_warmup" if run_id == RUN_IDS[0] else "registered_development_comparison",
            "manifest": (run / "manifest.json").relative_to(ROOT).as_posix(), "provenance": provenance,
            "verification": audit.summary(), "cases": cases, "paired_initialization": pairs,
            "controllers": [controller_summary(cases, c) for c in CONTROLLERS],
            "accounting": {**result["accounting"], "poststep_forward_calls": sum(c["poststep_forward_calls"] for c in cases),
                           "launcher_wall_seconds": manifest["elapsed_seconds"]}})
    warmup, comparison = evidence["runs"]
    evidence["accounting"] = {"warmup": warmup["accounting"], "comparison": comparison["accounting"],
        "combined_native_steps": sum(r["accounting"]["native_steps"] for r in evidence["runs"]),
        "combined_initialization_native_steps": sum(r["accounting"]["initialization_native_steps"] for r in evidence["runs"]),
        "combined_launcher_wall_seconds": sum(r["accounting"]["launcher_wall_seconds"] for r in evidence["runs"]),
        "ordinary_learned_training": {"runs": 0, "native_steps": 0}, "recovery_focused_learned_training": {"runs": 0, "native_steps": 0},
        "policy_optimization_or_fault_mining_runs": 0, "shared_failure_recovery_comparison_runs": 0,
        "this_review": {"native_steps": 0, "mj_forward_calls": 0, "simulator_render_calls": 0},
        "scope": "All scripted initialization and job work is charged. Warmup requests are separate, not added to the six-case comparison denominators. No compute-matched learning claim."}
    evidence["main_result"] = {"guided": comparison["controllers"][0], "continuation": comparison["controllers"][1],
        "interpretation": "Actual-target force-guided alignment seats all six requests. Continued insertion seats three nominal requests and times out on all three local offsets after reported witnessed contact stalls. Guided control encounters no witnessed stall and starts no retries: its demonstrated effect is prevention, not recovery.",
        "conditional_recovery_effect_established": False,
        "causal_force_compensation_benefit_isolated": False,
        "why_not_isolated": "Guidance changes target alignment and approach control as well as force handling; no compensation ablation was run."}
    evidence["scope_and_limitations"] = [
        "Six deterministic development cases per controller: three initial cable directions crossed with one nominal and one 2 mm visible local fixture offset. No independent training starts, random layout population or final test.",
        "The cases share one robot home, connector geometry and mechanical model. The warmup repeats the nominal layout and adds no independent comparison case.",
        "Both controllers operate with simulator poses and exact-model bias feedforward. The practical baseline uses the actual target pose and a measured precontact wrist-load bias; continued axial insertion is a weak comparator.",
        "The raw 20 N wrist/plug abort uses the maximum of native-solve and refreshed samples. Force compensation does not redefine or remove this raw limit.",
        "All native force samples and exact initial force prefixes are checked. Robot poses/targets are saved every 10 ms, so native-rate seating-progress/stall predicates and every dwell pose cannot be independently replayed; recorded native evaluator results are distinguished from force-stream checks.",
        "Recorded precontact bias vectors match between arms; magnitude-only initialization force logs do not independently reconstruct the world-frame vector average.",
        "The distal cable end is free. There is no required earlier connection, clip or snag; this is not the requested combined cable-fault recovery benchmark.",
        "The plug has an immutable ideal preset grasp. A 0.5 s held seating dwell does not establish released latch retention, grasp reliability, electrical/optical function or hardware transfer.",
        "No shared competent failed prefix was handed to different recovery controllers. Differently selected controller failures cannot establish a conditional recovery advantage.",
        "No learned policy, training campaign, predictive interaction model, algorithmic novelty or superiority over a competent cable-aware baseline is demonstrated.",
        "Earlier native validation retains material timestep sensitivity despite the selected 0.25 ms engineering setting; this comparison does not establish physics convergence."]
    evidence["decision"] = {"status": "retain_simple_guided_insertion_baseline", "learned_benefit_established": False,
        "recovery_benefit_established": False, "novelty_claim": False, "full_cable_recovery_comparison_gate_passed": False,
        "next_action": "Establish physical connector retention and a feasible required-connection/clip plus optional-snag extension, then test whether the competent baseline leaves a reproducible recovery failure before introducing learning."}
    audits = [r["verification"] for r in evidence["runs"]] + [c["verification"] for r in evidence["runs"] for c in r["cases"]]
    evidence["verification"] = {"status": "passed" if all(a["status"] == "passed" for a in audits) else "failed",
                                "checks": sum(a["checks"] for a in audits),
                                "failed_checks": [s for a in audits for s in a["failed_checks"]]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if evidence["verification"]["status"] == "passed":
        render_figure(args.output.with_suffix(""), comparison)
        evidence["figures"] = [{"path": args.output.with_suffix("." + ext).relative_to(ROOT).as_posix(),
                                "sha256": digest(args.output.with_suffix("." + ext))} for ext in ("png", "pdf")]
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf8")
    print(json.dumps({"verification": evidence["verification"], "accounting": evidence["accounting"],
                      "main_result": evidence["main_result"], "evidence": str(args.output)}, indent=2))
    return 0 if evidence["verification"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
