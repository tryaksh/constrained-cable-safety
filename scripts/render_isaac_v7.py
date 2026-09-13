"""Re-render the exported route in Isaac Sim, for looks only.

The MuJoCo renders in this repository come from MuJoCo's own offscreen renderer,
which exists to check that a scene is built correctly, not to look good. This
script opens the USD stage ``scripts/export_usd_v7.py`` wrote and renders the
same recorded motion again with Isaac Sim's RTX renderer: real lights, soft
shadows, reflections.

NOTHING ABOUT THE PHYSICS CHANGES. The stage holds positions that MuJoCo already
computed and that the routing block already scored. Isaac Sim is a camera here
and nothing else, and no number in this repository was measured in it, checked
against it, or validated by it.

Run it with Isaac Sim's own interpreter, not this project's:

    C:/isaac-sim/python.bat scripts/render_isaac_v7.py

Frames land under artifacts/showcase/isaac/ and are encoded to mp4 by
scripts/encode_isaac_v7.py, which runs in the cable environment because that is
where ffmpeg lives.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The stage the USD export wrote. Its geometry is in metres even though the
#: exporter stamps metersPerUnit 0.01, so camera positions here are metres.
DEFAULT_STAGE = "artifacts/showcase/usd/cable_cell_v6/frames/frame_200.usd"

#: Where the five clips sit in the compiled world, measured off the stage, and
#: the two camera set-ups worth having: one that holds the whole jig and one
#: close on the ridge clip that lets go.
LOOK_AT = (-0.548, 0.061, 1.220)
VIEWS = {
    # Chosen by rendering candidates and looking at them, not by arithmetic.
    "wide": {"eye": (0.10, -0.90, 1.75), "target": (-0.55, 0.06, 1.290)},
    "ridge": {"eye": (-0.16, -0.62, 1.55), "target": (-0.57, 0.05, 1.245)},
}

#: Candidate camera set-ups for --probe. One Isaac session boots in about half a
#: minute, so guessing a camera one run at a time is the expensive way to do it;
#: this renders one frame from each and lets the pictures decide.
PROBE = {
    "q_a": {"eye": (-0.10, -0.62, 1.66), "target": (-0.56, 0.05, 1.250), "focal": 30.0},
    "q_b": {"eye": (-0.02, -0.72, 1.70), "target": (-0.56, 0.05, 1.255), "focal": 34.0},
    "q_c": {"eye": (0.10, -0.90, 1.75), "target": (-0.55, 0.06, 1.290), "focal": 40.0},
    "q_d": {"eye": (-0.22, -0.78, 1.62), "target": (-0.58, 0.04, 1.245), "focal": 34.0},
    "q_e": {"eye": (0.16, -0.78, 1.86), "target": (-0.55, 0.05, 1.270), "focal": 34.0},
    "q_f": {"eye": (-0.40, -0.95, 1.80), "target": (-0.58, 0.04, 1.290), "focal": 30.0},
}


def compose(record: dict, args) -> dict:
    """Wrap one render in the scope it has to carry, and save it.

    Written BEFORE the simulation app is closed. Isaac's shutdown can take the
    process with it, and the first full render here finished, exited zero and
    left no record at all because this ran after ``app.close()``.
    """
    record["scope"] = (
        "A RE-RENDER of positions MuJoCo computed and the routing block scored. Isaac Sim is "
        "used as a camera. No number in this repository was measured in it, checked against it "
        "or validated by it, and this changes nothing about any published result.")
    path = ROOT / args.out
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    existing.setdefault("schema", 1)
    existing["id"] = "showcase_isaac_v7"
    existing["created_on"] = "2026-09-12"
    existing["what_this_is"] = (
        "One route from the v6 routing block, re-rendered with Isaac Sim's RTX renderer from "
        "the USD stage scripts/export_usd_v7.py wrote. MuJoCo's own renderer exists to check "
        "that a scene is built correctly; this one exists to look at.")
    existing["what_this_is_not"] = [
        "Not a simulation. The states are replayed, not stepped: Isaac Sim computes nothing here.",
        "Not a validation anywhere but MuJoCo, and not an Isaac Sim project.",
    ]
    existing.setdefault("views", {})[args.view] = record
    existing["scope"] = record["scope"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return record


def build(args) -> dict:
    from isaacsim import SimulationApp

    app = SimulationApp({"headless": True, "renderer": "RayTracedLighting",
                         "width": args.width, "height": args.height})

    import carb  # noqa: F401
    import omni.replicator.core as rep
    import omni.usd
    from pxr import Gf, Sdf, UsdGeom, UsdLux

    started = time.monotonic()
    stage_path = str((ROOT / args.stage).resolve())
    omni.usd.get_context().open_stage(stage_path)
    app.update()
    stage = omni.usd.get_context().get_stage()
    for _ in range(30):
        app.update()

    # The exporter stamps centimetres on a stage whose numbers are metres.
    # Correcting it here is what makes the camera positions below mean metres.
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    lights = Sdf.Path("/World/showLights")
    UsdGeom.Xform.Define(stage, lights)
    dome = UsdLux.DomeLight.Define(stage, lights.AppendChild("dome"))
    dome.CreateIntensityAttr(args.dome)
    dome.CreateColorAttr(Gf.Vec3f(0.62, 0.70, 0.82))
    key = UsdLux.DistantLight.Define(stage, lights.AppendChild("key"))
    key.CreateIntensityAttr(args.key)
    key.CreateAngleAttr(1.6)
    key.CreateColorAttr(Gf.Vec3f(1.0, 0.97, 0.92))
    UsdGeom.Xformable(key).AddRotateXYZOp().Set(Gf.Vec3f(-46.0, 0.0, 38.0))
    # Distant lights, not sphere lights. A sphere light renders as a white ball
    # in shot, and the several documented ways of hiding one did not take.
    fill = UsdLux.DistantLight.Define(stage, lights.AppendChild("fill"))
    fill.CreateIntensityAttr(args.fill/2200.0)
    fill.CreateAngleAttr(12.0)
    fill.CreateColorAttr(Gf.Vec3f(0.72, 0.82, 1.0))
    UsdGeom.Xformable(fill).AddRotateXYZOp().Set(Gf.Vec3f(-28.0, 0.0, -66.0))
    rim = UsdLux.DistantLight.Define(stage, lights.AppendChild("rim"))
    rim.CreateIntensityAttr(args.rim/2200.0)
    rim.CreateAngleAttr(6.0)
    rim.CreateColorAttr(Gf.Vec3f(1.0, 0.86, 0.68))
    UsdGeom.Xformable(rim).AddRotateXYZOp().Set(Gf.Vec3f(-62.0, 0.0, 176.0))

    if args.probe:
        # One frame from every candidate camera, in one session, so a camera can
        # be chosen by looking instead of by another thirty-second boot.
        records = []
        for name, spec in PROBE.items():
            camera = rep.create.camera(position=spec["eye"], look_at=spec["target"],
                                       focal_length=spec.get("focal", args.focal_length))
            product = rep.create.render_product(camera, (args.width, args.height))
            out_dir = ROOT / args.out_dir / "probe" / name
            out_dir.mkdir(parents=True, exist_ok=True)
            writer = rep.WriterRegistry.get("BasicWriter")
            writer.initialize(output_dir=str(out_dir), rgb=True)
            writer.attach([product])
            rep.orchestrator.step(rt_subframes=args.subframes, delta_time=0.0,
                                  pause_timeline=False)
            rep.orchestrator.wait_until_complete()
            writer.detach()
            product.destroy()
            records.append({"name": name, **spec,
                            "images": [p.relative_to(ROOT).as_posix()
                                       for p in sorted(out_dir.rglob("rgb_*.png"))]})
        app.close()
        return {"frames_written": sum(len(r["images"]) for r in records),
                "probe": records, "stage": args.stage,
                "wall_seconds": round(time.monotonic()-started, 1)}

    spec = dict(VIEWS[args.view])
    if args.eye:
        spec["eye"] = tuple(args.eye)
    if args.target:
        spec["target"] = tuple(args.target)
    camera = rep.create.camera(position=spec["eye"], look_at=spec["target"],
                               focal_length=args.focal_length,
                               f_stop=args.f_stop,
                               focus_distance=args.focus_distance)
    product = rep.create.render_product(camera, (args.width, args.height))
    out_dir = ROOT / args.out_dir / args.view
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(output_dir=str(out_dir), rgb=True)
    writer.attach([product])

    first = stage.GetStartTimeCode()
    last = stage.GetEndTimeCode()
    total = int(last-first)+1
    stride = max(1, total//args.frames)
    # One short of the end: the last capture lands after the stage's final time
    # sample and comes back as empty background.
    codes = [first+index*stride for index in range(args.frames)]
    codes = [code for code in codes if code < last-stride]

    # Let the timeline run the stage, and let Replicator advance it one stage
    # frame per capture. Setting the time by hand and holding the timeline still
    # looked right and was not: the scene left frame partway through every run.
    import omni.timeline

    fps = float(stage.GetFramesPerSecond()) or 24.0
    timeline = omni.timeline.get_timeline_interface()
    timeline.set_time_codes_per_second(fps)
    timeline.set_start_time(float(first)/fps)
    timeline.set_end_time(float(last)/fps)
    timeline.set_looping(False)
    timeline.set_current_time(float(first)/fps)
    timeline.play()
    for _ in range(4):
        app.update()

    for rendered in range(1, len(codes)+1):
        rep.orchestrator.step(rt_subframes=args.subframes, delta_time=stride/fps,
                              pause_timeline=False)
        if rendered % 20 == 0:
            print(json.dumps({"rendered": rendered, "of": len(codes),
                              "stage_time_s": round(timeline.get_current_time(), 3),
                              "seconds": round(time.monotonic()-started, 1)}), flush=True)
    rep.orchestrator.wait_until_complete()
    timeline.stop()

    images = sorted(out_dir.rglob("rgb_*.png"))
    record = {
        "stage": args.stage,
        "view": args.view,
        "camera": {**spec, "focal_length_mm": args.focal_length, "f_stop": args.f_stop},
        "resolution": [args.width, args.height],
        "frames_requested": args.frames,
        "frames_written": len(images),
        "time_codes": [float(first), float(last)],
        "stride_time_codes": stride,
        "rt_subframes": args.subframes,
        "output_dir": out_dir.relative_to(ROOT).as_posix(),
        "wall_seconds": round(time.monotonic()-started, 1),
    }
    compose(record, args)
    app.close()
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", default=DEFAULT_STAGE)
    parser.add_argument("--out-dir", default="artifacts/showcase/isaac")
    parser.add_argument("--view", default="wide", choices=sorted(VIEWS))
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--focal-length", type=float, default=38.0)
    parser.add_argument("--f-stop", type=float, default=0.0)
    parser.add_argument("--focus-distance", type=float, default=0.45)
    parser.add_argument("--subframes", type=int, default=12)
    parser.add_argument("--dome", type=float, default=120.0)
    parser.add_argument("--key", type=float, default=1100.0)
    parser.add_argument("--fill", type=float, default=2600.0)
    parser.add_argument("--rim", type=float, default=1600.0)
    parser.add_argument("--probe", action="store_true",
                        help="Render one frame from every candidate camera and stop.")
    parser.add_argument("--eye", type=float, nargs=3)
    parser.add_argument("--target", type=float, nargs=3)
    parser.add_argument("--out", default="artifacts/showcase/isaac.json")
    args = parser.parse_args()

    record = build(args)
    print(json.dumps(record, indent=1), flush=True)
    return 0 if record["frames_written"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
