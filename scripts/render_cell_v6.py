"""Render the routing cell: what the CAD jig and the installed cable actually look like.

Builds the registered cell at one accepted service loop, settles it, and writes a
few still views. Two of them are the point of the exercise: the same scene with
the CAD meshes shown and with only the primitive collision geometry shown. The
cable touches the second one and only ever looks at the first.

It renders and decides nothing. Run it after a block, not during one - it
compiles a scene and takes a settle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_cell_v6 import cell_case, group_id  # noqa: E402
from assembly_recovery.cable_constrained_v2 import build_scene, clip_state  # noqa: E402
from scripts.evaluate_cable_recovery_v2 import settle  # noqa: E402

#: Camera set-ups, in the compiled world. ``look`` names what each frames.
VIEWS = {
    "cell": {"distance": 0.62, "azimuth": 138, "elevation": -26, "offset": (0.10, 0.0, 0.02),
             "look": "route"},
    "clips": {"distance": 0.24, "azimuth": 118, "elevation": -18, "offset": (0.02, 0.0, 0.01),
              "look": "route"},
    "corner": {"distance": 0.17, "azimuth": 58, "elevation": -24, "offset": (0.0, 0.0, 0.008),
               "look": "last_clip"},
}


def look_at(scene, spec):
    clips = [np.asarray(c["origin_world"], dtype=float) for c in scene.clips]
    if spec["look"] == "last_clip":
        return clips[-1]
    return np.mean(clips, axis=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path,
                        default=ROOT / "configs/cable_cell_v6_candidates.json")
    parser.add_argument("--screen", type=Path, default=ROOT / "evidence/cable_cell_screen_v6.json")
    parser.add_argument("--cad", type=Path, default=ROOT / "evidence/cable_cell_cad_v6.json")
    parser.add_argument("--base", type=Path, default=ROOT / "configs/cable_recovery_task_v2.json")
    parser.add_argument("--out", type=Path, default=ROOT / "evidence")
    parser.add_argument("--loop", type=float, help="Accepted service loop; default the middle one.")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=860)
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
    base = json.loads(args.base.read_text(encoding="utf-8-sig"))
    screen = json.loads(args.screen.read_text(encoding="utf-8"))
    cad = json.loads(args.cad.read_text(encoding="utf-8"))
    cell = screen["registered_cell"]
    layout = next(e for e in candidates["layouts"] if e["id"] == cell)
    loops = sorted(a["installed_loop_m"] for a in screen["accepted_cell_detail"]
                   if a["layout"] == cell)
    loop = args.loop if args.loop is not None else loops[len(loops)//2]

    runtime = {**base, "render_visuals": True}
    written = []
    for tag, asset in (("cad", cad), ("primitives", None)):
        case = cell_case(layout, loop, candidates, base, asset,
                         id=f"render_{group_id(cell, loop)}_{tag}",
                         controller="force_guided_insertion", calibration_seed=76000,
                         gate="render", purpose="Routing-cell still render.")
        directory = ROOT / "artifacts/cell/render" / case["id"]
        directory.mkdir(parents=True, exist_ok=True)
        scene = build_scene(ROOT, runtime, case, directory)
        settled, reason = settle(scene, runtime)[1:]
        state = clip_state(scene)
        print(json.dumps({"variant": tag, "settled": bool(settled), "reason": reason,
                          "required_retained": state["summary"]["required_retained"],
                          "geoms": int(scene.model.ngeom)}), flush=True)
        renderer = mujoco.Renderer(scene.model, width=args.width, height=args.height)
        renderer.scene.maxgeom = max(renderer.scene.maxgeom, 4000)
        options = mujoco.MjvOption()
        camera = mujoco.MjvCamera()
        for name, spec in VIEWS.items():
            camera.lookat[:] = look_at(scene, spec)+np.asarray(spec["offset"])
            camera.distance, camera.azimuth = spec["distance"], spec["azimuth"]
            camera.elevation = spec["elevation"]
            renderer.update_scene(scene.data, camera=camera, scene_option=options)
            path = args.out / f"cable_cell_v6_{name}_{tag}.png"
            Image.fromarray(renderer.render()).save(path)
            written.append(path.relative_to(ROOT).as_posix())
        renderer.close()

    print(json.dumps({"cell": cell, "installed_loop_m": loop, "written": written}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
