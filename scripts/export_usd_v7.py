"""Export a compiled scene to a USD stage, so it can be rendered somewhere else.

The owner wants the OPTION of re-rendering this work in a better renderer later
without moving the physics. MuJoCo ships a USD exporter; this drives it over a
scene this repository already compiled, steps it, and writes one stage.

SCOPE, and it is narrow: this is a RENDERING EXPORT. It changes nothing about the
physics, it is not an Isaac Sim project, and nothing measured in MuJoCo may be
described as validated anywhere else because a .usd of it exists.

It runs in its OWN virtual environment. usd-core and pillow are not in the cable
environment and must not be: that environment's exact package set is recorded in
every run manifest, and the project's provenance depends on it not drifting.

    .deps/usd-venv/Scripts/python.exe scripts/export_usd_v7.py

The gotcha that costs an hour if you meet it cold: ``output_directory`` must be a
RELATIVE name and ``output_directory_root`` its absolute parent. An absolute
``output_directory`` is joined into an invalid path and throws from inside
OpenUSD, several frames below anything you wrote.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

#: A USD prim path segment is an identifier: letters, digits and underscores,
#: not starting with a digit. MuJoCo builds prim paths straight out of geom
#: names, and this scene carries 36 that are not - dots and slashes from the
#: imported robot description, and minus signs from the fixture's own
#: coordinate-tagged names.
LEGAL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

ROOT = Path(__file__).resolve().parents[1]

#: The scene the replay clips were rendered from: the registered five-clip cell
#: with the CAD meshes attached as visual geometry. Any compiled scene.xml this
#: repository wrote will do.
DEFAULT_SCENE = ("artifacts/showcase/video/RC1_l15_compliant4000_m0_E0_conservative_r0/scene.xml")


def legalise(name: str, taken: set[str]) -> str:
    """The nearest legal identifier to a MuJoCo name, kept unique."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned or not cleaned[0].isalpha() and cleaned[0] != "_":
        cleaned = "g_"+cleaned
    candidate, index = cleaned, 1
    while candidate in taken:
        index += 1
        candidate = f"{cleaned}_{index}"
    taken.add(candidate)
    return candidate


def sanitise_scene(scene_xml: Path) -> tuple[Path, dict]:
    """A copy of the scene whose geom and tendon names USD will accept.

    Written BESIDE the original, because the asset paths inside it are relative
    and a copy somewhere else would not find the meshes. Only the names USD
    parses are touched, each of which occurs exactly once in the file, and the
    physics is untouched: this file is never stepped for a measurement, only for
    a picture.
    """
    text = scene_xml.read_text(encoding="utf-8")
    tree = ET.fromstring(text)
    taken = {elem.get("name") for elem in tree.iter() if elem.get("name")}
    renames = {}
    for tag in ("geom", "tendon", "site", "light", "camera"):
        for elem in tree.iter(tag):
            original = elem.get("name")
            if original and not LEGAL.match(original):
                renames[original] = legalise(original, taken)
    for original, replacement in renames.items():
        quoted = f'name="{original}"'
        if text.count(quoted) != 1:
            raise RuntimeError(f"{original!r} is not a single unambiguous name attribute; "
                               f"refusing to rewrite it")
        text = text.replace(quoted, f'name="{replacement}"')
    out = scene_xml.with_name(scene_xml.stem+"__usd.xml")
    out.write_text(text, encoding="utf-8")
    return out, renames


def export(scene_xml: Path, capture: Path, out_root: Path, name: str, frames: int,
           width: int, height: int) -> dict:
    """Write one stage from a rollout this repository already recorded.

    The states are REPLAYED, not re-stepped. Stepping a compiled scene with no
    controller collapses the arm under gravity inside five milliseconds - the
    first attempt here did exactly that and wrote 200 frames of a fall - and the
    resulting stage would be a picture of nothing that happened. Replaying the
    captured qpos gives the rollout the block actually scored.
    """
    from mujoco.usd import exporter

    legal, renames = sanitise_scene(scene_xml)
    model = mujoco.MjModel.from_xml_path(str(legal))
    data = mujoco.MjData(model)
    archive = np.load(capture, allow_pickle=False)
    positions = archive["qpos"]
    stride = max(1, len(positions)//frames)
    chosen = positions[::stride][:frames]
    out_root.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    # RELATIVE directory, ABSOLUTE root. The other way round throws from OpenUSD.
    usd = exporter.USDExporter(model=model, height=height, width=width,
                               output_directory=name,
                               output_directory_root=str(out_root.resolve()),
                               verbose=False)
    for state in chosen:
        data.qpos[:] = state
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)
        usd.update_scene(data)
    usd.save_scene(filetype="usd")
    wall = time.monotonic()-started

    stage_dir = out_root / name
    stages = sorted(p for p in stage_dir.rglob("*.usd") if p.is_file())
    return {
        "scene_xml": scene_xml.relative_to(ROOT).as_posix(),
        "scene_xml_exported": legal.relative_to(ROOT).as_posix(),
        "names_made_usd_legal": len(renames),
        "names_made_usd_legal_examples": dict(list(renames.items())[:4]),
        "stage_directory": stage_dir.relative_to(ROOT).as_posix(),
        "stages": [{"file": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size}
                   for p in stages],
        "assets": sorted({p.suffix for p in stage_dir.rglob("*") if p.is_file()}),
        "capture": capture.relative_to(ROOT).as_posix(),
        "source_frames_available": int(len(positions)),
        "frames_written": int(len(chosen)),
        "capture_stride_frames": stride,
        "stepped_at_export_time": False,
        "model": {"nbody": int(model.nbody), "ngeom": int(model.ngeom),
                  "nmesh": int(model.nmesh), "timestep_s": float(model.opt.timestep)},
        "wall_seconds": round(wall, 1),
    }


