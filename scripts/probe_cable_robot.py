"""Bounded native UR5e scripted torque-control insertion diagnostic worker."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from assembly_recovery.cable_robot import (  # noqa: E402
    apply_cartesian_impedance,
    build_scene,
    measure_contacts,
)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def render(scene, directory, name):
    try:
        from PIL import Image

        renderer = mujoco.Renderer(scene.model, width=1000, height=800)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = scene.initial_tip
        camera.distance = 1.4
        camera.azimuth = 135
        camera.elevation = -20
        options = mujoco.MjvOption()
        options.geomgroup[3] = 1
        renderer.update_scene(scene.data, camera=camera, scene_option=options)
        Image.fromarray(renderer.render()).save(directory/f"{name}.png")
        renderer.close()
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def contact_details(scene):
    result = []
    for index, contact in enumerate(scene.data.contact):
        wrench = np.zeros(6)
        mujoco.mj_contactForce(scene.model, scene.data, index, wrench)
        magnitude = float(np.linalg.norm(wrench[:3]))
        if magnitude > 1e-6:
            result.append({"geom1": scene.model.geom(int(contact.geom1)).name,
                           "geom2": scene.model.geom(int(contact.geom2)).name,
                           "force_n": magnitude, "distance_m": float(contact.dist)})
    return result


def run_case(cfg, case, directory):
    import psutil

    case_started = time.monotonic()
    process = psutil.Process()
    minimum_available_ram = psutil.virtual_memory().available
    peak_rss = process.memory_info().rss
    directory.mkdir()
    scene = build_scene(ROOT, cfg, case, directory)
    model, data = scene.model, scene.data
    render_errors = [render(scene, directory, "initial")]
    peak_rss = max(peak_rss, process.memory_info().rss)
    minimum_available_ram = min(minimum_available_ram, psutil.virtual_memory().available)
    write(directory/"adaptation.json", scene.report)
    init_seconds = cfg["initialization_seconds"]
    attempt_end = init_seconds+cfg["attempt_seconds"]
    deadline = attempt_end+cfg["retract_seconds"]
    acceptance = cfg["acceptance"]
    peaks = {key: 0.0 for key in measure_contacts(scene)}
    native_peaks = dict(peaks)
    forward_peaks = dict(peaks)
    cable_max_displacement = 0.0
    phase_other_contact_peaks = {}
    phase_peaks = {phase: dict(peaks) for phase in ["initialization", "insertion", "retraction"]}
    rows, states, velocities, controls, force_stream = [], [], [], [], []
    initial_tracking_samples = 0
    steps = init_steps = contact_steps = saturation_steps = 0
    dwell = 0.0
    success = aborted = False
    finite = True
    max_angle = initial_tracking = initial_contact = 0.0
    min_error = float("inf")
    first_contact = seating_time = None
    dt = case["dt"]
    report_period = max(1, round(.01/dt))
    start = time.monotonic()
    write(directory/"progress.json", {"native_steps": 0, "initialization_native_steps": 0})
    for index in range(round(deadline/dt)):
        t = index*dt
        phase = "initialization" if t < init_seconds else "insertion" if t < attempt_end else "retraction"
        distance = 0.0
        if phase != "initialization":
            distance = min((t-init_seconds)*cfg["approach_speed_m_per_s"], cfg["initial_distance_m"]+.001)
        if phase == "retraction":
            distance -= min((t-attempt_end)*cfg["retract_speed_m_per_s"], cfg["initial_distance_m"]+.001)
        target = scene.initial_tip+scene.insertion_axis*distance
        control = apply_cartesian_impedance(scene, target, scene.target_rotation, cfg["controller"])
        saturation_steps += int(control["joint_torque_saturated"])
        mujoco.mj_step(model, data)
        steps += 1
        init_steps += int(phase == "initialization")
        native_loads = measure_contacts(scene)
        native_sensor_vector = data.sensordata.copy()
        native_contact_details = contact_details(scene) if native_loads["other_contact_n"] > phase_peaks[phase]["other_contact_n"] else None
        # Refresh kinematics/contact/force at the integrated right endpoint; no
        # state writing or extra integration. These calls are counted separately.
        mujoco.mj_forward(model, data)
        if steps % 1000 == 0:
            peak_rss = max(peak_rss, process.memory_info().rss)
            minimum_available_ram = min(minimum_available_ram, psutil.virtual_memory().available)
            write(directory/"progress.json", {"native_steps": steps, "initialization_native_steps": init_steps,
                                               "poststep_forward_calls": steps})
        finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all() and not np.any(data.warning.number))
        if not finite:
            break
        forward_loads = measure_contacts(scene)
        loads = {key: max(native_loads[key], forward_loads[key]) for key in native_loads}
        force_stream.append([t, float(data.time), *native_loads.values(), *forward_loads.values()])
        if loads["other_contact_n"] > phase_peaks[phase]["other_contact_n"]:
            native_wins = native_loads["other_contact_n"] >= forward_loads["other_contact_n"]
            phase_other_contact_peaks[phase] = {"time_s": t if native_wins else float(data.time),
                "sample": "native_solve" if native_wins else "postforward",
                "pairs": native_contact_details if native_wins else contact_details(scene)}
        for key in loads:
            native_peaks[key] = max(native_peaks[key], native_loads[key])
            forward_peaks[key] = max(forward_peaks[key], forward_loads[key])
        if len(scene.cable_bodies):
            cable_max_displacement = max(cable_max_displacement, float(np.max(np.linalg.norm(
                data.xpos[scene.cable_bodies]-scene.initial_cable_positions, axis=1))))
        for key, value in loads.items():
            peaks[key] = max(peaks[key], value)
            phase_peaks[phase][key] = max(phase_peaks[phase][key], value)
        if loads["plug_port_contact_n"] > .05:
            contact_steps += 1
            if first_contact is None:
                first_contact = float(data.time)
        position = data.site_xpos[scene.tip_site]
        error = float(np.linalg.norm(position-data.site_xpos[scene.port_site]))
        rotation = data.site_xmat[scene.tip_site].reshape(3, 3)
        angle = float(np.arccos(np.clip((np.trace(rotation.T@scene.target_rotation)-1)/2, -1, 1)))
        max_angle = max(max_angle, angle)
        min_error = min(min_error, error)
        if phase == "initialization":
            initial_contact = max(initial_contact, loads["plug_port_contact_n"])
            if t > init_seconds-.5:
                initial_tracking_samples += 1
                initial_tracking = max(initial_tracking, float(np.linalg.norm(position-target)))
        seated = (error < acceptance["position_tolerance_m"] and angle < acceptance["orientation_tolerance_rad"])
        dwell = dwell+dt if seated and phase == "insertion" else 0.0
        if dwell >= acceptance["dwell_s"] and not success:
            success = True
            seating_time = float(data.time)
            render_errors.append(render(scene, directory, "seated"))
        if index % report_period == 0:
            rows.append([float(data.time), *position.tolist(), *target.tolist(), error, angle, *native_loads.values(), *forward_loads.values()])
            states.append(data.qpos.copy())
            velocities.append(data.qvel.copy())
            controls.append(data.ctrl.copy())
        if loads["raw_wrist_load_n"] > acceptance["raw_wrist_load_abort_n"] or loads["raw_plug_load_n"] > acceptance["raw_plug_load_abort_n"]:
            aborted = True
            break
    final_error = float(np.linalg.norm(data.site_xpos[scene.tip_site]-data.site_xpos[scene.port_site]))
    cable_displacement = float(np.max(np.linalg.norm(data.xpos[scene.cable_bodies]-scene.initial_cable_positions, axis=1))) if len(scene.cable_bodies) else 0.0
    render_errors.append(render(scene, directory, "final"))
    np.savez_compressed(directory/"trajectory.npz", samples=np.array(rows), qpos=np.array(states), qvel=np.array(velocities), ctrl=np.array(controls),
                        columns=np.array(["time_s", "tip_x", "tip_y", "tip_z", "target_x", "target_y", "target_z",
                                          "tip_error_m", "tip_angle_rad",
                                          *("native_"+key for key in peaks), *("forward_"+key for key in peaks)]))
    np.savez_compressed(directory/"native_force_stream.npz", samples=np.asarray(force_stream),
                        columns=np.array(["native_time_s", "forward_time_s",
                            *("native_"+key for key in peaks), *("forward_"+key for key in peaks)]))
    np.savez_compressed(directory/"terminal_state.npz", time_s=data.time, qpos=data.qpos.copy(),
                        qvel=data.qvel.copy(), ctrl=data.ctrl.copy(), native_sensors=native_sensor_vector,
                        postforward_sensors=data.sensordata.copy())
    result = {"case": case, "status": "completed" if finite else "failed", "controller": "scripted_native_ur5e_cartesian_impedance_with_model_bias_compensation",
              "finite_dynamics": finite, "raw_load_abort": aborted, "seating_dwell_reached": success,
              "valid_seating_attempt": success and not aborted and finite,
              "attempt_outcome": "force_abort" if aborted else "seating_dwell" if success else "no_seating",
              "native_robot_actuated": True, "is_learned_policy": False, "is_official_aic_score": False,
              "final_connection_claimed": False, "fixed_preset_grasp": True,
              "minimum_tip_error_m": min_error, "maximum_tip_angle_rad": max_angle,
              "final_seating_error_m": final_error, "initial_tracking_error_m": initial_tracking if initial_tracking_samples else None,
              "initial_tracking_samples": initial_tracking_samples,
              "initialization_completed": init_steps >= round(init_seconds/dt),
              "initial_contact_peak_n": initial_contact, "peak_loads": peaks, "phase_peak_loads": phase_peaks,
              "phase_other_contact_peak_pairs": phase_other_contact_peaks,
              "native_solve_peak_loads": native_peaks, "postforward_peak_loads": forward_peaks,
              "contact_native_steps": contact_steps, "first_contact_s": first_contact, "seating_time_s": seating_time,
              "joint_torque_saturation_steps": saturation_steps, "cable_max_displacement_m": cable_max_displacement,
              "cable_final_displacement_m": cable_displacement,
              "native_steps": steps, "initialization_native_steps": init_steps, "poststep_forward_calls": steps,
              "elapsed_s": time.monotonic()-start,
              "resources": {"case_wall_seconds_including_build_render": time.monotonic()-case_started,
                  "native_steps_per_second_including_build_render": steps/(time.monotonic()-case_started),
                  "peak_process_rss_bytes_sampled": peak_rss, "minimum_machine_available_ram_bytes_sampled": minimum_available_ram,
                  "dynamics_device": "CPU", "rendering_device": "MuJoCo OpenGL",
                  "sample_interval_native_steps": 1000, "cable_batch_capacity_claimed": False},
              "render_errors": [e for e in render_errors if e],
              "sample_convention": "Native solve loads sampled immediately after mj_step (left endpoint) and retained before mj_forward; refreshed right-endpoint loads stored separately. Aborts/peaks include both; trajectory pose/time at right endpoint.",
              "acceptance_checks": {"finite": finite, "initial_contact_free": initial_contact <= acceptance["initial_contact_tolerance_n"],
                  "initial_tracking": init_steps >= round(init_seconds/dt) and initial_tracking_samples > 0 and initial_tracking <= acceptance["tracking_tolerance_m"], "seated": success and not aborted,
                  "contact_positive": peaks["plug_port_contact_n"] > .05,
                  "retracted": success and not aborted and final_error >= acceptance["retraction_min_distance_m"]},
              "terminal_contact_pairs": [{"geom1": model.geom(int(c.geom1)).name, "geom2": model.geom(int(c.geom2)).name,
                  "penetration_m": min(0.0, float(c.dist))} for c in data.contact],
              "adaptation": scene.report,
              "limitations": ["Ideal fixed preset grasp cannot demonstrate pickup or grasp/drop reliability.",
                  "Fixture placed from initial FK; not a sampled official layout.", "Cable mechanical values are registered simulation parameters without hardware calibration.",
                  "Actuator force clamps do not certify contact force safety; native measured load abort remains separate."]}
    write(directory/"progress.json", {"native_steps": steps, "initialization_native_steps": init_steps, "poststep_forward_calls": steps})
    write(directory/"result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--case")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    selected = [case for case in cfg["cases"] if not args.case or args.case == case["id"]]
    if not selected:
        parser.error("No selected case")
    results = []
    start = time.monotonic()
    for case in selected:
        result = run_case(cfg, case, args.run_dir/case["id"])
        results.append(result)
        write(args.run_dir/"result.json", {"status": ("completed" if all(r["finite_dynamics"] for r in results) else "failed") if len(results) == len(selected) else "running",
            "scope": cfg["scope"], "cases": results, "expected_case_ids": [c["id"] for c in selected],
            "accounting": {"native_steps": sum(r["native_steps"] for r in results),
                           "initialization_native_steps": sum(r["initialization_native_steps"] for r in results)},
            "elapsed_s": time.monotonic()-start})
        print(json.dumps({key: result[key] for key in ["case", "attempt_outcome", "minimum_tip_error_m", "peak_loads", "native_steps"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
