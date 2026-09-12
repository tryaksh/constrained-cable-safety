"""Replay clips of the routing block: the rollout the block scored, rendered offline.

The routing result is a claim about what three supervisors do with the same
information in the same cell, and a table cannot show it. These clips can.

Two stages, in this order, the same shape scripts/render_perception_video_v4.py
established for the perception study:

``capture``  Re-runs a named registered route with its registered seeds and
             records the state densely. It does NOT re-implement the worker's
             loop - it calls ``scripts.evaluate_cable_routing_v6.run_case`` with
             a per-tick observer, so there is exactly one control path and one
             perception stream. A replay that drew one extra random number would
             be a picture of a rollout that never happened; with one loop that
             cannot occur, and ``reproduces_block`` checks it anyway against the
             request the block already scored.
``render``   Replays the captured states offline - no ``mj_step`` at render time
             - and encodes. Every number drawn comes from the capture or from the
             block's own ``result.json``, never from anything recomputed here.

Three layouts, one per thing worth seeing:

``triptych`` One cell, one estimate, three supervisors in one frame.
``estimate`` What the supervisor reads against what is true, with the nodes the
             fixture hides drawn differently from the ones it does not.
``budget``   The clip budget draining: what the filter reports at each decision
             and what the issued motion spends of it.

Videos go under ``artifacts/showcase/video``, an ignored output directory.
Nothing here is a study result and nothing here refits anything.
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
from scripts.evaluate_cable_routing_v6 import run_case  # noqa: E402

BG = (13, 18, 25)
PANEL = (20, 29, 40)
RULE = (44, 58, 74)
WHITE = (237, 244, 248)
MUTED = (147, 166, 183)
GREEN = (86, 209, 176)
AMBER = (255, 179, 106)
RED = (240, 106, 106)
VIOLET = (199, 161, 242)

#: Registered cameras over the routing cell. ``look`` names what each frames:
#: the mean of the five clip origins, the clip at the top of the ridge, or the
#: plug tip as it retreats.
VIEWS = {
    "route": {"distance": 0.40, "azimuth": 138, "elevation": -20,
              "offset": (0.05, 0.0, 0.04), "look": "clips"},
    "clips": {"distance": 0.33, "azimuth": 138, "elevation": -18,
              "offset": (0.02, 0.0, 0.03), "look": "clips"},
    "ridge": {"distance": 0.18, "azimuth": 132, "elevation": -14,
              "offset": (0.0, 0.0, 0.010), "look": "ridge"},
    # Wide enough to hold the plug, the whole cable run and the clamp at once,
    # which is what the estimate-against-truth clip has to show.
    "wide": {"distance": 0.46, "azimuth": 138, "elevation": -20,
             "offset": (0.04, 0.0, 0.05), "look": "clips"},
}

#: How far above a clip origin its state marker floats. Far enough to read, near
#: enough that nobody mistakes it for part of the jig.
MARKER_UP_M = 0.016

#: Which supervisor is which, in the words the page uses.
SUPERVISOR_LABEL = {
    "unfiltered": ("no check", "largest move, every time"),
    "filtered": ("the check", "largest move it calls safe"),
    "conservative": ("the check, read for ranking", "move with the most headroom"),
}

FOOTER = ("Simulation only. The error model is a model of how perception fails, "
          "not camera perception. No hardware claim.")


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def font(size: int, bold: bool = False):
    for name in (("segoeuib.ttf", "seguisb.ttf") if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/"+name, size)
        except OSError:
            continue
    return ImageFont.load_default()


# --------------------------------------------------------------------------- capture

def capture(case_id: str, runtime: dict, out_dir: Path, capture_hz: float,
            block_dir: Path) -> dict:
    """Re-run one registered route, recording dense state from the worker's own loop."""
    case = next((c for c in runtime["cases"] if c["id"] == case_id), None)
    if case is None:
        raise SystemExit(f"{case_id} is not a registered request")
    out_dir.mkdir(parents=True, exist_ok=True)
    stride = max(1, round(runtime["clocks"]["servo_hz"]/capture_hz))
    frames: list[dict] = []
    geometry: dict = {}

    def observer(tick: dict) -> None:
        if not geometry:
            # Where the clips actually ended up in the compiled world, so a camera
            # can be aimed at them without guessing at geom names.
            geometry["clip_origins_world"] = [list(map(float, c["origin_world"]))
                                              for c in tick["scene"].clips]
            geometry["clip_ids"] = [c["id"] for c in tick["scene"].clips]
        if tick["tick"] % stride:
            return
        scene, scorer = tick["scene"], tick["scorer"]
        state, loads = tick["state"], tick["loads"]
        frames.append({
            "t": tick["time_s"],
            "qpos": scene.data.qpos.copy(),
            "truth_line": np.asarray(tick["centreline"], dtype=float),
            "estimate_line": np.asarray(tick["estimate"].cable_centerline, dtype=float),
            "weights": np.asarray(tick["weights"], dtype=float),
            "truth_socket": np.asarray(tick["truth"].seated_position, dtype=float),
            "estimate_socket": np.asarray(tick["estimate"].seated_position, dtype=float),
            "min_bend_radius": float(scorer.min_bend_radius_m),
            "peak_anchor": float(scorer.peak_anchor_n),
            "anchor": float(loads["anchor_load_n"]),
            "wrist": float(loads["raw_wrist_load_n"]),
            "clips": np.asarray([c["has_retained_passage"] for c in state["per_clip"]], dtype=bool),
            "required_retained": int(state["summary"]["required_retained"]),
            "step_index": int(tick["step_index"]),
            "progress": float(tick["progress"]),
            "phase": tick["phase"],
        })

    started = time.monotonic()
    outcome = run_case(runtime, case, out_dir, observer)
    wall = time.monotonic()-started

    np.savez_compressed(
        out_dir / "capture.npz",
        **{key: np.asarray([f[key] for f in frames])
           for key in ("t", "qpos", "truth_line", "estimate_line", "weights", "truth_socket",
                       "estimate_socket", "min_bend_radius", "peak_anchor", "anchor", "wrist",
                       "clips", "required_retained", "step_index", "progress", "phase")})

    reference = block_dir / case_id / "result.json"
    block = json.loads(reference.read_text(encoding="utf-8")) if reference.is_file() else None
    record = {
        "case": case_id, "supervisor": outcome["supervisor"],
        "error_level": outcome["error_level"],
        "cell": {**outcome["cell"], **geometry},
        "frames": len(frames), "capture_hz": capture_hz,
        "stride_servo_ticks": stride,
        "failure_reason": outcome["job"]["failure_reason"],
        "route_completed": outcome["route_completed"], "seated": outcome["seated"],
        "elapsed_s": outcome["job"]["elapsed_s"],
        "terminal_clips": outcome["terminal_clips"],
        "clip_loss_attribution": outcome["clip_loss_attribution"],
        "wall_seconds": round(wall, 1),
        "block_result": relative(reference),
        **compare(outcome, block),
    }
    (out_dir / "capture.json").write_text(json.dumps(record, indent=2, allow_nan=False,
                                                     default=float), encoding="utf-8")
    return record


