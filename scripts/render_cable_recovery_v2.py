"""Labelled release figure for the constrained-cable recovery block.

Frames are rendered from states recorded in the run ledgers, so they are a
faithful view of the physics that ran, not a staged or hand-set pose. Traces come
from the same ledgers. Rendering adds no new dynamics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

VIEWS = {
    "overview": {"distance": 0.95, "azimuth": 128, "elevation": -22, "offset": (0.11, -0.02, -0.10)},
    "connector": {"distance": 0.175, "azimuth": 118, "elevation": -14, "offset": (0.004, 0.0, -0.012)},
}


def frames(case_dir: Path, want: list[str], view: str, size=(900, 700)):
    """Render the requested recorded states through one registered camera."""
    ledger = np.load(case_dir / "ledger.npz", allow_pickle=False)
    names = [str(n) for n in ledger["event_names"]]
    model = mujoco.MjModel.from_xml_path(str(case_dir / "scene.xml"))
    data = mujoco.MjData(model)
    tip = model.site("plug__frame__sc_tip_link").id
    spec = VIEWS[view]
    renderer = mujoco.Renderer(model, width=size[1], height=size[0])
    options = mujoco.MjvOption()
    options.geomgroup[3] = 1
    out = {}
    for name in want:
        if name not in names:
            continue
        index = names.index(name)
        data.qpos[:] = ledger["event_qpos"][index]
        data.qvel[:] = ledger["event_qvel"][index]
        mujoco.mj_forward(model, data)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = data.site_xpos[tip] + np.asarray(spec["offset"])
        camera.distance, camera.azimuth, camera.elevation = spec["distance"], spec["azimuth"], spec["elevation"]
        renderer.update_scene(data, camera=camera, scene_option=options)
        out[name] = renderer.render().copy()
    renderer.close()
    return out, ledger, names


def traces(axis, ledger, title, release_travel_m):
    channels = {name: i for i, name in enumerate(ledger["servo_channels"])}
    rows = ledger["servo"]
    time = rows[:, channels["time_s"]]
    retreat = (rows[:, channels["tip_z"]] - rows[0, channels["tip_z"]]) * 1000
    axis.plot(time, retreat, color="#1f77b4", lw=1.4, label="plug retreat from home (mm)")
    axis.plot(time, rows[:, channels["raw_wrist_load_n"]], color="#8c8c8c", lw=1.0, label="raw wrist load (N)")
    axis.plot(time, rows[:, channels["anchor_load_n"]] * 100, color="#2ca02c", lw=1.2,
              label="strain-relief reaction (N x100)")
    axis.axhline(release_travel_m * 1000, color="#d62728", ls="--", lw=1.0,
                 label=f"measured clip-release travel {release_travel_m * 1000:.1f} mm")
    lost = np.flatnonzero(rows[:, channels["clip_retained"]] < 0.5)
    if len(lost):
        axis.axvline(time[lost[0]], color="#d62728", lw=1.4)
        axis.text(time[lost[0]], axis.get_ylim()[1] * 0.92, "  required clip released",
                  color="#d62728", fontsize=8, va="top")
    axis.set_title(title, fontsize=9)
    axis.set_xlabel("job time (s)", fontsize=8)
    axis.tick_params(labelsize=7)
    axis.grid(alpha=0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence/cable_recovery_block_v2.json")
    parser.add_argument("--out", type=Path, default=ROOT / "evidence/cable_recovery_v2")
    args = parser.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    block = json.loads(args.evidence.read_text(encoding="utf-8"))
    release = block["measured_task_constants"]["clip_release_travel_m"]
    good, _, _ = frames(args.run_dir / "g2_o5_rules", ["settled", "first_witness", "repair_start", "terminal"], "overview")
    close, good_ledger, _ = frames(args.run_dir / "g2_o5_rules", ["first_witness", "terminal"], "connector")
    bad, bad_ledger, _ = frames(args.run_dir / "g1_bad_repair_near_home", ["terminal"], "overview")

    figure = plt.figure(figsize=(15.5, 9.6), dpi=130)
    grid = figure.add_gridspec(3, 4, height_ratios=[1.5, 1.0, 0.95], hspace=0.24, wspace=0.06)
    panels = [("settled", "1  settled installation"), ("first_witness", "2  witnessed contact stall"),
              ("repair_start", "3  robot-driven repair begins"), ("terminal", "4  held clip-preserving seating")]
    for column, (name, label) in enumerate(panels):
        axis = figure.add_subplot(grid[0, column])
        axis.imshow(good[name])
        axis.set_title(label, fontsize=9.5)
        axis.axis("off")
    # Callouts are placed in axes fraction against the first overview panel; the
    # targets are the rendered fixture parts, measured once from that panel.
    labels = [("plug", (0.36, 0.33), (0.04, 0.16)),
              ("mounted port", (0.35, 0.40), (0.02, 0.52)),
              ("service loop", (0.48, 0.46), (0.20, 0.08)),
              ("shallow post", (0.565, 0.585), (0.36, 0.90)),
              ("required open clip", (0.60, 0.60), (0.50, 0.80)),
              ("strain relief", (0.70, 0.60), (0.70, 0.90))]
    for text, target, place in labels:
        figure.axes[0].annotate(
            text, xy=(target[0], 1 - target[1]), xytext=(place[0], 1 - place[1]), xycoords="axes fraction",
            fontsize=7.5, color="#111111", ha="left", va="center",
            bbox={"boxstyle": "round,pad=0.18", "fc": "#ffffffdd", "ec": "none"},
            arrowprops={"arrowstyle": "-", "lw": 0.7, "color": "#dddddd", "shrinkA": 1, "shrinkB": 1})
    for column, (name, label) in enumerate([("first_witness", "connector close-up at the witnessed stall"),
                                            ("terminal", "connector close-up at held seating")]):
        axis = figure.add_subplot(grid[1, column])
        axis.imshow(close[name])
        axis.set_title(label, fontsize=9)
        axis.axis("off")
    axis = figure.add_subplot(grid[1, 2])
    axis.imshow(bad["terminal"])
    axis.set_title("negative control: repair beyond the envelope", fontsize=9)
    axis.axis("off")
    notes = figure.add_subplot(grid[1, 3])
    notes.axis("off")
    notes.text(0.0, 1.0, "\n".join([
        "Simulation, MuJoCo 3.3.7, CPU. Frames rendered from recorded states.",
        "Controller: blind existing insertion routine, then scripted cable-aware",
        "repair rules. No learned model of any kind is present.",
        "Endpoint: robot still holds the plug, detector contact plus 0.5 s",
        "continuous seating dwell, required open clip retained throughout.",
        "NOT a released or latched connection, learned pickup, or hardware result.",
        "",
        f"Measured clip-release travel: {release * 1000:.1f} mm of plug retreat.",
        "Release is kinematic slack exhaustion; the strain-relief reaction stays",
        "below 0.2 N throughout. Playback: static frames, not real time.",
    ]), fontsize=8, va="top", family="monospace")
    traces(figure.add_subplot(grid[2, :2]), good_ledger,
           "blind attempt, witnessed stall, repair, held seating (g2_o5_rules)", release)
    axis = figure.add_subplot(grid[2, 2:])
    traces(axis, bad_ledger, "same library, repair beyond the envelope (g1_bad_repair_near_home)", release)
    axis.legend(fontsize=7, loc="upper left", framealpha=0.9)
    figure.suptitle("Constrained-cable connector recovery: held, clip-preserving seating (block v2 r01)", fontsize=12)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.out.with_suffix(".png"), bbox_inches="tight")
    figure.savefig(args.out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)
    print(json.dumps({"png": str(args.out.with_suffix(".png")), "pdf": str(args.out.with_suffix(".pdf"))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
