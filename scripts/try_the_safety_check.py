"""Run the shipped safety check on a real decision, with no simulator installed.

`SafetyFilter` is the piece of this project someone else could pick up. It needs
numpy and nothing heavier: the simulator is only ever needed to *generate* the
state the check reads, never to *use* the check. Nothing here demonstrated that,
so this does.

It loads the five-clip rig the routing study registered, takes the estimate that
study's own job held at its first repair decision, and asks the check what it
would allow — at each of the three declared eyesight levels. For the largest move
it allows, it says which of the three limits is closest to being broken and how
much of each budget that move spends.

The estimates are committed in `artifacts/showcase/demo.json` and every number
printed below is computed here, from them, by the same filter the study ran.

    .venv/Scripts/python.exe scripts/try_the_safety_check.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_safety_filter_v4 import SafetyFilter  # noqa: E402

EYESIGHT = {"E0": "perfect information", "E2": "small error", "E4": "large error"}

#: What each constraint is, in words a reader who has not read the contract can
#: use. The ids are what the code and the records call them.
PLAIN = {
    "C1_clip": "the cable stays in its clips",
    "C2_bend": "the cable is not bent too tightly",
    "C3_anchor": "the clamp is not pulled too hard",
}


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def registered_rig() -> dict:
    """The rig this demonstration runs on, read out of the files that declare it."""
    demo = read("artifacts/showcase/demo.json")
    candidates = read("configs/cable_cell_v6_candidates.json")
    screen = read("evidence/cable_cell_screen_v6.json")
    cell = demo["levels"]["E0"]["case"].split("_l")[0]
    loop_mm = float(demo["levels"]["E0"]["case"].split("_l")[1].split("_")[0]) / 10.0
    layout = next(entry for entry in candidates["layouts"] if entry["id"] == cell)
    installed = next(entry for entry in screen["accepted_cell_detail"]
                     if entry["layout"] == cell
                     and abs(entry["installed_loop_m"] * 1000 - loop_mm) < 1e-9)
    return {"cell": cell, "loop_mm": loop_mm, "clips": len(layout["clips"]),
            "installed": installed, "demo": demo}


def cross_check(filter_: SafetyFilter, demo: dict) -> tuple[bool, float, float]:
    """The clip headroom here must equal the one the committed job result recorded."""
    decision = demo["levels"]["E0"]["decision"]
    rule = filter_.rules["C1_clip"]
    here = rule.effective_threshold(demo["levels"]["E0"]["declared_error"])-decision["boot_to_anchor_m"]
    recorded = read("artifacts/showcase/tool.json")["checks"][2]["expected"]["c1_headroom_series_m"][0]
    return abs(here-recorded) < 5e-10, here, recorded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--level", choices=sorted(EYESIGHT), default="E0",
                        help="which eyesight level to break the chosen move down under")
    args = parser.parse_args()

    rig = registered_rig()
    demo = rig["demo"]
    source = demo["safety_filter"]
    filter_ = SafetyFilter.from_evidence(ROOT / source["fit"], ROOT / source["contract"],
                                         ROOT / source["base"])
    actions = demo["candidate_actions"]

    print("\nThe shipped check, deciding a real move. Nothing here runs a simulator.\n")
    print(f"  the rig     {rig['cell']}, {rig['clips']} clips, {rig['loop_mm']:.1f} mm of service "
          f"loop, installed at "
          f"{rig['installed']['boot_to_anchor_m'] * 1000:.1f} mm plug-to-clamp")
    print(f"  the check   one distance, against a threshold of "
          f"{filter_.rules['C1_clip'].threshold_m * 1000:.1f} mm less whatever margin the "
          f"estimator asks for")
    print(f"  the state   the first repair decision of the registered job "
          f"{demo['levels']['E0']['case']},")
    print("              and the same decision at each of the other two levels")
    print(f"\n  {'eyesight':<21}{'margin':>8}{'limit':>10}{'allows':>9}"
          f"  {'biggest move it allows':<26}{'binds on'}")

    breakdown = None
    for level, block in demo["levels"].items():
        decision, declared = block["decision"], block["declared_error"]
        run = block["run_direction_xy"]
        rule = filter_.rules["C1_clip"]
        allowed = sum(1 for action in actions
                      if filter_.verdict(decision, action, run, declared)["safe"])
        chosen = filter_.best_action(decision, actions, run, declared, prefer="largest")
        move = ("nothing" if chosen is None else
                f"{chosen['action']['retreat_m'] * 1000:.0f} mm back, "
                f"{chosen['action']['excursion_m'] * 1000:.0f} mm across")
        binds = "-" if chosen is None else chosen["verdict"]["binding_constraint"]
        print(f"  {EYESIGHT[level]:<21}{rule.margin(declared) * 1000:>6.1f}mm"
              f"{rule.effective_threshold(declared) * 1000:>8.1f}mm"
              f"{f'{allowed} of {len(actions)}':>9}  {move:<26}{binds}")
        if level == args.level and chosen is not None:
            breakdown = (level, decision, declared, run, chosen)

    if breakdown is None:
        print(f"\nThe check allows nothing at {args.level}, so there is no move to break down.")
        return 0

    level, decision, declared, run, chosen = breakdown
    budget = filter_.budget(decision, chosen["action"], run, declared)
    print(f"\n  What that move costs at {EYESIGHT[level]}. Every figure is millimetres of")
    print("  plug-to-clamp distance: one distance, three thresholds, three budgets.\n")
    for name, entry in chosen["verdict"]["constraints"].items():
        spent = budget[name]
        print(f"  {name:<11}{PLAIN[name]:<35}"
              f"{spent['headroom_at_decision_m'] * 1000:>6.1f} of room, spends "
              f"{spent['spent_fraction']:>4.0%}, leaves "
              f"{entry['headroom_m'] * 1000:>5.1f}")

    agrees, here, recorded = cross_check(filter_, demo)
    print(f"\n  Cross-check: the clip headroom computed here is {here * 1000:.6f} mm; the job "
          f"the study\n  ran recorded {recorded * 1000:.6f} mm at the same decision. "
          f"{'They agree.' if agrees else 'THEY DISAGREE.'}")
    block = read("artifacts/cell/block.json")["the_two_numbers_the_block_turns_on"]
    print(f"\n  Reading it: this rig loses a clip somewhere past "
          f"{block['what_the_cell_admits_m'] * 1000:.0f} mm of commanded pull-back, and the "
          f"check is\n  still approving "
          f"{chosen['action']['retreat_m'] * 1000:.0f} mm. The threshold was fitted on a "
          f"one-clip rig where far more\n  cable could straighten out to absorb the pull. That "
          f"gap is finding 3 in README.md.\n")
    return 0 if agrees else 1


if __name__ == "__main__":
    raise SystemExit(main())