def signature(result: dict) -> dict:
    """The part of a request's outcome a replay has to reproduce exactly."""
    return {
        "failure_reason": result["job"]["failure_reason"],
        "elapsed_s": round(float(result["job"]["elapsed_s"]), 6),
        "route_completed": bool(result["route_completed"]),
        "seated": bool(result["seated"]),
        "terminal_clips": result["terminal_clips"],
        "clip_loss_attribution": {k: {"time_s": round(float(v["time_s"]), 6),
                                      "during_step": v["during_step"]}
                                  for k, v in result["clip_loss_attribution"].items()},
        "constraints": {k: v["state"] for k, v in result["constraints"].items()},
        "issued": [{"step": r["step"], "time_s": round(float(r["time_s"]), 6),
                    "action_index": r["action_index"],
                    "magnitude_m": None if r["magnitude_m"] is None
                    else round(float(r["magnitude_m"]), 9),
                    "headroom_m": None if r["headroom_m"] is None
                    else round(float(r["headroom_m"]), 9),
                    "motion_completed": r["motion_completed"]}
                   for r in result["issued"]],
    }


def compare(outcome: dict, block: dict | None) -> dict:
    """Does this replay reproduce the request the block scored?"""
    if block is None:
        return {"reproduces_block": None, "block_signature": None, "replay_signature": None,
                "mismatch": "the block result for this request is not on disk"}
    mine, theirs = signature(outcome), signature(block)
    differing = sorted(k for k in theirs if mine.get(k) != theirs[k])
    return {"reproduces_block": not differing,
            "block_signature": theirs, "replay_signature": mine,
            "mismatch": differing or None}


