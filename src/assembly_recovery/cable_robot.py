"""Native AIC UR5e diagnostic adapter with an explicit fixed preset grasp.

Robot rigid geometry, kinematics, joints, inertias, and native wrist sensor come
from pinned AIC MJCF. Connector collisions come from the newer pinned SDF rather
than the stale embedded native-world connector. All robot collision geoms remain.
The connector is a fixed child of the gripper tool: grasping/drop robustness is
not learned or validated. The elasticity cable uses registered project material
parameters, not the uncalibrated oversized inertias in AIC's native world.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from assembly_recovery.cable_assets import Pose, import_sdf_model, prepare_native_robot

ARM_JOINTS = ("shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
              "wrist_1_joint", "wrist_2_joint", "wrist_3_joint")


def fmt(values):
    return " ".join(format(float(x), ".17g") for x in values)


def add_cable(root, plug_body, cfg):
    """Attach a gravity-loaded elastic chain at the retained plug's boot exit."""
    extension = root.find("extension")
    if extension is None:
        extension = ET.SubElement(root, "extension")
    ET.SubElement(extension, "plugin", plugin="mujoco.elasticity.cable")
    # The source plug boot ends at x=-0.045752 m; the start clears its collision.
    # Initial lateral orientation is a declared cable shape, not an upstream trajectory.
    origin = ET.SubElement(plug_body, "body", name="cable_origin", pos="-0.048 0 0",
                           quat=fmt((math.sqrt(.5), 0, .5, -.5)))
    composite = ET.SubElement(origin, "composite", prefix="cable_", type="cable", curve="s",
                              count=f"{cfg['segments']+1} 1 1", size=str(cfg["length_m"]), initial="ball")
    plugin = ET.SubElement(composite, "plugin", plugin="mujoco.elasticity.cable")
    ET.SubElement(plugin, "config", key="twist", value=str(cfg["twist_modulus_pa"]))
    ET.SubElement(plugin, "config", key="bend", value=str(cfg["youngs_modulus_pa"]))
    ET.SubElement(composite, "joint", kind="main", damping=str(cfg["joint_damping"]))
    density = cfg["linear_density_kg_per_m"]/(math.pi*cfg["radius_m"]**2)
    ET.SubElement(composite, "geom", type="capsule", size=str(cfg["radius_m"]), density=str(density),
                  rgba="0.04 0.65 0.75 1", friction="0.5 0.005 0.0001")