def inspect(stage: Path) -> dict:
    """Open the stage back up and say what is actually in it.

    A file that exists is not a stage that opens, and a stage that opens is not
    one with geometry in it.
    """
    from pxr import Usd, UsdGeom

    opened = Usd.Stage.Open(str(stage))
    if opened is None:
        return {"opens": False}
    prims = list(opened.Traverse())
    meshes = [p for p in prims if p.IsA(UsdGeom.Mesh)]
    xforms = [p for p in prims if p.IsA(UsdGeom.Xform)]
    animated = 0
    for prim in xforms:
        for op in UsdGeom.Xformable(prim).GetOrderedXformOps():
            if len(op.GetAttr().GetTimeSamples()) > 1:
                animated += 1
                break
    return {
        "opens": True,
        "prims": len(prims),
        "meshes": len(meshes),
        "xforms": len(xforms),
        "xforms_animated_over_time": animated,
        "time_codes": [float(opened.GetStartTimeCode()), float(opened.GetEndTimeCode())],
        "frames_per_second": float(opened.GetFramesPerSecond()),
        "default_prim": str(opened.GetDefaultPrim().GetPath()) if opened.GetDefaultPrim() else None,
        "up_axis": str(UsdGeom.GetStageUpAxis(opened)),
        "meters_per_unit": float(UsdGeom.GetStageMetersPerUnit(opened)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", type=Path, default=ROOT / DEFAULT_SCENE)
    parser.add_argument("--capture", type=Path,
                        help="capture.npz to replay; default the one beside --scene.")
    parser.add_argument("--out-root", type=Path, default=ROOT / "artifacts/showcase/usd")
    parser.add_argument("--name", default="cable_cell_v6",
                        help="Relative stage directory name. Never absolute.")
    parser.add_argument("--frames", type=int, default=200,
                        help="How many recorded states to write, spread over the rollout.")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/showcase/usd.json")
    args = parser.parse_args()

    capture = args.capture or args.scene.with_name("capture.npz")
    if not args.scene.is_file():
        parser.error(f"No compiled scene at {args.scene}. Render a replay clip or run the "
                     f"workbench first; both write a scene.xml.")
    if not capture.is_file():
        parser.error(f"No recorded rollout at {capture}. Run scripts/render_routing_video_v6.py "
                     f"for this request first; stepping the scene here instead would export a "
                     f"fall, not a route.")
    if Path(args.name).is_absolute():
        parser.error("--name must be RELATIVE; an absolute output_directory is joined into an "
                     "invalid path and throws from inside OpenUSD.")

    written = export(args.scene, capture, args.out_root, args.name, args.frames,
                     args.width, args.height)
    biggest = max(written["stages"], key=lambda s: s["bytes"]) if written["stages"] else None
    checked = inspect(ROOT / biggest["file"]) if biggest else {"opens": False}
    record = {
        "schema": 1, "id": "showcase_usd_v7", "stage": "D",
        "created_on": "2026-09-12",
        "status": ("verified" if checked.get("opens") and checked.get("meshes", 0) > 0
                   and checked.get("xforms_animated_over_time", 0) > 0 else "FAILED"),
        "what_this_is": "A RENDERING EXPORT of an already-compiled MuJoCo scene to a USD stage, "
                        "so the work can be re-rendered elsewhere later without moving the "
                        "physics.",
        "what_this_is_not": [
            "Not an Isaac Sim project, and not a validation anywhere but MuJoCo.",
            "No number in this repository was measured in, or checked against, anything that "
            "reads this stage.",
            "The cable is a MuJoCo cable plugin; a renderer reading this stage gets the geometry "
            "it was in at each captured frame, not the model that produced it.",
            "The states are replayed from a recorded rollout, not re-stepped. Stepping a compiled "
            "scene here with no controller collapses the arm in five milliseconds, and the first "
            "attempt in this session wrote 200 frames of exactly that before the check caught it.",
        ],
        "environment": {
            "why_separate": "usd-core and pillow are not in the cable environment and must not "
                            "be. That environment's exact package set is recorded in every run "
                            "manifest and the provenance depends on it not drifting.",
            "interpreter": ".deps/usd-venv/Scripts/python.exe",
            "packages": ["usd-core", "pillow", "mujoco==3.3.7", "numpy<2"],
        },
        "the_gotcha": "output_directory must be RELATIVE and output_directory_root its absolute "
                      "parent. An absolute output_directory is joined into an invalid path and "
                      "throws from inside OpenUSD.",
        "export": written,
        "read_back": checked,
        "command": ".deps/usd-venv/Scripts/python.exe scripts/export_usd_v7.py",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, default=float), encoding="utf-8")
    print(json.dumps({"status": record["status"], "stages": written["stages"],
                      "read_back": checked, "wall_seconds": written["wall_seconds"]}, indent=1))
    return 0 if record["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