# --------------------------------------------------------------------------- render

class Panel:
    """One captured route, ready to be drawn into a frame."""

    def __init__(self, directory: Path, width: int, height: int, view: str):
        self.dir = directory
        self.record = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
        self.result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        self.archive = np.load(directory / "capture.npz", allow_pickle=False)
        self.model = mujoco.MjModel.from_xml_path(str(directory / "scene.xml"))
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, width=width, height=height)
        self.renderer.scene.maxgeom = max(self.renderer.scene.maxgeom, 6000)
        self.options = mujoco.MjvOption()
        self.options.geomgroup[3] = 1
        self.camera = mujoco.MjvCamera()
        self.spec = VIEWS[view]
        self.origins = np.asarray(self.record["cell"]["clip_origins_world"], dtype=float)
        self.frames = len(self.archive["t"])

    def close(self):
        self.renderer.close()

    def look_at(self, index: int, origins: np.ndarray) -> np.ndarray:
        if self.spec["look"] == "ridge":
            return origins[2]
        return origins.mean(axis=0)

    def image(self, index: int, origins: np.ndarray, ghosts: bool,
              markers: bool = True, lost: tuple = ()) -> Image.Image:
        index = min(index, self.frames-1)
        self.data.qpos[:] = self.archive["qpos"][index]
        self.data.qvel[:] = 0.0
        mujoco.mj_forward(self.model, self.data)
        self.camera.lookat[:] = self.look_at(index, origins)+np.asarray(self.spec["offset"])
        self.camera.distance = self.spec["distance"]
        self.camera.azimuth, self.camera.elevation = self.spec["azimuth"], self.spec["elevation"]
        self.renderer.update_scene(self.data, camera=self.camera, scene_option=self.options)
        if markers:
            # One bead per clip, green while the cable is still through it. The
            # count in the caption is the same array; the bead says WHICH.
            held = self.archive["clips"][index]
            ids = self.record["cell"]["clip_ids"]
            for clip, origin in enumerate(self.origins):
                still = bool(held[clip]) and ids[clip] not in lost
                add_marker(self.renderer.scene, origin+np.array([0.0, 0.0, MARKER_UP_M]),
                           0.0035 if still else 0.0052,
                           (0.34, 0.82, 0.69, 0.95) if still else (0.94, 0.42, 0.42, 0.98))
        if ghosts:
            weights = self.archive["weights"][index]
            for node, point in enumerate(self.archive["estimate_line"][index]):
                hidden = weights[node] > 0.5
                add_marker(self.renderer.scene, point, 0.0040 if hidden else 0.0026,
                           (1.0, 0.42, 0.42, 0.92) if hidden else (0.78, 0.63, 0.95, 0.85))
            add_marker(self.renderer.scene, self.archive["estimate_socket"][index], 0.006,
                       (1.0, 0.70, 0.25, 0.92))
            add_marker(self.renderer.scene, self.archive["truth_socket"][index], 0.004,
                       (0.34, 0.82, 0.69, 0.92))
        return Image.fromarray(self.renderer.render())


