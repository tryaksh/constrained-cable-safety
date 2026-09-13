"""Isolated force-driven seating followed by prescribed net axial extraction.

The plug is constrained by one fixed-axis slide throughout every trial. This
isolates axial resistance in the public rigid SC geometry; it is not free-body
retention, a robot baseline, a latch model, or a hardware test. No job pose,
attachment, or constraint is changed after initialization.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from assembly_recovery.cable_assets import Pose, import_sdf_model  # noqa: E402


def fmt(values):
    return " ".join(format(float(value), ".17g") for value in values)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def make_scene(cfg, directory):
    root = ET.Element("mujoco", model="isolated_sc_axial_retention")
    ET.SubElement(root, "compiler", angle="radian", autolimits="true")
    ET.SubElement(root, "option", timestep=str(cfg["dt"]), gravity=fmt(cfg["gravity_m_per_s2"]),
                  integrator="implicitfast", solver="Newton", iterations="100", tolerance="1e-10", cone="elliptic")
    defaults = ET.SubElement(root, "default")
    ET.SubElement(defaults, "geom", solref="0.004 1", solimp="0.95 0.99 0.001", friction="0.5 0.005 0.0001")
    visual = ET.SubElement(root, "visual")
    ET.SubElement(visual, "global", offwidth="900", offheight="700")
    ET.SubElement(visual, "headlight", ambient=".35 .35 .35", diffuse=".8 .8 .8")
    assets = ET.SubElement(root, "asset")
    world = ET.SubElement(root, "worldbody")
    models = ROOT/".deps/aic/aic_assets/models"
    port = import_sdf_model(models/"SC Port/model.sdf", "port", visual_directory=directory/"meshes")
    plug = import_sdf_model(models/"SC Plug/model.sdf", "plug", visual_directory=directory/"meshes")
    assets.extend(port.assets+plug.assets)
    port_pose = Pose((0, 0, .15), (math.sqrt(.5), math.sqrt(.5), 0, 0))
    port.body.attrib.update(port_pose.attributes())
    target_tip = port_pose.compose(port.frames["sc_port_base_link"])
    seated_plug = target_tip.compose(plug.frames["sc_tip_link"].inverse())
    withdrawal_axis = -np.asarray(target_tip.rotate((0, 0, 1)))
    initial_position = np.asarray(seated_plug.position)+withdrawal_axis*cfg["initial_tip_distance_m"]
    initial_pose = Pose(tuple(initial_position), seated_plug.quaternion)
    plug.body.attrib.update(initial_pose.attributes())
    local_slide_axis = initial_pose.inverse().rotate(withdrawal_axis)
    ET.SubElement(plug.body, "joint", name="axial_slide", type="slide", axis=fmt(local_slide_axis), damping="0", frictionloss="0")
    world.extend([port.body, plug.body])
    actuator = ET.SubElement(root, "actuator")
    limit = cfg["motor_force_limit_n"]
    ET.SubElement(actuator, "motor", name="axial_motor", joint="axial_slide", ctrllimited="true", ctrlrange=f"{-limit} {limit}")
    sensors = ET.SubElement(root, "sensor")
    ET.SubElement(sensors, "actuatorfrc", name="applied_motor_force", actuator="axial_motor")
    path = directory/"scene.xml"
    ET.indent(root)
    path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    model = mujoco.MjModel.from_xml_path(str(path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    mass = float(model.body_mass[model.body("plug").id])
    gravity_projection = mass*float(np.dot(model.opt.gravity, withdrawal_axis))
    report = {"plug": plug.report, "port": port.report,
              "fixture": "One unchanging axial slide; rotation and lateral translation constrained; no grasp or latch attachment",
              "positive_axis_world": withdrawal_axis.tolist(), "plug_mass_kg": mass,
              "gravity_force_along_positive_axis_n": gravity_projection,
              "gravity_compensation_actuator_n": -gravity_projection,
              "initial_tip_distance_m": cfg["initial_tip_distance_m"], "no_force_attraction_or_latch": True,
              "joint_damping_and_frictionloss": 0.0, "contact_geometry_omissions": 0}
    return model, data, withdrawal_axis, gravity_projection, report


def measure_contact(model, data, withdrawal_axis):
    force_sum = detector_sum = 0.0
    resultant = np.zeros(3)
    pairs = []
    for index, contact in enumerate(data.contact):
        names = [model.geom(int(geom)).name or "" for geom in (contact.geom1, contact.geom2)]
        if not (any(name.startswith("plug__") for name in names) and any(name.startswith("port__") for name in names)):
            continue
        wrench = np.zeros(6)
        mujoco.mj_contactForce(model, data, index, wrench)
        force = float(np.linalg.norm(wrench[:3]))
        force_sum += force
        if any("contact_collision" in name for name in names):
            detector_sum += force
        # MuJoCo's contact normal points from geom1 to geom2. Positive local
        # force acts on geom2; use the corresponding sign for the plug resultant.
        sign = 1 if names[1].startswith("plug__") else -1
        resultant += sign*contact.frame.reshape(3, 3).T@wrench[:3]
        if force > 1e-6:
            pairs.append({"geom1": names[0], "geom2": names[1], "force_n": force, "distance_m": float(contact.dist)})
    return {"contact_force_sum_n": force_sum, "detector_force_sum_n": detector_sum,
            "contact_resultant_norm_n": float(np.linalg.norm(resultant)),
            "contact_axial_on_plug_n": float(resultant@withdrawal_axis), "pairs": pairs}


def render(model, data, directory, name):
    try:
        from PIL import Image

        renderer = mujoco.Renderer(model, width=900, height=700)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = data.site("port__frame__sc_port_base_link").xpos
        camera.distance = .15
        camera.azimuth = 135
        camera.elevation = -20
        renderer.update_scene(data, camera=camera)
        Image.fromarray(renderer.render()).save(directory/f"{name}.png")
        renderer.close()
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def run_case(cfg, case, directory):
    import psutil

    started = time.monotonic()
    directory.mkdir()
    model, data, axis, gravity_force, adaptation = make_scene(cfg, directory)
    joint = model.joint("axial_slide")
    dof, qaddr = int(joint.dofadr[0]), int(joint.qposadr[0])
    tip_id = model.site("plug__frame__sc_tip_link").id
    target_id = model.site("port__frame__sc_port_base_link").id
    dt = cfg["dt"]
    approach_steps = round(cfg["approach_seconds"]/dt)
    load_steps = round(cfg["load_seconds"]/dt)
    total_steps = approach_steps+load_steps
    acceptance = cfg["acceptance"]
    initial_contact = measure_contact(model, data, axis)
    initial_clear = initial_contact["contact_force_sum_n"] <= acceptance["initial_contact_tolerance_n"]
    steps = approach_executed = load_executed = 0
    dwell = 0.0
    seated_during_approach = False
    load_started_seated = False
    finite = True
    aborted = lost_seating = escaped = False
    first_loss_s = first_contact_s = None
    start_load_tip = None
    peaks = {phase: {"native_contact_n": 0.0, "forward_contact_n": 0.0, "native_detector_n": 0.0,
                      "forward_detector_n": 0.0} for phase in ["approach", "extraction_load"]}
    native_peak_pairs = {phase: [] for phase in peaks}
    minimum_error = float("inf")
    rows = []
    images = [render(model, data, directory, "initial")]
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    min_ram = psutil.virtual_memory().available
    write(directory/"progress.json", {"native_steps": 0})
    native_sensor_vector = data.sensordata.copy()
    terminal_native = initial_contact
    for index in range(total_steps):
        phase = "approach" if index < approach_steps else "extraction_load"
        if index == approach_steps:
            current_error = float(np.linalg.norm(data.site_xpos[tip_id]-data.site_xpos[target_id]))
            load_started_seated = seated_during_approach and current_error <= acceptance["seating_position_tolerance_m"]
            if not (load_started_seated and initial_clear and peaks["approach"]["native_contact_n"] > acceptance["positive_contact_threshold_n"]):
                break
            start_load_tip = data.site_xpos[tip_id].copy()
            images.append(render(model, data, directory, "load_start"))
        if phase == "approach":
            net_command = -cfg["net_insertion_force_n"]-cfg["approach_velocity_damping_ns_per_m"]*float(data.qvel[dof])
            net_command = float(np.clip(net_command, -cfg["net_insertion_force_n"], cfg["net_insertion_force_n"]))
        else:
            net_command = case["net_extraction_load_n"]
        actuator_force = net_command-gravity_force
        if abs(actuator_force) > cfg["motor_force_limit_n"]:
            raise ValueError("Registered net force exceeds the actual motor limit after gravity compensation")
        data.ctrl[0] = actuator_force
        native_time = float(data.time)
        mujoco.mj_step(model, data)
        steps += 1
        approach_executed += int(phase == "approach")
        load_executed += int(phase == "extraction_load")
        terminal_native = measure_contact(model, data, axis)
        native_sensor_vector = data.sensordata.copy()
        native_acceleration = float(data.qacc[dof])
        mujoco.mj_forward(model, data)
        forward = measure_contact(model, data, axis)
        finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all() and not np.any(data.warning.number))
        if not finite:
            break
        native_force, forward_force = terminal_native["contact_force_sum_n"], forward["contact_force_sum_n"]
        if native_force > peaks[phase]["native_contact_n"]:
            native_peak_pairs[phase] = terminal_native["pairs"]
        for key, value in [("native_contact_n", native_force), ("forward_contact_n", forward_force),
                           ("native_detector_n", terminal_native["detector_force_sum_n"]),
                           ("forward_detector_n", forward["detector_force_sum_n"])]:
            peaks[phase][key] = max(peaks[phase][key], value)
        if max(native_force, forward_force) > acceptance["positive_contact_threshold_n"] and first_contact_s is None:
            first_contact_s = native_time
        tip = data.site_xpos[tip_id]
        error = float(np.linalg.norm(tip-data.site_xpos[target_id]))
        axial_error = float((tip-data.site_xpos[target_id])@axis)
        rotation = data.site_xmat[tip_id].reshape(3, 3)
        target_rotation = data.site_xmat[target_id].reshape(3, 3)
        angle = float(np.arccos(np.clip((np.trace(rotation.T@target_rotation)-1)/2, -1, 1)))
        minimum_error = min(minimum_error, error)
        seated = error <= acceptance["seating_position_tolerance_m"] and angle <= acceptance["seating_orientation_tolerance_rad"]
        if phase == "approach":
            dwell = dwell+dt if seated else 0.0
            seated_during_approach |= dwell >= acceptance["seating_dwell_s"]
        elif not seated:
            lost_seating = True
            if first_loss_s is None:
                first_loss_s = float(data.time)-cfg["approach_seconds"]
        extraction = float((tip-start_load_tip)@axis) if start_load_tip is not None else 0.0
        rows.append([native_time, float(data.time), 0 if phase == "approach" else 1, net_command,
                     actuator_force, gravity_force, float(data.actuator_force[0]), native_force, forward_force,
                     terminal_native["contact_resultant_norm_n"], forward["contact_resultant_norm_n"],
                     terminal_native["contact_axial_on_plug_n"], forward["contact_axial_on_plug_n"],
                     error, axial_error, angle, extraction, float(data.qpos[qaddr]), float(data.qvel[dof]), native_acceleration])
        if steps % 1000 == 0:
            peak_rss = max(peak_rss, process.memory_info().rss)
            min_ram = min(min_ram, psutil.virtual_memory().available)
            write(directory/"progress.json", {"native_steps": steps, "approach_native_steps": approach_executed,
                                               "load_native_steps": load_executed})
        if max(native_force, forward_force) > acceptance["raw_contact_abort_n"]:
            aborted = True
            break
        if phase == "extraction_load" and extraction >= acceptance["early_extraction_stop_m"]:
            escaped = True
            break
    load_assessable = bool(initial_clear and load_started_seated and load_executed > 0 and finite)
    retained = bool(load_assessable and load_executed == load_steps and not lost_seating and not aborted)
    final_error = float(np.linalg.norm(data.site_xpos[tip_id]-data.site_xpos[target_id]))
    images.append(render(model, data, directory, "final"))
    np.savez_compressed(directory/"samples.npz", samples=np.asarray(rows), columns=np.array([
        "native_time_s", "forward_time_s", "phase_0_approach_1_load", "declared_net_force_n", "motor_command_n",
        "gravity_axis_force_n", "measured_actuator_force_n", "native_contact_sum_n", "forward_contact_sum_n",
        "native_contact_resultant_n", "forward_contact_resultant_n", "native_contact_axial_on_plug_n",
        "forward_contact_axial_on_plug_n", "tip_error_m", "tip_axial_error_m", "tip_angle_rad",
        "extraction_since_load_start_m", "qpos_m", "qvel_m_per_s", "native_qacc_m_per_s2"]))
    np.savez_compressed(directory/"terminal_state.npz", time_s=data.time, qpos=data.qpos.copy(), qvel=data.qvel.copy(),
                        ctrl=data.ctrl.copy(), native_sensors=native_sensor_vector, forward_sensors=data.sensordata.copy())
    result = {"case": case, "status": "completed" if finite else "failed", "finite_dynamics": finite,
              "controller": "isolated_axial_force_fixture_then_constant_net_extraction",
              "attempt_outcome": "force_abort" if aborted else "retention_unassessable" if not load_assessable else "retained_in_axial_fixture" if retained else "lost_seating_under_load",
              "retention_assessable": load_assessable, "retained_in_axial_fixture": retained,
              "seated_before_load": load_started_seated, "seating_dwell_reached": seated_during_approach,
              "initial_contact_clear": initial_clear, "first_contact_s": first_contact_s,
              "first_loss_after_load_s": first_loss_s, "lost_seating": lost_seating, "early_extraction_stop": escaped,
              "minimum_tip_error_m": minimum_error, "final_tip_error_m": final_error,
              "raw_contact_abort": aborted, "phase_peaks": peaks, "native_peak_contact_pairs": native_peak_pairs,
              "terminal_native_contact": terminal_native, "native_steps": steps, "initialization_native_steps": 0,
              "approach_native_steps": approach_executed, "load_native_steps": load_executed,
              "poststep_forward_calls": steps, "elapsed_s": time.monotonic()-started,
              "resources": {"peak_process_rss_bytes_sampled": peak_rss, "minimum_machine_available_ram_bytes_sampled": min_ram,
                  "native_steps_per_second_including_build_render": steps/(time.monotonic()-started), "physics_device": "CPU"},
              "adaptation": adaptation, "render_errors": [error for error in images if error],
              "physical_latch_claimed": False, "free_body_retention_claimed": False, "official_aic_score": False,
              "limitations": ["One-axis fixture suppresses lateral and rotational escape throughout the trial.",
                  "Exact rigid source collisions lack an articulated elastic latch; no latch force or attachment is added.",
                  "Zero-net-load persistence alone is not mechanical retention; gravity compensation is stated explicitly.",
                  "Initial pose is already aligned2mm above seating; this is a retention diagnostic, not a full insertion baseline."]}
    write(directory/"result.json", result)
    write(directory/"progress.json", {"native_steps": steps, "approach_native_steps": approach_executed, "load_native_steps": load_executed})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--case")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    selected = [case for case in cfg["cases"] if not args.case or case["id"] == args.case]
    if not selected:
        parser.error("No selected case")
    results = []
    started = time.monotonic()
    for case in selected:
        result = run_case(cfg, case, args.run_dir/case["id"])
        results.append(result)
        write(args.run_dir/"result.json", {"status": ("completed" if all(r["finite_dynamics"] for r in results) else "failed") if len(results) == len(selected) else "running",
            "scope": cfg["scope"], "cases": results, "expected_case_ids": [c["id"] for c in selected],
            "accounting": {"native_steps": sum(r["native_steps"] for r in results), "initialization_native_steps": 0,
                "approach_native_steps": sum(r["approach_native_steps"] for r in results), "load_native_steps": sum(r["load_native_steps"] for r in results)},
            "elapsed_s": time.monotonic()-started})
        print(json.dumps({key: result[key] for key in ["case", "attempt_outcome", "seated_before_load", "first_loss_after_load_s", "native_steps"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
