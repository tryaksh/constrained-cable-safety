"""Source-only geometry integrity checks; no simulator or external assets required."""

import hashlib
import math
import xml.etree.ElementTree as ET

import pytest

from assembly_recovery.cable_assets import Pose, import_sdf_model, prepare_native_robot, sdf_pose


def write_sdf(tmp_path, links, extra=""):
    path = tmp_path/"model.sdf"
    path.write_text(f'<sdf version="1.9"><model name="fixture">{links}{extra}</model></sdf>', encoding="utf-8")
    return path


def rigid_box(name="housing", pose="0 0 0 0 0 0", dimensions="2 4 6", mass=12):
    return f'''<link name="{name}"><pose>{pose}</pose>
      <inertial auto="true"><mass>{mass}</mass></inertial>
      <collision name="box"><geometry><box><size>{dimensions}</size></box></geometry></collision>
      </link>'''


def values(element, attribute):
    return tuple(float(v) for v in element.get(attribute).split())


def test_sdf_extrinsic_xyz_rotation_and_inverse():
    pose = sdf_pose(ET.fromstring('<pose degrees="true">1 2 3 90 0 90</pose>'))
    assert pose.rotate((0, 0, 1)) == pytest.approx((1, 0, 0), abs=1e-14)
    identity = pose.compose(pose.inverse())
    assert identity.position == pytest.approx((0, 0, 0), abs=1e-14)
    assert identity.quaternion == pytest.approx((1, 0, 0, 0), abs=1e-14)


def test_box_sizes_mass_and_analytical_inertia_are_preserved(tmp_path):
    result = import_sdf_model(write_sdf(tmp_path, rigid_box()), "test")
    geom = result.body.find("geom")
    inertia = result.body.find("inertial")
    assert values(geom, "size") == (1, 2, 3)
    assert float(inertia.get("mass")) == 12
    assert values(inertia, "fullinertia") == pytest.approx((52, 40, 20, 0, 0, 0))
    assert result.report["collision_count"] == 1
    assert result.report["forbidden_geometry_omissions"] == 0


def test_marker_mass_and_parallel_axis_contribution_are_retained(tmp_path):
    marker = '''<link name="tip"><pose>2 0 0 0 0 0</pose><inertial><mass>1</mass>
      <inertia><ixx>1</ixx><iyy>2</iyy><izz>3</izz></inertia></inertial></link>'''
    extra = '<joint name="fixed" type="fixed"><parent>housing</parent><child>tip</child></joint>'
    result = import_sdf_model(write_sdf(tmp_path, rigid_box(dimensions="2 2 2", mass=1)+marker, extra), "test")
    inertia = result.body.find("inertial")
    assert float(inertia.get("mass")) == 2
    assert values(inertia, "pos") == (1, 0, 0)
    assert values(inertia, "fullinertia") == pytest.approx((1+2/3, 4+2/3, 5+2/3, 0, 0, 0))


def test_named_relative_frame_rotation_applies_to_geometry(tmp_path):
    link = '''<link name="housing"><pose>0 1 0 0 0 1.5707963267948966</pose>
      <inertial auto="true"><mass>1</mass></inertial>
      <collision name="box"><pose relative_to="entrance">0 0 0 0 0 0</pose>
      <geometry><box><size>1 2 3</size></box></geometry></collision></link>'''
    frame = '<frame name="entrance" attached_to="housing"><pose>1 0 0 0 0 0</pose></frame>'
    result = import_sdf_model(write_sdf(tmp_path, link, frame), "test")
    assert result.frames["entrance"].position == pytest.approx((0, 2, 0))
    assert values(result.body.find("geom"), "pos") == pytest.approx((0, 2, 0))
    assert values(result.body.find("inertial"), "fullinertia") == pytest.approx((10/12, 13/12, 5/12, 0, 0, 0))


def test_cylinder_and_sphere_collision_dimensions_and_counts(tmp_path):
    link = '''<link name="housing"><inertial auto="true"><mass>0.04</mass></inertial>
      <collision name="ferrule"><pose>0.00465 0.00635 0 0 1.5707963267948966 0</pose>
      <geometry><cylinder><radius>0.00125</radius><length>0.014</length></cylinder></geometry></collision>
      <collision name="end"><geometry><sphere><radius>0.002</radius></sphere></geometry></collision></link>'''
    result = import_sdf_model(write_sdf(tmp_path, link), "plug")
    cylinder, sphere = result.body.findall("geom")
    assert values(cylinder, "size") == (0.00125, 0.007)
    assert values(sphere, "size") == (0.002,)
    axis = Pose(quaternion=values(cylinder, "quat")).rotate((0, 0, 1))
    assert axis == pytest.approx((1, 0, 0), abs=1e-14)
    assert result.report["collision_count"] == 2
    assert float(result.body.find("inertial").get("mass")) == 0.04


