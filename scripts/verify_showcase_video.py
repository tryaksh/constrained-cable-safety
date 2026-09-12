"""Check the replay clips by opening them, not by trusting an exit code.

A render command that returns zero has proved nothing: ffmpeg will happily write
a file of black frames. This decodes every clip, counts its frames, reads its
resolution back out of the container, samples frames across the whole clip and
measures how much of each one is actually painted, and re-reads every capture
record to confirm the rollout it shows is the rollout the block scored.

Writes artifacts/showcase/video.json, which is Stage A's done-condition.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

#: A frame is "painted" if it has real spread and is not almost entirely one
#: colour. A uniformly blank frame - black, or one flat fill - fails both.
MIN_STD = 8.0
MAX_FLAT_FRACTION = 0.97


def sample_frames(path: Path, wanted: int = 9) -> dict:
    """Decode the whole clip, measuring an even spread of frames as it goes.

    Every frame is decoded, because a count taken from the writer is not evidence
    the file holds them; only a spread of them is kept and measured, because a
    1920x900 clip held whole is a gigabyte of nothing useful.
    """
    reader = imageio_ffmpeg.read_frames(str(path))
    meta = next(reader)
    width, height = meta["size"]
    expected = max(1, round(float(meta.get("duration") or 0.0)*float(meta["fps"])))
    stride = max(1, expected//wanted)
    frames = 0
    measured: list[dict] = []
    for index, packet in enumerate(reader):
        frames += 1
        if index % stride or len(measured) >= wanted:
            continue
        grey = np.frombuffer(packet, dtype=np.uint8).reshape(height, width, 3).mean(axis=2)
        values, counts = np.unique((grey//8).astype(np.uint8), return_counts=True)
        measured.append({"frame": index, "std": float(grey.std()),
                         "flattest_fraction": float(counts.max()/grey.size),
                         "distinct_bands": int(len(values))})
    return {"resolution": [width, height], "fps": float(meta["fps"]),
            "duration_s": round(float(meta.get("duration") or 0.0), 2),
            "frames_decoded": frames, "frames_measured": len(measured), "sampled": measured,
            "blank_frames": sum(1 for m in measured
                                if m["std"] < MIN_STD
                                or m["flattest_fraction"] > MAX_FLAT_FRACTION)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-dir", type=Path, default=ROOT / "artifacts/showcase/video")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/showcase/video.json")
    parser.add_argument("--min-width", type=int, default=1280)
    parser.add_argument("--min-height", type=int, default=720)
    args = parser.parse_args()

    clips = []
    for record_path in sorted(args.video_dir.glob("*.json")):
        summary = json.loads(record_path.read_text(encoding="utf-8"))
        if "video" not in summary:
            continue
        path = ROOT / summary["video"]
        measured = sample_frames(path)
        captures = []
        for case in summary["cases"]:
            capture = json.loads((args.video_dir / case / "capture.json")
                                 .read_text(encoding="utf-8"))
            captures.append({"case": case, "supervisor": capture["supervisor"],
                             "error_level": capture["error_level"],
                             "frames": capture["frames"],
                             "capture_hz": capture["capture_hz"],
                             "outcome": capture["failure_reason"] or "route completed",
                             "route_completed": capture["route_completed"],
                             "terminal_required_clips": capture["terminal_clips"],
                             "block_result": capture["block_result"],
                             "reproduces_block": capture["reproduces_block"],
                             "mismatch": capture["mismatch"]})
        checks = {
            "decodes": measured["frames_decoded"] > 0,
            "frame_count_matches_render": measured["frames_decoded"] == summary["frames"],
            "resolution_at_least_declared": (measured["resolution"][0] >= args.min_width
                                             and measured["resolution"][1] >= args.min_height),
            "fps_at_least_30": measured["fps"] >= 30.0,
            "no_blank_sampled_frames": measured["blank_frames"] == 0,
            "every_capture_reproduces_the_block": all(c["reproduces_block"] for c in captures),
        }
        clips.append({"name": record_path.stem, "layout": summary["layout"],
                      "view": summary["view"], "video": summary["video"],
                      "bytes": summary["bytes"], "declared_frames": summary["frames"],
                      "measured": measured, "captures": captures, "checks": checks,
                      "passes": all(checks.values())})

    report = {
        "schema": 1, "id": "showcase_video_v7", "stage": "A",
        "status": "verified" if clips and all(c["passes"] for c in clips) else "FAILED",
        "created_on": "2026-09-12",
        "what_this_is": "Offline replay clips of registered requests from the v6 routing block. "
                        "Not a study result, not a new measurement and not a hardware claim.",
        "how_they_are_made": [
            "scripts/render_routing_video_v6.py calls the routing worker's own run_case with a "
            "per-tick observer, so the replay shares one control path and one perception stream "
            "with the block. A capture that drew a different number of random numbers would show "
            "a rollout that never happened.",
            "Every capture is compared against the request's committed result.json on failure "
            "reason, elapsed time, seating, route completion, per-clip retention, clip-loss "
            "attribution, every constraint label and every issued action. A clip whose capture "
            "does not reproduce the block is refused before it is rendered.",
            "Rendering replays recorded states; mj_step is never called at render time.",
        ],
        "checks_run_here": {
            "decode": "Every frame is decoded from the written file, not counted from the writer.",
            "resolution": f"at least {args.min_width}x{args.min_height}, read from the container",
            "not_blank": f"sampled frames must have grey standard deviation >= {MIN_STD} and no "
                         f"single 8-level band covering more than "
                         f"{100*MAX_FLAT_FRACTION:.0f}% of the frame",
            "reproduction": "every capture record's reproduces_block is true",
        },
        "clips": clips,
        "evidence_behind_the_numbers_on_screen": {
            "route outcomes, per-clip retention, issued actions, budgets":
                "artifacts/cable/routing-v6-s1/<request>/result.json",
            "the block's fitted verdicts": "evidence/cable_routing_v6.json",
            "18 mm admitted against 58 mm permitted": "artifacts/cell/block.json - "
                                                      "the_two_numbers_the_block_turns_on",
            "declared perception error at each level":
                "configs/cable_routing_v6.json - perception.levels",
        },
    }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"],
                      "clips": [{"name": c["name"], "passes": c["passes"],
                                 "frames": c["measured"]["frames_decoded"],
                                 "resolution": c["measured"]["resolution"],
                                 "blank": c["measured"]["blank_frames"]} for c in clips]},
                     indent=1))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
