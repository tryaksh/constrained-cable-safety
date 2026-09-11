"""Print the perception study's record as a table a person can read.

Reads the fitted evidence file and prints what the contract's rule decided, the
per-level arm comparison for each constraint, the cost axis and the denominator.
It computes nothing: every number here is read from the record, so a line in this
table and a line in the JSON cannot disagree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("B0", "B0plus", "B2", "B1", "M", "Mh")
LABEL = {"B0": "B0  scalar", "B0plus": "B0+ scalar+margin", "B2": "B2  force only",
         "B1": "B1  features", "M": "M   shape", "Mh": "Mh  shape+history"}


def cell(value, width=7, places=3):
    if value is None:
        return "-".rjust(width)
    try:
        if value != value:
            return "nan".rjust(width)
    except TypeError:
        return str(value).rjust(width)
    return f"{value:.{places}f}".rjust(width)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit", type=Path, default=Path("evidence/cable_perception_v4.json"))
    args = parser.parse_args()
    fit = json.loads((ROOT / args.fit).read_text(encoding="utf-8"))

    denominator = fit["denominator"]
    print(f"\n{fit['id']}   {fit['status']}")
    print(f"requests {denominator['requests']:,}   usable {denominator['usable_for_fitting']:,}   "
          f"guards {fit['guards']['verdict']}   margin check {fit['margin_resolution_verdict']}")
    print("outcomes: " + "  ".join(f"{k} {v}" for k, v in denominator["by_job_reason"].items()))

    for constraint, block in fit["results"].items():
        if "per_level" not in block:
            print(f"\n{constraint}: {block.get('status')}")
            continue
        crossing = fit["crossover"][constraint]
        print(f"\n=== {constraint} ===")
        print(f"train rows {block['train_rows']:,}  violation rate "
              f"{block['train_violation_rate']:.3f}  "
              f"B0 threshold {block['selection']['B0']['threshold_m']:.4f} m")
        levels = list(block["per_level"])
        print("\n  false-safe rate at matched coverage")
        print("  " + "arm".ljust(20) + "".join(f"{name:>10}" for name in levels))
        for arm in ARMS:
            row = [block["per_level"][level]["arms"][arm]["false_safe_matched_coverage"]["rate"]
                   for level in levels]
            print(f"  {LABEL[arm]:<20}" + "".join(cell(v, 10) for v in row))
        print("  " + "censored share".ljust(20)
              + "".join(cell(block["per_level"][level]["censored_rate"], 10)
                        for level in levels))
        print("\n  action-ranking regret")
        print("  " + "arm".ljust(20) + "".join(f"{name:>10}" for name in levels))
        for arm in ARMS:
            row = [block["per_level"][level]["arms"][arm]["ranking_regret"]["regret"]
                   for level in levels]
            print(f"  {LABEL[arm]:<20}" + "".join(cell(v, 10) for v in row))
        resolutions = {level: block["per_level"][level]["arms"]["B0"]["ranking_regret"]["resolution"]
                       for level in levels}
        print("  " + "metric resolution".ljust(20)
              + "".join(cell(v, 10) for v in resolutions.values()))
        where = ("FOUND at {level} by {arm}".format(**crossing["crossover"])
                 if crossing["crossover_found"] else "none inside the registered range")
        print(f"\n  crossover: {where}")
        print("  force-only beats B0+ by more than the margin: " +
              ", ".join(f"{k}={'yes' if v else 'no'}"
                        for k, v in crossing["force_only_beats_B0plus_by_level"].items()))

    print("\n=== registered prediction ===")
    for key, text in fit["prediction"].items():
        if key in ("declared_before_collection", "falsification"):
            continue
        print(f"  {key}: {text}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