def test_sdf_sliding_friction_is_explicit_and_visual_omission_recorded(tmp_path):
    link = rigid_box().replace('</collision>', '''<surface><friction><bullet>
      <friction>0.05</friction><friction2>0.05</friction2></bullet></friction></surface></collision>''')
    link = link.replace('</link>', '<visual name="original"><geometry><mesh><uri>mesh.glb</uri></mesh></geometry></visual></link>')
    result = import_sdf_model(write_sdf(tmp_path, link), "plug", friction=(0.5, 0.003, 0.0002))
    assert values(result.body.find("geom"), "friction") == (0.05, 0.003, 0.0002)
    assert result.report["omitted_visuals"] == ["original"]
    assert result.report["contact_adaptation"]["solver_equivalence"] is False


@pytest.mark.parametrize("replacement,match", [
    ('<mesh><uri>convex.obj</uri></mesh>', 'Unsupported collision'),
    ('<box><size>0 1 1</size></box>', 'positive and finite'),
    ('<box><size>nan 1 1</size></box>', 'finite numbers'),
])
def test_unsupported_or_invalid_collision_never_silently_disappears(tmp_path, replacement, match):
    link = rigid_box().replace('<box><size>2 4 6</size></box>', replacement)
    with pytest.raises(ValueError, match=match):
        import_sdf_model(write_sdf(tmp_path, link), "test")


def test_moving_joints_and_missing_inertia_are_not_silently_changed(tmp_path):
    with pytest.raises(ValueError, match="Moving SDF joints"):
        import_sdf_model(write_sdf(tmp_path, rigid_box(), '<joint type="ball"/>'), "test")
    with pytest.raises(ValueError, match="no declared inertia"):
        import_sdf_model(write_sdf(tmp_path, rigid_box().replace('<inertial auto="true"><mass>12</mass></inertial>', '')), "test")


def test_relative_frame_cycles_fail(tmp_path):
    link = rigid_box().replace('<pose>0 0 0 0 0 0</pose>', '<pose relative_to="loop">0 0 0 0 0 0</pose>')
    with pytest.raises(ValueError, match="cyclic"):
        import_sdf_model(write_sdf(tmp_path, link, '<frame name="loop" attached_to="housing"/>'), "test")


def native_fixture(tmp_path, data=b"known-collision-bytes"):
    source = tmp_path/"aic_utils/aic_mujoco/mjcf/aic_robot.xml"
    source.parent.mkdir(parents=True)
    digest = hashlib.sha1(data).hexdigest()
    source.write_text(f'''<mujoco><asset><mesh name="collision" file="base-{digest}.stl"/>
      <mesh name="visual" file="absent.obj"/></asset><worldbody><body name="robot">
      <geom name="physical" type="mesh" mesh="collision"/>
      <geom name="render" type="mesh" mesh="visual" contype="0" conaffinity="0"/>
      </body></worldbody></mujoco>''', encoding="utf-8")
    directory = tmp_path/"meshes"
    directory.mkdir()
    (directory/"base.stl").write_bytes(data)
    return source, directory


def test_native_restoration_requires_exact_collision_bytes_and_records_visual_loss(tmp_path):
    _, directory = native_fixture(tmp_path)
    root, report = prepare_native_robot(tmp_path, directory)
    assert [g.get("name") for g in root.findall(".//geom")] == ["physical"]
    assert report["omitted_visual_geoms"] == ["render"]
    assert report["collision_geoms_removed"] == 0
    assert report["preserved_collision_geom_count"] == 1
    assert report["restored_collision_meshes"][0]["sha256"] == hashlib.sha256(b"known-collision-bytes").hexdigest()
    assert root.find("asset/mesh").get("file") == str((directory/"base.stl").resolve())


def test_native_mesh_hash_mismatch_is_fatal(tmp_path):
    _, directory = native_fixture(tmp_path)
    (directory/"base.stl").write_bytes(b"different geometry")
    with pytest.raises(ValueError, match="differs from native"):
        prepare_native_robot(tmp_path, directory)


def test_visual_with_nonzero_contact_affinity_cannot_be_omitted(tmp_path):
    source, directory = native_fixture(tmp_path)
    source.write_text(source.read_text().replace('contype="0" conaffinity="0"', 'contype="0" conaffinity="1"'))
    with pytest.raises(FileNotFoundError, match="Missing collision mesh"):
        prepare_native_robot(tmp_path, directory)


def test_explicit_rotated_inertia_preserves_tensor_eigenvalues(tmp_path):
    link = '''<link name="housing"><inertial><pose>0 0 0 0 0 1.5707963267948966</pose>
      <mass>1</mass><inertia><ixx>2</ixx><iyy>3</iyy><izz>4</izz></inertia></inertial></link>'''
    result = import_sdf_model(write_sdf(tmp_path, link), "test")
    assert values(result.body.find("inertial"), "fullinertia") == pytest.approx((3, 2, 4, 0, 0, 0), abs=1e-14)
    assert math.isclose(result.report["total_declared_mass_kg"], 1)