def add_world_cable(root, plug_body, cable_cfg, plug_world_pose):
    """Free elastic chain with a permanent ball-like endpoint constraint.

    Initial vertices form an outboard/hanging curve. ``flat=true`` keeps the
    stress-free material straight, independent of those initial vertices.
    Endpoint constraints are constructed before compilation and never changed.
    """
    import numpy as np

    extension = root.find("extension")
    if extension is None:
        extension = ET.SubElement(root, "extension")
    ET.SubElement(extension, "plugin", plugin="mujoco.elasticity.cable")
    local_anchor = (-cable_cfg["attachment_back_m"], 0, 0)
    ET.SubElement(plug_body, "site", name="plug_cable_anchor", pos=fmt(local_anchor), size=".001")
    anchor = plug_world_pose.compose(Pose(local_anchor)).position
    outward = np.asarray(cable_cfg["initial_outward_world_xy"], dtype=float)
    outward /= np.linalg.norm(outward)
    point = np.asarray(anchor)
    points = [point.copy()]
    segment_length = cable_cfg["length_m"]/cable_cfg["segments"]
    bend_segments = cable_cfg["initial_bend_segments"]
    for i in range(cable_cfg["segments"]):
        angle = .5*math.pi*min(1.0, i/bend_segments)
        direction = np.array([outward[0]*math.cos(angle), outward[1]*math.cos(angle), -math.sin(angle)])
        point = point+segment_length*direction
        points.append(point.copy())
    if "initial_vertices_world_m" in cable_cfg:
        points = [np.asarray(p, dtype=float) for p in cable_cfg["initial_vertices_world_m"]]
        if len(points) != cable_cfg["segments"]+1 or not np.allclose(points[0], anchor, atol=1e-9):
            raise ValueError("Explicit cable vertices must match segment count and plug anchor")
        length = sum(np.linalg.norm(b-a) for a, b in zip(points[:-1], points[1:], strict=True))
        if abs(length-cable_cfg["length_m"]) > 1e-8:
            raise ValueError("Explicit cable vertices must preserve registered cable length")
    composite = ET.SubElement(root.find("worldbody"), "composite", prefix="cable_", type="cable",
                              vertex=fmt(np.asarray(points).flatten()), initial="free")
    plugin = ET.SubElement(composite, "plugin", plugin="mujoco.elasticity.cable")
    for key, value in [("twist", cable_cfg["twist_modulus_pa"]), ("bend", cable_cfg["youngs_modulus_pa"]), ("flat", "true")]:
        ET.SubElement(plugin, "config", key=key, value=str(value))
    ET.SubElement(composite, "joint", kind="main", damping=str(cable_cfg["joint_damping"]))
    density = cable_cfg["linear_density_kg_per_m"]/(math.pi*cable_cfg["radius_m"]**2)
    ET.SubElement(composite, "geom", type="capsule", size=str(cable_cfg["radius_m"]), density=str(density),
                  rgba=".04 .65 .75 1", friction=".5 .005 .0001")
    ET.SubElement(composite, "site", size=".001")
    equality = root.find("equality")
    if equality is None:
        equality = ET.SubElement(root, "equality")
    ET.SubElement(equality, "connect", name="permanent_cable_plug_connection", site1="plug_cable_anchor",
                  site2="cable_S_first", solref=".004 1", solimp=".99 .999 .0001")
    return {"initial_vertices_world_m": [p.tolist() for p in points], "material_stress_free": "straight; flat=true",
            "root_connection": "Permanent site connect, free rotation, finite solver compliance; no within-job attachment changes"}


def _set_initial_joints(model, data, cfg):
    """Initialization only; no qpos writes are made by the controller."""
    for name, value in zip(ARM_JOINTS, cfg["home_q_rad"], strict=True):
        data.qpos[model.joint(name).qposadr[0]] = value
    for name in ("gripper/left_finger_joint", "gripper/right_finger_joint"):
        data.qpos[model.joint(name).qposadr[0]] = cfg["finger_opening_m"]


@dataclass
class RobotScene:
    model: object
    data: object
    tip_site: int
    port_site: int
    plug_body: int
    arm_dofs: object
    arm_actuators: object
    initial_tip: object
    target_tip: object
    target_rotation: object
    insertion_axis: object
    initial_cable_positions: object
    cable_bodies: object
    report: dict


