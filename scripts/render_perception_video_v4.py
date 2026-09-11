"""Render honest videos of the perception study: what is true, beside what is seen.

The point of the study is that a controller and every predictor read an ESTIMATE
while the constraints are scored against truth. A still figure cannot show that.
These videos can: the rendered scene carries ghost markers at the estimated
socket pose and along the estimated cable centreline, with the occluded nodes
drawn differently from the visible ones, and a side panel tracks the three
constraints live against their declared limits.

Two stages, in this order:

``capture``  Re-runs a named registered request with its registered seeds and
             records the state densely. It runs the same scene, the same
             controller, the same estimate and the same scorer as the study
             worker, and the capture record asserts that the outcome it reaches
             matches the outcome the block recorded for that request. A video of
             a different rollout would be a picture of nothing.
``render``   Replays the captured states offline - no ``mj_step`` - and encodes.
             Displayed numbers come from the capture, not from anything recomputed
             at render time.

Videos are written under ``artifacts/cable/video-v4``, which is an ignored output
directory. Nothing here is a study result.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import imageio_ffmpeg
import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_constrained_v2 import (  # noqa: E402
    apply_cartesian_impedance,
    build_scene,
    cable_centerline,
    clip_state,
    measure_loads,
    raw_loads,
)
from assembly_recovery.cable_constraints_v4 import ConstraintScorer  # noqa: E402
from assembly_recovery.cable_jobs import CableJob, CableJobLimits, CableSample  # noqa: E402
from assembly_recovery.cable_perception_v4 import EpisodePerception  # noqa: E402
from assembly_recovery.cable_recovery_control_v2 import (  # noqa: E402
    ForceGuidedInsertion,
    RecoveryObservation,
    parametric_macro,
    repair_library,
)
from assembly_recovery.cable_study_v4 import build_cases, merge_runtime  # noqa: E402
from scripts.evaluate_cable_perception_v4 import (  # noqa: E402
    effective_level,
    estimated_observation,
)
from scripts.evaluate_cable_recovery_v2 import clip_margin, settle, wrist_world  # noqa: E402

BG = (14, 20, 27)
PANEL = (21, 31, 42)
WHITE = (236, 244, 247)
MUTED = (150, 170, 186)
GREEN = (86, 209, 176)
AMBER = (255, 179, 106)
RED = (240, 106, 106)
BLUE = (110, 170, 245)

VIEWS = {
    "overview": {"distance": 0.92, "azimuth": 128, "elevation": -22, "offset": (0.11, -0.02, -0.10)},
    "clip": {"distance": 0.30, "azimuth": 140, "elevation": -26, "offset": (0.0, 0.0, 0.0)},
}


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/" + ("segoeuib.ttf" if bold else "segoeui.ttf"),
                                  size)
    except OSError:
        return ImageFont.load_default()


def capture(case: dict, runtime: dict, contract: dict, out_dir: Path, capture_hz: float) -> dict:
    """Re-run one registered request, recording the state densely.

    The control path here is the study worker's control path: the same scene, the
    same estimate, the same controller and the same scorer. What is added is a
    dense record of qpos, of the estimated centreline and of the estimated socket
    pose, which the study ledger does not carry because 16,080 requests could not
    afford it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    runtime = {**runtime, "clocks": {**runtime["clocks"], **case.get("clocks_override", {})},
               "cable": {**runtime["cable"], **case.get("cable_overrides", {})}}
    scene = build_scene(ROOT, runtime, case, out_dir)
    data = scene.data
    physics = runtime["clocks"]["physics_hz"]
    dt = 1.0/physics
    servo_every = round(physics/runtime["clocks"]["servo_hz"])
    policy_every = round(physics/runtime["clocks"]["policy_hz"])
    every = max(1, round(physics/capture_hz))
    limits = CableJobLimits(**{**runtime["job_limits"], **case.get("job_limits_override", {})})
    job = CableJob(limits)
    settle_steps, settled, settle_reason = settle(scene, runtime)
    bias = wrist_world(scene).copy()

    level = effective_level(runtime, case)
    node_count = len(cable_centerline(scene))
    perception = EpisodePerception(level, scene.fixture, runtime["perception"]["camera"],
                                   int(case["perception_seed"]), servo_every*dt, node_count)
    constraints = runtime["constraints"]
    scorer = ConstraintScorer(
        bend_radius_spec_m=float(constraints["C2_bend"]["spec_m"]),
        anchor_limit_n=float(constraints["C3_anchor"]["limit_n"]),
        bend_radius_secondary_m=float(constraints["C2_bend"]["secondary_m"]),
        anchor_secondary_n=float(constraints["C3_anchor"]["secondary_n"]),
        segment_length_m=float(runtime["cable"]["segment_length_m"]),
        max_turn_deg=float(runtime["cable"]["max_initial_turn_deg"]))

    macros = repair_library(runtime["repair_library"])
    macros["parametric"] = parametric_macro(case["repair_action"])
    run_direction = np.array([*case["run_direction_xy"], 0.0])
    estimated_axis = perception.insertion_axis(scene.insertion_axis)
    controller = ForceGuidedInsertion(runtime["force_guided_controller"], scene.initial_tip,
                                      estimated_axis)
    target = scene.initial_tip.copy()
    axis, initial_tip = scene.insertion_axis, scene.initial_tip
    cable_bodies = np.asarray(scene.cable_bodies)
    repair_start_tip = None
    frames: list[dict] = []
    phase = "align"
    total = round(limits.deadline_s*physics) if settled else 0
    repair_at = None

    for i in range(total):
        job_time = i*dt
        if i % servo_every == 0:
            centreline = cable_centerline(scene)
            state = clip_state(scene, centreline)
            loads = measure_loads(scene)
            reaction = np.asarray(loads["anchor_constraint_world_n"])
            truth = RecoveryObservation(
                job_time, data.site_xpos[scene.tip_site].copy(),
                data.site_xmat[scene.tip_site].reshape(3, 3).copy(),
                data.site_xpos[scene.port_site].copy(), axis, wrist_world(scene).copy(), bias,
                loads["plug_port_contact_n"], loads["cable_clip_contact_n"],
                loads["cable_post_contact_n"], reaction, centreline,
                state["has_retained_passage"], clip_margin(scene, state, centreline),
                job.first_witness_s is not None)
            perception.advance()
            estimate, weights = estimated_observation(scene, perception, truth, None)
            progress = (0.0 if repair_start_tip is None
                        else float(np.linalg.norm(truth.tip_position-repair_start_tip)))
            scorer.update(centreline, float(np.linalg.norm(reaction)),
                          bool(state["has_retained_passage"]), progress)
            if level.process_force_n:
                data.xfrc_applied[cable_bodies, :3] = (perception.process_force_world_n
                                                       / len(cable_bodies))
            if i % policy_every == 0:
                due = job_time >= (case.get("forced_macro_at_s") or 0.0)
                if (due and not controller.repairs_started
                        and controller.request_repair(macros[case["forced_macro"]],
                                                      estimate.tip_position, run_direction,
                                                      job_time)):
                    repair_start_tip = np.asarray(truth.tip_position, dtype=float).copy()
                    repair_at = job_time
                target, phase, _ = controller.step(estimate, policy_every*dt)
            apply_cartesian_impedance(scene, target, scene.target_rotation, runtime["controller"])
            sample = CableSample(
                job_time+servo_every*dt, servo_every*dt,
                float(np.linalg.norm(truth.tip_position-truth.seated_position)), 0.0,
                float((truth.tip_position-initial_tip) @ axis),
                float((target-initial_tip) @ axis),
                loads["raw_wrist_load_n"], loads["raw_plug_load_n"],
                float(np.linalg.norm(reaction)), loads["plug_port_contact_n"],
                loads["cable_post_contact_n"], bool(state["has_retained_passage"]), True,
                loads["port_detector_contact_n"] > limits.contact_witness_n, 0)
            job.update(sample)
            if not state["has_retained_passage"] and job.status == "active":
                job.fail("lost_required_clip")
            elif getattr(controller, "terminal", False) and job.status == "active":
                job.fail("controller_"+phase)
            if i % every == 0:
                frames.append({
                    "t": job_time, "qpos": data.qpos.copy(),
                    "truth_line": np.asarray(centreline, dtype=float).copy(),
                    "estimate_line": np.asarray(estimate.cable_centerline, dtype=float).copy(),
                    "weights": np.asarray(weights, dtype=float).copy(),
                    "truth_socket": np.asarray(truth.seated_position, dtype=float).copy(),
                    "estimate_socket": np.asarray(estimate.seated_position, dtype=float).copy(),
                    "min_bend_radius": scorer.min_bend_radius_m,
                    "peak_anchor": scorer.peak_anchor_n,
                    "anchor": float(np.linalg.norm(reaction)),
                    "clip": bool(state["has_retained_passage"]),
                    "wrist": float(loads["raw_wrist_load_n"]),
                    "phase": phase, "progress": progress,
                })
        mujoco.mj_step(scene.model, data)
        wrist, plug, anchor = raw_loads(scene)
        if wrist > limits.wrist_force_n or plug > limits.plug_force_n:
            job.fail("force_abort")
        elif anchor > limits.anchor_force_n:
            job.fail("prior_connection_load_abort")
        if job.status != "active":
            break
    data.xfrc_applied[:] = 0.0
    if job.status == "active" and settled:
        job.fail("deadline")
    mujoco.mj_forward(scene.model, data)
    terminal = clip_state(scene)
    move_completed = bool(settled and controller.repairs_started
                          and job.failure_reason not in ("force_abort", "prior_connection_load_abort",
                                                         "nonfinite_dynamics", "deadline"))
    labels = scorer.labels(move_completed, terminal["has_retained_passage"])
    record = {
        "case": case["id"], "error_level": case["error_level"],
        "declared_level": {k: v for k, v in level.__dict__.items()},
        "job_status": job.status, "failure_reason": job.failure_reason,
        "settled": settled, "settle_reason": settle_reason,
        "settle_native_steps": settle_steps,
        "repair_requested_at_s": repair_at,
        "constraints": labels, "constraint_report": scorer.report(),
        "terminal_clip_retained": terminal["has_retained_passage"],
        "frames": len(frames), "capture_hz": capture_hz,
        "scene_xml": str((out_dir / "scene.xml").relative_to(ROOT)),
    }
    np.savez_compressed(
        out_dir / "capture.npz",
        t=np.asarray([f["t"] for f in frames]),
        qpos=np.asarray([f["qpos"] for f in frames]),
        truth_line=np.asarray([f["truth_line"] for f in frames]),
        estimate_line=np.asarray([f["estimate_line"] for f in frames]),
        weights=np.asarray([f["weights"] for f in frames]),
        truth_socket=np.asarray([f["truth_socket"] for f in frames]),
        estimate_socket=np.asarray([f["estimate_socket"] for f in frames]),
        min_bend_radius=np.asarray([f["min_bend_radius"] for f in frames]),
        peak_anchor=np.asarray([f["peak_anchor"] for f in frames]),
        anchor=np.asarray([f["anchor"] for f in frames]),
        clip=np.asarray([f["clip"] for f in frames]),
        wrist=np.asarray([f["wrist"] for f in frames]),
        progress=np.asarray([f["progress"] for f in frames]),
        phase=np.asarray([f["phase"] for f in frames]),
    )
    (out_dir / "capture.json").write_text(json.dumps(record, indent=2, allow_nan=False,
                                                     default=float), encoding="utf-8")
    return record


