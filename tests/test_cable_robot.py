"""CPU contracts for finite robot actuation and invariant cable material setup."""

import sys
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from assembly_recovery.cable_assets import Pose
from assembly_recovery.cable_robot import add_world_cable, apply_cartesian_impedance

np = pytest.importorskip("numpy")


def test_cartesian_controller_clamps_torques_without_writing_robot_state(monkeypatch):
    def jacobian(model, data, translation, rotation, site):
        translation[:, :3] = np.eye(3)
        rotation[:, 3:6] = np.eye(3)

    monkeypatch.setitem(sys.modules, "mujoco", SimpleNamespace(mj_jacSite=jacobian))
    model = SimpleNamespace(nv=8, joint=lambda name: SimpleNamespace(qposadr=[6], dofadr=[6]),
                            actuator=lambda name: SimpleNamespace(id=6))
    data = SimpleNamespace(qpos=np.zeros(8), qvel=np.zeros(8), ctrl=np.zeros(7),
                           qfrc_bias=np.full(8, 100.0), site_xpos=np.zeros((1, 3)),
                           site_xmat=np.eye(3).reshape(1, 9))
    scene = SimpleNamespace(model=model, data=data, arm_dofs=np.arange(6), arm_actuators=np.arange(6), tip_site=0)
    cfg = dict(translation_stiffness_n_per_m=1500, translation_damping_ns_per_m=90,
               rotation_stiffness_nm_per_rad=80, rotation_damping_nms_per_rad=15,
               cartesian_force_limit_n=15, cartesian_torque_limit_nm=8,
               joint_torque_limits_nm=[1, 2, 3, 4, 5, 6], finger_opening_m=.0125)
    state_before = (data.qpos.copy(), data.qvel.copy())
    outcome = apply_cartesian_impedance(scene, np.ones(3)*100, np.eye(3), cfg)
    np.testing.assert_array_equal(data.ctrl[:6], [1, 2, 3, 4, 5, 6])
    np.testing.assert_array_equal(outcome["force_command"], [15, 15, 15])
    np.testing.assert_array_equal(data.qpos, state_before[0])
    np.testing.assert_array_equal(data.qvel, state_before[1])
    assert outcome["joint_torque_saturated"]
    assert abs(data.ctrl[6]) <= 15


def cable_config():
    return dict(attachment_back_m=.052, initial_outward_world_xy=[1, 0], length_m=.96,
                segments=24, initial_bend_segments=4, radius_m=.002,
                twist_modulus_pa=4e6, youngs_modulus_pa=1e7, joint_damping=.00002,
                linear_density_kg_per_m=.0520833333333333)


def test_curved_initialization_preserves_length_and_straight_stress_free_material():
    root = ET.fromstring('<mujoco><worldbody><body name="plug"/></worldbody></mujoco>')
    report = add_world_cable(root, root.find("worldbody/body"), cable_config(), Pose((1, 2, 3)))
    points = np.asarray(report["initial_vertices_world_m"])
    assert points.shape == (25, 3)
    assert np.linalg.norm(np.diff(points, axis=0), axis=1).sum() == pytest.approx(.96)
    np.testing.assert_allclose(points[0], [.948, 2, 3])
    composite = root.find("worldbody/composite")
    assert composite.find("plugin/config[@key='flat']").get("value") == "true"
    assert composite.get("initial") == "free"
    connection = root.find("equality/connect")
    assert connection.get("site1") == "plug_cable_anchor"
    assert connection.get("site2") == "cable_S_first"


def test_explicit_layout_cannot_change_length_or_move_attachment():
    root = ET.fromstring('<mujoco><worldbody><body name="plug"/></worldbody></mujoco>')
    cfg = cable_config()
    cfg["initial_vertices_world_m"] = [[0, 0, 0]]*25
    with pytest.raises(ValueError, match="match segment count and plug anchor"):
        add_world_cable(root, root.find("worldbody/body"), cfg, Pose())