def build_scene(project_root: Path, cfg: dict, case: dict, directory: Path) -> RobotScene:
    """Compile the robot scene and place a fixture at a reachable initial approach.

    Port placement uses initial forward kinematics before any job steps. The
    scene is then recompiled and remains unchanged during the job. This defines
    a reachable engineering fixture, not a sampled official benchmark layout.
    """
    import mujoco
    import numpy as np

    root, robot_report = prepare_native_robot(project_root/".deps/aic", project_root/cfg["robot_mesh_directory"])
    root.set("model", "aic_native_ur5e_sc_diagnostic")
    root.find("compiler").set("autolimits", "true")
    option = root.find("option")
    option.attrib.update(timestep=str(case["dt"]), integrator="implicitfast", solver="Newton",
                         iterations="100", tolerance="1e-10", cone="elliptic", gravity="0 0 -9.81")
    ET.SubElement(root.find("default"), "geom", solref="0.004 1", solimp="0.95 0.99 0.001",
                  friction="0.5 0.005 0.0001")
    root.find("visual/global").attrib.update(offwidth="1000", offheight="800")
    root.find("visual/headlight").attrib.update(ambient=".35 .35 .35", diffuse=".8 .8 .8", specular=".1 .1 .1")
    world = root.find("worldbody")
    ET.SubElement(world, "light", pos="-0.7 -1 2.7", dir="0 0 -1", diffuse="0.9 0.9 0.9")
    ET.SubElement(world, "geom", name="floor", type="plane", size="3 3 .1", rgba=".15 .18 .23 1")
    models = project_root/".deps/aic/aic_assets/models"
    visuals = directory/"meshes" if cfg.get("render_visuals", True) else None
    plug = import_sdf_model(models/"SC Plug/model.sdf", "plug", visual_directory=visuals)
    port = import_sdf_model(models/"SC Port/model.sdf", "port", visual_directory=visuals)
    root.find("asset").extend(plug.assets+port.assets)
    tool = root.find(".//body[@name='ati/tool_link']")
    plug_rotation = Pose(quaternion=plug.frames["sc_tip_link"].quaternion).inverse()
    grasp = Pose(tuple(cfg["plug_origin_in_tool_m"]), plug_rotation.quaternion)
    plug.body.attrib.update(grasp.attributes())
    ET.SubElement(plug.body, "site", name="plug_load_sensor", pos="0 0 0", size=".001")
    tool.append(plug.body)
    world_cable = case["with_cable"] and cfg["cable"].get("initial_shape") == "outboard_hanging_curve"
    if case["with_cable"] and not world_cable:
        add_cable(root, plug.body, cfg["cable"])
    sensors = root.find("sensor")
    ET.SubElement(sensors, "force", name="plug_load_force", site="plug_load_sensor")
    ET.SubElement(sensors, "torque", name="plug_load_torque", site="plug_load_sensor")
    for i, name in enumerate(ARM_JOINTS):
        motor = root.find(f"actuator/general[@joint='{name}']")
        limit = cfg["controller"]["joint_torque_limits_nm"][i]
        motor.attrib.update(ctrllimited="true", ctrlrange=f"{-limit} {limit}")
    finger_motor = root.find("actuator/general[@joint='gripper/left_finger_joint']")
    finger_motor.attrib.update(ctrllimited="true", ctrlrange="-15 15")
    provisional = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    provisional_data = mujoco.MjData(provisional)
    _set_initial_joints(provisional, provisional_data, cfg)
    mujoco.mj_forward(provisional, provisional_data)
    tip_site = provisional.site("plug__frame__sc_tip_link").id
    initial_tip = provisional_data.site_xpos[tip_site].copy()
    tip_rotation = provisional_data.site_xmat[tip_site].reshape(3, 3).copy()
    axis = tip_rotation[:, 2]
    cable_adaptation = None
    if world_cable:
        plug_id = provisional.body("plug").id
        plug_pose_world = Pose(tuple(provisional_data.xpos[plug_id]), tuple(provisional_data.xquat[plug_id]))
        cable_adaptation = add_world_cable(root, plug.body, cfg["cable"], plug_pose_world)
    goal = initial_tip+axis*cfg["initial_distance_m"]
    # A local lateral offset moves the fixture; the identical observed reference
    # remains offset by this declared error for the diagnostic first attempt.
    goal += tip_rotation[:, :2] @ np.asarray(case.get("fixture_offset_m", [0, 0]))
    quaternion = np.empty(4)
    mujoco.mju_mat2Quat(quaternion, tip_rotation.flatten())
    port_pose = Pose(tuple(goal), tuple(quaternion)).compose(port.frames["sc_port_base_link"].inverse())
    port.body.attrib.update(port_pose.attributes())
    world.append(port.body)
    scene_path = directory/"scene.xml"
    ET.indent(root)
    scene_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    model = mujoco.MjModel.from_xml_path(str(scene_path))
    data = mujoco.MjData(model)
    _set_initial_joints(model, data, cfg)
    mujoco.mj_forward(model, data)
    cable_bodies = np.array([i for i in range(model.nbody)
        if (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i) or "").startswith("cable_")], dtype=int)
    report = {"robot": robot_report, "plug": plug.report, "port": port.report,
              "scene_xml": str(scene_path), "fixed_preset_grasp": True,
              "grasp_transform": grasp.attributes(), "grasp_strength_validated": False,
              "fixture_placement": "Initial FK plus registered approach distance; set before job steps",
              "source_collision_omissions": 0, "cable_adaptation": cable_adaptation, "cable_parameters": cfg["cable"] if case["with_cable"] else None,
              "initial_contact_count": data.ncon,
              "initial_contact_pairs": [{"geom1": model.geom(c.geom1).name, "geom2": model.geom(c.geom2).name,
                  "distance": float(c.dist)} for c in data.contact],
              "actor_observations": ["native qpos/qvel", "simulator tip and target frame poses", "native wrist force/torque",
                  "model Jacobian", "model generalized bias force for feedforward"],
              "observation_limitations": "No camera perception; simulator state and exact model feedforward are idealized"}
    return RobotScene(model, data, model.site("plug__frame__sc_tip_link").id,
                      model.site("port__frame__sc_port_base_link").id, model.body("plug").id,
                      np.array([model.joint(name).dofadr[0] for name in ARM_JOINTS]),
                      np.array([model.actuator(name+"_motor").id for name in ARM_JOINTS]),
                      initial_tip, goal, tip_rotation, axis, data.xpos[cable_bodies].copy(), cable_bodies, report)


