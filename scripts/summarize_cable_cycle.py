"""Close the executed native cable cycle from immutable run/evidence records."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_IDS = (
    "cable-contact-v1-r01",
    "cable-contact-v1-r02",
    "cable-contact-v1-r03",
    "cable-robot-v1-r01",
    "cable-robot-v1-r02",
    "cable-robot-v2-r01",
    "cable-robot-v3-r01",
    "cable-baseline-v1-r01",
    "cable-baseline-v2-r01",
    "cable-retention-v1-r01",
    "cable-retention-v1-r02",
    "cable-retention-v2-r01",
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize():
    reviews = [
        "cable_contact_validation_v1.json",
        "cable_robot_validation_v1.json",
        "cable_baseline_v2.json",
        "cable_retention_v1.json",
        "cable_literature_review_v1.json",
    ]
    evidence_refs = [{"path": "evidence/" + name, "sha256": digest(ROOT / "evidence" / name)} for name in reviews]
    launches = []
    physical_trials = 0
    for name in RUN_IDS:
        directory = ROOT / "artifacts/cable" / name
        manifest = read(directory / "manifest.json")
        accounting = manifest.get("accounting") or {}
        if (directory / "result.json").exists():
            physical_trials += len(read(directory / "result.json").get("cases", []))
        launches.append(
            {
                "run_id": name,
                "status": manifest["status"],
                "manifest_sha256": digest(directory / "manifest.json"),
                "source_commit_at_start": manifest.get("source_commit_at_start"),
                "source_archive": manifest.get("source_archive"),
                "accounting": accounting,
                "launcher_wall_seconds": manifest["elapsed_seconds"],
                "error": manifest.get("error"),
            }
        )
    baseline = read(ROOT / "artifacts/cable/cable-baseline-v2-r01/result.json")
    if baseline["status"] != "completed" or len(baseline["cases"]) != 12:
        raise ValueError("Incomplete comparison")
    summaries = []
    for controller in ["scripted_force_guided_retry", "scripted_continuation"]:
        cases = [c for c in baseline["cases"] if c["controller"] == controller]
        summaries.append(
            {
                "controller": controller,
                "requests": len(cases),
                "seated_with_contact_and_dwell": sum(c["job"]["status"] == "completed" for c in cases),
                "failed_requests": sum(c["job"]["status"] == "failed" for c in cases),
                "initialization_failures": sum(not c["initialization_valid"] for c in cases),
                "force_aborts": sum("force_abort" in (c["job"]["failure_reason"] or "") for c in cases),
                "deadline_failures": sum(c["job"]["failure_reason"] == "deadline" for c in cases),
                "witnessed_stalls": sum(c["job"]["first_witness_s"] is not None for c in cases),
                "completed_after_witnessed_stall": sum(
                    c["job"]["first_witness_s"] is not None and c["job"]["status"] == "completed" for c in cases
                ),
                "retries_started": sum(c["retries_started"] for c in cases),
                "native_steps": sum(c["native_steps"] for c in cases),
                "initialization_native_steps": sum(c["initialization_native_steps"] for c in cases),
                "mean_simulated_seconds_per_request_including_initialization": sum(
                    c["native_steps"] * c["case"]["dt"] for c in cases
                )
                / len(cases),
                "mean_job_seconds_after_initialization_including_failures": sum(c["job"]["elapsed_s"] for c in cases)
                / len(cases),
                "training_cost": 0,
            }
        )
    retention = []
    for name in ["cable-retention-v1-r02", "cable-retention-v2-r01"]:
        result = read(ROOT / "artifacts/cable" / name / "result.json")
        for case in result["cases"]:
            retention.append(
                {
                    "run_id": name,
                    "case": case["case"],
                    "seated_before_load": case["seated_before_load"],
                    "retention_assessable": case["retention_assessable"],
                    "retained_in_axial_fixture": case["retained_in_axial_fixture"],
                    "first_loss_after_load_s": case["first_loss_after_load_s"],
                    "attempt_outcome": case["attempt_outcome"],
                }
            )
    if not all(c["retention_assessable"] and c["seated_before_load"] for c in retention):
        raise ValueError("Retention prerequisite not satisfied")
    positive = [c for c in retention if c["case"]["net_extraction_load_n"] > 0]
    if any(c["retained_in_axial_fixture"] for c in positive):
        raise ValueError("Decision must be revisited for retained positive load")
    document = {
        "schema": 1,
        "decision_id": "cable_cycle_decision_v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "decision": "revise_physical_connection_retention_model",
        "cycle_status": "closed_at_failed_retention_gate",
        "objective": "A credible cable/connector task, strong baseline, justified improvement and controlled result; proceed to learned joint connector/cable repair only when physical task gates support it.",
        "demonstrated_findings": [
            "Pinned AIC UR5e/current SC collisions run in a native Windows MuJoCo adapter, with exact source/asset provenance and bounded jobs.",
            "Force-guided observed-pose alignment/precontact compensation seats all six small development cases; continuation fails all three visible offset cases. This is prevention, not recovery after a common competent failure.",
            "Rigid SC geometry seats under insertion load but provides no opposing axial contact during positive extraction; 0.5/2 N unseat it in about12/6ms at both tested resolutions.",
            "Native cable initialization and contact are timestep-sensitive. Corrected curves permit engineering insertion at0.5/.25ms; no general cable-contact convergence claim.",
        ],
        "not_demonstrated": [
            "Released or latched final connection, hardware/electrical/optical function, pickup or drop robustness.",
            "Retaining prior clips/connections, distal snag generation/repair, held-out mechanical/layout or connector transfer.",
            "Ordinary or recovery-focused learned cable training, recurrent baseline training, interaction-prediction accuracy, matched learned benefit or algorithmic novelty.",
        ],
        "baseline": summaries,
        "baseline_scope": "Six deterministic development cases per arm: three initial free-cable directions crossed with0/2mm visible offset, one robot home and one mechanical model. Full simulator poses/exact model feedforward, fixed preset grasp. Weak continuation comparator; no claim over a competent recovery method.",
        "retention": retention,
        "retention_scope": "Independent one-axis force fixture with exact SC collisions. Seating/dwell/contact established before removing insertion force and applying gravity-compensated net extraction. Constrained axial evidence about this model, not actual SC hardware; no attachment changes or invented latch.",
        "method_status": {
            "ordinary_learned_training": "not_run",
            "recovery_focused_learned_training": "not_run",
            "recurrent_learned_baseline": "not_run",
            "candidate_interaction_predictor": "not_implemented_or_trained",
            "scripted_force_guided_controller": "executed; zero retries and zero witnessed recoveries in final six-case comparison",
            "scripted_continuation": "executed; three witnessed contact stalls remain unfinished",
            "visible_snag_rule_and_cable_planner": "not_run; extension support and final-connection gate unmet",
            "checkpoints_created": [],
        },
        "gates": {
            "exact_connector_collision_import": True,
            "contact_positive_and_free_controls": True,
            "bounded_native_robot_seating": True,
            "general_cable_contact_convergence": False,
            "physical_final_connection_retention": False,
            "prior_clip_and_clearable_snag_support": False,
            "substantial_learning_comparison": False,
        },
        "cost": {
            "launcher_attempts": len(launches),
            "physical_trials": physical_trials,
            "explicit_native_integration_steps": sum(r["accounting"].get("native_steps", 0) for r in launches),
            "initialization_explicit_native_steps": sum(
                r["accounting"].get("initialization_native_steps", 0) for r in launches
            ),
            "summed_launcher_wall_seconds": sum(r["launcher_wall_seconds"] for r in launches),
            "learning_transitions": 0,
            "training_runs": 0,
            "checkpoint_count": 0,
            "cost_unit": "one explicit mj_step call for one environment; not old peg reference transitions",
            "known_extra_review_forward_calls": 99,
            "scope": "All physical runs, repeats, initialization, timeouts, aborts and failed launcher/worker wall times included. Setup/implementation/CPU reviews are separate from summed launcher time. Compilation, rendering and poststep forward work are included in launcher wall time; native calls are explicit integration work. No absorbing batch padding or phantom training cost.",
            "capacity": "Native CPU dynamics with one environment per trial; measured case throughput/RSS recorded. No2,048/4,096-env cable GPU benchmark or extrapolation from peg.",
        },
        "provenance": {
            "starting_project_commit": "4040de31c903ea085c992cada566f9e18ed562a2",
            "aic_revision": "e9145480c945f2afc3741f355233f44082cc3b06",
            "ur5e_collision_revision": "ef93882e17d8aa628837915da4b83208fe5e519a",
            "runtime": "Python3.11.15/MuJoCo3.3.7; exact packages in configs/cable_dependencies_v1.json",
            "runtime_source": "Every launched worker has prelaunch exact source/asset snapshots. The retained BOM launcher failure occurred before source capture and before any worker; no run-time provenance or result is invented for it.",
            "review_evidence": evidence_refs,
        },
        "launches": launches,
        "negative_evidence": [
            "Visual-only mesh compile failure retained; shell inertia correction changed no collision geometry.",
            "Two straight-cable initialization failures and one1ms corrected-curve initialization failure retained.",
            "Three continuation timeouts retained; no losing request removed.",
            "BOM launcher failure retained; later parser supports BOM while archiving exact original bytes.",
            "All four positive-extraction retention failures retained across both resolutions.",
        ],
        "prior_art_boundary": {
            "compensation": "Staritz Force Guided Assembly Under Bias already models cable/hose load bias.",
            "predictive_connector_optimization": "Kienle et al. already predicts motion/wrench and optimizes mating searches.",
            "cable_recovery": "Tactile primitives, corrective skill selection, cable graphs and assembly-relation preservation have existing prior art.",
            "current_distinction": "An executed native integration and specific verified asset/retention boundary; no new learning algorithm or demonstrated joint-repair benefit.",
            "confidence": "High for the recorded model/code outcomes; unknown for proposed method benefit and hardware transfer.",
        },
        "next_action": "Independently specify and validate a passive connection-retention/load model, or select a connector model with supported retention, using engaged/disengaged/release controls. Then validate required-clip and physically clearable snag support before reopening learned comparisons.",
        "next_action_constraints": [
            "Preserve this rigid-model negative result and keep corrected task versions separate.",
            "Do not substitute a pose freeze or contact-triggered attachment for demonstrated passive retention.",
            "Do not launch further training or an expensive arm matrix under failed gates.",
            "Keep full observations available equally; simple rules/planning challenge the proposed predictor before learning spend.",
        ],
        "historical_peg_scope": "Peg code, ordinary training, prior negative evidence and capacity results are preserved unchanged and are not cable performance. No new peg simulator job ran.",
        "release": {
            "branch": "research/assembly-recovery-training",
            "main_modified": False,
            "maintained_markdown_files": ["AGENTS.md", "README.md", "ROADMAP.md"],
            "verification": "evidence/cable_cycle_verification_v1.json",
            "figures": [
                "evidence/cable_baseline_v2.pdf",
                "evidence/cable_retention_v1.pdf",
                "evidence/cable_robot_validation_v1.pdf",
            ],
        },
    }
    if document["cost"]["explicit_native_integration_steps"] != 1185841 or physical_trials != 37:
        raise ValueError("Cost/trial reconciliation mismatch")
    output = ROOT / "evidence/cable_cycle_decision_v1.json"
    with output.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, allow_nan=False)
    print(json.dumps({"decision": document["decision"], "cost": document["cost"], "baseline": summaries}, indent=2))


if __name__ == "__main__":
    summarize()
