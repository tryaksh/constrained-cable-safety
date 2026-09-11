"""Constrained-cable recovery worker: separated clocks, real loads, replay ledger.

One request is one job: settle, then run the registered controller until held
clip-preserving seating, an abort, a clip loss or the deadline. Every failed
request is preserved. This is a project engineering experiment, not official AIC
scoring, a released connection or a learned-policy result.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
from assembly_recovery.cable_jobs import CableJob, CableJobLimits, CableSample  # noqa: E402
from assembly_recovery.cable_recovery_control_v2 import (  # noqa: E402
    PHASE_CODE,
    BlindThenRecover,
    CableAwareRules,
    ForceGuidedInsertion,
    RecoveryObservation,
    ScriptedProgram,
    repair_library,
)
from scripts.probe_cable_robot import render  # noqa: E402

SERVO_CHANNELS = 28


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False, default=float), encoding="utf-8")


def wrist_world(scene):
    rotation = scene.data.site_xmat[scene.model.sensor("AtiForceTorqueSensor_force").objid[0]].reshape(3, 3)
    return rotation @ scene.data.sensor("AtiForceTorqueSensor_force").data


def clip_margin(scene, state, centerline) -> float:
    """Signed vertical margin of the retained passage below the clip lip.

    Positive means captured with that much travel before release; negative means
    the centerline is already above the lip. Geometry only: the physical release
    control, not this number, establishes that release can occur.
    """
    predicate = scene.clip_predicate
    if not state["retained_passages"]:
        local = (np.asarray(centerline) - scene.clip_origin) @ scene.clip_rotation
        near = local[np.argmin(np.abs(local[:, 0]))]
        return float(predicate["lip_height_m"] - predicate["cable_radius_m"] - near[2])
    return min(predicate["lip_height_m"] - predicate["cable_radius_m"] - p["point"][2]
               for p in state["retained_passages"])


def settle(scene, cfg):
    """Initialization: ease the constructed route into its resting configuration.

    Gravity is ramped from zero over the registered window so the installation
    pose relaxes instead of whipping; the ramp is a between-job initialization
    step and is restored exactly before the job starts. Within a job the mutation
    guard fails the request if gravity, any attachment or any state is written.
    """
    physics = cfg["clocks"]["physics_hz"]
    servo_every = round(physics / cfg["clocks"]["servo_hz"])
    steps = round(cfg["settle_seconds"] * physics)
    ramp = max(1, round(cfg["settle_gravity_ramp_s"] * physics))
    registered = float(cfg["registered_gravity_z"])
    for i in range(steps):
        if i % servo_every == 0:
            scene.model.opt.gravity[2] = registered * min(1.0, (i + 1) / ramp)
            apply_cartesian_impedance(scene, scene.initial_tip, scene.target_rotation, cfg["controller"])
        mujoco.mj_step(scene.model, scene.data)
        if not np.isfinite(scene.data.qpos).all() or np.any(scene.data.warning.number):
            scene.model.opt.gravity[2] = registered
            return steps, False, "settle_instability"
    scene.model.opt.gravity[2] = registered
    mujoco.mj_forward(scene.model, scene.data)
    loads = measure_loads(scene)
    speeds = np.linalg.norm(scene.data.cvel[scene.cable_bodies, 3:], axis=1)
    acceptance = cfg["settle_acceptance"]
    tracking = float(np.linalg.norm(scene.data.site_xpos[scene.tip_site] - scene.initial_tip))
    reason = None
    if tracking > acceptance["max_tip_tracking_m"]:
        reason = "settle_tracking"
    elif loads["plug_port_contact_n"] > acceptance["max_plug_port_contact_n"]:
        reason = "settle_initial_contact"
    elif float(speeds.max()) > acceptance["max_cable_speed_m_per_s"]:
        reason = "settle_cable_motion"
    elif acceptance["require_clip_retained"] and not clip_state(scene)["has_retained_passage"]:
        reason = "settle_clip_not_retained"
    return steps, reason is None, reason


def build_controller(cfg, case, scene, macros):
    """Instantiate the registered controller for this request."""
    name = case["controller"]
    run = np.array([*case["run_direction_xy"], 0.0])
    if name == "scripted_program":
        return ScriptedProgram(case["program"], scene.initial_tip, scene.insertion_axis, run), run
    if name == "force_guided_insertion":
        return ForceGuidedInsertion(cfg["force_guided_controller"], scene.initial_tip, scene.insertion_axis), run
    if name == "cable_aware_rules":
        return CableAwareRules(cfg["force_guided_controller"], scene.initial_tip, scene.insertion_axis,
                               macros, cfg["cable_aware_rules"]), run
    if name == "blind_then_recover":
        return BlindThenRecover(cfg["force_guided_controller"], scene.initial_tip, scene.insertion_axis,
                                macros, cfg["cable_aware_rules"], cfg["blind_first_attempt"]), run
    raise ValueError(f"Unregistered controller {name!r}")


def run_case(cfg, case, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    cfg = {**cfg, "clocks": {**cfg["clocks"], **case.get("clocks_override", {})},
           "cable": {**cfg["cable"], **case.get("cable_overrides", {})}}
    scene = build_scene(ROOT, cfg, case, directory)
    build_seconds = time.monotonic() - started
    write(directory / "adaptation.json", scene.report)
    data = scene.data
    physics = cfg["clocks"]["physics_hz"]
    dt = 1.0 / physics
    servo_every = round(physics / cfg["clocks"]["servo_hz"])
    policy_every = round(physics / cfg["clocks"]["policy_hz"])
    if servo_every < 1 or policy_every % servo_every:
        raise ValueError("Clock rates must give integer, nested tick ratios")
    limits = CableJobLimits(**{**cfg["job_limits"], **case.get("job_limits_override", {})})
    job = CableJob(limits)
    settle_steps, settled, settle_reason = settle(scene, cfg)
    guard = MutationGuard(scene)
    render(scene, directory, "settled")
    bias = wrist_world(scene).copy()
    settled_state = {"qpos": data.qpos.copy(), "qvel": data.qvel.copy(), "centerline": cable_centerline(scene)}
    if not settled:
        job.fail(settle_reason)

    macros = repair_library(cfg["repair_library"])
    controller, run_direction = build_controller(cfg, case, scene, macros)
    native = np.zeros((round(limits.deadline_s * physics) + 2, 4))
    servo = np.zeros((round(limits.deadline_s * cfg["clocks"]["servo_hz"]) + 2, SERVO_CHANNELS))
    events, dense, phase = [], [], "settle"
    native_rows = servo_rows = steps = 0
    target = scene.initial_tip.copy()
    peaks = dict.fromkeys(LOAD_KEYS, 0.0)
    witness_macro = None
    injection = case.get("inject_forbidden_write_s")
    injected = False
    forced = case.get("forced_macro")
    dense_every = max(1, round(cfg["ledger"]["dense_state_stride_s"] * physics))
    axis, initial_tip = scene.insertion_axis, scene.initial_tip
    base_time = float(data.time)

    def record_event(name):
        events.append({"name": name, "job_time_s": float(data.time) - base_time, "phase": phase,
                       "qpos": data.qpos.copy(), "qvel": data.qvel.copy(), "ctrl": data.ctrl.copy(),
                       "centerline": cable_centerline(scene)})

    record_event("settled")
    total = round(limits.deadline_s * physics) if settled else 0
    for i in range(total):
        job_time = i * dt
        if i % servo_every == 0:
            centerline = cable_centerline(scene)
            state = clip_state(scene, centerline)
            loads = measure_loads(scene)
            reaction = np.asarray(loads["anchor_constraint_world_n"])
            margin = clip_margin(scene, state, centerline)
            observation = RecoveryObservation(
                job_time, data.site_xpos[scene.tip_site].copy(),
                data.site_xmat[scene.tip_site].reshape(3, 3).copy(), data.site_xpos[scene.port_site].copy(),
                axis, wrist_world(scene).copy(), bias, loads["plug_port_contact_n"],
                loads["cable_clip_contact_n"], loads["cable_post_contact_n"], reaction, centerline,
                state["has_retained_passage"], margin, job.first_witness_s is not None)
            guard.before_control()
            if injection is not None and job_time >= injection and not injected:
                # Registered positive control: a deliberate controller-side pose
                # write that the mutation guard must detect and fail.
                data.qpos[scene.arm_dofs[0]] += 1e-4
                injected = True
            # Policy tick: the reference is recomputed only here and held between
            # ticks, so the physical control cadence is independent of dt.
            if i % policy_every == 0:
                if isinstance(controller, ScriptedProgram):
                    target, phase = controller.step(job_time, observation.tip_position, policy_every * dt)
                else:
                    if isinstance(controller, CableAwareRules) and job.first_witness_s is not None:
                        chosen = controller.on_witness(observation, run_direction, job_time)
                        if chosen:
                            witness_macro = chosen
                            record_event("repair_start")
                    due = (job.first_witness_s is not None if case.get("forced_macro_at_s") == "witness"
                           else job_time >= (case.get("forced_macro_at_s") or 0.0))
                    if (forced and due and not controller.repairs_started
                            and controller.request_repair(macros[forced], observation.tip_position,
                                                          run_direction, job_time)):
                        witness_macro = forced
                        record_event("repair_start")
                    target, phase, _ = controller.step(observation, policy_every * dt)
            apply_cartesian_impedance(scene, target, scene.target_rotation, cfg["controller"])
            guard.after_control()
            position = observation.tip_position
            angle = float(np.arccos(np.clip(
                (np.trace(observation.tip_rotation.T @ scene.target_rotation) - 1) / 2, -1, 1)))
            sample = CableSample(
                job_time + servo_every * dt, servo_every * dt,
                float(np.linalg.norm(position - observation.seated_position)), angle,
                float((position - initial_tip) @ axis), float((target - initial_tip) @ axis),
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
            if previous_witness is None and job.first_witness_s is not None:
                record_event("first_witness")
            if getattr(controller, "terminal", False) and job.status == "active":
                job.fail("controller_" + phase)
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
    if job.status == "active" and settled:
        job.fail("deadline")
    mujoco.mj_forward(scene.model, scene.data)
    phase = "terminal"
    record_event("terminal")
    render(scene, directory, "final")
    terminal_state = clip_state(scene)
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
        terminal_qpos=data.qpos.copy(), terminal_qvel=data.qvel.copy(), terminal_ctrl=data.ctrl.copy(),
        terminal_centerline=cable_centerline(scene),
    )
    wall = time.monotonic() - started
    outcome = {
        "case": case, "controller": case["controller"], "status": "completed",
        "job": job.report(), "settled": settled, "settle_reason": settle_reason,
        "terminal_clip_retained": terminal_state["has_retained_passage"],
        "terminal_clip_margin_m": clip_margin(scene, terminal_state, cable_centerline(scene)),
        "repairs_started": getattr(controller, "repairs_started", 0),
        "repair_log": getattr(controller, "repair_log", []),
        "retries_started": getattr(controller, "retries", 0),
        "witness_macro": witness_macro, "last_phase": phase,
        "precontact_bias_world_n": bias.tolist(), "peak_loads": peaks,
        "mutation_guard": guard.report(),
        "compiled_cable_mass_kg": scene.report["compiled_cable_mass_kg"],
        "routed_direct_length_m": scene.report["cable"]["direct_length_m"],
        "geometric_service_loop_m": scene.report["cable"]["rest_length_m"] - scene.report["cable"]["direct_length_m"],
        "max_initial_turn_deg": scene.report["cable"]["max_initial_turn_deg"],
        "clocks": cfg["clocks"], "force_protocol": cfg["force_protocol"]["authoritative_stream"],
        "accounting": {"native_steps": steps, "settle_native_steps": settle_steps,
                       "servo_ticks": servo_rows, "model_compilations": 2,
                       "build_seconds": build_seconds, "wall_seconds": wall,
                       "native_steps_per_second": (steps + settle_steps) / max(wall - build_seconds, 1e-9)},
        "scope": [
            "Held, clip-preserving seating before gripper release. No latch, release, electrical function or hardware claim.",
            "Fixed preset grasp and world-fixed fixture are disclosed construction boundaries.",
            "All arms receive the identical declared observation and action authority; this is not camera perception.",
            "Raw sensor norms include dynamic and gravity load; contact sums are witnesses, not net forces.",
        ],
    }
    write(directory / "result.json", outcome)
    print(json.dumps({"case": case["id"], "controller": case["controller"], "status": job.status,
                      "reason": job.failure_reason, "witness": job.witness_type,
                      "clip": terminal_state["has_retained_passage"], "steps": steps}), flush=True)
    return outcome


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


def _worker(item):
    return guarded_case(*item)


def guarded_case(cfg, case, directory: Path) -> dict:
    """Run one request, preserving an infeasible construction as a failed request."""
    try:
        return run_case(cfg, case, directory)
    except (ValueError, KeyError) as exc:
        directory.mkdir(parents=True, exist_ok=True)
        outcome = {"case": case, "controller": case["controller"], "status": "completed",
                   "job": {"status": "failed", "failure_reason": "construction_infeasible",
                           "elapsed_s": 0.0, "dwell_s": 0.0, "first_witness_s": None,
                           "witness_type": None, "samples": 0},
                   "settled": False, "settle_reason": "construction_infeasible",
                   "construction_error": f"{type(exc).__name__}: {exc}",
                   "terminal_clip_retained": False, "terminal_clip_margin_m": 0.0,
                   "repairs_started": 0, "repair_log": [], "retries_started": 0,
                   "witness_macro": None, "last_phase": "construction",
                   "accounting": {"native_steps": 0, "settle_native_steps": 0, "servo_ticks": 0,
                                  "model_compilations": 0, "build_seconds": 0.0, "wall_seconds": 0.0,
                                  "native_steps_per_second": 0.0},
                   "scope": ["Infeasible construction retained in the all-request denominator."]}
        write(directory / "result.json", outcome)
        print(json.dumps({"case": case["id"], "controller": case["controller"], "status": "failed",
                          "reason": "construction_infeasible", "detail": str(exc)}), flush=True)
        return outcome


if __name__ == "__main__":
    raise SystemExit(main())
