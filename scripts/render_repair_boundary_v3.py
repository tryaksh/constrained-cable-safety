"""Render the release figure for the safe-repair boundary block.

Three panels, drawn only from the compact dataset and the fit report, so the
figure cannot drift from the numbers the evidence records. Outcome classes are
separated by position rather than by colour: the good and critical status hues
are close enough under deuteranopia that colour alone could not carry them.
"""

from __future__ import annotations

import argparse
import json
import math
import textwrap
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
RETAINED, LOST = "#2a78d6", "#e34948"
PREDICTOR = {"B0": "#2a78d6", "B1": "#eb6834", "M": "#1baf7a", "none": "#898781"}
BAR_LABEL = {"B0": "B0", "B1": "B1", "M": "M", "none": "none"}
OUTCOME_ORDER = ["completed_clip_retained", "load_abort", "deadline", "clip_lost", "completed_clip_lost"]
OUTCOME_LABEL = {"completed_clip_retained": "seated, clip kept", "load_abort": "load abort",
                 "deadline": "deadline", "clip_lost": "clip released",
                 "completed_clip_lost": "seated, clip lost"}


def style(axes):
    axes.set_facecolor(SURFACE)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color("#c3c2b7")
        axes.spines[side].set_linewidth(0.8)
    axes.tick_params(colors=MUTED, labelsize=8, length=3, width=0.8)
    for label in axes.get_xticklabels()+axes.get_yticklabels():
        label.set_color(INK_2)


def panel_boundary(axes, rows, threshold_mm):
    """Every executed action against the one number the analytic baseline uses."""
    present = [o for o in OUTCOME_ORDER if any(r["outcome"] == o for r in rows)]
    rng = np.random.default_rng(7)
    blended = axes.get_yaxis_transform()
    for position, outcome in enumerate(present):
        values = [1000*r["features"]["endpoint_boot_to_anchor_m"] for r in rows if r["outcome"] == outcome]
        jitter = rng.uniform(-0.2, 0.2, len(values))
        colour = LOST if outcome.endswith("clip_lost") else RETAINED
        axes.scatter(values, position+jitter, s=9, c=colour, alpha=0.55, linewidths=0)
        axes.text(0.015, position+0.3, f"n={len(values)}", transform=blended, fontsize=7, color=MUTED)
    axes.set_ylim(-0.6, len(present)-0.35)
    axes.axvline(threshold_mm, color=INK, linewidth=1.4, linestyle=(0, (5, 3)), zorder=3)
    axes.annotate(f"fitted threshold {threshold_mm:.0f} mm", xy=(threshold_mm, -0.5),
                  xytext=(6, 0), textcoords="offset points", fontsize=7.5, color=INK, va="center")
    axes.set_yticks(range(len(present)))
    axes.set_yticklabels([OUTCOME_LABEL[o] for o in present], fontsize=8)
    axes.set_xlabel("straight-line plug-boot to strain-relief distance\nat the commanded endpoint (mm)",
                    fontsize=8, color=INK_2)
    axes.set_title("A  Clip loss against the one-number budget", fontsize=9.5,
                   color=INK, loc="left", pad=8)
    axes.grid(axis="x", color=GRID, linewidth=0.7)
    axes.set_axisbelow(True)


def panel_actions(axes, rows):
    """The commanded detour, in the plane that decides whether the clip survives."""
    for label, colour, marker, wanted in (("clip kept", RETAINED, "o", 0), ("clip released", LOST, "^", 1)):
        subset = [r for r in rows if r["clip_lost"] == wanted]
        axes.scatter([1000*r["action"]["retreat_m"] for r in subset],
                     [1000*r["action"]["excursion_m"]*math.cos(r["action"]["bearing_rad"]) for r in subset],
                     s=18, c=colour, marker=marker, alpha=0.75, linewidths=0, label=label)
    axes.axhline(0, color=GRID, linewidth=0.8, zorder=0)
    low, high = axes.get_ylim()
    axes.set_ylim(low-0.22*(high-low), high)   # room for the legend under the marks
    axes.set_xlabel("commanded axial retreat (mm)", fontsize=8, color=INK_2)
    axes.set_ylabel("excursion toward the strain relief (mm)", fontsize=8, color=INK_2)
    axes.set_title("B  Moving toward the anchor buys retreat back", fontsize=9.5,
                   color=INK, loc="left", pad=10)
    legend = axes.legend(frameon=False, fontsize=8, loc="lower left", handletextpad=0.4)
    for text in legend.get_texts():
        text.set_color(INK_2)
    axes.grid(color=GRID, linewidth=0.7)
    axes.set_axisbelow(True)


