"""Recheck bounded cable fixture artifacts and plot measured controls, no simulator."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(run_id):
    directory = ROOT / "artifacts/cable" / run_id
    manifest = json.loads((directory / "manifest.json").read_text())
    pre = json.loads((directory / "prelaunch.json").read_text())
    checks = {"prelaunch_unchanged": sha(directory / "prelaunch.json") == manifest["prelaunch_sha256"]}
    with zipfile.ZipFile(directory / "source.zip") as archive:
        checks["source_bytes_match_prelaunch"] = all(
            hashlib.sha256(archive.read(p)).hexdigest() == digest for p, digest in pre["source_hashes"].items()
        )
    checks["artifact_bytes_match"] = all(
        sha(directory / item["path"]) == item["sha256"] for item in manifest["artifacts"]
    )
    checks["aic_pinned"] = pre["upstream"]["aic"]["commit"] == "e9145480c945f2afc3741f355233f44082cc3b06"
    if not all(checks.values()):
        raise ValueError((run_id, checks))
    return {
        "run_id": run_id,
        "status": manifest["status"],
        "checks": checks,
        "manifest_sha256": sha(directory / "manifest.json"),
        "source_archive_sha256": sha(directory / "source.zip"),
        "accounting": manifest.get("accounting"),
        "elapsed_seconds": manifest["elapsed_seconds"],
    }


def main():
    run_ids = ["cable-contact-v1-r01", "cable-contact-v1-r02", "cable-contact-v1-r03"]
    runs = [verify_run(r) for r in run_ids]
    directory = ROOT / "artifacts/cable/cable-contact-v1-r03"
    result = json.loads((directory / "result.json").read_text())
    cases = result["cases"]
    measured = []
    for case in cases:
        trace = np.load(directory / case["case"]["id"] / "trace.npz")
        data = trace["trace"]
        if not np.isfinite(data).all() or len(data) < 10 or not np.all(np.diff(data[:, 0]) > 0):
            raise ValueError("Invalid trace")
        measured.append(
            {
                k: case[k]
                for k in (
                    "case",
                    "attempt_outcome",
                    "is_robot_baseline",
                    "valid_seating_attempt",
                    "minimum_tip_error_m",
                    "maximum_tip_angle_rad",
                    "initial_contact_peak_n",
                    "peak_stage_wrist_force_n",
                    "peak_plug_port_contact_n",
                    "peak_port_detector_contact_n",
                    "native_steps",
                    "initialization_native_steps",
                    "acceptance_checks",
                )
            }
        )
    by_id = {r["case"]["id"]: r for r in cases}
    gates = {
        "all_finite": all(r["finite_dynamics"] for r in cases),
        "all_initially_connector_contact_free": all(r["acceptance_checks"]["initial_contact_free"] for r in cases),
        "all_tracking_checks": all(r["acceptance_checks"]["free_tracking"] for r in cases),
        "aligned_seating_both_timesteps_with_and_without_cable": all(
            by_id[k]["valid_seating_attempt"]
            for k in ("aligned_1ms", "aligned_05ms", "aligned_cable_1ms", "aligned_cable_05ms")
        ),
        "free_space_zero_connector_contact": by_id["free_space_1ms"]["peak_plug_port_contact_n"] == 0,
        "misaligned_contact_positive_controls": all(
            by_id[k]["peak_plug_port_contact_n"] > 0.05 and not by_id[k]["valid_seating_attempt"]
            for k in ("misaligned_1ms", "misaligned_cable_1ms")
        ),
    }
    pair_metrics = []
    for prefix in ("aligned", "aligned_cable"):
        a = by_id[f"{prefix}_1ms"]
        b = by_id[f"{prefix}_05ms"]
        pair_metrics.append(
            {
                "pair": prefix,
                "same_dwell_outcome": a["seating_dwell_reached"] == b["seating_dwell_reached"],
                "all_phase_peak_contact_difference_n": abs(
                    a["peak_plug_port_contact_n"] - b["peak_plug_port_contact_n"]
                ),
                "minimum_tip_error_difference_m": abs(a["minimum_tip_error_m"] - b["minimum_tip_error_m"]),
            }
        )
    evidence = {
        "schema": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "diagnostic_controls_passed" if all(gates.values()) else "revise_diagnostic",
        "scope_and_limitations": [
            "Force-actuated three-axis fixture using exact public SC SDF collision geometry; no robot baseline, grasp validation, official AIC score or cable recovery comparison.",
            "Fixture allows no connector rotation and compensates whole moving subtree gravity, including floor-supported cable mass.",
            "Peaks include initialization, insertion and deliberate post-dwell retraction. Seating was observed during the attempt; no final connected-job claim.",
            "v1 cable root is 48 mm behind the plug rather than public 52 mm; ball root has no elastic attachment moment. Cable modulus is a declared simulation model, uncalibrated to hardware.",
            "v1 sensor/contact/pose traces are at the pre-integration solve; the velocity columns were advanced one step. Seating/contact outcomes do not use those velocity columns. v2 corrects timestamps and phase metrics prospectively.",
            "Two sampled timesteps establish narrow sensitivity of these controls, not general convergence or transfer.",
        ],
        "controller": "scripted_cartesian_force_stage_approach_retract",
        "runs": runs,
        "failed_experiments": [
            {
                "run_id": run_ids[0],
                "status": "process_failed",
                "error": "MuJoCo rejected zero-volume GLB visual mesh before explicit simulation step",
                "explicit_native_steps": 0,
                "correction": "Visual-only OBJ meshes use shell inertia; collision geometry unchanged; exact failed and corrected sources archived.",
            }
        ],
        "gates": gates,
        "cases": measured,
        "representative_refinement": pair_metrics,
        "cost": {
            "explicit_native_steps": sum((r["accounting"] or {}).get("native_steps", 0) for r in runs),
            "initialization_explicit_native_steps": sum(
                (r["accounting"] or {}).get("initialization_native_steps", 0) for r in runs
            ),
            "launcher_wall_seconds": sum(r["elapsed_seconds"] for r in runs),
            "learning_transitions": 0,
            "training_runs": 0,
            "cost_scope": "Includes repeated aligned r02, all seven r03 controls and failed process wall time. MuJoCo compile/forward work included in wall time; native count is explicit integration calls.",
        },
        "decision": "Continue to native robot baseline and sensor/load validation; no learning comparison gate opened.",
        "next_action": "Validate native UR5e insertion on the same current SDF geometry, with explicit preset-grasp and cable-load scope.",
    }
    output = ROOT / "evidence/cable_contact_validation_v1.json"
    with output.open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, allow_nan=False)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), layout="constrained")
    for key, label, color in (
        ("aligned_cable_1ms", "Aligned + cable, 1 ms", "#087e8b"),
        ("aligned_cable_05ms", "Aligned + cable, 0.5 ms", "#83b5b1"),
        ("misaligned_cable_1ms", "3 mm offset + cable", "#c9523c"),
        ("free_space_1ms", "Free-space control", "#797d83"),
    ):
        tr = np.load(directory / key / "trace.npz")["trace"]
        axes[0].plot(tr[:, 0], tr[:, 10] * 1000, label=label, color=color)
        axes[1].plot(tr[:, 0], tr[:, 8], label=label, color=color)
    axes[0].axhline(1, color="#999999", linestyle=":", linewidth=1)
    axes[0].set(xlabel="Simulated time (s)", ylabel="Tip-to-base distance (mm)", ylim=(0, 45))
    axes[1].set(xlabel="Simulated time (s)", ylabel="Plug–port contact magnitude sum (N)")
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.axvspan(0, 2, color="#e8edf2", alpha=0.7)
        ax.axvline(10, color="#999999", linestyle="--", linewidth=1)
    fig.suptitle("SC contact controls: physical seating and blocked misalignment", fontsize=14)
    fig.supxlabel(
        "Force-actuated fixture • 0–2 s initialization • retraction after 10 s • no robot or learning result",
        fontsize=9,
    )
    for suffix in ("png", "pdf"):
        fig.savefig(ROOT / f"evidence/cable_contact_validation_v1.{suffix}", dpi=180)
    print(json.dumps({"status": evidence["status"], "gates": gates, "cost": evidence["cost"]}))


if __name__ == "__main__":
    main()