def add_marker(scene_view, position, size, rgba):
    """Append one visual sphere to an already-updated MjvScene."""
    if scene_view.ngeom >= scene_view.maxgeom:
        return
    geom = scene_view.geoms[scene_view.ngeom]
    mujoco.mjv_initGeom(geom, mujoco.mjtGeom.mjGEOM_SPHERE, np.array([size, 0.0, 0.0]),
                        np.asarray(position, dtype=float), np.eye(3).flatten(),
                        np.asarray(rgba, dtype=np.float32))
    scene_view.ngeom += 1


def render(directory: Path, out_path: Path, contract: dict, fps: int, view: str,
           width: int, height: int) -> dict:
    record = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
    archive = np.load(directory / "capture.npz", allow_pickle=False)
    model = mujoco.MjModel.from_xml_path(str(directory / "scene.xml"))
    data = mujoco.MjData(model)
    tip = model.site("plug__frame__sc_tip_link").id
    spec = VIEWS[view]
    scene_width = int(width*0.66)
    renderer = mujoco.Renderer(model, width=scene_width, height=height)
    renderer.scene.maxgeom = max(renderer.scene.maxgeom, 4000)
    options = mujoco.MjvOption()
    options.geomgroup[3] = 1
    camera = mujoco.MjvCamera()
    c2_spec = float(contract["constraints"]["C2_bend"]["spec_m"])
    c3_limit = float(contract["constraints"]["C3_anchor"]["limit_n"])
    big, mid, small = font(21, True), font(15), font(13)

    writer = imageio_ffmpeg.write_frames(str(out_path), (width, height), fps=fps, quality=8,
                                         macro_block_size=1)
    writer.send(None)
    count = len(archive["t"])
    for index in range(count):
        data.qpos[:] = archive["qpos"][index]
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)
        camera.lookat[:] = data.site_xpos[tip]+np.asarray(spec["offset"])
        camera.distance = spec["distance"]
        camera.azimuth, camera.elevation = spec["azimuth"], spec["elevation"]
        renderer.update_scene(data, camera=camera, scene_option=options)
        weights = archive["weights"][index]
        for node, point in enumerate(archive["estimate_line"][index]):
            hidden = weights[node] > 0.5
            add_marker(renderer.scene, point, 0.0035 if hidden else 0.0025,
                       (1.0, 0.42, 0.42, 0.85) if hidden else (0.43, 0.67, 0.96, 0.65))
        add_marker(renderer.scene, archive["estimate_socket"][index], 0.006, (1.0, 0.7, 0.25, 0.9))
        add_marker(renderer.scene, archive["truth_socket"][index], 0.004, (0.34, 0.82, 0.69, 0.9))
        pixels = renderer.render()

        frame = Image.new("RGB", (width, height), BG)
        frame.paste(Image.fromarray(pixels), (0, 0))
        draw = ImageDraw.Draw(frame)
        x0 = scene_width+16
        draw.rectangle([scene_width, 0, width, height], fill=PANEL)
        level = record["declared_level"]
        offset = float(np.linalg.norm(archive["estimate_socket"][index]
                                      - archive["truth_socket"][index]))
        radius = float(archive["min_bend_radius"][index])
        lines = [
            (big, WHITE, record["case"]),
            (small, MUTED, f"t = {archive['t'][index]:6.2f} s      phase {archive['phase'][index]}"),
            (small, MUTED, ""),
            (mid, WHITE, f"perception level {record['error_level']}"),
            (small, MUTED, f"declared socket bias   {1000*level['socket_bias_m']:.2f} mm"),
            (small, MUTED, f"declared occluded node {1000*level['centreline_occluded_m']:.2f} mm"),
            (small, AMBER, f"socket estimate is off by {1000*offset:.2f} mm"),
            (small, MUTED, ""),
            (mid, WHITE, "constraints, scored against truth"),
            (small, GREEN if archive["clip"][index] else RED,
             f"C1 clip retained        {'yes' if archive['clip'][index] else 'NO'}"),
            (small, GREEN if radius >= c2_spec else RED,
             f"C2 min bend radius      {1000*radius:6.1f} mm   limit {1000*c2_spec:.0f}"),
            (small, GREEN if archive["peak_anchor"][index] <= c3_limit else RED,
             f"C3 peak anchor load     {archive['peak_anchor'][index]:6.3f} N    limit {c3_limit:.2f}"),
            (small, MUTED, f"wrist load              {archive['wrist'][index]:6.2f} N"),
            (small, MUTED, f"detour travelled        {1000*archive['progress'][index]:6.1f} mm"),
            (small, MUTED, ""),
            (small, BLUE, "blue  estimated cable node"),
            (small, (255, 107, 107), "red   estimated node the fixture hides"),
            (small, AMBER, "amber estimated socket pose"),
            (small, GREEN, "green true socket pose"),
        ]
        y = 18
        for typeface, colour, text in lines:
            if text:
                draw.text((x0, y), text, font=typeface, fill=colour)
            y += typeface.size+8 if text else 6
        draw.text((x0, height-46),
                  "Simulation only. The error model is a model of how perception fails,",
                  font=small, fill=MUTED)
        draw.text((x0, height-28), "not camera perception. No hardware claim.",
                  font=small, fill=MUTED)
        writer.send(np.asarray(frame))
    writer.close()
    renderer.close()
    return {"video": str(out_path.relative_to(ROOT)), "frames": count, "fps": fps,
            "bytes": out_path.stat().st_size, "case": record["case"],
            "outcome": record["failure_reason"] or "completed",
            "constraints": {k: v["state"] for k, v in record["constraints"].items()}}


