"""Bounded SC geometry/contact diagnostics using a force-actuated test stage.

A Cartesian fixture isolates mating geometry before robot-controller development.
It is never labelled a robot policy, learned recovery, or official AIC evaluation.
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
sys.path.insert(0, str(ROOT / "src"))
from assembly_recovery.cable_assets import Pose, import_sdf_model  # noqa: E402


def fmt(values):
    return " ".join(f"{float(v):.12g}" for v in values)


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


def make_stage(cfg, case, directory):
    root = ET.Element("mujoco", model="aic_sc_contact_stage")
    ET.SubElement(root, "compiler", angle="radian", autolimits="true")
    ET.SubElement(
        root,
        "option",
        timestep=str(case["dt"]),
        integrator="implicitfast",
        solver="Newton",
        iterations="100",
        tolerance="1e-10",
        cone="elliptic",
    )
    vis = ET.SubElement(root, "visual")
    ET.SubElement(vis, "global", offwidth="1000", offheight="800")
    defaults = ET.SubElement(root, "default")
    ET.SubElement(defaults, "geom", solref="0.004 1", solimp="0.95 0.99 0.001", friction="0.5 0.005 0.0001")
    assets = ET.SubElement(root, "asset")
    world = ET.SubElement(root, "worldbody")
    ET.SubElement(world, "light", pos="0 -1 2", dir="0 0 -1", diffuse="0.8 0.8 0.8")
    ET.SubElement(world, "geom", name="floor", type="plane", size="2 2 0.1", pos="0 0 0", rgba="0.16 0.2 0.25 1")
    models = ROOT / ".deps/aic/aic_assets/models"
    port = import_sdf_model(models / "SC Port/model.sdf", "port", visual_directory=directory / "meshes")
    plug = import_sdf_model(models / "SC Plug/model.sdf", "plug", visual_directory=directory / "meshes")
    port_pose = Pose((0.0, 0.0, 0.16), (math.sqrt(0.5), math.sqrt(0.5), 0.0, 0.0))
    port.body.set("pos", fmt(port_pose.position))
    port.body.set("quat", fmt(port_pose.quaternion))
    world.append(port.body)
    for asset in port.assets + plug.assets:
        assets.append(asset)
    seated_tip = port_pose.compose(port.frames["sc_port_base_link"])
    seated_plug = seated_tip.compose(plug.frames["sc_tip_link"].inverse())
    initial = np.array(seated_plug.position) + np.array(
        [*case["offset_m"], cfg["diagnostic_stage"]["initial_distance_m"]]
    )
    stage = ET.SubElement(world, "body", name="stage", pos=fmt(initial))
    ET.SubElement(
        stage, "inertial", pos="0 0 0", mass=str(cfg["diagnostic_stage"]["mass_kg"]), diaginertia="0.0001 0.0001 0.0001"
    )
    for i, axis in enumerate(np.eye(3)):
        ET.SubElement(stage, "joint", name=f"stage_{i}", type="slide", axis=fmt(axis), damping="0")
    plug.body.set("pos", "0 0 0")
    plug.body.set("quat", fmt(seated_plug.quaternion))
    ET.SubElement(plug.body, "site", name="stage_load", pos="0 0 0", size="0.002")
    stage.append(plug.body)
    if case["with_cable"]:
        cable_cfg = cfg["cable"]
        ext = ET.SubElement(root, "extension")
        ET.SubElement(ext, "plugin", plugin="mujoco.elasticity.cable")
        # Cable starts at the back of the plug and initially extends horizontally.
        cable_pose = (
            Pose((0.0, 0.0, 0.0), seated_plug.quaternion)
            .inverse()
            .compose(Pose((0.0, 0.0, cable_cfg.get("attachment_back_m", 0.048)), (1.0, 0.0, 0.0, 0.0)))
        )
        cable_root = ET.SubElement(
            plug.body, "body", name="cable_origin", pos=fmt(cable_pose.position), quat=fmt(cable_pose.quaternion)
        )
        composite = ET.SubElement(
            cable_root,
            "composite",
            prefix="cable_",
            type="cable",
            curve="s",
            count=f"{cable_cfg['segments'] + 1} 1 1",
            size=str(cable_cfg["length_m"]),
            initial="ball",
        )
        plugin = ET.SubElement(composite, "plugin", plugin="mujoco.elasticity.cable")
        ET.SubElement(plugin, "config", key="twist", value=str(cable_cfg["twist_modulus_pa"]))
        ET.SubElement(plugin, "config", key="bend", value=str(cable_cfg["youngs_modulus_pa"]))
        ET.SubElement(composite, "joint", kind="main", damping=str(cable_cfg["joint_damping"]))
        density = cable_cfg["linear_density_kg_per_m"] / (math.pi * cable_cfg["radius_m"] ** 2)
        ET.SubElement(
            composite,
            "geom",
            type="capsule",
            size=str(cable_cfg["radius_m"]),
            density=str(density),
            rgba="0.05 0.65 0.8 1",
        )
    actuator = ET.SubElement(root, "actuator")
    for i in range(3):
        limit = cfg["diagnostic_stage"]["actuator_limit_n"]
        ET.SubElement(actuator, "motor", joint=f"stage_{i}", ctrlrange=f"{-limit} {limit}")
    sensors = ET.SubElement(root, "sensor")
    ET.SubElement(sensors, "force", name="wrist_force", site="stage_load")
    ET.SubElement(sensors, "torque", name="wrist_torque", site="stage_load")
    path = directory / "scene.xml"
    ET.indent(root)
    path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    return (
        path,
        initial,
        np.array(seated_plug.position),
        np.array(seated_tip.position),
        {"plug": plug.report, "port": port.report},
    )


def run_case(cfg, case, directory):
    directory.mkdir()
    path, initial, seated, tip_target, adaptation = make_stage(cfg, case, directory)
    model = mujoco.MjModel.from_xml_path(str(path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    stage_id = model.body("stage").id
    tip_id = model.site("plug__frame__sc_tip_link").id
    port_base_id = model.site("port__frame__sc_port_base_link").id
    stage_cfg = cfg["diagnostic_stage"]
    # Initialization settles the real cable by simulation with the stage held.
    initialization_s = 2.0
    deadline = initialization_s + stage_cfg["attempt_seconds"] + stage_cfg["retract_seconds"]
    rows = []
    peak = 0.0
    peak_contact = 0.0
    seated_dwell = 0.0
    completed = False
    aborted = False
    finite = True
    steps = 0
    init_steps = 0
    port_geom_ids = {
        i
        for i in range(model.ngeom)
        if (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or "").startswith("port")
    }
    plug_geom_ids = {
        i
        for i in range(model.ngeom)
        if (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or "").startswith("plug")
    }
    contact_sensor_force = 0.0
    contact_steps = 0
    first_contact = None
    initial_contact_peak = 0.0
    free_tracking_error = 0.0
    max_tip_angle = 0.0
    minimum_tip_error = float("inf")
    peak_detector_force = 0.0
    started_accounting = {"native_steps": 0, "initialization_native_steps": 0}
    write(directory / "progress.json", started_accounting)
    cable_body_ids = [
        i
        for i in range(model.nbody)
        if (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i) or "").startswith("cable_")
    ]
    cable_start = data.xpos[cable_body_ids].copy()
    cable_max_displacement = 0.0
    phase_metrics = {
        phase: {"native_steps": 0, "peak_wrist_n": 0.0, "peak_connector_contact_n": 0.0}
        for phase in ("initialization", "attempt", "retraction")
    }
    start = time.monotonic()
    for step in range(round(deadline / case["dt"])):
        t = step * case["dt"]
        target = initial.copy()
        if t > initialization_s:
            attempt_t = min(t - initialization_s, stage_cfg["attempt_seconds"])
            target[2] -= min(stage_cfg["speed_m_per_s"] * attempt_t, stage_cfg["initial_distance_m"] + 0.001)
        if t > initialization_s + stage_cfg["attempt_seconds"]:
            target[2] += min((t - initialization_s - stage_cfg["attempt_seconds"]) * 0.01, 0.025)
        pos = data.xpos[stage_id]
        force = (
            stage_cfg["translation_stiffness_n_per_m"] * (target - pos)
            - stage_cfg["translation_damping_ns_per_m"] * data.qvel[:3]
        )
        force[2] += model.body_subtreemass[stage_id] * 9.81
        data.ctrl[:] = np.clip(force, -stage_cfg["actuator_limit_n"], stage_cfg["actuator_limit_n"])
        pre_step_velocity = data.qvel[:3].copy()
        mujoco.mj_step(model, data)
        # mj_step leaves solved sensors/contact/kinematics at the left endpoint.
        # Pair these with pre-step velocity, never the advanced qvel.
        steps += 1
        init_steps += int(t < initialization_s)
        if steps % 1000 == 0:
            write(directory / "progress.json", {"native_steps": steps, "initialization_native_steps": init_steps})
        if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all() or np.any(data.warning.number):
            finite = False
            break
        contact_force = 0.0
        contact_sensor_force = 0.0
        for k in range(data.ncon):
            c = data.contact[k]
            pair = {c.geom1, c.geom2}
            if pair & plug_geom_ids and pair & port_geom_ids:
                wrench = np.zeros(6)
                mujoco.mj_contactForce(model, data, k, wrench)
                cf = float(np.linalg.norm(wrench[:3]))
                contact_force += cf
                if any(
                    "contact_collision" in (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, int(g)) or "")
                    for g in pair
                ):
                    contact_sensor_force += cf
        load = float(np.linalg.norm(data.sensordata[:3]))
        phase = (
            "initialization"
            if t < initialization_s
            else "attempt"
            if t < initialization_s + stage_cfg["attempt_seconds"]
            else "retraction"
        )
        pm = phase_metrics[phase]
        pm["native_steps"] += 1
        pm["peak_wrist_n"] = max(pm["peak_wrist_n"], load)
        pm["peak_connector_contact_n"] = max(pm["peak_connector_contact_n"], contact_force)
        if cable_body_ids:
            cable_max_displacement = max(
                cable_max_displacement, float(np.linalg.norm(data.xpos[cable_body_ids] - cable_start, axis=1).max())
            )
        peak = max(peak, load)
        peak_contact = max(peak_contact, contact_force)
        if contact_force > 0.05:
            contact_steps += 1
            if first_contact is None:
                first_contact = float(t)
        error = float(np.linalg.norm(data.site_xpos[tip_id] - data.site_xpos[port_base_id]))
        tip_r = data.site_xmat[tip_id].reshape(3, 3)
        base_r = data.site_xmat[port_base_id].reshape(3, 3)
        tip_angle = float(np.arccos(np.clip((np.trace(tip_r.T @ base_r) - 1) / 2, -1, 1)))
        max_tip_angle = max(max_tip_angle, tip_angle)
        minimum_tip_error = min(minimum_tip_error, error)
        peak_detector_force = max(peak_detector_force, contact_sensor_force)
        if t < initialization_s:
            initial_contact_peak = max(initial_contact_peak, contact_force)
        if t >= 0.2 and contact_force <= cfg["acceptance"]["initial_contact_free_tolerance_n"]:
            free_tracking_error = max(free_tracking_error, float(np.linalg.norm(data.xpos[stage_id] - target)))
        seated_now = (
            initialization_s <= t <= initialization_s + stage_cfg["attempt_seconds"]
            and error < cfg["acceptance"]["success_position_tolerance_m"]
            and tip_angle <= 0.03
        )
        seated_dwell = seated_dwell + case["dt"] if seated_now else 0.0
        completed |= seated_dwell >= cfg["acceptance"]["dwell_s"]
        if t >= initialization_s and load > cfg["acceptance"]["raw_load_abort_n"]:
            aborted = True
        if step % max(1, round(0.01 / case["dt"])) == 0:
            rows.append(
                [t, *data.xpos[stage_id], *target, load, contact_force, contact_sensor_force, error, *pre_step_velocity]
            )
        if aborted:
            break
    np.savez_compressed(
        directory / "trace.npz",
        trace=np.array(rows),
        columns=np.array(
            [
                "time_s",
                "x",
                "y",
                "z",
                "target_x",
                "target_y",
                "target_z",
                "stage_wrist_force_n",
                "plug_port_contact_n",
                "port_detector_contact_n",
                "seating_error_m",
                "vx",
                "vy",
                "vz",
            ]
        ),
    )
    image_error = None
    try:
        renderer = mujoco.Renderer(model, height=800, width=1000)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = [0.02, 0.0, 0.17]
        camera.distance = 0.3 if not case["with_cable"] else 1.25
        camera.azimuth = 120
        camera.elevation = -25
        renderer.update_scene(data, camera=camera)
        from PIL import Image

        Image.fromarray(renderer.render()).save(directory / "final.png")
        renderer.close()
    except Exception as exc:
        image_error = f"{type(exc).__name__}: {exc}"
    result = {
        "case": case,
        "controller": "scripted_cartesian_force_stage_approach_retract",
        "status": "completed" if finite else "failed",
        "attempt_outcome": "force_abort" if aborted else "seating_dwell" if completed else "no_seating",
        "final_connection_claimed": False,
        "valid_seating_attempt": bool(completed and finite and not aborted),
        "minimum_tip_error_m": minimum_tip_error,
        "maximum_tip_angle_rad": max_tip_angle,
        "peak_port_detector_contact_n": peak_detector_force,
        "initial_contact_peak_n": initial_contact_peak,
        "free_tracking_error_m": free_tracking_error,
        "acceptance_checks": {
            "finite": finite,
            "initial_contact_free": initial_contact_peak <= cfg["acceptance"]["initial_contact_free_tolerance_n"],
            "contact_detected": peak_contact > cfg["acceptance"]["positive_contact_threshold_n"],
            "free_tracking": free_tracking_error <= cfg["acceptance"]["stage_free_tracking_tolerance_m"],
            "aligned_orientation": max_tip_angle <= 0.03,
        },
        "is_robot_baseline": False,
        "finite_dynamics": finite,
        "raw_load_abort": aborted,
        "seating_dwell_reached": bool(completed),
        "peak_stage_wrist_force_n": peak,
        "peak_plug_port_contact_n": peak_contact,
        "contact_native_steps": contact_steps,
        "first_contact_s": first_contact,
        "final_seating_error_m": float(np.linalg.norm(data.site_xpos[tip_id] - data.site_xpos[port_base_id])),
        "native_steps": steps,
        "initialization_native_steps": init_steps,
        "elapsed_s": time.monotonic() - start,
        "mass_kg": float(model.body_subtreemass[stage_id]),
        "cable_max_displacement_m": cable_max_displacement,
        "phase_metrics": phase_metrics,
        "sample_convention": "contact/sensor/pose/pre-step velocity at left endpoint before the counted integration step",
        "native_steps_are_explicit_mj_step_calls": True,
        "render_error": image_error,
        "adaptation": adaptation,
        "limitations": [
            "Force-actuated Cartesian fixture with fixed connector orientation; no UR5e control or grasp validation.",
            "Completion requires seating dwell; upstream contact detector is reported separately; no post-contact attachment or freeze.",
            "Cable and connector share the fixture force sensor; this sensor is not the native robot wrist sensor.",
        ],
    }
    write(directory / "progress.json", {"native_steps": steps, "initialization_native_steps": init_steps})
    write(directory / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--case")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    results = []
    start = time.monotonic()
    selected_cases = [case for case in cfg["cases"] if not args.case or case["id"] == args.case]
    if not selected_cases:
        parser.error("No selected cases")
    for case in selected_cases:
        result = run_case(cfg, case, args.run_dir / case["id"])
        results.append(result)
        write(
            args.run_dir / "result.json",
            {
                "status": ("completed" if all(r["finite_dynamics"] for r in results) else "failed")
                if len(results) == len(selected_cases)
                else "running",
                "expected_case_ids": [c["id"] for c in selected_cases],
                "scope": cfg["scope"],
                "cases": results,
                "accounting": {
                    "native_steps": sum(r["native_steps"] for r in results),
                    "initialization_native_steps": sum(r["initialization_native_steps"] for r in results),
                },
                "elapsed_s": time.monotonic() - start,
            },
        )
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "case",
                        "finite_dynamics",
                        "seating_dwell_reached",
                        "peak_stage_wrist_force_n",
                        "peak_plug_port_contact_n",
                        "native_steps",
                    )
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