def apply_cartesian_impedance(scene: RobotScene, target_position, target_rotation, cfg: dict):
    """Finite joint torque control; never writes poses, velocities, or attachments."""
    import mujoco
    import numpy as np

    model, data = scene.model, scene.data
    jp, jr = np.zeros((3, model.nv)), np.zeros((3, model.nv))
    mujoco.mj_jacSite(model, data, jp, jr, scene.tip_site)
    jp, jr = jp[:, scene.arm_dofs], jr[:, scene.arm_dofs]
    velocity = data.qvel[scene.arm_dofs]
    rotation = data.site_xmat[scene.tip_site].reshape(3, 3)
    orientation_error = sum(np.cross(rotation[:, i], target_rotation[:, i]) for i in range(3))*.5
    force = cfg["translation_stiffness_n_per_m"]*(target_position-data.site_xpos[scene.tip_site])
    force -= cfg["translation_damping_ns_per_m"]*(jp @ velocity)
    torque = cfg["rotation_stiffness_nm_per_rad"]*orientation_error
    torque -= cfg["rotation_damping_nms_per_rad"]*(jr @ velocity)
    force = np.clip(force, -cfg["cartesian_force_limit_n"], cfg["cartesian_force_limit_n"])
    torque = np.clip(torque, -cfg["cartesian_torque_limit_nm"], cfg["cartesian_torque_limit_nm"])
    joint_torque = jp.T @ force+jr.T @ torque+data.qfrc_bias[scene.arm_dofs]
    limits = np.asarray(cfg["joint_torque_limits_nm"])
    saturated = bool(np.any(np.abs(joint_torque) > limits))
    data.ctrl[scene.arm_actuators] = np.clip(joint_torque, -limits, limits)
    finger = model.joint("gripper/left_finger_joint")
    motor = model.actuator("gripper/left_finger_joint_motor").id
    opening = cfg["finger_opening_m"]
    data.ctrl[motor] = np.clip(1000*(opening-data.qpos[finger.qposadr[0]])-5*data.qvel[finger.dofadr[0]], -15, 15)
    return {"force_command": force, "torque_command": torque, "joint_torque_saturated": saturated}


def measure_contacts(scene: RobotScene) -> dict:
    """Native contact forces with exact pair filtering and separate detector load."""
    import mujoco
    import numpy as np

    model, data = scene.model, scene.data
    total = detector = unrelated = 0.0
    for k in range(data.ncon):
        contact = data.contact[k]
        names = [model.geom(int(g)).name or "" for g in (contact.geom1, contact.geom2)]
        wrench = np.zeros(6)
        mujoco.mj_contactForce(model, data, k, wrench)
        magnitude = float(np.linalg.norm(wrench[:3]))
        if any(n.startswith("plug__") for n in names) and any(n.startswith("port__") for n in names):
            total += magnitude
            if any("contact_collision" in n for n in names):
                detector += magnitude
        else:
            unrelated += magnitude
    return {"plug_port_contact_n": total, "port_detector_contact_n": detector,
            "other_contact_n": unrelated,
            "raw_wrist_load_n": float(np.linalg.norm(data.sensor("AtiForceTorqueSensor_force").data)),
            "raw_plug_load_n": float(np.linalg.norm(data.sensor("plug_load_force").data))}
