"""Perception-study worker: every arm reads an estimate, truth is scoring-only.

One request is one clearance repair issued from one decision state at one
declared perception error level. The controller consumes the estimate, a
fail-closed privilege guard fails the request if control-side code touches a
scoring-only channel, and all three constraints are scored on the same rollout.

Differences from the v2/v3 worker, all of them deliberate and declared:

  * the controller is driven by an ``EpisodePerception`` estimate of the socket
    pose and the cable centreline, not by ``data.site_xpos[port_site]``;
  * the clip predicate is no longer on the controller's observation, because a
    clip predicate is not something a camera can see. The job still terminates on
    a true clip loss - that is an outcome, not an observation;
  * a declared stochastic disturbance force is applied to the cable, so the shape
    moves for reasons no estimator can attribute;
  * C1, C2 and C3 are scored at every servo tick from truth, with the force abort
    recorded as right-censoring rather than as a success;
  * a short observation history is captured at the decision, so an arm that needs
    history can be given it without a second collection.

Not official AIC scoring, not a released or latched connection, not learned
pickup, not camera perception and not a hardware claim.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_constrained_v2 import (  # noqa: E402
    LOAD_KEYS,
    MutationGuard,
    apply_cartesian_impedance,
    build_scene,
    cable_centerline,
    clip_state,
    measure_loads,
    raw_loads,
)
from assembly_recovery.cable_constraints_v4 import ConstraintScorer, min_bend_radius  # noqa: E402
from assembly_recovery.cable_jobs import CableJob, CableJobLimits, CableSample  # noqa: E402
from assembly_recovery.cable_perception_v4 import (  # noqa: E402
    EpisodePerception,
    PerceptionLevel,
    PrivilegeGuard,
)
from assembly_recovery.cable_recovery_control_v2 import (  # noqa: E402
    PHASE_CODE,
    ForceGuidedInsertion,
    RecoveryObservation,
    parametric_macro,
    repair_library,
)
from scripts.evaluate_cable_recovery_v2 import (  # noqa: E402
    SERVO_CHANNELS,
    clip_margin,
    settle,
    wrist_world,
    write,
)
from scripts.probe_cable_robot import render  # noqa: E402


def effective_level(cfg: dict, case: dict) -> PerceptionLevel:
    """The perception level this request runs at, after single-factor isolation."""
    from assembly_recovery.cable_study_v4 import effective_level as resolve

    contract = {"error_model": {"levels": cfg["perception"]["levels"],
                                "isolation": cfg["perception"].get("isolation")}}
    return PerceptionLevel.from_dict(
        resolve(contract, case["error_level"], case.get("error_isolation", "all")))


def estimated_observation(scene, perception: EpisodePerception, truth: RecoveryObservation,
                          guard: PrivilegeGuard) -> tuple[RecoveryObservation, np.ndarray]:
    """The declared common interface, built entirely from the estimate.

    Every arm receives this object and nothing else. ``clip_retained`` and
    ``clip_margin_m`` are set to the values a supervisor without a clip sensor
    would carry - retained, and a margin it cannot measure - so no arm can read
    the constraint it is being asked to predict.
    """
    centreline, weights = perception.centreline(truth.cable_centerline)
    estimate = replace(
        truth,
        seated_position=perception.socket_position(truth.seated_position),
        insertion_axis=perception.insertion_axis(truth.insertion_axis),
        cable_centerline=centreline,
        wrist_force_world=perception.force(truth.wrist_force_world),
        anchor_reaction_world=perception.force(truth.anchor_reaction_world),
        connector_contact_n=perception.scalar_force(truth.connector_contact_n),
        clip_contact_n=perception.scalar_force(truth.clip_contact_n),
        post_contact_n=perception.scalar_force(truth.post_contact_n),
        clip_retained=True,
        clip_margin_m=float("nan"),
    )
    return estimate, weights


def observed_decision_state(scene, estimate: RecoveryObservation, loads: dict,
                            perception: EpisodePerception, weights, history) -> dict:
    """The predictor input at the tick a repair is chosen. Estimate only.

    Stored as float64 lists, because a float32 ledger already broke exact replay
    once on this project. ``history`` is the short window of earlier estimated
    snapshots the Mh arm is allowed, captured here so no second collection is
    needed to test whether a rate-dependent constraint needs it.
    """
    tip = np.asarray(estimate.tip_position, dtype=float)
    centreline = np.asarray(estimate.cable_centerline, dtype=float)
    anchor = np.asarray(scene.fixture["anchor_site_world"], dtype=float)
    boot = centreline[0]
    seated = np.asarray(estimate.seated_position, dtype=float)
    axis = np.asarray(estimate.insertion_axis, dtype=float)
    return {
        "time_s": float(estimate.time_s),
        "tip_position_m": tip.tolist(),
        "boot_position_m": boot.tolist(),
        "anchor_site_m": anchor.tolist(),
        "insertion_axis": axis.tolist(),
        "seated_position_m": seated.tolist(),
        "boot_to_anchor_m": float(np.linalg.norm(boot-anchor)),
        "tip_to_seated_m": float(np.linalg.norm(tip-seated)),
        "depth_along_axis_m": float((tip-scene.initial_tip) @ axis),
        "routed_length_m": float(np.linalg.norm(np.diff(centreline, axis=0), axis=1).sum()),
        "clip_margin_m": float(estimate.clip_margin_m) if np.isfinite(estimate.clip_margin_m) else 0.0,
        "min_bend_radius_m": float(min_bend_radius(centreline)),
        "occluded_node_fraction": float(np.mean(np.asarray(weights) > 0.5)),
        "connector_contact_n": float(estimate.connector_contact_n),
        "clip_contact_n": float(estimate.clip_contact_n),
        "post_contact_n": float(estimate.post_contact_n),
        "shelf_contact_n": float(perception.scalar_force(loads["cable_shelf_contact_n"])),
        "anchor_reaction_n": float(np.linalg.norm(estimate.anchor_reaction_world)),
        "cable_boot_load_n": float(perception.scalar_force(loads["cable_boot_load_n"])),
        "wrist_force_n": float(np.linalg.norm(np.asarray(estimate.wrist_force_world)
                                              - np.asarray(estimate.precontact_bias_world))),
        "centerline_m": centreline.tolist(),
        "occlusion_weights": np.asarray(weights, dtype=float).tolist(),
        "history": history,
    }


def history_snapshot(estimate: RecoveryObservation) -> dict:
    """One earlier estimated snapshot, small enough to store for every request."""
    centreline = np.asarray(estimate.cable_centerline, dtype=float)
    return {"time_s": float(estimate.time_s),
            "tip_position_m": np.asarray(estimate.tip_position, dtype=float).tolist(),
            "seated_position_m": np.asarray(estimate.seated_position, dtype=float).tolist(),
            "boot_position_m": centreline[0].tolist(),
            "min_bend_radius_m": float(min_bend_radius(centreline)),
            "anchor_reaction_n": float(np.linalg.norm(estimate.anchor_reaction_world)),
            "wrist_force_n": float(np.linalg.norm(np.asarray(estimate.wrist_force_world)
                                                  - np.asarray(estimate.precontact_bias_world))),
            "routed_length_m": float(np.linalg.norm(np.diff(centreline, axis=0), axis=1).sum())}


def run_case(cfg, case, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    cfg = {**cfg, "clocks": {**cfg["clocks"], **case.get("clocks_override", {})},
           "cable": {**cfg["cable"], **case.get("cable_overrides", {})}}
    scene = build_scene(ROOT, cfg, case, directory)
    build_seconds = time.monotonic()-started
    write(directory / "adaptation.json", scene.report)
    data = scene.data
    physics = cfg["clocks"]["physics_hz"]
    dt = 1.0/physics
    servo_every = round(physics/cfg["clocks"]["servo_hz"])
    policy_every = round(physics/cfg["clocks"]["policy_hz"])
    if servo_every < 1 or policy_every % servo_every:
        raise ValueError("Clock rates must give integer, nested tick ratios")
    limits = CableJobLimits(**{**cfg["job_limits"], **case.get("job_limits_override", {})})
    job = CableJob(limits)
    settle_steps, settled, settle_reason = settle(scene, cfg)
    guard = MutationGuard(scene)
    privilege = PrivilegeGuard()
    render(scene, directory, "settled")
    bias = wrist_world(scene).copy()
    settled_state = {"qpos": data.qpos.copy(), "qvel": data.qvel.copy(),
                     "centerline": cable_centerline(scene)}
    if not settled:
        job.fail(settle_reason)

    level = effective_level(cfg, case)
    node_count = len(settled_state["centerline"])
    perception = EpisodePerception(level, scene.fixture, cfg["perception"]["camera"],
                                   int(case["perception_seed"]), servo_every*dt, node_count)
    constraints = cfg["constraints"]
    scorer = ConstraintScorer(
        bend_radius_spec_m=float(constraints["C2_bend"]["spec_m"]),
        anchor_limit_n=float(constraints["C3_anchor"]["limit_n"]),
        bend_radius_secondary_m=float(constraints["C2_bend"]["secondary_m"]),
        anchor_secondary_n=float(constraints["C3_anchor"]["secondary_n"]),
        segment_length_m=float(cfg["cable"]["segment_length_m"]),
        max_turn_deg=float(cfg["cable"]["max_initial_turn_deg"]))

    macros = repair_library(cfg["repair_library"])
    macros["parametric"] = parametric_macro(case["repair_action"])
    run_direction = np.array([*case["run_direction_xy"], 0.0])
    # The controller is built on the ESTIMATED insertion axis. The tool's own
    # orientation is robot-side and exactly known; what an orientation error
    # models is the estimator believing the socket is rotated relative to it, so
    # the approach and every repair frame are aimed along a slightly wrong axis.
    # The commanded tool rotation stays the robot's own and is not perturbed.
    estimated_axis = perception.insertion_axis(scene.insertion_axis)
    controller = ForceGuidedInsertion(cfg["force_guided_controller"], scene.initial_tip,
                                      estimated_axis)
    native = np.zeros((round(limits.deadline_s*physics)+2, 4))
    servo = np.zeros((round(limits.deadline_s*cfg["clocks"]["servo_hz"])+2, SERVO_CHANNELS))
    events, dense, phase = [], [], "settle"
    native_rows = servo_rows = steps = 0
    target = scene.initial_tip.copy()
    peaks = dict.fromkeys(LOAD_KEYS, 0.0)
    decision_state = None
    repair_start_tip = None
    history: list[dict] = []
    history_cfg = cfg["perception"]["history"]
    history_stride = max(1, round(history_cfg["stride_s"]*cfg["clocks"]["servo_hz"]))
    probe_truth_at = case.get("probe_truth_read_s")
    probed = False
    forced = case["forced_macro"]
    dense_every = max(1, round(cfg["ledger"]["dense_state_stride_s"]*physics))
    axis, initial_tip = scene.insertion_axis, scene.initial_tip
    base_time = float(data.time)
    cable_bodies = np.asarray(scene.cable_bodies)

    def record_event(name):
        events.append({"name": name, "job_time_s": float(data.time)-base_time, "phase": phase,
                       "qpos": data.qpos.copy(), "qvel": data.qvel.copy(),
                       "centerline": cable_centerline(scene)})

    record_event("settled")
    total = round(limits.deadline_s*physics) if settled else 0
    servo_tick = 0
    for i in range(total):
        job_time = i*dt
        if i % servo_every == 0:
            centerline = cable_centerline(scene)
            state = clip_state(scene, centerline)
            loads = measure_loads(scene)
            reaction = np.asarray(loads["anchor_constraint_world_n"])
            margin = clip_margin(scene, state, centerline)
            truth = RecoveryObservation(
                job_time, data.site_xpos[scene.tip_site].copy(),
                data.site_xmat[scene.tip_site].reshape(3, 3).copy(),
                data.site_xpos[scene.port_site].copy(), axis, wrist_world(scene).copy(), bias,
                loads["plug_port_contact_n"], loads["cable_clip_contact_n"],
                loads["cable_post_contact_n"], reaction, centerline,
                state["has_retained_passage"], margin, job.first_witness_s is not None)
            perception.advance()
            estimate, weights = estimated_observation(scene, perception, truth, privilege)
            # Scoring runs with the guard disarmed: truth is legitimate here and
            # nowhere else. The disturbance force is a physical event, not an
            # observation, and is applied outside the control window as well.
            progress = (0.0 if repair_start_tip is None
                        else float(np.linalg.norm(truth.tip_position-repair_start_tip)))
            scorer.update(centerline, float(np.linalg.norm(reaction)),
                          bool(state["has_retained_passage"]), progress)
            if level.process_force_n:
                data.xfrc_applied[cable_bodies, :3] = perception.process_force_world_n/len(cable_bodies)
            if servo_tick % history_stride == 0 and decision_state is None:
                history.append(history_snapshot(estimate))
                del history[:-int(history_cfg["length"])]
            guard.before_control()
            privilege.arm()
            if probe_truth_at is not None and job_time >= probe_truth_at and not probed:
                # Registered positive control: a deliberate control-side read of a
                # scoring-only channel that the privilege guard must detect.
                privilege.record("positive_control_true_port_site")
                probed = True
            if i % policy_every == 0:
                due = job_time >= (case.get("forced_macro_at_s") or 0.0)
                if (due and not controller.repairs_started
                        and controller.request_repair(macros[forced], estimate.tip_position,
                                                      run_direction, job_time)):
                    decision_state = observed_decision_state(scene, estimate, loads, perception,
                                                             weights, list(history))
                    repair_start_tip = np.asarray(truth.tip_position, dtype=float).copy()
                    record_event("repair_start")
                target, phase, _ = controller.step(estimate, policy_every*dt)
            privilege.disarm()
            apply_cartesian_impedance(scene, target, scene.target_rotation, cfg["controller"])
            guard.after_control()
            position = truth.tip_position
            angle = float(np.arccos(np.clip(
                (np.trace(truth.tip_rotation.T @ scene.target_rotation)-1)/2, -1, 1)))
            sample = CableSample(
                job_time+servo_every*dt, servo_every*dt,
                float(np.linalg.norm(position-truth.seated_position)), angle,
                float((position-initial_tip) @ axis), float((target-initial_tip) @ axis),
                loads["raw_wrist_load_n"], loads["raw_plug_load_n"], float(np.linalg.norm(reaction)),
                loads["plug_port_contact_n"], loads["cable_post_contact_n"],
                bool(state["has_retained_passage"]), True,
                loads["port_detector_contact_n"] > limits.contact_witness_n, guard.events)
            previous_witness = job.first_witness_s
            job.update(sample)
            for key in peaks:
                peaks[key] = max(peaks[key], loads[key])
            servo[servo_rows] = [job_time, *position, *target, sample.seating_error_m, angle,
                                 sample.insertion_depth_m, sample.commanded_depth_m,
                                 *[loads[k] for k in LOAD_KEYS], *reaction,
                                 float(sample.clip_retained), float(len(state["retained_passages"])),
                                 guard.events, PHASE_CODE.get(phase, len(PHASE_CODE))]
            servo_rows += 1
            servo_tick += 1
            if previous_witness is None and job.first_witness_s is not None:
                record_event("first_witness")
            # A true clip loss ends the request. It is an outcome, not an
            # observation: the controller never saw it and could not have.
            if not state["has_retained_passage"] and job.status == "active":
                job.fail("lost_required_clip")
            elif getattr(controller, "terminal", False) and job.status == "active":
                job.fail("controller_"+phase)
        mujoco.mj_step(scene.model, scene.data)
        steps += 1
        wrist, plug, anchor = raw_loads(scene)
        native[native_rows] = [job_time, wrist, plug, anchor]
        native_rows += 1
        if wrist > limits.wrist_force_n or plug > limits.plug_force_n:
            job.fail("force_abort")
        elif anchor > limits.anchor_force_n:
            job.fail("prior_connection_load_abort")
        elif not np.isfinite(data.qpos).all() or np.any(data.warning.number):
            job.fail("nonfinite_dynamics")
        if i % dense_every == 0:
            dense.append([job_time, *data.site_xpos[scene.tip_site], *data.qpos[:8]])
        if job.status != "active":
            break
    data.xfrc_applied[:] = 0.0
    if job.status == "active" and settled:
        job.fail("deadline")
    mujoco.mj_forward(scene.model, scene.data)
    phase = "terminal"
    record_event("terminal")
    render(scene, directory, "final")
    terminal_state = clip_state(scene)
    move_completed = bool(settled and controller.repairs_started
                          and job.failure_reason not in ("force_abort", "prior_connection_load_abort",
                                                         "nonfinite_dynamics", "deadline"))
    labels = scorer.labels(move_completed, terminal_state["has_retained_passage"])
    np.savez_compressed(
        directory / "ledger.npz",
        native=native[:native_rows], servo=servo[:servo_rows], dense=np.asarray(dense),
        native_channels=np.asarray(cfg["ledger"]["native_channels"]),
        servo_channels=np.asarray(cfg["ledger"]["servo_channels"]),
        event_names=np.asarray([e["name"] for e in events]),
        event_times=np.asarray([e["job_time_s"] for e in events]),
        event_qpos=np.asarray([e["qpos"] for e in events]),
        event_qvel=np.asarray([e["qvel"] for e in events]),
        event_centerline=np.asarray([e["centerline"] for e in events]),
        settled_qpos=settled_state["qpos"], settled_qvel=settled_state["qvel"],
        settled_centerline=settled_state["centerline"],
        terminal_qpos=data.qpos.copy(), terminal_qvel=data.qvel.copy(),
        terminal_centerline=cable_centerline(scene),
    )
    wall = time.monotonic()-started
    outcome = {
        "case": case, "controller": case["controller"], "status": "completed",
        "job": job.report(), "settled": settled, "settle_reason": settle_reason,
        "terminal_clip_retained": terminal_state["has_retained_passage"],
        "terminal_clip_margin_m": clip_margin(scene, terminal_state, cable_centerline(scene)),
        "repairs_started": controller.repairs_started, "repair_log": controller.repair_log,
        "retries_started": controller.retries, "last_phase": phase,
        "repair_action": case["repair_action"],
        "error_level": case["error_level"], "error_isolation": case.get("error_isolation", "all"),
        "applied_level": level.__dict__ if hasattr(level, "__dict__") else dict(level._asdict()),
        "decision_state": decision_state,
        "constraints": labels, "constraint_report": scorer.report(),
        "move_completed": move_completed,
        "precontact_bias_world_n": bias.tolist(), "peak_loads": peaks,
        "mutation_guard": guard.report(), "privilege_guard": privilege.report(),
        "compiled_cable_mass_kg": scene.report["compiled_cable_mass_kg"],
        "routed_direct_length_m": scene.report["cable"]["direct_length_m"],
        "geometric_service_loop_m": (scene.report["cable"]["rest_length_m"]
                                     - scene.report["cable"]["direct_length_m"]),
        "max_initial_turn_deg": scene.report["cable"]["max_initial_turn_deg"],
        "clocks": cfg["clocks"], "force_protocol": cfg["force_protocol"]["authoritative_stream"],
        "accounting": {"native_steps": steps, "settle_native_steps": settle_steps,
                       "servo_ticks": servo_rows, "model_compilations": 2,
                       "build_seconds": build_seconds, "wall_seconds": wall,
                       "native_steps_per_second": (steps+settle_steps)/max(wall-build_seconds, 1e-9)},
        "scope": [
            "Held, clip-preserving seating before gripper release. No latch, release, electrical "
            "function or hardware claim.",
            "Every arm reads the declared ESTIMATE; ground truth is scoring-only and the privilege "
            "guard fails the request if control-side code reads it.",
            "The error model is a model of how perception fails. It is not camera perception.",
            "Raw sensor norms include dynamic and gravity load; contact sums are witnesses, not net "
            "forces.",
        ],
    }
    # A privilege violation fails the request, exactly as a mutation event does.
    if privilege.events:
        outcome["job"]["status"] = "failed"
        outcome["job"]["failure_reason"] = "privilege_violation"
    write(directory / "result.json", outcome)
    print(json.dumps({"case": case["id"], "status": outcome["job"]["status"],
                      "reason": outcome["job"]["failure_reason"],
                      "level": case["error_level"],
                      "C1": labels["C1_clip"]["state"], "C2": labels["C2_bend"]["state"],
                      "C3": labels["C3_anchor"]["state"], "steps": steps}), flush=True)
    return outcome


def guarded_case(cfg, case, directory: Path) -> dict:
    """Run one request, preserving an infeasible construction as a failed request."""
    try:
        return run_case(cfg, case, directory)
    except (ValueError, KeyError) as exc:
        directory.mkdir(parents=True, exist_ok=True)
        censored = {name: {"state": "censored", "violation_progress_m": None,
                           "censoring_progress_m": 0.0}
                    for name in ("C1_clip", "C2_bend", "C3_anchor")}
        outcome = {"case": case, "controller": case["controller"], "status": "completed",
                   "job": {"status": "failed", "failure_reason": "construction_infeasible",
                           "elapsed_s": 0.0, "dwell_s": 0.0, "first_witness_s": None,
                           "witness_type": None, "samples": 0},
                   "settled": False, "settle_reason": "construction_infeasible",
                   "construction_error": f"{type(exc).__name__}: {exc}",
                   "terminal_clip_retained": False, "terminal_clip_margin_m": 0.0,
                   "repairs_started": 0, "repair_log": [], "retries_started": 0,
                   "last_phase": "construction", "decision_state": None,
                   "error_level": case.get("error_level"),
                   "error_isolation": case.get("error_isolation", "all"),
                   "constraints": censored, "move_completed": False,
                   "mutation_guard": {"events": 0}, "privilege_guard": {"events": 0, "reasons": [],
                                                                        "verdict": "clean"},
                   "accounting": {"native_steps": 0, "settle_native_steps": 0, "servo_ticks": 0,
                                  "model_compilations": 0, "build_seconds": 0.0, "wall_seconds": 0.0,
                                  "native_steps_per_second": 0.0},
                   "scope": ["Infeasible construction retained in the all-request denominator."]}
        write(directory / "result.json", outcome)
        print(json.dumps({"case": case["id"], "status": "failed",
                          "reason": "construction_infeasible", "detail": str(exc)[:160]}), flush=True)
        return outcome


def _worker(item):
    return guarded_case(*item)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--case")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    cases = [c for c in cfg["cases"] if not args.case or c["id"] == args.case]
    if not cases:
        parser.error("No selected cases")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    if args.workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            outcomes = list(pool.map(_worker, [(cfg, c, args.run_dir / c["id"]) for c in cases]))
    else:
        outcomes = [guarded_case(cfg, c, args.run_dir / c["id"]) for c in cases]
    write(args.run_dir / "result.json", {
        "status": "completed", "scope": cfg["scope"], "config_id": cfg["id"], "cases": outcomes,
        "expected_requests": len(cases),
        "accounting": {
            "native_steps": sum(o["accounting"]["native_steps"] for o in outcomes),
            "settle_native_steps": sum(o["accounting"]["settle_native_steps"] for o in outcomes),
            "wall_seconds": sum(o["accounting"]["wall_seconds"] for o in outcomes),
            "training_runs": 0,
        },
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
