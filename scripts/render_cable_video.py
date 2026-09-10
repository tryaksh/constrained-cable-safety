"""Render an honest side-by-side replay from verified recorded cable states.

No mj_step is called. qpos/qvel/ctrl assignments are offline replay operations,
not actions or state resets inside a physical evaluation job. Displayed metrics
come from recorded samples; terminal images are explicitly held after job end.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BG = "#101820"
PANEL = "#17232f"
WHITE = "#edf4f7"
MUTED = "#b0c1cf"
COLORS = ["#56d1b0", "#ffb36a"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def font(size, bold=False):
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype("C:/Windows/Fonts/" + name, size)


class Replay:
    def __init__(self, directory):
        self.directory = directory
        self.result = json.loads((directory / "result.json").read_text())
        self.archive = np.load(directory / "trajectory.npz", allow_pickle=False)
        self.samples = self.archive["samples"]
        self.times = self.samples[:, 0]
        self.model = mujoco.MjModel.from_xml_path(str(directory / "scene.xml"))
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, width=760, height=460)
        self.options = mujoco.MjvOption()
        self.options.geomgroup[3] = 1
        self.initialization_s = self.result["initialization_native_steps"] * self.result["case"]["dt"]
        self.last_index = -1
        self.forward_calls = self.render_calls = 0
        self.cache = None
        self.max_position_error = 0.0
        self.snapshot_errors = []
        self.model.vis.headlight.ambient[:] = [0.35, 0.35, 0.35]
        self.model.vis.headlight.diffuse[:] = [0.65, 0.65, 0.65]
        self.model.vis.headlight.specular[:] = [0.15, 0.15, 0.15]
        self.tip_id = self.model.site("plug__frame__sc_tip_link").id
        self.port_id = self.model.site("port__frame__sc_port_base_link").id

    def index(self, requested_time):
        before = max(0, min(len(self.times) - 1, int(np.searchsorted(self.times, requested_time, side="right") - 1)))
        after = min(before + 1, len(self.times) - 1)
        return after if abs(self.times[after] - requested_time) < abs(self.times[before] - requested_time) else before

    def images(self, requested_time, azimuth):
        index = self.index(requested_time)
        if index == self.last_index:
            return index, self.cache
        self.data.qpos[:] = self.archive["qpos"][index]
        self.data.qvel[:] = self.archive["qvel"][index]
        self.data.ctrl[:] = self.archive["ctrl"][index]
        self.data.time = self.times[index] + self.initialization_s
        mujoco.mj_forward(self.model, self.data)
        self.forward_calls += 1
        error = float(np.linalg.norm(self.data.site_xpos[self.tip_id] - self.samples[index, 1:4]))
        self.max_position_error = max(self.max_position_error, error)
        if error > 1e-8:
            raise ValueError(f"Replayed tip does not match saved position: {error}")
        port = self.data.site_xpos[self.port_id].copy()
        camera = mujoco.MjvCamera()
        camera.lookat[:] = port + [0.0, 0.0, 0.015]
        camera.distance = 0.16
        camera.azimuth = azimuth
        camera.elevation = -12
        self.renderer.update_scene(self.data, camera=camera, scene_option=self.options)
        close = Image.fromarray(self.renderer.render().copy())
        self.render_calls += 1
        camera.lookat[:] = port + [0.10, 0.03, -0.18]
        camera.distance = 1.5
        camera.azimuth = 135
        camera.elevation = -15
        self.renderer.update_scene(self.data, camera=camera, scene_option=self.options)
        wide = Image.fromarray(self.renderer.render().copy()).resize((248, 150), Image.Resampling.LANCZOS)
        self.render_calls += 1
        self.last_index = index
        self.cache = (close, wide)
        return index, self.cache

    def close(self):
        self.renderer.close()
        self.archive.close()


def frame(replays, job_time, azimuth, speed_label, *, intro=False, ending=False):
    canvas = Image.new("RGB", (1600, 1000), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (30, 18), "A 2 mm offset: alignment succeeds, continued insertion stalls", font=font(32, True), fill=WHITE
    )
    draw.text(
        (30, 63),
        "UR5e + SC connector  |  RECORDED SIMULATION  |  Both controllers are scripted",
        font=font(22),
        fill=MUTED,
    )
    draw.text(
        (30, 102),
        "Same physical case and load limits. Video starts after 3 s of initialization.",
        font=font(20),
        fill=MUTED,
    )
    labels = ["Force-guided alignment", "Continued insertion"]
    for arm, replay in enumerate(replays):
        x = 20 + arm * 800
        draw.rounded_rectangle((x, 146, x + 760, 918), radius=15, fill=PANEL)
        draw.text((x + 18, 158), labels[arm], font=font(28, True), fill=COLORS[arm])
        index, (close, wide) = replay.images(job_time, azimuth)
        row = replay.samples[index]
        ended = job_time >= replay.result["job"]["elapsed_s"]
        status = "ALIGN / INSERT"
        if replay.result["job"]["first_witness_s"] is not None and job_time >= replay.result["job"]["first_witness_s"]:
            status = "CONTACT STALL"
        if ended:
            status = "SEATED - FINAL FRAME HELD" if arm == 0 else "30 s TIMEOUT - FINAL FRAME HELD"
        draw.text((x + 18, 197), status, font=font(20, True), fill=COLORS[arm])
        canvas.paste(close, (x, 236))
        canvas.paste(wide, (x + 496, 246))
        draw.rectangle((x + 495, 245, x + 745, 397), outline=MUTED, width=1)
        draw.text(
            (x + 510, 400), "Whole robot and free cable", font=font(15), fill=WHITE, stroke_width=1, stroke_fill=BG
        )
        draw.text(
            (x + 18, 708),
            f"Recorded time {row[0]:5.2f} s     Distance to seat {1000 * row[7]:5.2f} mm",
            font=font(22),
            fill=WHITE,
        )
        draw.text((x + 18, 743), f"Plug-port contact {row[9]:5.2f} N", font=font(21), fill=MUTED)
        draw.text((x + 390, 743), "0 retries" if arm == 0 else "No corrective movement", font=font(20), fill=MUTED)
        left, top, width, height = x + 55, 795, 677, 85
        for value in (0, 10, 20):
            y = top + height - height * value / 24
            draw.line((left, y, left + width, y), fill="#354653", width=1)
            draw.text((x + 15, y - 10), str(value), font=font(14), fill=MUTED)
        series = replay.samples[: index + 1]
        points = [
            (left + width * float(r[0]) / 30, top + height - height * min(24, float(r[7]) * 1000) / 24) for r in series
        ]
        if len(points) > 1:
            draw.line(points, fill=COLORS[arm], width=3)
        if points:
            px, py = points[-1]
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=COLORS[arm])
        draw.text((left, 887), "Distance to seat (mm)  |  job time 0 - 30 s", font=font(15), fill=MUTED)
    if intro:
        footer = "Shared case: visible 2 mm offset, one cable end free, connector already grasped."
    elif ending:
        footer = "Result: alignment prevents failure. Held seating does not establish a latched connection."
    else:
        footer = f"{speed_label}  |  Saved poses replayed without new physics; completed frames are held."
    draw.text((30, 935), footer, font=font(22, True), fill=WHITE)
    draw.text(
        (30, 972),
        "No learned policy, pickup, cable-snag recovery or hardware transfer is shown.",
        font=font(17),
        fill=MUTED,
    )
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    source = ROOT / cfg["source_run"]
    manifest = json.loads((source / "manifest.json").read_text())
    if sha(source / "manifest.json") != cfg["source_manifest_sha256"]:
        raise ValueError("Source manifest changed")
    checked = 0
    for item in manifest["artifacts"]:
        if any(item["path"].startswith(name + "/") for name in cfg["case_directories"]):
            if sha(source / item["path"]) != item["sha256"]:
                raise ValueError("Source artifact changed: " + item["path"])
            checked += 1
    for item in manifest["external_files"]:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("External mesh changed")
        checked += 1
    replays = []
    started = time.monotonic()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    report = {
        "status": "running",
        "kind": "saved_state_video_replay",
        "source_manifest_sha256": sha(source / "manifest.json"),
        "source_artifacts_verified": checked,
        "selection_rule": cfg["selection_rule"],
        "source_case_directories": cfg["case_directories"],
        "accounting": {"native_steps": 0, "mj_forward_calls": 0, "render_calls": 0},
        "limitations": [
            "Offline saved-state replay; no new physics integration or performance measurement.",
            "Nearest saved poses, without interpolation; source poses were recorded every 10 ms plus terminal state.",
            "Three-second physical initialization omitted; movie clock reports original job time.",
            "Completed job images are explicitly held, not simulated further.",
            "All displayed forces and outcomes come from original records, not replay force calculations.",
            "View/lighting changes only; geometry, poses and original results are unchanged.",
        ],
    }
    write(args.run_dir / "result.json", report)
    try:
        replays = [Replay(source / name) for name in cfg["case_directories"]]
        if args.preview:
            for t, label in ((0.0, "start"), (3.0, "stalled"), (6.2375, "seated")):
                frame(replays, t, cfg["camera_azimuth"], "1x playback").save(args.run_dir / f"{label}.jpg", quality=92)
            frames_written = 3
        else:
            fps = cfg["fps"]
            sequence = [(0.0, "Pause", True, False)] * (2 * fps)
            sequence += [(i / fps, "1x playback", False, False) for i in range(8 * fps)]
            sequence += [(8 + 4 * i / fps, "4x playback", False, False) for i in range(round(5.5 * fps))]
            sequence += [(30.0, "Pause", False, True)] * (4 * fps)
            output = args.run_dir / "cable_comparison.mp4"
            command = [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                "1600x1000",
                "-r",
                str(fps),
                "-i",
                "-",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ]
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            with (args.run_dir / "encoder.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log, **kwargs)
                try:
                    for i, (t, speed, intro, ending) in enumerate(sequence):
                        picture = frame(replays, t, cfg["camera_azimuth"], speed, intro=intro, ending=ending)
                        process.stdin.write(picture.tobytes())
                        if i == 0:
                            picture.save(args.run_dir / "poster.jpg", quality=92)
                        if i == 2 * fps + round(6.24 * fps):
                            picture.save(args.run_dir / "seating.jpg", quality=92)
                        if i == len(sequence) - 1:
                            picture.save(args.run_dir / "final.jpg", quality=92)
                        if i % 60 == 0:
                            write(
                                args.run_dir / "progress.json",
                                {"native_steps": 0, "frames_written": i + 1, "frames_expected": len(sequence)},
                            )
                    process.stdin.close()
                    if process.wait(timeout=60) != 0:
                        raise RuntimeError("Video encoder failed")
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
            check = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-"],
                capture_output=True,
                text=True,
                timeout=120,
                **kwargs,
            )
            if check.returncode or check.stderr.strip():
                raise RuntimeError("Video decode check failed: " + check.stderr)
            frames_written = len(sequence)
            report.update(
                video={
                    "path": "cable_comparison.mp4",
                    "sha256": sha(output),
                    "bytes": output.stat().st_size,
                    "fps": fps,
                    "frames": frames_written,
                    "duration_s": frames_written / fps,
                    "decode_check": "passed",
                    "codec": "H.264",
                    "pixel_format": "yuv420p",
                    "dimensions": [1600, 1000],
                    "playback": "2 s intro; job0-8 s at1x; job8-30 s at4x;4 s terminal hold",
                },
                encoder={"package": "imageio-ffmpeg==0.6.0", "executable": ffmpeg, "sha256": sha(Path(ffmpeg))},
            )
        report.update(
            status="completed",
            frames_written=frames_written,
            elapsed_s=time.monotonic() - started,
            maximum_replayed_tip_error_m=max(r.max_position_error for r in replays),
            accounting={
                "native_steps": 0,
                "mj_forward_calls": sum(r.forward_calls for r in replays),
                "render_calls": sum(r.render_calls for r in replays),
            },
        )
        write(args.run_dir / "result.json", report)
        print(
            json.dumps({"status": report["status"], "frames": frames_written, "accounting": report["accounting"]}),
            flush=True,
        )
    finally:
        for replay in replays:
            replay.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
