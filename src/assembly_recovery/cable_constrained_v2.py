"""Constrained-cable connector recovery scene: strain relief, open clip and post.

This is a new task version, not a modification of the frozen free-cable v1
experiment. It adds a world-fixed fixture (mount plate, shelf, escapable open
clip, shallow post, instrumented strain-relief anchor) and real load, clip and
mutation instrumentation. The robot, plug, port and preset grasp are unchanged.

Scope: the endpoint is held, clip-preserving seating before gripper release. No
latch, release, learned pickup, grasp-strength or hardware claim is made here.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from assembly_recovery.cable_assets import Pose, import_sdf_model, prepare_native_robot
from assembly_recovery.cable_routes import clip_passages, route_length

ARM_JOINTS = ("shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
              "wrist_1_joint", "wrist_2_joint", "wrist_3_joint")

#: Contact group codes used by the precompiled geom->group table.
GROUP_OTHER, GROUP_PLUG, GROUP_PORT, GROUP_CABLE = 0, 1, 2, 3
GROUP_CLIP, GROUP_POST, GROUP_SHELF, GROUP_ROBOT, GROUP_ANCHOR = 4, 5, 6, 7, 8

#: Load channels reported at every registered sample. ``*_n`` are sums of contact
#: force norms (positive witnesses, never signed resultants); ``raw_*`` are native
#: sensor norms including dynamic and gravity load, not pure contact force.
LOAD_KEYS = ("plug_port_contact_n", "port_detector_contact_n", "cable_clip_contact_n",
             "cable_post_contact_n", "cable_shelf_contact_n", "cable_robot_contact_n",
             "other_contact_n", "raw_wrist_load_n", "raw_plug_load_n", "anchor_load_n")


def fmt(values):
    return " ".join(format(float(x), ".17g") for x in values)


def capsule_segment_mass(radius_m: float, segment_length_m: float, density: float) -> float:
    """Compiled mass of one composite capsule link, including both spherical caps."""
    return density*math.pi*radius_m*radius_m*(segment_length_m+4/3*radius_m)


def capsule_chain_density(total_mass_kg: float, radius_m: float, segment_length_m: float, segments: int) -> float:
    """Density that makes the compiled capsule chain reach an exact total mass.

    The v1 model set density from a plain cylinder formula and compiled 6.67%
    heavy, because each capsule adds two hemispherical caps. Solving the actual
    capsule volume conserves total mass exactly across segment refinement.
    """
    unit = capsule_segment_mass(radius_m, segment_length_m, 1.0)
    if unit <= 0 or segments < 1 or total_mass_kg <= 0:
        raise ValueError("Positive mass, radius, segment length and segment count required")
    return total_mass_kg/(segments*unit)


def _unit(vector):
    import numpy as np

    vector = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(vector))
    if norm < 1e-12:
        raise ValueError("Cannot normalise a zero-length direction")
    return vector/norm


def arc_turn(start, from_direction, to_direction, steps: int, segment_length: float):
    """Equal-chord circular blend between two directions, excluding ``start``."""
    import numpy as np

    a, b = _unit(from_direction), _unit(to_direction)
    total = float(np.arccos(np.clip(a @ b, -1, 1)))
    axis = np.cross(a, b)
    if np.linalg.norm(axis) < 1e-12:
        raise ValueError("Arc endpoints must not be parallel or antiparallel")
    axis = _unit(axis)
    point = np.asarray(start, dtype=float).copy()
    points = []
    for i in range(steps):
        angle = total*(i+0.5)/steps
        direction = (a*math.cos(angle)+np.cross(axis, a)*math.sin(angle)
                     + axis*(axis @ a)*(1-math.cos(angle)))
        point = point+segment_length*_unit(direction)
        points.append(point.copy())
    return points


def rounded_path(waypoints, fillet_radius_m: float, arc_samples: int = 8):
    """Dense polyline through waypoints with circular fillets at interior corners.

    Each fillet is clamped to half of the shorter adjacent leg, so the path stays
    inside the routed corridor. This is a construction guide for the initial
    cable configuration, not a planned robot trajectory.
    """
    import numpy as np

    points = [np.asarray(w, dtype=float) for w in waypoints]
    if len(points) < 2:
        raise ValueError("A route needs at least two waypoints")
    dense = [points[0].copy()]
    for i in range(1, len(points)-1):
        before, corner, after = points[i-1], points[i], points[i+1]
        a, b = before-corner, after-corner
        la, lb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if la < 1e-9 or lb < 1e-9:
            continue
        a, b = a/la, b/lb
        half = 0.5*float(np.arccos(np.clip(a @ b, -1, 1)))
        if half < 1e-6 or abs(half-0.5*math.pi) < 1e-9:
            dense.append(corner.copy())
            continue
        cut = min(fillet_radius_m/max(math.tan(half), 1e-9), 0.5*la, 0.5*lb)
        start, end = corner+a*cut, corner+b*cut
        dense.append(start)
        for k in range(1, arc_samples):
            u = k/arc_samples
            # Quadratic Bezier through the corner approximates the tangent fillet.
            dense.append((1-u)**2*start+2*(1-u)*u*corner+u*u*end)
        dense.append(end)
    dense.append(points[-1].copy())
    result = [dense[0]]
    for point in dense[1:]:
        if float(np.linalg.norm(point-result[-1])) > 1e-9:
            result.append(point)
    return [p.tolist() for p in result]


def guide_route(boot_world, fixture: dict, cable_cfg: dict, rest_length_m: float):
    """Dense design route from the plug boot exit to the strain-relief anchor.

    The route leaves the boot along the registered free outward direction, which
    clears the wrist and tool colliders, descends to the shelf, passes through
    the open clip and ends clamped at the strain relief. Extra shelf waypoints
    express a registered distal catch. It is a construction guide, not a claim
    about settled cable shape.
    """
    import numpy as np

    outward = _unit([*cable_cfg["outward_world_xy"], 0.0])
    boot = np.asarray(boot_world, dtype=float)
    waypoints = [boot, boot+outward*cable_cfg["lead_out_m"]]
    waypoints += [np.asarray(w, dtype=float) for w in fixture["route_waypoints_world"]]
    waypoints.append(np.asarray(fixture["anchor_site_world"], dtype=float))
    bow_leg = len(waypoints)-2 if fixture["slack_bow_leg"] == "last" else int(fixture["slack_bow_leg"])
    direct = route_length(rounded_path([waypoints[0], *waypoints[2:]], cable_cfg["fillet_radius_m"]))
    return matched_guide(waypoints, cable_cfg["fillet_radius_m"], rest_length_m,
                         np.asarray(fixture["bow_direction_world"], dtype=float),
                         cable_cfg["max_bow_m"], bow_leg), direct


def matched_guide(waypoints, fillet_radius_m: float, rest_length_m: float, bow_direction,
                  max_bow_m: float, bow_leg: int):
    """Meander one routed leg until the guide length equals the cable length.

    Installed service-loop slack is the experimental quantity, so the guide must
    carry exactly the surplus cable rather than leaving it for the chain fit to
    absorb as a fold. The surplus is placed as a lateral meander on the support
    leg, where a real service loop lies; the settling phase, not this
    construction, determines the resting shape.
    """
    import numpy as np

    from assembly_recovery.cable_routes import route_length

    waypoints = [np.asarray(w, dtype=float) for w in waypoints]
    taut = route_length(rounded_path(waypoints, fillet_radius_m))
    if taut > rest_length_m:
        raise ValueError(f"Routed path {taut:.4f} m exceeds the {rest_length_m:.4f} m cable")
    index = int(np.clip(bow_leg, 0, len(waypoints)-2))
    middle = 0.5*(waypoints[index]+waypoints[index+1])
    direction = bow_direction/np.linalg.norm(bow_direction)

    def length_at(height):
        bowed = [*waypoints[:index+1], middle+direction*height, *waypoints[index+1:]]
        return route_length(rounded_path(bowed, fillet_radius_m)), bowed

    low, high = 0.0, max_bow_m
    if length_at(high)[0] < rest_length_m:
        raise ValueError(f"Cable surplus over the routed path exceeds the {max_bow_m:.3f} m bow limit")
    for _ in range(60):
        middle_height = 0.5*(low+high)
        if length_at(middle_height)[0] < rest_length_m:
            low = middle_height
        else:
            high = middle_height
    return rounded_path(length_at(0.5*(low+high))[1], fillet_radius_m)


def fit_chain(guide, segments: int, segment_length: float, iterations: int = 4000, floor_z: float | None = None):
    """Place ``segments+1`` vertices with exact chord lengths and pinned ends.

    Gauss-Seidel distance projection from an equal-arclength resampling of the
    guide, alternated with an optional support-plane clamp so surplus cable
    length bows above the shelf instead of through it. Both endpoints are hard
    constraints. The result is a feasible initial configuration; the settling
    phase, not this helper, determines the resting cable shape.
    """
    import numpy as np

    from assembly_recovery.cable_routes import resample_polyline

    points = np.asarray(resample_polyline(guide, segments), dtype=float)
    first, last = points[0].copy(), points[-1].copy()
    if float(np.linalg.norm(last-first)) > segments*segment_length:
        raise ValueError("Anchor separation exceeds the available cable length")
    for iteration in range(iterations):
        worst = 0.0
        if floor_z is not None and iteration < iterations//2:
            np.maximum(points[1:-1, 2], floor_z, out=points[1:-1, 2])
        for i in range(segments):
            delta = points[i+1]-points[i]
            distance = float(np.linalg.norm(delta))
            if distance < 1e-12:
                delta, distance = np.array([1e-9, 0.0, 0.0]), 1e-9
            worst = max(worst, abs(distance-segment_length))
            correction = delta*(1-segment_length/distance)
            head, tail = i > 0, i+1 < segments
            if head and tail:
                points[i] += 0.5*correction
                points[i+1] -= 0.5*correction
            elif head:
                points[i] += correction
            elif tail:
                points[i+1] -= correction
        points[0], points[-1] = first, last
        if worst < 1e-10:
            break
    errors = [abs(float(np.linalg.norm(b-a))-segment_length) for a, b in zip(points[:-1], points[1:], strict=True)]
    if max(errors) > 1e-6:
        raise ValueError(f"Chain fit did not converge: max chord error {max(errors):.3e} m")
    return points


def chain_turn_angles_deg(points):
    """Interior turn angle at each chain vertex, in degrees."""
    import numpy as np

    points = np.asarray(points, dtype=float)
    before, after = points[1:-1]-points[:-2], points[2:]-points[1:-1]
    cosine = np.einsum("ij,ij->i", before, after)/(
        np.linalg.norm(before, axis=1)*np.linalg.norm(after, axis=1))
    return np.degrees(np.arccos(np.clip(cosine, -1, 1)))


def fixture_frame(cfg: dict, seated_tip, run_direction_xy):
    """Common fixture frame: shelf origin under the seated tip, run and side axes."""
    import numpy as np

    seated = np.asarray(seated_tip, dtype=float)
    run = _unit([*run_direction_xy, 0.0])
    side = np.cross([0.0, 0.0, 1.0], run)
    origin = np.array([seated[0], seated[1], seated[2]-cfg["fixture"]["shelf_drop_m"]])

    def at(along, across, up):
        return origin+run*along+side*across+np.array([0.0, 0.0, up])

    return at, run, side, origin


def solve_anchor_along(cfg: dict, seated_tip, run_direction_xy, route_waypoints, boot_world,
                       cable_cfg: dict, target_length_m: float) -> float:
    """Strain-relief position whose routed path leaves the declared service loop.

    Installed slack is the experimental factor, so the anchor is derived from it
    and the cable model stays byte-identical across conditions. Surplus cable
    never has to be parked as a swinging loop.
    """
    import numpy as np

    from assembly_recovery.cable_routes import route_length

    at, _, _, _ = fixture_frame(cfg, seated_tip, run_direction_xy)
    outward = _unit([*cable_cfg["outward_world_xy"], 0.0])
    boot = np.asarray(boot_world, dtype=float)
    height = cfg["fixture"]["route_height_m"]
    strain = cfg["fixture"]["strain_relief"]

    def routed(along):
        points = [boot, boot+outward*cable_cfg["lead_out_m"]]
        points += [at(a, c, height) for a, c in route_waypoints]
        points.append(at(along, strain["across_m"], strain["height_m"]))
        return route_length(rounded_path(points, cable_cfg["fillet_radius_m"]))

    low, high = cfg["fixture"]["anchor_search_along_m"]
    if routed(low) > target_length_m or routed(high) < target_length_m:
        raise ValueError(f"No strain-relief position in {low}-{high} m gives a "
                         f"{target_length_m:.4f} m routed path")
    for _ in range(60):
        middle = 0.5*(low+high)
        if routed(middle) < target_length_m:
            low = middle
        else:
            high = middle
    return 0.5*(low+high)


def _box(parent, name, centre, half, rgba, **kwargs):
    ET.SubElement(parent, "geom", name=name, type="box", pos=fmt(centre), size=fmt(half), rgba=rgba, **kwargs)


def build_fixture(world, cfg: dict, seated_tip, run_direction_xy, route_waypoints=None) -> dict:
    """Add the world-fixed mount plate, shelf, open clip, post and strain relief.

    All coordinates are derived from the measured seated tip pose and registered
    offsets, so the layout is reproducible from the compiled assets. The fixture
    is an infinitely rigid boundary, exactly like the v1 world-fixed port: it
    models mounting geometry, not fixture compliance.
    """
    import mujoco
    import numpy as np

    f = cfg["fixture"]
    route_waypoints = f["route_waypoints_along_across_m"] if route_waypoints is None else route_waypoints
    seated = np.asarray(seated_tip, dtype=float)
    run = _unit([*run_direction_xy, 0.0])
    side = np.cross([0.0, 0.0, 1.0], run)
    shelf_top = float(seated[2]-f["shelf_drop_m"])
    origin = np.array([seated[0], seated[1], shelf_top])

    def at(along, across, up):
        return origin+run*along+side*across+np.array([0.0, 0.0, up])

    body = ET.SubElement(world, "body", name="fixture", pos="0 0 0")
    plate_top = float(seated[2]-f["plate_clearance_m"])
    plate_half = f["plate_half_m"]
    _box(body, "fixture_plate", [seated[0], seated[1], plate_top-plate_half[2]], plate_half, ".62 .64 .68 1")
    for y in f["standoff_offsets_y_m"]:
        ET.SubElement(body, "geom", name=f"fixture_standoff_{y:+.4f}".replace(".", "p"), type="cylinder",
                      pos=fmt([seated[0], seated[1]+y, 0.5*(plate_top+seated[2]-f["port_flange_bottom_m"])]),
                      size=fmt([f["standoff_radius_m"], 0.5*abs(seated[2]-f["port_flange_bottom_m"]-plate_top)]),
                      rgba=".45 .47 .5 1")
    shelf_half = f["shelf_half_m"]
    shelf_centre = at(f["shelf_centre_along_m"], f["shelf_centre_across_m"], -shelf_half[2])
    _box(body, "fixture_shelf", shelf_centre, shelf_half, ".55 .58 .63 1", friction=fmt(f["shelf_friction"]))
    riser_half = f["riser_half_m"]
    _box(body, "fixture_riser", [seated[0]-f["riser_back_m"], seated[1],
                                 0.5*(shelf_top+plate_top-2*plate_half[2])],
         [riser_half[0], riser_half[1], 0.5*abs(plate_top-2*plate_half[2]-shelf_top)], ".5 .52 .57 1")
    column = f["column_half_m"]
    column_centre = at(f["column_along_m"], f["column_across_m"], -shelf_half[2]*2-column[2])
    _box(body, "fixture_column", column_centre, column, ".38 .4 .45 1")

    clip = f["clip"]
    clip_origin = at(clip["along_m"], clip["across_m"], 0.0)
    quaternion = np.empty(4)
    mujoco.mju_mat2Quat(quaternion, np.column_stack([run, side, [0.0, 0.0, 1.0]]).flatten())
    clip_body = ET.SubElement(body, "body", name="fixture_clip", pos=fmt(clip_origin), quat=fmt(quaternion))
    wall = clip["wall_thickness_m"]
    half_width, lip, gap = clip["half_width_m"], clip["lip_height_m"], clip["lip_gap_m"]
    length = clip["length_m"]
    for sign in (1, -1):
        _box(clip_body, f"fixture_clip_wall_{'p' if sign > 0 else 'm'}",
             [0.0, sign*(half_width+0.5*wall), 0.5*lip], [0.5*length, 0.5*wall, 0.5*lip], ".85 .55 .15 1",
             friction=fmt(clip["friction"]))
        _box(clip_body, f"fixture_clip_lip_{'p' if sign > 0 else 'm'}",
             [0.0, sign*0.5*(0.5*gap+half_width), lip+0.5*clip["lip_thickness_m"]],
             [0.5*length, 0.5*(half_width-0.5*gap), 0.5*clip["lip_thickness_m"]], ".9 .62 .2 1",
             friction=fmt(clip["friction"]))

    post = f["post"]
    post_centre = at(post["along_m"], post["across_m"], 0.5*post["height_m"])
    ET.SubElement(body, "geom", name="fixture_post", type="cylinder", pos=fmt(post_centre),
                  size=fmt([post["radius_m"], 0.5*post["height_m"]]), rgba=".75 .25 .3 1",
                  friction=fmt(post["friction"]))
    ET.SubElement(body, "geom", name="fixture_post_cap", type="sphere", pos=fmt(post_centre+np.array([0, 0, 0.5*post["height_m"]])),
                  size=str(post["radius_m"]), rgba=".75 .25 .3 1", friction=fmt(post["friction"]))

    strain = f["strain_relief"]
    anchor_site = at(strain["along_m"], strain["across_m"], strain["height_m"])
    block_centre = anchor_site+run*strain["block_offset_m"]
    anchor_body = ET.SubElement(body, "body", name="strain_relief", pos=fmt(block_centre))
    _box(anchor_body, "fixture_strain_relief", [0.0, 0.0, 0.0], strain["block_half_m"], ".2 .55 .35 1",
         density=str(strain["block_density"]))
    ET.SubElement(anchor_body, "site", name="strain_relief_site",
                  pos=fmt(-run*strain["block_offset_m"]), size=".0015", rgba=".1 .9 .4 1")
    ET.SubElement(anchor_body, "site", name="strain_relief_load", pos="0 0 0", size=".001")
    return {"shelf_top_z": shelf_top, "run_direction_xy": list(run[:2]), "side_direction_xy": list(side[:2]),
            "anchor_site_world": anchor_site.tolist(),
            "clip_origin_world": clip_origin.tolist(),
            "clip_rotation_world": np.column_stack([run, side, [0.0, 0.0, 1.0]]).tolist(),
            "post_centre_world": post_centre.tolist(), "post_radius_m": post["radius_m"],
            "post_top_z": float(post_centre[2]+0.5*post["height_m"]),
            "slack_bow_leg": f["slack_bow_leg"],
            "bow_direction_world": (side*f["slack_bow_across"]+run*f["slack_bow_along"]
                                    + np.array([0.0, 0.0, f["slack_bow_up"]])).tolist(),
            "clip_predicate": {"half_width_m": half_width, "floor_height_m": clip["floor_height_m"],
                               "lip_height_m": lip, "cable_radius_m": cfg["cable"]["radius_m"]},
            "route_waypoints_world": [at(along, across, f["route_height_m"]).tolist()
                                      for along, across in route_waypoints],
            "route_waypoints_along_across_m": [list(p) for p in route_waypoints],
            "plate_top_z": plate_top, "fixture_origin_world": origin.tolist()}


def add_constrained_cable(root, plug_body, cable_cfg: dict, fixture: dict, plug_pose):
    """Attach an inextensible capsule chain clamped at the fixture strain relief.

    Both endpoint equalities are constructed before compilation and are never
    changed during a job. ``flat=true`` keeps the stress-free material straight,
    so the initial bowed vertices do not create a preloaded rest curvature.
    """
    import numpy as np

    extension = root.find("extension")
    if extension is None:
        extension = ET.SubElement(root, "extension")
    ET.SubElement(extension, "plugin", plugin="mujoco.elasticity.cable")
    local = (-cable_cfg["attachment_back_m"], 0, 0)
    ET.SubElement(plug_body, "site", name="plug_cable_anchor", pos=fmt(local), size=".001")
    boot = np.asarray(plug_pose.compose(Pose(local)).position, dtype=float)
    segments, step = cable_cfg["segments"], cable_cfg["segment_length_m"]
    guide, taut = guide_route(boot, fixture, cable_cfg, segments*step)
    floor = fixture["shelf_top_z"]+cable_cfg["radius_m"]+cable_cfg["support_clearance_m"]
    points = fit_chain(guide, segments, step, floor_z=floor)
    # A folded initial chain stores elastic energy that destroys the integration
    # before any job starts. Reject the construction instead of running it.
    turns = chain_turn_angles_deg(points)
    if float(turns.max()) > cable_cfg["max_initial_turn_deg"]:
        raise ValueError(f"Initial cable chain folds: max turn {turns.max():.1f} deg exceeds "
                         f"{cable_cfg['max_initial_turn_deg']} deg; adjust route length or segment count")
    density = capsule_chain_density(cable_cfg["total_mass_kg"], cable_cfg["radius_m"], step, segments)
    composite = ET.SubElement(root.find("worldbody"), "composite", prefix="cable_", type="cable",
                              vertex=fmt(points.flatten()), initial="free")
    plugin = ET.SubElement(composite, "plugin", plugin="mujoco.elasticity.cable")
    for key, value in [("twist", cable_cfg["twist_modulus_pa"]), ("bend", cable_cfg["youngs_modulus_pa"]),
                       ("flat", "true")]:
        ET.SubElement(plugin, "config", key=key, value=str(value))
    ET.SubElement(composite, "joint", kind="main", damping=str(cable_cfg["joint_damping"]))
    ET.SubElement(composite, "geom", type="capsule", size=str(cable_cfg["radius_m"]), density=str(density),
                  rgba=".04 .65 .75 1", friction=fmt(cable_cfg["friction"]))
    ET.SubElement(composite, "site", size=".001")
    equality = root.find("equality")
    if equality is None:
        equality = ET.SubElement(root, "equality")
    solver = {"solref": cable_cfg["endpoint_solref"], "solimp": cable_cfg["endpoint_solimp"]}
    ET.SubElement(equality, "connect", name="plug_boot_connection", site1="plug_cable_anchor",
                  site2="cable_S_first", **solver)
    ET.SubElement(equality, "connect", name="strain_relief_connection", site1="strain_relief_site",
                  site2="cable_S_last", **solver)
    guide_len = route_length(guide)
    return {"initial_vertices_world_m": points.tolist(), "guide_length_m": guide_len, "direct_length_m": taut,
            "rest_length_m": segments*step, "compiled_density_kg_per_m3": density,
            "boot_anchor_world_m": boot.tolist(),
            "max_initial_turn_deg": float(chain_turn_angles_deg(points).max()),
            "material_stress_free": "straight; flat=true", "segment_length_m": step,
            "root_boundary": "Point connect at the boot: force and its lever arm transfer, no direct elastic boot couple.",
            "distal_boundary": "Point connect at the strain relief: a fixed boundary condition, not a validated latched connector."}


def _set_initial_joints(model, data, cfg):
    """Initialization only; the controller never writes qpos."""
    for name, value in zip(ARM_JOINTS, cfg["home_q_rad"], strict=True):
        data.qpos[model.joint(name).qposadr[0]] = value
    for name in ("gripper/left_finger_joint", "gripper/right_finger_joint"):
        data.qpos[model.joint(name).qposadr[0]] = cfg["finger_opening_m"]


@dataclass
class ConstrainedScene:
    model: object
    data: object
    tip_site: int
    port_site: int
    plug_body: int
    arm_dofs: object
    arm_actuators: object
    finger_actuator: int
    initial_tip: object
    target_tip: object
    target_rotation: object
    insertion_axis: object
    cable_bodies: object
    segment_length_m: float
    geom_group: object
    wrist_sensor: tuple
    plug_sensor: tuple
    anchor_sensor: tuple
    anchor_equality: int
    clip_origin: object
    clip_rotation: object
    clip_predicate: dict
    fixture: dict
    detector_geoms: object = None
    report: dict = field(default_factory=dict)


def _sensor(model, name):
    sensor = model.sensor(name)
    return int(sensor.adr[0]), int(sensor.dim[0])


def build_scene(project_root: Path, cfg: dict, case: dict, directory: Path) -> ConstrainedScene:
    """Compile the constrained recovery scene for one registered case."""
    import mujoco
    import numpy as np

    root, robot_report = prepare_native_robot(project_root/".deps/aic", project_root/cfg["robot_mesh_directory"])
    root.set("model", "aic_ur5e_sc_constrained_recovery_v2")
    root.find("compiler").set("autolimits", "true")
    root.find("option").attrib.update(timestep=str(1.0/cfg["clocks"]["physics_hz"]), integrator="implicitfast",
                                      solver="Newton", iterations="100", tolerance="1e-10", cone="elliptic",
                                      gravity="0 0 -9.81")
    ET.SubElement(root.find("default"), "geom", solref="0.004 1", solimp="0.95 0.99 0.001",
                  friction="0.5 0.005 0.0001")
    root.find("visual/global").attrib.update(offwidth="1280", offheight="960")
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
    grasp = Pose(tuple(cfg["plug_origin_in_tool_m"]), Pose(quaternion=plug.frames["sc_tip_link"].quaternion).inverse().quaternion)
    plug.body.attrib.update(grasp.attributes())
    ET.SubElement(plug.body, "site", name="plug_load_sensor", pos="0 0 0", size=".001")
    tool.append(plug.body)
    sensors = root.find("sensor")
    ET.SubElement(sensors, "force", name="plug_load_force", site="plug_load_sensor")
    ET.SubElement(sensors, "torque", name="plug_load_torque", site="plug_load_sensor")
    for i, name in enumerate(ARM_JOINTS):
        limit = cfg["controller"]["joint_torque_limits_nm"][i]
        root.find(f"actuator/general[@joint='{name}']").attrib.update(ctrllimited="true", ctrlrange=f"{-limit} {limit}")
    root.find("actuator/general[@joint='gripper/left_finger_joint']").attrib.update(ctrllimited="true", ctrlrange="-15 15")

    provisional = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    provisional_data = mujoco.MjData(provisional)
    _set_initial_joints(provisional, provisional_data, cfg)
    mujoco.mj_forward(provisional, provisional_data)
    tip_site = provisional.site("plug__frame__sc_tip_link").id
    initial_tip = provisional_data.site_xpos[tip_site].copy()
    tip_rotation = provisional_data.site_xmat[tip_site].reshape(3, 3).copy()
    axis = tip_rotation[:, 2]
    seated = initial_tip+axis*cfg["initial_distance_m"]
    scene_cfg = dict(cfg)
    merged = dict(cfg["fixture"])
    for key, value in case.get("fixture_overrides", {}).items():
        merged[key] = {**merged[key], **value} if isinstance(value, dict) else value
    scene_cfg["fixture"] = merged
    cable_cfg = dict(cfg["cable"], outward_world_xy=case["outward_xy"], **case.get("cable_overrides", {}))
    route_waypoints = case.get("route_waypoints_along_across_m") or merged["route_waypoints_along_across_m"]
    plug_id = provisional.body("plug").id
    plug_pose = Pose(tuple(provisional_data.xpos[plug_id]), tuple(provisional_data.xquat[plug_id]))
    boot_world = plug_pose.compose(Pose((-cable_cfg["attachment_back_m"], 0, 0))).position
    rest = cable_cfg["segments"]*cable_cfg["segment_length_m"]
    loop = case.get("installed_loop_m", merged["installed_loop_m"])
    strain = dict(merged["strain_relief"])
    strain["along_m"] = solve_anchor_along(scene_cfg, seated, case["run_direction_xy"], route_waypoints,
                                           boot_world, cable_cfg, rest-loop)
    merged["strain_relief"] = strain
    scene_cfg["fixture"] = merged
    fixture = build_fixture(world, scene_cfg, seated, case["run_direction_xy"], route_waypoints)
    fixture["installed_loop_m"] = loop
    fixture["solved_anchor_along_m"] = strain["along_m"]
    ET.SubElement(sensors, "force", name="strain_relief_load_force", site="strain_relief_load")
    ET.SubElement(sensors, "torque", name="strain_relief_load_torque", site="strain_relief_load")
    cable_report = add_constrained_cable(root, plug.body, cable_cfg, fixture, plug_pose)
    # The declared local fault moves the fixture; the observed reference follows it.
    goal = seated+tip_rotation[:, :2] @ np.asarray(case.get("fixture_offset_m", [0, 0]))
    quaternion = np.empty(4)
    mujoco.mju_mat2Quat(quaternion, tip_rotation.flatten())
    port.body.attrib.update(Pose(tuple(goal), tuple(quaternion)).compose(port.frames["sc_port_base_link"].inverse()).attributes())
    world.append(port.body)
    scene_path = directory/"scene.xml"
    ET.indent(root)
    scene_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    model = mujoco.MjModel.from_xml_path(str(scene_path))
    data = mujoco.MjData(model)
    _set_initial_joints(model, data, cfg)
    mujoco.mj_forward(model, data)

    name_of = lambda kind, i: mujoco.mj_id2name(model, kind, i) or ""  # noqa: E731
    cable_bodies = np.array([i for i in range(model.nbody)
                             if name_of(mujoco.mjtObj.mjOBJ_BODY, i).startswith("cable_")], dtype=int)

    group = np.full(model.ngeom, GROUP_OTHER, dtype=np.int32)
    robot_bodies = {"shoulder_link", "upper_arm_link", "forearm_link", "wrist_1_link", "wrist_2_link",
                    "wrist_3_link", "ati/tool_link", "gripper/hande_finger_link_l", "gripper/hande_finger_link_r"}
    for g in range(model.ngeom):
        geom, body = name_of(mujoco.mjtObj.mjOBJ_GEOM, g), name_of(mujoco.mjtObj.mjOBJ_BODY, model.geom_bodyid[g])
        if body.startswith("cable_"):
            group[g] = GROUP_CABLE
        elif body == "plug":
            group[g] = GROUP_PLUG
        elif body == "port":
            group[g] = GROUP_PORT
        elif body == "strain_relief":
            group[g] = GROUP_ANCHOR
        elif geom.startswith("fixture_clip"):
            group[g] = GROUP_CLIP
        elif geom.startswith("fixture_post"):
            group[g] = GROUP_POST
        elif geom.startswith("fixture_") or geom == "floor":
            group[g] = GROUP_SHELF
        elif body in robot_bodies:
            group[g] = GROUP_ROBOT
    detector = np.zeros(model.ngeom, dtype=bool)
    for g in range(model.ngeom):
        detector[g] = "contact_collision" in name_of(mujoco.mjtObj.mjOBJ_GEOM, g)

    cable_mass = float(sum(model.body_mass[i] for i in cable_bodies))
    report = {"robot": robot_report, "plug": plug.report, "port": port.report, "scene_xml": str(scene_path),
              "fixed_preset_grasp": True, "grasp_transform": grasp.attributes(), "grasp_strength_validated": False,
              "fixture": fixture, "cable": cable_report, "cable_parameters": cable_cfg,
              "compiled_cable_mass_kg": cable_mass,
              "compiled_cable_mass_error_kg": cable_mass-cable_cfg["total_mass_kg"],
              "initial_contact_count": int(data.ncon),
              "initial_contact_pairs": [{"geom1": model.geom(int(c.geom1)).name, "geom2": model.geom(int(c.geom2)).name,
                                         "distance": float(c.dist)} for c in data.contact],
              "clocks": cfg["clocks"],
              "actor_observations": ["native qpos/qvel", "simulator tip/port/clip/post/anchor frames",
                                     "native wrist and plug force-torque", "cable centerline vertices",
                                     "measured anchor reaction", "model Jacobian and generalized bias force"],
              "observation_limitations": "No camera perception; simulator state and exact model feedforward are idealized.",
              "fixture_scope": "World-fixed infinitely rigid mounting geometry; fixture compliance is not modelled."}
    scene = ConstrainedScene(
        model, data, model.site("plug__frame__sc_tip_link").id, model.site("port__frame__sc_port_base_link").id,
        model.body("plug").id,
        np.array([model.joint(n).dofadr[0] for n in ARM_JOINTS]),
        np.array([model.actuator(n+"_motor").id for n in ARM_JOINTS]),
        int(model.actuator("gripper/left_finger_joint_motor").id),
        initial_tip, goal, tip_rotation, axis, cable_bodies, float(cable_cfg["segment_length_m"]), group,
        _sensor(model, "AtiForceTorqueSensor_force"), _sensor(model, "plug_load_force"),
        _sensor(model, "strain_relief_load_force"),
        int(model.equality("strain_relief_connection").id),
        np.asarray(fixture["clip_origin_world"]), np.asarray(fixture["clip_rotation_world"]),
        fixture["clip_predicate"], fixture, detector, report)
    scene.report["detector_geom_count"] = int(detector.sum())
    return scene


def apply_cartesian_impedance(scene: ConstrainedScene, target_position, target_rotation, cfg: dict):
    """Finite joint torque control; never writes poses, velocities or attachments.

    Called only at registered servo ticks. Between ticks the commanded torque is
    held, so the physical control cadence is independent of the integration step.
    """
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
    data.ctrl[scene.arm_actuators] = np.clip(joint_torque, -limits, limits)
    finger = model.joint("gripper/left_finger_joint")
    opening = cfg["finger_opening_m"]
    data.ctrl[scene.finger_actuator] = float(np.clip(
        1000*(opening-data.qpos[finger.qposadr[0]])-5*data.qvel[finger.dofadr[0]], -15, 15))
    return {"force_command": force, "torque_command": torque,
            "joint_torque_saturated": bool(np.any(np.abs(joint_torque) > limits)),
            "commanded_force_norm_n": float(np.linalg.norm(force))}


def raw_loads(scene: ConstrainedScene):
    """Native-rate abort channels: three direct sensor reads, no contact loop."""
    import numpy as np

    sensordata = scene.data.sensordata
    out = []
    for adr, dim in (scene.wrist_sensor, scene.plug_sensor, scene.anchor_sensor):
        out.append(float(np.linalg.norm(sensordata[adr:adr+dim])))
    return out


def measure_loads(scene: ConstrainedScene) -> dict:
    """Grouped contact witnesses and signed resultants at a registered sample.

    ``*_contact_n`` are sums of contact force norms: positive contact witnesses,
    never net forces. ``*_resultant_world_n`` are signed vector sums in world
    coordinates, with the sign convention verified by the known-load controls.
    """
    import mujoco
    import numpy as np

    model, data = scene.model, scene.data
    group = scene.geom_group
    sums = dict.fromkeys(LOAD_KEYS, 0.0)
    resultants = {"cable_clip": np.zeros(3), "cable_post": np.zeros(3), "plug_port": np.zeros(3)}
    detector = scene.detector_geoms
    wrench = np.zeros(6)
    for k in range(data.ncon):
        contact = data.contact[k]
        g1, g2 = int(contact.geom1), int(contact.geom2)
        a, b = int(group[g1]), int(group[g2])
        mujoco.mj_contactForce(model, data, k, wrench)
        magnitude = float(np.linalg.norm(wrench[:3]))
        pair = (a, b) if a <= b else (b, a)
        if pair == (GROUP_PLUG, GROUP_PORT):
            sums["plug_port_contact_n"] += magnitude
            resultants["plug_port"] += contact.frame.reshape(3, 3).T @ wrench[:3]
            if detector[g1] or detector[g2]:
                sums["port_detector_contact_n"] += magnitude
        elif pair == (GROUP_CABLE, GROUP_CLIP):
            sums["cable_clip_contact_n"] += magnitude
            resultants["cable_clip"] += contact.frame.reshape(3, 3).T @ wrench[:3]
        elif pair == (GROUP_CABLE, GROUP_POST):
            sums["cable_post_contact_n"] += magnitude
            resultants["cable_post"] += contact.frame.reshape(3, 3).T @ wrench[:3]
        elif pair == (GROUP_CABLE, GROUP_SHELF) or pair == (GROUP_CABLE, GROUP_ANCHOR):
            sums["cable_shelf_contact_n"] += magnitude
        elif pair in ((GROUP_CABLE, GROUP_ROBOT), (GROUP_PLUG, GROUP_CABLE)):
            sums["cable_robot_contact_n"] += magnitude
        else:
            sums["other_contact_n"] += magnitude
    wrist, plug, anchor = raw_loads(scene)
    sums["raw_wrist_load_n"], sums["raw_plug_load_n"], sums["anchor_load_n"] = wrist, plug, anchor
    sums["anchor_constraint_world_n"] = anchor_constraint_force(scene).tolist()
    for key, value in resultants.items():
        sums[key+"_resultant_world_n"] = value.tolist()
    return sums


def anchor_constraint_force(scene: ConstrainedScene):
    """World-frame reaction carried by the strain-relief equality constraint.

    Read from the active constraint rows rather than inferred, and cross-checked
    against the strain-relief force sensor by the known-load positive control.
    """
    import mujoco
    import numpy as np

    data = scene.data
    rows = np.flatnonzero((data.efc_type[:data.nefc] == mujoco.mjtConstraint.mjCNSTR_EQUALITY)
                          & (data.efc_id[:data.nefc] == scene.anchor_equality))
    if rows.size != 3:
        return np.zeros(3)
    return data.efc_force[rows].copy()


def cable_centerline(scene: ConstrainedScene):
    """World cable vertices from boot to strain relief, in cable arclength order.

    The composite exposes only endpoint sites, so vertices come from the ordered
    capsule body frames plus the far end of the last capsule.
    """
    import numpy as np

    data = scene.data
    points = data.xpos[scene.cable_bodies].copy()
    last = scene.cable_bodies[-1]
    end = data.xpos[last]+data.xmat[last].reshape(3, 3) @ np.array([scene.segment_length_m, 0.0, 0.0])
    return np.vstack([points, end])


def clip_state(scene: ConstrainedScene, centerline=None) -> dict:
    """Geometric passage of the cable centerline through the open clip channel."""
    import numpy as np

    points = cable_centerline(scene) if centerline is None else centerline
    local = (np.asarray(points)-scene.clip_origin) @ scene.clip_rotation
    return clip_passages(local.tolist(), **scene.clip_predicate)


class MutationGuard:
    """Fail-closed detector for forbidden within-job state and model changes.

    Counts any controller-side pose/velocity write, native clock rewind, change
    of equality or actuator definition, or contact-model edit. Simulator
    integration is expected to change state; reinitialization inside a job is not.
    """

    FIELDS = ("eq_active0", "eq_obj1id", "eq_obj2id", "eq_data", "eq_type",
              "actuator_ctrllimited", "actuator_ctrlrange", "geom_contype", "geom_conaffinity",
              "body_mass", "dof_damping")

    def __init__(self, scene: ConstrainedScene):
        import numpy as np

        self.scene = scene
        self._model = {k: np.array(getattr(scene.model, k), copy=True) for k in self.FIELDS}
        self._model["opt.gravity"] = np.array(scene.model.opt.gravity, copy=True)
        self._time = float(scene.data.time)
        self._qpos = np.array(scene.data.qpos, copy=True)
        self._qvel = np.array(scene.data.qvel, copy=True)
        self.events = 0
        self.reasons: list[str] = []

    def before_control(self):
        """Snapshot the authoritative post-integration state before a controller call."""
        import numpy as np

        data = self.scene.data
        if float(data.time) < self._time-1e-12:
            self._fail("native_clock_rewind")
        self._time = float(data.time)
        self._qpos = np.array(data.qpos, copy=True)
        self._qvel = np.array(data.qvel, copy=True)

    def after_control(self) -> int:
        """Fail closed on any controller-side state, model or attachment write."""
        import numpy as np

        data, model = self.scene.data, self.scene.model
        for key, saved in self._model.items():
            current = model.opt.gravity if key == "opt.gravity" else getattr(model, key)
            if not np.array_equal(np.asarray(current), saved):
                self._fail(f"model_field_changed:{key}")
        if float(data.time) != self._time:
            self._fail("controller_moved_native_clock")
        if not np.array_equal(data.qpos, self._qpos):
            self._fail("controller_wrote_qpos")
        if not np.array_equal(data.qvel, self._qvel):
            self._fail("controller_wrote_qvel")
        return self.events

    def _fail(self, reason: str):
        self.events += 1
        if reason not in self.reasons:
            self.reasons.append(reason)

    def report(self) -> dict:
        return {"forbidden_events": self.events, "reasons": self.reasons,
                "checked_model_fields": list(self.FIELDS),
                "scope": "Checked around every controller call: controller pose/velocity/clock writes and equality, "
                         "actuator, contact-model, mass or damping edits. Integration between checks is expected; "
                         "reinitialization inside a job is not."}