def add_marker(view, position, size, rgba):
    """Append one visual sphere to an already-updated MjvScene."""
    if view.ngeom >= view.maxgeom:
        return
    geom = view.geoms[view.ngeom]
    mujoco.mjv_initGeom(geom, mujoco.mjtGeom.mjGEOM_SPHERE, np.array([size, 0.0, 0.0]),
                        np.asarray(position, dtype=float), np.eye(3).flatten(),
                        np.asarray(rgba, dtype=np.float32))
    view.ngeom += 1


def bar(draw, box, fraction, background, fill, radius=3):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=background)
    width = max(0.0, min(1.0, fraction))*(x1-x0)
    if width > 1:
        draw.rounded_rectangle([x0, y0, x0+width, y1], radius=radius, fill=fill)


def caption(draw, panel, fps, scene_w, height, small):
    """The request id and the playback speed, legible over a rendered scene."""
    text = f"{panel.record['case']}  -  {speed_label(panel.record['capture_hz'], fps)}"
    draw.rectangle([0, height-40, scene_w, height], fill=(10, 14, 20))
    draw.text((22, height-29), text, font=small, fill=MUTED)


def footer(draw, width, height, small):
    draw.line([(0, height-38), (width, height-38)], fill=RULE, width=1)
    draw.text((24, height-28), FOOTER, font=small, fill=MUTED)


def speed_label(capture_hz: float, fps: int) -> str:
    ratio = fps/capture_hz
    if abs(ratio-1.0) < 1e-6:
        return "offline replay, real time"
    return f"offline replay, {ratio:g} x real time"


def render_triptych(panels: list[Panel], out_path: Path, fps: int, width: int, height: int,
                    origins: np.ndarray) -> dict:
    pad, gap = 22, 32
    panel_w = (width-2*pad-2*gap)//3
    panel_h = 520
    top = 104
    big, mid, small, tiny = font(30, True), font(19, True), font(16), font(14)
    total = max(p.frames for p in panels)
    writer = imageio_ffmpeg.write_frames(str(out_path), (width, height), fps=fps, quality=9,
                                         macro_block_size=1)
    writer.send(None)
    reference = panels[0].record
    for index in range(total):
        frame = Image.new("RGB", (width, height), BG)
        draw = ImageDraw.Draw(frame)
        draw.text((pad, 24), "Same cell, same estimate, three supervisors", font=big, fill=WHITE)
        draw.text((pad, 64),
                  f"routing study v6 - cell RC1, error level {reference['error_level']}, "
                  f"five required clips - {speed_label(reference['capture_hz'], fps)}",
                  font=small, fill=MUTED)
        elapsed = float(panels[-1].archive["t"][min(index, panels[-1].frames-1)])
        draw.text((width-pad-140, 68), f"t = {elapsed:5.2f} s", font=small, fill=MUTED)
        for slot, panel in enumerate(panels):
            x0 = pad+slot*(panel_w+gap)
            done = index >= panel.frames
            # The capture stride can end a route a few milliseconds before the
            # clip actually goes, so a frozen panel is drawn with the outcome the
            # block recorded rather than with its last sampled frame.
            gone = tuple(panel.record["terminal_clips"]["lost"]) if done else ()
            picture = panel.image(index, origins, ghosts=False, lost=gone)
            frame.paste(picture.resize((panel_w, panel_h)), (x0, top))
            step = int(panel.archive["step_index"][min(index, panel.frames-1)])
            # Past the end of a route the capture has nothing more to say, so the
            # caption reports the outcome the block recorded rather than the last
            # frame that happened to land on the capture stride.
            kept = (panel.record["terminal_clips"]["required_retained"] if done
                    else int(panel.archive["required_retained"][index]))
            title, rule = SUPERVISOR_LABEL[panel.record["supervisor"]]
            y = top+panel_h+16
            draw.text((x0, y), title, font=mid, fill=WHITE)
            draw.text((x0, y+26), rule, font=tiny, fill=MUTED)
            colour = GREEN if kept == 5 else RED
            lost = panel.record["terminal_clips"]["lost"] if done else []
            draw.text((x0, y+54),
                      f"{kept} of 5 required clips still held"
                      + (f"  -  lost {', '.join(lost)}" if lost else ""),
                      font=small, fill=colour)
            issued = [r for r in panel.result["issued"] if r.get("requested")]
            latest = issued[step-1] if 0 < step <= len(issued) else None
            if latest is not None:
                draw.text((x0, y+80),
                          f"move {step}: {1000*latest['magnitude_m']:.0f} mm commanded",
                          font=small, fill=MUTED)
                spent = latest["budget"]["C1_clip"]["spent_fraction"]
                reports = ("the check would have reported"
                           if panel.record["supervisor"] == "unfiltered"
                           else "the check reports")
                draw.text((x0, y+104),
                          f"spends {100*spent:.0f}% of the clip budget {reports}",
                          font=small, fill=AMBER if spent > 0.5 else GREEN)
                bar(draw, (x0, y+130, x0+panel_w, y+140), min(spent, 1.0), RULE,
                    RED if spent >= 1.0 else (AMBER if spent > 0.5 else GREEN))
            else:
                draw.text((x0, y+80), "no move issued yet", font=small, fill=MUTED)
            if done:
                reason = panel.record["failure_reason"] or "route completed, connector seated"
                draw.text((x0, top+panel_h-26),
                          {"lost_required_clip": "cable pulled out of a clip"}.get(reason, reason),
                          font=mid, fill=GREEN if panel.record["route_completed"] else RED)
        footer(draw, width, height, tiny)
        writer.send(np.asarray(frame))
    writer.close()
    return {"video": relative(out_path), "frames": total, "fps": fps,
            "resolution": [width, height],
            "cases": [p.record["case"] for p in panels],
            "reproduces_block": all(p.record["reproduces_block"] for p in panels)}


