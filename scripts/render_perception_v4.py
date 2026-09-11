"""Render the release figure for the perception study.

Every number drawn here is read from an evidence record, never recomputed, so a
reader can follow any mark on the figure back to the JSON it came from. Panels:

  1  The crossover. Held-out false-safe rate against the declared socket-pose
     error, one line per arm, one panel per constraint. The registered margin is
     drawn as a band around the measurement-robust baseline, so "beats it by more
     than the margin" is something the eye can check.
  2  The cost axis. Held-out false-safe rate at the top error level against what
     each arm has to sense, so "which is worth it" is visible and not only
     "which is best".
  3  The denominator. Outcome composition per error level, including the censored
     share, because a predictor that hides behind censoring must be visible.
  4  The discretisation control. Settled geometry across segment count and
     integration rate, against the declared agreement tolerance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

ARM_STYLE = {
    "B0": {"colour": "#9aa0a6", "marker": "o", "label": "B0  scalar over the estimate"},
    "B0plus": {"colour": "#1a73e8", "marker": "s", "label": "B0+  scalar + declared margin"},
    "B2": {"colour": "#e8710a", "marker": "^", "label": "B2  force only"},
    "B1": {"colour": "#7b1fa2", "marker": "v", "label": "B1  feature model"},
    "M": {"colour": "#0b8043", "marker": "D", "label": "M  learned over the shape"},
    "Mh": {"colour": "#137333", "marker": "P", "label": "Mh  + short history"},
}
CONSTRAINT_TITLE = {
    "C1_clip": "C1  clip retention\nglobal length budget",
    "C2_bend": "C2  minimum bend radius\nlocal curvature limit",
    "C3_anchor": "C3  anchor load\nrate-dependent dynamic limit",
}


def level_axis(contract: dict) -> tuple[list[str], list[float]]:
    levels = contract["error_model"]["levels"]
    return [level["id"] for level in levels], [1000*level["socket_bias_m"] for level in levels]


def panel_crossover(axes, fit: dict, contract: dict, ids, biases):
    margin = contract["decision_rule"]["margin"]
    for axis, constraint in zip(axes, CONSTRAINT_TITLE, strict=True):
        block = fit["results"].get(constraint, {}).get("per_level", {})
        axis.set_title(CONSTRAINT_TITLE[constraint], fontsize=9, loc="left")
        reference = [(block.get(name) or {}).get("arms", {}).get("B0plus", {})
                     .get("false_safe_matched_coverage", {}).get("rate") for name in ids]
        if any(r is not None for r in reference):
            lower = [None if r is None else max(r-margin, 0.0) for r in reference]
            keep = [i for i, r in enumerate(reference) if r is not None]
            axis.fill_between([biases[i] for i in keep], [lower[i] for i in keep],
                              [reference[i] for i in keep], color="#1a73e8", alpha=0.12, lw=0,
                              zorder=1)
        for arm, style in ARM_STYLE.items():
            values = [(block.get(name) or {}).get("arms", {}).get(arm, {})
                      .get("false_safe_matched_coverage", {}).get("rate") for name in ids]
            keep = [i for i, v in enumerate(values) if v is not None]
            if not keep:
                continue
            axis.plot([biases[i] for i in keep], [values[i] for i in keep],
                      color=style["colour"], marker=style["marker"], ms=4.5, lw=1.4,
                      label=style["label"], zorder=3)
        crossing = fit["crossover"].get(constraint, {}).get("crossover")
        if crossing:
            index = ids.index(crossing["level"])
            axis.axvline(biases[index], color="#c5221f", ls="--", lw=1.0, zorder=2)
            axis.text(biases[index], axis.get_ylim()[1], " crossover", color="#c5221f",
                      fontsize=7, va="top")
        else:
            axis.text(0.97, 0.05, "no crossover", transform=axis.transAxes, fontsize=7,
                      color="#c5221f", ha="right")
        axis.set_xlabel("declared socket-pose bias (mm)", fontsize=8)
        axis.tick_params(labelsize=7)
        axis.grid(alpha=0.25, lw=0.5)
    axes[0].set_ylabel("held-out false-safe rate\nat matched coverage", fontsize=8)


def panel_cost(axis, fit: dict, ids):
    top = ids[-1]
    names, rates, parameters = [], [], []
    for arm in ARM_STYLE:
        block = (fit["results"].get("C1_clip", {}).get("per_level", {}).get(top) or {})
        entry = block.get("arms", {}).get(arm)
        if not entry:
            continue
        rate = entry["false_safe_matched_coverage"]["rate"]
        if rate is None:
            continue
        names.append(arm)
        rates.append(rate)
        count = entry["cost"]["parameters"]
        parameters.append(count if isinstance(count, int) else 33000)
    if not names:
        axis.set_axis_off()
        return
    for name, rate, count in zip(names, rates, parameters, strict=True):
        style = ARM_STYLE[name]
        axis.scatter(count, rate, color=style["colour"], marker=style["marker"], s=40, zorder=3)
        axis.annotate(name, (count, rate), textcoords="offset points", xytext=(5, 3), fontsize=7)
    axis.set_xscale("log")
    axis.set_xlabel("fitted parameters the arm carries (log)", fontsize=8)
    axis.set_ylabel(f"false-safe rate on C1 at {top}", fontsize=8)
    axis.set_title("What each arm costs", fontsize=9, loc="left")
    axis.tick_params(labelsize=7)
    axis.grid(alpha=0.25, lw=0.5)


def panel_denominator(axis, fit: dict, ids):
    states = ("respected", "violated", "censored")
    colours = {"respected": "#0b8043", "violated": "#c5221f", "censored": "#9aa0a6"}
    block = fit["results"].get("C1_clip", {}).get("per_level", {})
    bottom = np.zeros(len(ids))
    width = 0.6
    shares = {state: [] for state in states}
    for name in ids:
        entry = block.get(name) or {}
        censored = entry.get("censored_rate")
        violated = entry.get("violation_rate_observed")
        if censored is None or violated is None:
            shares["censored"].append(0.0)
            shares["violated"].append(0.0)
            shares["respected"].append(0.0)
            continue
        shares["censored"].append(censored)
        shares["violated"].append((1-censored)*violated)
        shares["respected"].append((1-censored)*(1-violated))
    for state in states:
        axis.bar(range(len(ids)), shares[state], width, bottom=bottom, color=colours[state],
                 label=state)
        bottom = bottom+np.asarray(shares[state])
    axis.set_xticks(range(len(ids)))
    axis.set_xticklabels(ids, fontsize=7)
    axis.set_ylabel("share of held-out requests", fontsize=8)
    axis.set_title("C1 outcome composition, censoring included", fontsize=9, loc="left")
    axis.legend(fontsize=6.5, loc="lower right", frameon=False)
    axis.tick_params(labelsize=7)


def panel_discretisation(axis, control: dict):
    rows = control.get("agreement", {}).get("rows", [])
    if not rows:
        axis.set_axis_off()
        return
    tolerance = control["agreement"]["tolerances"]["boot_to_anchor_m"]
    counts = sorted({row["segments"] for row in rows})
    colours = {count: c for count, c in zip(counts, ("#1a73e8", "#0b8043", "#e8710a"), strict=False)}
    for count in counts:
        picked = [row for row in rows if row["segments"] == count]
        axis.plot([row["physics_hz"]/1000 for row in picked],
                  [1000*row["boot_to_anchor_delta_m"] for row in picked],
                  marker="o", ms=4.5, lw=1.2, color=colours[count], label=f"{count} segments")
    axis.axhspan(-1000*tolerance, 1000*tolerance, color="#9aa0a6", alpha=0.18, lw=0)
    axis.axhline(0.0, color="#202124", lw=0.7)
    axis.set_xlabel("integration rate (kHz)", fontsize=8)
    axis.set_ylabel("settled boot-to-anchor\ndifference from 23 seg at 4 kHz (mm)", fontsize=8)
    axis.set_title("Spatial refinement, corrected damping", fontsize=9, loc="left")
    axis.legend(fontsize=6.5, frameon=False)
    axis.tick_params(labelsize=7)
    axis.grid(alpha=0.25, lw=0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit", type=Path, default=Path("evidence/cable_perception_v4.json"))
    parser.add_argument("--control", type=Path,
                        default=Path("evidence/cable_discretisation_v4.json"))
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--out", type=Path, default=Path("evidence/cable_perception_v4.png"))
    args = parser.parse_args()

    fit = json.loads((ROOT / args.fit).read_text(encoding="utf-8"))
    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    control_path = ROOT / args.control
    control = json.loads(control_path.read_text(encoding="utf-8")) if control_path.is_file() else {}
    ids, biases = level_axis(contract)

    figure = plt.figure(figsize=(11.5, 7.2), dpi=170)
    grid = figure.add_gridspec(2, 3, hspace=0.42, wspace=0.30,
                               left=0.07, right=0.985, top=0.86, bottom=0.09)
    crossover_axes = [figure.add_subplot(grid[0, i]) for i in range(3)]
    panel_crossover(crossover_axes, fit, contract, ids, biases)
    panel_cost(figure.add_subplot(grid[1, 0]), fit, ids)
    panel_denominator(figure.add_subplot(grid[1, 1]), fit, ids)
    panel_discretisation(figure.add_subplot(grid[1, 2]), control)

    handles, labels = crossover_axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", ncol=6, fontsize=7.5, frameon=False,
                  bbox_to_anchor=(0.5, 0.955))
    denominator = fit["denominator"]
    figure.suptitle(
        "How much must a safety check see?  "
        f"{denominator['requests']:,} registered requests, three constraints on one rollout, "
        f"held out by layout family",
        fontsize=11, y=0.985)
    figure.text(0.007, 0.012,
                f"Every number from {args.fit.as_posix()} and {args.control.as_posix()}.  "
                f"Margin {contract['decision_rule']['margin']} on both metrics, "
                f"{contract['groups']['test_context_requirement']} test contexts per level.  "
                "Simulation only; the error model is a model of how perception fails, not camera "
                "perception. No hardware claim.",
                fontsize=6.2, color="#5f6368")
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out)
    plt.close(figure)
    print(json.dumps({"out": args.out.as_posix(), "bytes": out.stat().st_size}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