def panel_predictors(axes, results, margin):
    """Held-out comparison on the two pre-registered metrics."""
    metrics = [("false-safe rate\n(matched coverage)", "false_safe_rate_matched_coverage"),
               ("ranking regret\n(largest safe repair)", None)]
    names = ["B0", "B1", "M", "none"]
    width, ceiling = 0.21, 0.0
    # Each bar is labelled with its predictor and its value, so identity never
    # rests on colour and the sub-3:1 aqua slot carries the required relief.
    reference = results["no_filter_reference"]
    for slot, name in enumerate(names):
        entry = reference if name == "none" else results[name]
        values = []
        for _, key in metrics:
            if key is None:
                value = entry["ranking_regret_clip"]["regret"]
            elif name == "none":
                value = entry["clip_loss_base_rate"]   # full coverage by construction
            else:
                value = entry[key]
            values.append(float("nan") if value is None else float(value))
        positions = np.arange(len(metrics))+(slot-1.5)*width
        bars = axes.bar(positions, [0.0 if math.isnan(v) else v for v in values],
                        width=width*0.86, color=PREDICTOR[name], linewidth=0)
        for bar, value in zip(bars, values, strict=True):
            height = 0.0 if math.isnan(value) else value
            ceiling = max(ceiling, height)
            axes.text(bar.get_x()+bar.get_width()/2, height+0.008,
                      "n/a" if math.isnan(value) else f"{value:.2f}",
                      ha="center", va="bottom", fontsize=7.5, color=INK_2)
            axes.text(bar.get_x()+bar.get_width()/2, -0.02, BAR_LABEL[name], ha="center", va="top",
                      fontsize=7.5, color=PREDICTOR[name], linespacing=0.95)
    axes.set_xticks(np.arange(len(metrics)))
    axes.set_xticklabels([label for label, _ in metrics], fontsize=8)
    axes.tick_params(axis="x", pad=26)
    axes.set_ylabel("held-out rate (lower is better)", fontsize=8, color=INK_2)
    axes.set_title(f"C  Held-out groups, decision margin {margin:g}", fontsize=9.5,
                   color=INK, loc="left", pad=8)
    axes.grid(axis="y", color=GRID, linewidth=0.7)
    axes.set_axisbelow(True)
    axes.set_ylim(0, max(0.25, ceiling*1.18))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    rows = dataset["rows"]
    test_rows = [r for r in rows if r["split"] == "test"]
    threshold_mm = 1000*dataset["b0_threshold_m"]

    figure, axes = plt.subplots(1, 3, figsize=(13.2, 4.3), facecolor=SURFACE,
                                gridspec_kw={"width_ratios": [1.12, 0.95, 1.05], "wspace": 0.3})
    for pane in axes:
        style(pane)
    panel_boundary(axes[0], rows, threshold_mm)
    panel_actions(axes[1], rows)
    panel_predictors(axes[2], report["held_out_results"], report["decision"]["margin"])

    counts = report["denominator"]["outcome_counts"]
    splits = report["splits"]
    caption = (
        f"Constrained-cable connector recovery, block {report['id']}. "
        f"{report['denominator']['requests']} executed requests over "
        f"{len({r['context'] for r in rows})} registered contexts, of which "
        f"{report['denominator']['usable_for_fitting']} carried an issued repair. "
        "Outcomes: " + ", ".join(f"{OUTCOME_LABEL.get(k, k)} {v}" for k, v in sorted(counts.items())) + ". "
        f"Held-out test groups {', '.join(splits['test']['groups'])}: "
        f"{splits['test']['requests']} requests, {splits['test']['clip_lost']} clip losses. "
        "The no-filter bar allows every action, so it sits at full coverage by construction. "
        f"Pre-registered verdict: {report['decision']['verdict']}. "
        "Simulation only; no hardware, released retention or latching claim."
    )
    lines = textwrap.wrap(caption, width=190)
    for line, text in enumerate(lines):
        figure.text(0.008, 0.013+0.023*(len(lines)-1-line), text, fontsize=6.4, color=MUTED, va="bottom")
    figure.subplots_adjust(left=0.095, right=0.99, top=0.9, bottom=0.30)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf"):
        figure.savefig(args.out.with_suffix(suffix), dpi=200, facecolor=SURFACE)
    print(json.dumps({"figure": str(args.out.with_suffix(".png")),
                      "rows": len(rows), "test_rows": len(test_rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
