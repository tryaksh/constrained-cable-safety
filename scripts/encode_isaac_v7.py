"""Encode the Isaac Sim frame sequence to an mp4, and check the file that comes out.

Runs in the cable environment, because that is where ffmpeg lives. Isaac Sim
writes numbered PNGs; this stitches them, stamps the one caption the clip has to
carry, and then decodes the result back to confirm it holds what it claims to.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]

CAPTION = ("Re-rendered in Isaac Sim from recorded MuJoCo positions. "
           "Rendering only - the physics, and every measured number, are MuJoCo's.")


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def font(size: int, bold: bool = False):
    for name in (("segoeuib.ttf",) if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/"+name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def order(paths):
    def key(path: Path):
        digits = re.findall(r"(\d+)", path.stem)
        return (int(digits[-1]) if digits else 0, path.name)
    return sorted(paths, key=key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-dir", type=Path,
                        default=ROOT / "artifacts/showcase/isaac/wide")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/showcase/isaac/isaac_wide.mp4")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Shrink the frames before encoding; the artifact host caps a "
                             "binary file at 15 MB.")
    parser.add_argument("--quality", type=int, default=9)
    parser.add_argument("--title", default="Five clips, one check")
    parser.add_argument("--subtitle",
                        default="the route the study scored, re-rendered for looks")
    args = parser.parse_args()

    images = order(args.frames_dir.rglob("rgb_*.png"))
    if not images:
        parser.error(f"No rgb_*.png under {args.frames_dir}")
    first = Image.open(images[0]).convert("RGB")
    width, height = first.size
    if args.scale != 1.0:
        width, height = int(width*args.scale)//2*2, int(height*args.scale)//2*2
    big, small = font(30, True), font(17)

    writer = imageio_ffmpeg.write_frames(str(args.out), (width, height), fps=args.fps,
                                         quality=args.quality, macro_block_size=1)
    writer.send(None)
    for path in images:
        frame = Image.open(path).convert("RGB")
        if frame.size != (width, height):
            frame = frame.resize((width, height), Image.LANCZOS)
        draw = ImageDraw.Draw(frame, "RGBA")
        draw.rectangle([0, height-82, width, height], fill=(8, 12, 17, 205))
        draw.text((26, height-70), args.title, font=big, fill=(236, 244, 248))
        draw.text((26, height-32), CAPTION, font=small, fill=(150, 170, 186))
        draw.text((width-26, height-70), args.subtitle, font=small, fill=(150, 170, 186),
                  anchor="ra")
        writer.send(np.asarray(frame))
    writer.close()

    reader = imageio_ffmpeg.read_frames(str(args.out))
    meta = next(reader)
    decoded = 0
    brightest = 0.0
    for index, packet in enumerate(reader):
        decoded += 1
        if index % max(1, len(images)//6) == 0:
            grey = np.frombuffer(packet, dtype=np.uint8).reshape(height, width, 3).mean(axis=2)
            brightest = max(brightest, float(grey.std()))
    record = {
        "video": relative(args.out),
        "source_frames": len(images),
        "frames_decoded": decoded,
        "resolution": list(meta["size"]),
        "fps": float(meta["fps"]),
        "bytes": args.out.stat().st_size,
        "worst_sampled_contrast": round(brightest, 2),
        "passes": decoded == len(images) and brightest > 8.0,
    }
    print(json.dumps(record, indent=1), flush=True)
    return 0 if record["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
