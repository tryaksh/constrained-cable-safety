"""Show the safety layer being used, on a decision state the block actually recorded.

A threshold in a table is not something anybody can pick up. This takes one real
decision state out of the executed block, loads the fitted filter the way a
planner would, and walks through what it gives you: the shape of the motions it
allows, which constraint binds, what a chosen motion spends, and what is left for
the step after. It also draws the envelope, because the shape of an allowed
region says more about a safety rule than its threshold does.

Runs no physics. Reads the evidence record and one recorded decision state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_safety_filter_v4 import SafetyFilter  # noqa: E402
from assembly_recovery.cable_study_v4 import core_actions, level_by_id  # noqa: E402


def find_decision(run_dirs, level_id: str, split: str = "test") -> dict:
    """One recorded decision state, from a held-out context at the named level."""
    for run_dir in run_dirs:
        for path in sorted(Path(run_dir).glob("*/result.json")):
            result = json.loads(path.read_text(encoding="utf-8"))
            case = result.get("case", {})
            if (case.get("study_split") != split or case.get("error_level") != level_id
                    or case.get("error_isolation", "all") != "all"
                    or result.get("decision_state") is None):
                continue
            return {"case": case["id"], "run_direction_xy": case["run_direction_xy"],
                    "decision": result["decision_state"],
                    "recorded_outcome": {
                        "reason": result["job"]["failure_reason"] or "completed",
                        **{k: v["state"] for k, v in result["constraints"].items()}},
                    "action_that_ran": case["repair_action"]}
    raise SystemExit(f"No usable {split}-split decision state at {level_id} in the given run dirs")


def draw(envelopes: dict, out_path: Path, filter_: SafetyFilter, contract: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    levels = list(envelopes)
    figure, axes = plt.subplots(1, len(levels), figsize=(3.2*len(levels), 4.3), dpi=170,
                                sharey=True)
    figure.subplots_adjust(bottom=0.22, top=0.86)
    axes = np.atleast_1d(axes)
    for axis, level_id in zip(axes, levels, strict=True):
        envelope = envelopes[level_id]
        safe = np.asarray(envelope["safe"])
        retreats = np.asarray(envelope["retreat_m"])*1000
        excursions = np.asarray(envelope["excursion_m"])*1000
        # Share of bearings that are safe at each (retreat, excursion): the
        # envelope is three-dimensional, and how much of the compass is open is
        # the part a planner cares about.
        share = safe.mean(axis=0)
        mesh = axis.pcolormesh(excursions, retreats, share, cmap="BuGn", vmin=0.0, vmax=1.0,
                               shading="nearest")
        axis.contour(excursions, retreats, share, levels=[0.999], colors="#0b8043", linewidths=1.4)
        axis.set_title(f"{level_id}   threshold {1000*envelope['effective_threshold_m']:.1f} mm",
                       fontsize=9, loc="left")
        axis.set_xlabel("excursion (mm)", fontsize=8)
        axis.tick_params(labelsize=7)
    axes[0].set_ylabel("retreat beyond the standard retract (mm)", fontsize=8)
    bar = figure.colorbar(mesh, ax=axes.tolist(), fraction=0.03, pad=0.02)
    bar.set_label("share of bearings the rule allows", fontsize=8)
    bar.ax.tick_params(labelsize=7)
    figure.suptitle("What the safety layer allows, and how the declared estimator error shrinks it",
                    fontsize=10.5, y=0.99)
    figure.text(0.006, 0.035,
                f"Threshold from {filter_.source.get('fit_id')}; margin from the declared "
                f"covariance at each level. Geometry only: this is what the rule permits, not what "
                f"the physics permits. Simulation; no hardware claim.",
                fontsize=6.2, color="#5f6368")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_path)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit", type=Path, default=Path("evidence/cable_perception_v4.json"))
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--level", default="E2")
    parser.add_argument("--out", type=Path, default=Path("evidence/cable_safety_envelope_v4.json"))
    parser.add_argument("--figure", type=Path,
                        default=Path("evidence/cable_safety_envelope_v4.png"))
    parser.add_argument("--resolution", type=int, default=28)
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    filter_ = SafetyFilter.from_evidence(ROOT / args.fit, ROOT / args.contract,
                                         ROOT / contract["base_config"]["path"])
    picked = find_decision([ROOT / d for d in args.run_dir], args.level)
    decision, run = picked["decision"], picked["run_direction_xy"]
    actions = core_actions(contract["action_design"])
    bounds = contract["action_design"]["bounds"]
    levels = [level["id"] for level in contract["error_model"]["levels"]]

    envelopes, walkthrough = {}, {}
    for level_id in levels:
        level = level_by_id(contract, level_id)
        envelope = filter_.envelope(decision, run, level, bounds, resolution=args.resolution)
        envelopes[level_id] = envelope
        chosen = filter_.best_action(decision, actions, run, level, prefer="largest")
        walkthrough[level_id] = {
            "margin_m": (list(filter_.rules.values())[0].margin(level) if filter_.rules else None),
            "effective_threshold_m": envelope["effective_threshold_m"],
            "share_of_action_space_allowed": envelope["safe_fraction"],
            "largest_safe_retreat_m": envelope["largest_safe_retreat_m"],
            "largest_safe_excursion_m": envelope["largest_safe_excursion_m"],
            "abstained": chosen is None,
            "chosen": (None if chosen is None else {
                "action": chosen["action"], "commanded_magnitude_m": chosen["magnitude_m"],
                "headroom_m": chosen["headroom_m"],
                "binding_constraint": chosen["verdict"]["binding_constraint"],
                "budget": filter_.budget(decision, chosen["action"], run, level)}),
        }

    report = {
        "schema": 1, "id": "cable_safety_envelope_v4", "created_on": contract["created_on"],
        "status": "worked_example_of_the_shipped_safety_layer",
        "scope": "A demonstration of the fitted filter on one recorded decision state. Runs no "
                 "physics and establishes no result; the numbers are the filter's own, applied to "
                 "a state the block recorded.",
        "filter": filter_.report(),
        "decision_state": {
            "case": picked["case"],
            "boot_to_anchor_m": decision["boot_to_anchor_m"],
            "min_bend_radius_m": decision.get("min_bend_radius_m"),
            "occluded_node_fraction": decision.get("occluded_node_fraction"),
            "anchor_reaction_n": decision.get("anchor_reaction_n"),
            "recorded_outcome": picked["recorded_outcome"],
            "action_that_actually_ran": picked["action_that_ran"],
            "note": "Held out of the fit. The recorded outcome is what the physics did with the "
                    "action the block issued, which is not necessarily the action the filter would "
                    "choose.",
        },
        "walkthrough": walkthrough,
        "envelope_grid": {"resolution": args.resolution, "bounds": bounds,
                          "stored": "safe_fraction and the axes only; the full boolean grid is "
                                    "large and is recomputed on demand by the filter"},
        "envelope_summary": {level_id: {
            "safe_fraction": envelopes[level_id]["safe_fraction"],
            "effective_threshold_m": envelopes[level_id]["effective_threshold_m"],
            "largest_safe_retreat_m": envelopes[level_id]["largest_safe_retreat_m"],
            "largest_safe_excursion_m": envelopes[level_id]["largest_safe_excursion_m"],
        } for level_id in levels},
        "reading": "As the declared estimator error grows the margin grows with it and the allowed "
                   "region shrinks. That is the whole content of a measurement-robust margin, and "
                   "it is what a planner sees: not a different rule, a smaller envelope.",
        "scope_and_limitations": [
            "Geometry only. The envelope is what the fitted rule allows, not what the physics "
            "permits; the study's held-out false-safe rate measures how often those differ.",
            "One decision state. The envelope's shape depends on where the boot is relative to the "
            "anchor, so this is an illustration of the rule, not a universal map.",
            "Simulation only; no hardware claim.",
        ],
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float), encoding="utf-8")
    draw(envelopes, ROOT / args.figure, filter_, contract)

    print(f"\nSafety layer loaded from {args.fit.name}")
    print(f"  rules: {', '.join(filter_.rules) or 'none'}")
    print(f"  unscored: {', '.join(filter_.report()['unscored']) or 'none'}")
    print(f"\nDecision state {picked['case']}")
    print(f"  boot to anchor {1000*decision['boot_to_anchor_m']:.1f} mm   "
          f"{100*decision.get('occluded_node_fraction', 0):.0f}% of the cable hidden")
    print(f"\n{'level':<7}{'margin':>9}{'threshold':>11}{'allowed':>9}{'issues':>28}{'spends':>9}")
    for level_id in levels:
        entry = walkthrough[level_id]
        chosen = entry["chosen"]
        issued = "abstains" if chosen is None else (
            f"retreat {1000*chosen['action']['retreat_m']:.0f} mm, "
            f"excursion {1000*chosen['action']['excursion_m']:.0f} mm")
        spends = ("-" if chosen is None else
                  f"{100*list(chosen['budget'].values())[0]['spent_fraction']:.0f}%")
        print(f"{level_id:<6}{1000*entry['margin_m']:>7.1f}mm"
              f"{1000*entry['effective_threshold_m']:>9.1f}mm"
              f"{100*entry['share_of_action_space_allowed']:>8.0f}%{issued:>32}{spends:>9}")
    print(f"\nwrote {args.out.as_posix()} and {args.figure.as_posix()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
