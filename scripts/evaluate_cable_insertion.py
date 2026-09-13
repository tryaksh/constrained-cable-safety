"""Controlled native SC insertion baseline, with all-request job accounting.

This measures seating under a fixed preset grasp and a free distal cable. It is
not official AIC scoring, released connector retention, or a cable-snag study.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import mujoco
import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_control import (  # noqa:E402
    CableControllerConfig,
    CableInsertionController,
    CableObservation,
)
from assembly_recovery.cable_jobs import CableJob, CableJobLimits, CableSample  # noqa:E402
from assembly_recovery.cable_robot import apply_cartesian_impedance, build_scene, measure_contacts  # noqa:E402
from scripts.probe_cable_robot import render  # noqa:E402


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


def wrist_world(scene):
    sensor = scene.model.sensor("AtiForceTorqueSensor_force")
    rotation = scene.data.site_xmat[sensor.objid[0]].reshape(3, 3)
    return rotation @ scene.data.sensor("AtiForceTorqueSensor_force").data.copy()


def solve_step(scene, target, cfg):
    apply_cartesian_impedance(scene, target, scene.target_rotation, cfg)
    mujoco.mj_step(scene.model, scene.data)
    solved = measure_contacts(scene)
    mujoco.mj_forward(scene.model, scene.data)
    refreshed = measure_contacts(scene)
    return {k: max(solved[k], refreshed[k]) for k in solved}, solved, refreshed


def run_case(cfg, case, controller_name, directory):
    directory.mkdir()
    started = time.monotonic()
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    scene_cfg = json.loads(json.dumps(cfg["scene"]))
    scene_cfg["cable"]["initial_outward_world_xy"] = case["outward_xy"]
    scene = build_scene(ROOT, scene_cfg, case, directory)
    write(directory / "adaptation.json", scene.report)
    data = scene.data
    dt = case["dt"]
    steps = 0
    init_steps = 0
    rows = []
    states = []
    velocities = []
    controls = []
    native = []
    bias_samples = []
    init_valid = True
    init_reason = None
    init_contact = 0.0
    init_tracking = 0.0
    tracking_samples = 0
    peaks = {k: 0.0 for k in measure_contacts(scene)}
    for i in range(round(scene_cfg["initialization_seconds"] / dt)):
        loads, solved, refreshed = solve_step(scene, scene.initial_tip, scene_cfg["controller"])
        steps += 1
        init_steps += 1
        native.append([float(data.time), *[solved[k] for k in peaks], *[refreshed[k] for k in peaks]])
        for k in peaks:
            peaks[k] = max(peaks[k], loads[k])
        if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all() or np.any(data.warning.number):
            init_valid = False
            init_reason = "nonfinite_initialization"
            break
        if (
            loads["raw_wrist_load_n"] > cfg["job_limits"]["wrist_force_n"]
            or loads["raw_plug_load_n"] > cfg["job_limits"]["plug_force_n"]
        ):
            init_valid = False
            init_reason = "initialization_force_abort"
            break
        init_contact = max(init_contact, loads["plug_port_contact_n"])
        if (i + 1) * dt > scene_cfg["initialization_seconds"] - 0.5:
            bias_samples.append(wrist_world(scene))
            tracking_samples += 1
            init_tracking = max(
                init_tracking, float(np.linalg.norm(data.site_xpos[scene.tip_site] - scene.initial_tip))
            )
        if steps % 1000 == 0:
            write(directory / "progress.json", {"native_steps": steps, "initialization_native_steps": init_steps})
    if tracking_samples == 0 or init_contact > 0.001 or init_tracking > 0.002:
        init_valid = False
        init_reason = init_reason or "initialization_validation_failed"
    bias = np.mean(bias_samples, axis=0) if bias_samples else np.zeros(3)
    job = CableJob(CableJobLimits(**cfg["job_limits"]))
    controller = CableInsertionController(CableControllerConfig(**cfg["force_guided_controller"]))
    if not init_valid:
        job.fail(init_reason)
    phases = []
    last_command = None
    retries = 0
    phase = "initialization"
    control_every = round(1 / cfg["policy_hz"] / dt)
    render(scene, directory, "initial")
    for i in range(round(cfg["job_limits"]["deadline_s"] / dt)) if init_valid else []:
        t = i * dt
        position = data.site_xpos[scene.tip_site].copy()
        if controller_name == "scripted_force_guided_retry":
            if i % control_every == 0:
                observation = CableObservation(
                    t, position, data.site_xpos[scene.port_site].copy(), scene.insertion_axis, wrist_world(scene), bias
                )
                last_command = controller.step(observation)
                retries = last_command.retries_started
                phase = last_command.phase
                if last_command.terminal:
                    job.fail("controller_" + phase)
                    break
            target = np.asarray(last_command.target_tip_position)
        elif controller_name == "scripted_continuation":
            target = scene.initial_tip + scene.insertion_axis * min(
                t * cfg["force_guided_controller"]["speed_m_per_s"], scene_cfg["initial_distance_m"] + 0.0003
            )
            phase = "continued_insertion"
        else:
            raise ValueError(controller_name)
        loads, solved, refreshed = solve_step(scene, target, scene_cfg["controller"])
        steps += 1
        native.append([float(data.time), *[solved[k] for k in peaks], *[refreshed[k] for k in peaks]])
        for k in peaks:
            peaks[k] = max(peaks[k], loads[k])
        if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all() or np.any(data.warning.number):
            job.fail("nonfinite_dynamics")
            break
        position = data.site_xpos[scene.tip_site].copy()
        port = data.site_xpos[scene.port_site]
        angle = float(
            np.arccos(
                np.clip(
                    (np.trace(data.site_xmat[scene.tip_site].reshape(3, 3).T @ scene.target_rotation) - 1) / 2, -1, 1
                )
            )
        )
        sample = CableSample(
            (i + 1) * dt,
            dt,
            float(np.linalg.norm(position - port)),
            angle,
            float((position - scene.initial_tip) @ scene.insertion_axis),
            float((target - scene.initial_tip) @ scene.insertion_axis),
            loads["raw_wrist_load_n"],
            loads["raw_plug_load_n"],
            0.0,
            loads["plug_port_contact_n"],
            0.0,
            True,
            True,
            loads["port_detector_contact_n"] > 0.05,
        )
        job.update(sample)
        if i % max(1, round(0.01 / dt)) == 0 or job.status != "active":
            rows.append([sample.time_s, *position, *target, sample.seating_error_m, angle, *[loads[k] for k in peaks]])
            states.append(data.qpos.copy())
            velocities.append(data.qvel.copy())
            controls.append(data.ctrl.copy())
            phases.append(phase)
        if steps % 1000 == 0:
            peak_rss = max(peak_rss, process.memory_info().rss)
            write(directory / "progress.json", {"native_steps": steps, "initialization_native_steps": init_steps})
        if job.status != "active":
            break
    if job.status == "active":
        job.fail("deadline")
    render(scene, directory, "final")
    np.savez_compressed(
        directory / "trajectory.npz",
        samples=np.asarray(rows),
        qpos=np.asarray(states),
        qvel=np.asarray(velocities),
        ctrl=np.asarray(controls),
        phases=np.asarray(phases),
        native_forces=np.asarray(native),
        native_force_keys=np.asarray(list(peaks)),
        terminal_qpos=data.qpos.copy(),
        terminal_qvel=data.qvel.copy(),
        terminal_ctrl=data.ctrl.copy(),
    )
    outcome = {
        "case": case,
        "controller": controller_name,
        "status": "completed",
        "job": job.report(),
        "initialization_valid": init_valid,
        "initialization_reason": init_reason,
        "initial_tracking_error_m": init_tracking,
        "tracking_samples": tracking_samples,
        "precontact_bias_world_n": bias.tolist(),
        "retries_started": retries,
        "last_phase": phase,
        "peak_loads_all_phases": peaks,
        "native_steps": steps,
        "initialization_native_steps": init_steps,
        "poststep_forward_calls": steps,
        "resources": {
            "wall_seconds": time.monotonic() - started,
            "peak_rss_sampled_bytes": peak_rss,
            "native_steps_per_second": steps / (time.monotonic() - started),
        },
        "scope": [
            "Seating with verified detector contact and dwell under an immutable preset grasp; no release or latch retention demonstrated.",
            "Free distal cable, no earlier clip/connection or optional post. Not the requested cable-snag factorial.",
            "Full simulated robot/plug/port pose and exact-model bias feedforward; no camera perception.",
            "Both controllers receive identical observations and action authority. Continuation is a weak diagnostic comparator; the force-guided controller is the practical baseline.",
            "No controller-specific resets, state writes, attachment changes, learned weights or final-test seeds.",
        ],
    }
    write(directory / "progress.json", {"native_steps": steps, "initialization_native_steps": init_steps})
    write(directory / "result.json", outcome)
    print(
        json.dumps({"case": case["id"], "controller": controller_name, "job": job.report(), "native_steps": steps}),
        flush=True,
    )
    return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--case")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    cases = [c for c in cfg["cases"] if not args.case or c["id"] == args.case]
    if not cases:
        parser.error("No selected cases")
    outcomes = []
    for case in cases:
        for method in cfg["controllers"]:
            outcomes.append(run_case(cfg, case, method, args.run_dir / (case["id"] + "__" + method)))
            finished = len(outcomes) == len(cases) * len(cfg["controllers"])
            write(
                args.run_dir / "result.json",
                {
                    "status": "completed" if finished else "running",
                    "scope": cfg["scope"],
                    "cases": outcomes,
                    "expected_requests": len(cases) * len(cfg["controllers"]),
                    "accounting": {
                        "native_steps": sum(r["native_steps"] for r in outcomes),
                        "initialization_native_steps": sum(r["initialization_native_steps"] for r in outcomes),
                    },
                    "training_runs": 0,
                },
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