def block_outcome(case_id: str, run_dirs) -> dict | None:
    for run_dir in run_dirs:
        path = ROOT / run_dir / case_id / "result.json"
        if path.is_file():
            result = json.loads(path.read_text(encoding="utf-8"))
            return {"failure_reason": result["job"]["failure_reason"],
                    "constraints": {k: v["state"] for k, v in result["constraints"].items()}}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--case", action="append", required=True,
                        help="A registered request id. Repeat for several videos.")
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/cable/video-v4"))
    parser.add_argument("--run-dir", type=Path, action="append", default=None,
                        help="Executed shard to check the captured outcome against.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--capture-hz", type=float, default=30.0)
    parser.add_argument("--view", default="overview", choices=sorted(VIEWS))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    base = json.loads((ROOT / contract["base_config"]["path"]).read_text(encoding="utf-8-sig"))
    runtime = merge_runtime(base, contract)
    cases = {case["id"]: case for case in build_cases(contract)}
    out_root = ROOT / args.out_dir
    out_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    videos = []
    for case_id in args.case:
        if case_id not in cases:
            parser.error(f"{case_id} is not a registered request")
        directory = out_root / case_id
        record = capture(cases[case_id], runtime, contract, directory, args.capture_hz)
        reference = block_outcome(case_id, args.run_dir or [])
        record["block_outcome"] = reference
        record["reproduces_block"] = (
            None if reference is None
            else bool(reference["failure_reason"] == record["failure_reason"]
                      and reference["constraints"] == {k: v["state"]
                                                       for k, v in record["constraints"].items()}))
        (directory / "capture.json").write_text(
            json.dumps(record, indent=2, allow_nan=False, default=float), encoding="utf-8")
        video = render(directory, out_root / f"{case_id}__{args.view}.mp4", contract, args.fps,
                       args.view, args.width, args.height)
        video["reproduces_block"] = record["reproduces_block"]
        videos.append(video)
        print(json.dumps(video), flush=True)

    summary = {"videos": videos, "wall_seconds": round(time.monotonic()-started, 1),
               "view": args.view,
               "scope": "Offline replay of recorded states. No mj_step is called at render time. "
                        "Simulation only; not a hardware claim."}
    (out_root / "videos.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