def render_estimate(panel: Panel, out_path: Path, fps: int, width: int, height: int,
                    origins: np.ndarray, contract: dict) -> dict:
    scene_w = int(width*0.64)
    big, mid, small, tiny = font(26, True), font(18, True), font(16), font(14)
    c2_spec = float(contract["constraints"]["C2_bend"]["spec_m"])
    c3_limit = float(contract["constraints"]["C3_anchor"]["limit_n"])
    level = next(e for e in contract["perception"]["levels"]
                 if e["id"] == panel.record["error_level"])
    writer = imageio_ffmpeg.write_frames(str(out_path), (width, height), fps=fps, quality=9,
                                         macro_block_size=1)
    writer.send(None)
    for index in range(panel.frames):
        frame = Image.new("RGB", (width, height), BG)
        # No clip beads here: the legend below names four marker colours and the
        # picture must not carry a fifth.
        frame.paste(panel.image(index, origins, ghosts=True, markers=False)
                    .resize((scene_w, height)), (0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle([scene_w, 0, width, height], fill=PANEL)
        x0 = scene_w+22
        hidden = int((panel.archive["weights"][index] > 0.5).sum())
        nodes = len(panel.archive["weights"][index])
        offset = float(np.linalg.norm(panel.archive["estimate_socket"][index]
                                      - panel.archive["truth_socket"][index]))
        radius = float(panel.archive["min_bend_radius"][index])
        kept = int(panel.archive["required_retained"][index])
        rows = [
            (big, WHITE, "What it reads"),
            (tiny, MUTED, "against what is true"),
            (None, None, None),
            (small, MUTED, f"t = {panel.archive['t'][index]:5.2f} s"),
            (small, MUTED, f"error level {panel.record['error_level']}"),
            (None, None, None),
            (mid, WHITE, "the estimate"),
            (small, VIOLET, f"{nodes-hidden} cable nodes the camera can see"),
            (small, RED, f"{hidden} the fixture hides"),
            (small, AMBER, f"socket estimate off by {1000*offset:5.2f} mm"),
            (tiny, MUTED, f"declared: socket {1000*level['socket_bias_m']:.1f} mm, "
                          f"hidden node {1000*level['centreline_occluded_m']:.1f} mm"),
            (None, None, None),
            (mid, WHITE, "the truth, scored separately"),
            (small, GREEN if kept == 5 else RED, f"C1  {kept} of 5 required clips held"),
            (small, GREEN if radius >= c2_spec else RED,
             f"C2  min bend radius {1000*radius:5.1f} mm   spec {1000*c2_spec:.0f}"),
            (small, GREEN if panel.archive["peak_anchor"][index] <= c3_limit else RED,
             f"C3  peak clamp load {panel.archive['peak_anchor'][index]:5.2f} N   "
             f"limit {c3_limit:.2f}"),
            (None, None, None),
            (tiny, VIOLET, "violet   estimated cable node"),
            (tiny, RED, "red      estimated node the fixture hides"),
            (tiny, AMBER, "amber    estimated socket pose"),
            (tiny, GREEN, "green    true socket pose"),
            (None, None, None),
            (tiny, MUTED, "No supervisor here ever reads the truth column."),
            (tiny, MUTED, "A guard fails any run whose control code"),
            (tiny, MUTED, "touches it, and it never fired in 2,340 routes."),
        ]
        y = 26
        for typeface, colour, text in rows:
            if text is None:
                y += 12
                continue
            draw.text((x0, y), text, font=typeface, fill=colour)
            y += typeface.size+9
        caption(draw, panel, fps, scene_w, height, tiny)
        draw.text((x0, height-30), "Simulation only. No hardware claim.", font=tiny, fill=MUTED)
        writer.send(np.asarray(frame))
    writer.close()
    return {"video": relative(out_path), "frames": panel.frames, "fps": fps,
            "resolution": [width, height], "cases": [panel.record["case"]],
            "reproduces_block": panel.record["reproduces_block"]}


def render_budget(panel: Panel, out_path: Path, fps: int, width: int, height: int,
                  origins: np.ndarray) -> dict:
    scene_w = int(width*0.58)
    big, mid, tiny = font(26, True), font(18, True), font(13)
    issued = [r for r in panel.result["issued"] if r.get("requested")]
    budgets = [r["budget"]["C1_clip"] for r in issued]
    full = max(b["headroom_at_decision_m"] for b in budgets)
    writer = imageio_ffmpeg.write_frames(str(out_path), (width, height), fps=fps, quality=9,
                                         macro_block_size=1)
    writer.send(None)
    for index in range(panel.frames):
        frame = Image.new("RGB", (width, height), BG)
        frame.paste(panel.image(index, origins, ghosts=False).resize((scene_w, height)), (0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle([scene_w, 0, width, height], fill=PANEL)
        x0, x1 = scene_w+22, width-22
        draw.text((x0, 24), "The budget draining", font=big, fill=WHITE)
        draw.text((x0, 58), "how much plug-to-clamp distance the check says is left before",
                  font=tiny, fill=MUTED)
        draw.text((x0, 74), "its fitted threshold, and what the move issued there spends of it",
                  font=tiny, fill=MUTED)
        step = int(panel.archive["step_index"][index])
        y = 108
        for number, (record, budget) in enumerate(zip(issued, budgets, strict=True)):
            reached = number < step
            head = budget["headroom_at_decision_m"]
            spent = budget["spent_by_this_motion_m"]
            ink = WHITE if reached else (70, 86, 102)
            draw.text((x0, y), f"decision {number+1}   t = {record['time_s']:.1f} s",
                      font=mid, fill=ink)
            draw.text((x1-118, y+2), f"{1000*head:5.1f} mm", font=mid,
                      fill=GREEN if reached else (70, 86, 102))
            bar(draw, (x0, y+30, x1, y+44), head/full if reached else 0.0, RULE, (36, 74, 68))
            if reached:
                bar(draw, (x0, y+30, x0+(x1-x0)*head/full, y+44), spent/head, (36, 74, 68), AMBER)
                draw.text((x0, y+50),
                          f"the 6 mm move spends {1000*spent:.1f} mm "
                          f"({100*budget['spent_fraction']:.0f}%)", font=tiny, fill=AMBER)
            else:
                draw.text((x0, y+50), "not reached yet", font=tiny, fill=(70, 86, 102))
            y += 88
        draw.line([(x0, y+2), (x1, y+2)], fill=RULE, width=1)
        kept = int(panel.archive["required_retained"][index])
        draw.text((x0, y+16), f"{kept} of 5 required clips still held", font=mid,
                  fill=GREEN if kept == 5 else RED)
        draw.text((x0, y+46),
                  "This route physically admits about 18 mm of commanded pull-back.",
                  font=tiny, fill=MUTED)
        draw.text((x0, y+62),
                  "The check permits 58 mm - eleven of its twelve candidate moves.",
                  font=tiny, fill=MUTED)
        draw.text((x0, y+78),
                  "Both were measured in the pilot, before any route was scored.",
                  font=tiny, fill=MUTED)
        caption(draw, panel, fps, scene_w, height, tiny)
        draw.text((x0, height-30), "Simulation only. No hardware claim.", font=tiny, fill=MUTED)
        writer.send(np.asarray(frame))
    writer.close()
    return {"video": relative(out_path), "frames": panel.frames, "fps": fps,
            "resolution": [width, height], "cases": [panel.record["case"]],
            "reproduces_block": panel.record["reproduces_block"]}


# --------------------------------------------------------------------------- entry

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path,
                        default=ROOT / "artifacts/cable/routing-v6-s1__runtime.json")
    parser.add_argument("--block-dir", type=Path,
                        default=ROOT / "artifacts/cable/routing-v6-s1")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "artifacts/showcase/video")
    parser.add_argument("--layout", required=True, choices=("triptych", "estimate", "budget"))
    parser.add_argument("--case", action="append", required=True,
                        help="Registered request id. The triptych takes three, in the order "
                             "no-check, check, check-read-for-ranking.")
    parser.add_argument("--name", help="Output file stem; defaults to the layout name.")
    parser.add_argument("--view", default="clips", choices=sorted(VIEWS))
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--capture-hz", type=float, default=15.0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--recapture", action="store_true",
                        help="Re-run the physics even if a capture is already on disk.")
    args = parser.parse_args()

    runtime = json.loads(args.runtime.read_text(encoding="utf-8-sig"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    records = []
    for case_id in args.case:
        directory = args.out_dir / case_id
        if args.recapture or not (directory / "capture.npz").is_file():
            record = capture(case_id, runtime, directory, args.capture_hz, args.block_dir)
        else:
            record = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
        print(json.dumps({"case": case_id, "frames": record["frames"],
                          "reproduces_block": record["reproduces_block"],
                          "mismatch": record["mismatch"]}), flush=True)
        if not record["reproduces_block"]:
            raise SystemExit(f"{case_id} did not reproduce the block; refusing to publish it")
        records.append(record)

    origins = np.asarray(records[0]["cell"]["clip_origins_world"], dtype=float)
    stem = args.name or args.layout
    out_path = args.out_dir / f"{stem}.mp4"
    if args.layout == "triptych":
        width = args.width if args.width > 1300 else 1920
        height = args.height if args.height > 800 else 900
        panels = [Panel(args.out_dir / c, (width-2*22-2*32)//3, 520, args.view)
                  for c in args.case]
        summary = render_triptych(panels, out_path, args.fps, width, height, origins)
    else:
        scene_fraction = 0.64 if args.layout == "estimate" else 0.58
        panel = Panel(args.out_dir / args.case[0], int(args.width*scene_fraction), args.height,
                      args.view)
        panels = [panel]
        summary = (render_estimate(panel, out_path, args.fps, args.width, args.height, origins,
                                   runtime)
                   if args.layout == "estimate"
                   else render_budget(panel, out_path, args.fps, args.width, args.height,
                                      origins))
    for panel in panels:
        panel.close()

    summary.update({"layout": args.layout, "view": args.view,
                    "bytes": out_path.stat().st_size,
                    "wall_seconds": round(time.monotonic()-started, 1),
                    "scope": "Offline replay of recorded states; no mj_step at render time. "
                             "Simulation only, not a hardware claim."})
    (args.out_dir / f"{stem}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
