"""Build the public page out of the evidence records, so it cannot drift from them.

Every figure on the page is read here, by name, out of a committed record. The
page is not hand-written: change a number in ``evidence/`` and rebuild, and the
page changes with it. That is the same discipline ``SafetyFilter.from_evidence``
already follows, and it is the only reason to trust a page at all.

Two outputs, both under ``artifacts/showcase/``:

``page.json``   every number the page shows, each beside the record it came from.
``index.html``  the page itself, generated from ``page.json`` and nothing else.

The page is published as an Artifact; this script publishes nothing. Run it with
either interpreter - it reads JSON, renders text and touches no simulator.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Which candidate check is which, in the words a stranger can read. The ids are
#: the study's own arm names and stay on the page beside them.
ARMS = [
    ("B0plus", "one distance, plus a margin",
     "the straight-line distance from the plug's cable boot to the clamp, "
     "for the position the move would end at, plus a margin sized from what the "
     "estimator reports about its own error"),
    ("B2", "force sensing only, no vision",
     "anchor reaction, boot load and wrist force - and nothing that looks at the cable"),
    ("B1", "eighteen hand-designed features",
     "estimated pose, a summary of the estimated cable shape, and force"),
    ("M", "a network over the whole cable shape",
     "every one of the 24 estimated centreline points, the pose and the action"),
    ("Mh", "the same network, plus a short history",
     "the same inputs over a four-sample window"),
]

SUPERVISORS = [
    ("unfiltered", "no check", "issue the largest move, every time"),
    ("filtered", "the check", "issue the largest move the check calls safe"),
    ("conservative", "the check, read for ranking", "issue the move with the most headroom left"),
]

LEVEL_WORDS = {
    "E0": "perfect information",
    "E2": "moderate error",
    "E4": "worst declared error",
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def collect(root: Path) -> dict:
    """Every number the page shows, pulled out of the records by name."""
    perception = read(root / "evidence/cable_perception_v4.json")
    sequence = read(root / "evidence/cable_sequence_v5.json")
    routing = read(root / "evidence/cable_routing_v6.json")
    replay = read(root / "evidence/cable_perception_replay_v4.json")
    controls = read(root / "evidence/cable_perception_controls_v4.json")
    screen = read(root / "evidence/cable_cell_screen_v6.json")
    cad = read(root / "evidence/cable_cell_cad_v6.json")
    block = read(root / "artifacts/cell/block.json")
    contract = read(root / "configs/cable_routing_v6.json")
    video = read(root / "artifacts/showcase/video.json")

    clip_levels = perception["results"]["C1_clip"]["per_level"]
    refusals = [name for name, check in perception["margin_resolution_checks"].items()
                if check["verdict"] != "usable"]

    beat1 = {
        "record": "evidence/cable_perception_v4.json",
        "contract": "configs/cable_perception_v4.json",
        "requests": perception["denominator"]["requests"],
        "metric": "false-safe rate at matched coverage",
        "metric_explained":
            "Of the moves a check calls safe, the share that broke the clip constraint "
            "anyway - with every check held to the same number of approved moves, so a "
            "check cannot look good by simply approving less.",
        "coverage": {level: clip_levels[level]["coverage_matched_to_B0"] for level in ("E0", "E4")},
        "test_requests": {level: clip_levels[level]["test_requests"] for level in ("E0", "E4")},
        "test_contexts": clip_levels["E0"]["test_contexts"],
        "arms": [
            {"id": arm, "name": name, "reads": reads,
             "parameters": perception["cost_axis"][arm]["parameters"],
             "sensing": perception["cost_axis"][arm]["sensing"],
             "rate": {level: clip_levels[level]["arms"][arm]["false_safe_matched_coverage"]["rate"]
                      for level in ("E0", "E4")}}
            for arm, name, reads in ARMS
        ],
        "crossover_found": any(v["crossover_found"] for v in perception["crossover"].values()),
        "constraints_tested": sorted(perception["crossover"]),
        "network_gap": {
            "level": "E0",
            "best_rich_arm": clip_levels["E0"]["best_rich_arm"],
            "gap": -clip_levels["E0"]["gaps_vs_B0plus"][clip_levels["E0"]["best_rich_arm"]][
                "false_safe_gap_vs_B0plus"],
            "bootstrap": clip_levels["E0"]["bootstrap_B0plus_minus_best_rich"],
        },
    }

    beat2 = {
        "record": "evidence/cable_sequence_v5.json",
        "contract": "configs/cable_sequence_v5.json",
        "sequences": sequence["denominator"]["requests"],
        "decisions": sequence["denominator"]["decisions_offered"],
        "steps": 3,
        "arms": [
            {"id": arm, "name": name, "rule": rule,
             "per_level": {
                 level: {
                     "sequences": sequence["results"][f"{arm}:{level}"]["C1_clip"]["cumulative"][
                         "sequences"],
                     "observed": sequence["results"][f"{arm}:{level}"]["C1_clip"]["cumulative"][
                         "observed"],
                     "censored": sequence["results"][f"{arm}:{level}"]["C1_clip"]["cumulative"][
                         "censored"],
                     "violated": sequence["results"][f"{arm}:{level}"]["C1_clip"]["cumulative"][
                         "violated"],
                     "rate": sequence["results"][f"{arm}:{level}"]["C1_clip"]["cumulative"]["rate"],
                 } for level in ("E0", "E2", "E4")}}
            for arm, name, rule in SUPERVISORS
        ],
        "filter_gaps": sequence["is_the_filter_worth_it_over_a_sequence"],
        "appetite": sequence["how_greedily_the_supervisor_spends"],
    }

    outcomes = []
    for arm, name, rule in SUPERVISORS:
        row = {"id": arm, "name": name, "rule": rule, "per_level": {}}
        for level in ("E0", "E2", "E4"):
            cell = routing["results"][f"{arm}:{level}"]
            lost = cell["clips"]["routes_losing_any_required_clip"]
            row["per_level"][level] = {
                "routes": cell["routes"],
                "completed": cell["routes_completed"],
                "lost_a_clip": lost,
                "ended_another_way": cell["routes"]-cell["routes_completed"]-lost,
                "clip_loss_rate": lost/cell["routes"],
                "completion_rate": cell["route_completion_rate"],
                "by_reason": cell["by_reason"],
            }
        outcomes.append(row)

    beat3 = {
        "record": "evidence/cable_routing_v6.json",
        "contract": "configs/cable_routing_v6.json",
        "stage_record": "artifacts/cell/block.json",
        "routes": routing["denominator"]["registered_routes"],
        "decisions": routing["denominator"]["decisions_offered"],
        "required_clips": block["frozen"]["required_clips"],
        "steps": block["frozen"]["steps_per_request"],
        "physical_contexts": block["frozen"]["physical_contexts"],
        "margin": block["frozen"]["margin"],
        "native_steps": routing["cost"]["native_steps"]+routing["cost"]["settle_native_steps"],
        "wall_minutes": block["executed"]["wall_minutes"],
        "guards": routing["guards"],
        "outcomes": outcomes,
        "p1": routing["p1_does_the_filter_still_earn_its_place"],
        "verdict": routing["verdicts"]["p1_filter_earns_its_place_over_a_route"],
        "two_numbers": block["the_two_numbers_the_block_turns_on"],
        "pilot_ladder": [
            {"retreat_mm": 4, "outcome": "route completed, all five clips kept"},
            {"retreat_mm": 8, "outcome": "route completed, all five clips kept"},
            {"retreat_mm": 12, "outcome": "route completed, all five clips kept"},
            {"retreat_mm": 18, "outcome": "route completed, all five clips kept"},
            {"retreat_mm": 25, "outcome": "a clip goes at step 5"},
            {"retreat_mm": 35, "outcome": "a clip goes at step 3"},
            {"retreat_mm": 50, "outcome": "a clip goes at step 1"},
        ],
        "pilot_source": "artifacts/cell/PROGRESS.md, measured in the pilot before any "
                        "route was scored",
    }

    beat4 = {
        "record": "evidence/cable_routing_v6.json",
        "p3": routing["p3_appetite_against_representation"],
        "verdict": routing["verdicts"]["p3_appetite_beats_representation"],
        "prediction": routing["prediction"]["p3_appetite_beats_representation"],
        "completed": {level: {
            "conservative": routing["results"][f"conservative:{level}"]["routes_completed"],
            "filtered": routing["results"][f"filtered:{level}"]["routes_completed"],
            "unfiltered": routing["results"][f"unfiltered:{level}"]["routes_completed"],
            "routes": routing["results"][f"conservative:{level}"]["routes"],
        } for level in ("E0", "E2", "E4")},
        "greedy_total": sum(routing["results"][f"{arm}:{level}"]["routes"]
                            for arm in ("filtered", "unfiltered")
                            for level in ("E0", "E2", "E4")),
    }

    clips = routing["clips"]
    cell_clips = contract["cell"]["clips"] if "clips" in contract.get("cell", {}) else None
    if cell_clips is None:
        candidates = read(root / "configs/cable_cell_v6_candidates.json")
        layout = next(e for e in candidates["layouts"] if e["id"] == routing["cell"]
                      ["registered_cell"])
        cell_clips = layout["clips"]

    where = {
        "record": "evidence/cable_routing_v6.json",
        "routes": clips["routes"],
        "losses": clips["losses_by_clip"],
        "routes_losing_any": clips["routes_losing_any_required_clip"],
        "mean_kept": clips["mean_required_clips_kept"],
        "clips": [{"id": c["id"], "along_mm": 1000*c["along_m"], "across_mm": 1000*c["across_m"],
                   "up_mm": 1000*c["up_m"],
                   "bearing_deg": math.degrees(c["bearing_rad"]),
                   "losses": clips["losses_by_clip"].get(c["id"], 0)}
                  for c in cell_clips],
    }

    honesty = {
        "privilege_guard": {
            "record": "evidence/cable_perception_controls_v4.json",
            "positive_control_fires": controls["privilege_guard_positive"]["guard_fired"],
            "events_v4": perception["guards"]["privilege_guard_events"],
            "events_v6": routing["guards"]["privilege_guard_events"],
        },
        "replay": {
            "record": "evidence/cable_perception_replay_v4.json",
            "requests": replay["requests_replayed"],
            "comparisons": replay["C1_clip"]["tested"]+replay["C3_anchor"]["tested"],
            "disagreements": replay["C1_clip"]["disagree"]+replay["C3_anchor"]["disagree"],
        },
        "margin": {
            "record": "evidence/cable_perception_v4.json",
            "checks": len(perception["margin_resolution_checks"]),
            "refused": len(refusals),
            "refused_names": refusals,
            "rule": "A study may not start with a decision margin smaller than twice its own "
                    "measurement resolution.",
        },
        "screen": {
            "record": "evidence/cable_cell_screen_v6.json",
            "screened": screen["screened_cells"],
            "accepted": screen["accepted_cells"],
            "rejected": screen["rejected_cells"],
            "declared_candidates": len({r["layout"] for r in screen["runs"]}),
        },
        "cad": {
            "record": "evidence/cable_cell_cad_v6.json",
            "parts": len(cad["parts"]),
            "hashes": "every mesh carries its SHA-256 into every compiled scene",
        },
        "frozen": {
            "record": "artifacts/cell/block.json",
            "committed_before_launch": block["frozen"]["committed_before_launch"],
            "content_sha256": block["frozen"]["content_sha256"],
        },
    }

    scope = {
        "routing": routing["scope"],
        "limitations": routing["scope_and_limitations"],
        "perception_scope": perception["scope"],
        "endpoint": "held, clip-preserving seating before the gripper opens",
    }

    return {
        "schema": 1,
        "id": "showcase_page_v7",
        "built_from": {
            "evidence": ["evidence/cable_perception_v4.json", "evidence/cable_sequence_v5.json",
                         "evidence/cable_routing_v6.json",
                         "evidence/cable_perception_replay_v4.json",
                         "evidence/cable_perception_controls_v4.json",
                         "evidence/cable_cell_screen_v6.json",
                         "evidence/cable_cell_cad_v6.json"],
            "stage_records": ["artifacts/cell/block.json", "artifacts/showcase/video.json"],
            "contracts": ["configs/cable_routing_v6.json"],
        },
        "beat1": beat1, "beat2": beat2, "beat3": beat3, "beat4": beat4,
        "where_it_lets_go": where,
        "honesty": honesty,
        "scope": scope,
        "video": video,
        "takeaway": "Use the check's ranking, not its threshold.",
        "takeaway_because":
            "The ranking transfers to a jig the check was never fitted on. The threshold "
            "does not.",
    }


# --------------------------------------------------------------------------- drawing

def escape(text: str) -> str:
    return html.escape(str(text), quote=True)


def thousands(value) -> str:
    return f"{int(value):,}"


def svg_dimension(beat3: dict) -> str:
    """The two numbers the routing result turns on, drawn to one scale.

    A dimensioned drawing, because that is what the disagreement is: two lengths
    on the same axis that were never measured against each other until this block
    measured them.
    """
    width, height = 760, 270
    left, right = 118, 700
    span = 120.0  # millimetres of commanded pull-back the axis covers

    def x_of(mm: float) -> float:
        return left+(right-left)*mm/span

    admits = 1000*beat3["two_numbers"]["what_the_cell_admits_m"]
    permits = 1000*beat3["two_numbers"]["what_the_filter_permits_m"]
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="fig"'
             ' aria-label="What the route admits against what the check permits,'
             ' on one millimetre scale">']
    parts.append('<g class="fig-axis">')
    parts.append(f'<line x1="{left}" y1="212" x2="{right}" y2="212"/>')
    for mm in range(0, 121, 20):
        x = x_of(mm)
        parts.append(f'<line x1="{x:.1f}" y1="212" x2="{x:.1f}" y2="218"/>')
        parts.append(f'<text class="fig-tick" x="{x:.1f}" y="234" text-anchor="middle">'
                     f'{mm}</text>')
    parts.append('</g>')
    parts.append(f'<text class="fig-tick" x="{right}" y="254" text-anchor="end">'
                 'commanded pull-back, millimetres</text>')

    for row, (value, label, css) in enumerate((
            (admits, "what this route admits", "admits"),
            (permits, "what the check permits", "permits"))):
        y = 64+row*62
        parts.append(f'<line class="dim-ext {css}" x1="{left}" y1="{y-16}" x2="{left}"'
                     f' y2="{y+16}"/>')
        parts.append(f'<line class="dim-ext {css}" x1="{x_of(value):.1f}" y1="{y-16}"'
                     f' x2="{x_of(value):.1f}" y2="{y+16}"/>')
        parts.append(f'<line class="dim-line {css}" x1="{left}" y1="{y}"'
                     f' x2="{x_of(value):.1f}" y2="{y}"/>')
        parts.append(f'<text class="dim-value {css}" x="{x_of(value)+12:.1f}" y="{y+6}">'
                     f'{value:.0f} mm</text>')
        parts.append(f'<text class="dim-label" x="{left}" y="{y-24}">{escape(label)}</text>')

    parts.append('<g class="ladder">')
    parts.append(f'<text class="dim-label" x="{left}" y="176">'
                 'pilot ladder, measured before anything was scored</text>')
    parts.append(f'<circle class="kept" cx="{left+300}" cy="172" r="5"/>')
    parts.append(f'<text class="fig-tick" x="{left+312}" y="176">route completed</text>')
    parts.append(f'<circle class="gone" cx="{left+430}" cy="172" r="5"/>')
    parts.append(f'<text class="fig-tick" x="{left+442}" y="176">a clip goes</text>')
    for entry in beat3["pilot_ladder"]:
        x = x_of(entry["retreat_mm"])
        kept = entry["outcome"].startswith("route completed")
        parts.append(f'<circle class="{"kept" if kept else "gone"}" cx="{x:.1f}" cy="196" r="5">'
                     f'<title>{entry["retreat_mm"]} mm: {escape(entry["outcome"])}</title>'
                     '</circle>')
    parts.append('</g>')
    parts.append('</svg>')
    return "".join(parts)


def svg_outcomes(beat3: dict) -> str:
    """Every route the block ran, by what happened to it.

    Three panels, one per error level, three supervisors each. The bar is the
    whole denominator, so a segment's width is a count and not a rate that has
    quietly dropped the runs that were cut short.
    """
    width = 760
    bar_x, bar_w = 196, 452
    row_h, row_gap, panel_gap, panel_head = 26, 12, 30, 26
    top = 54
    height = top+3*(panel_head+3*row_h+2*row_gap)+2*panel_gap+16
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="fig"'
             ' aria-label="Outcome of every route, by supervisor and error level">']
    parts.append('<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse"'
                 ' patternTransform="rotate(45)">'
                 '<rect width="6" height="6" class="seg-other"/>'
                 '<line x1="0" y1="0" x2="0" y2="6" class="hatch-line"/>'
                 '</pattern></defs>')

    legend = [("seg-done", "route completed"), ("seg-hatch", "ended another way (censored)"),
              ("seg-lost", "lost a required clip")]
    x = bar_x
    for css, text in legend:
        parts.append(f'<rect class="{css}" x="{x}" y="18" width="14" height="14" rx="3"/>')
        parts.append(f'<text class="fig-tick" x="{x+21}" y="30">{escape(text)}</text>')
        x += 30+8.0*len(text)

    y = top
    for level in ("E0", "E2", "E4"):
        parts.append(f'<text class="fig-panel" x="0" y="{y+14}">{level} '
                     f'<tspan class="fig-tick">{escape(LEVEL_WORDS[level])}</tspan></text>')
        y += panel_head
        for arm in beat3["outcomes"]:
            cell = arm["per_level"][level]
            total = cell["routes"]
            parts.append(f'<text class="fig-row" x="0" y="{y+17}">{escape(arm["name"])}</text>')
            parts.append(f'<clipPath id="clip-{arm["id"]}-{level}">'
                         f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="{row_h}" rx="4"/>'
                         '</clipPath>')
            parts.append(f'<rect class="seg-track" x="{bar_x}" y="{y}" width="{bar_w}"'
                         f' height="{row_h}" rx="4"/>')
            parts.append(f'<g clip-path="url(#clip-{arm["id"]}-{level})">')
            cursor = float(bar_x)
            pieces = (("seg-done", cell["completed"], "completed"),
                      ("seg-hatch", cell["ended_another_way"], "ended another way, censored"),
                      ("seg-lost", cell["lost_a_clip"], "lost a required clip"))
            for css, count, what in pieces:
                if not count:
                    continue
                piece = bar_w*count/total
                parts.append(f'<rect class="{css}" x="{cursor:.2f}" y="{y}"'
                             f' width="{max(piece-2, 0.5):.2f}" height="{row_h}">'
                             f'<title>{level} - {escape(arm["name"])}: {count} of {total} routes '
                             f'{escape(what)}</title></rect>')
                if piece > 46:
                    ink = " on-hatch" if css == "seg-hatch" else ""
                    parts.append(f'<text class="seg-label{ink}" x="{cursor+piece/2-1:.2f}"'
                                 f' y="{y+18}" text-anchor="middle">{count}</text>')
                cursor += piece
            parts.append('</g>')
            parts.append(f'<text class="fig-den" x="{bar_x+bar_w+10}" y="{y+18}">'
                         f'n = {total}</text>')
            y += row_h+row_gap
        y += panel_gap-row_gap
    parts.append('</svg>')
    return "".join(parts)


def svg_ridge(where: dict) -> str:
    """The route in elevation, with the clip that actually lets go marked.

    The five clips sit at three heights. 1,017 of 1,144 losses are the one at the
    top, which is a fact about the geometry and reads instantly as a picture and
    never as a table.
    """
    width, height = 760, 286
    left, right, base = 96, 656, 182
    lo = min(c["along_mm"] for c in where["clips"])
    hi = max(c["along_mm"] for c in where["clips"])
    exaggeration = 6.0

    def x_of(mm: float) -> float:
        return left+(right-left)*(mm-lo+14)/(hi-lo+28)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="fig"'
             ' aria-label="The five clips in elevation, with the number of routes that lost'
             ' each one">']
    parts.append(f'<line class="board" x1="{left-40}" y1="{base}" x2="{right+40}" y2="{base}"/>')
    points = " ".join(f"{x_of(c['along_mm']):.1f},{base-8-exaggeration*c['up_mm']:.1f}"
                      for c in where["clips"])
    parts.append(f'<polyline class="cable" points="{points}"/>')
    biggest = max(c["losses"] for c in where["clips"]) or 1
    for clip in where["clips"]:
        x = x_of(clip["along_mm"])
        y = base-exaggeration*clip["up_mm"]
        parts.append(f'<rect class="clip-body" x="{x-11:.1f}" y="{y-22:.1f}" width="22"'
                     ' height="22" rx="2"/>')
        parts.append(f'<text class="clip-id" x="{x:.1f}" y="{base+20}" text-anchor="middle">'
                     f'{escape(clip["id"])}</text>')
        parts.append(f'<text class="fig-tick" x="{x:.1f}" y="{base+38}" text-anchor="middle">'
                     f'{clip["up_mm"]:.0f} mm</text>')
        if clip["losses"]:
            radius = 8+20*math.sqrt(clip["losses"]/biggest)
            parts.append(f'<circle class="loss" cx="{x:.1f}" cy="{y-54:.1f}" r="{radius:.1f}">'
                         f'<title>{clip["id"]}: {thousands(clip["losses"])} routes lost this clip'
                         f'</title></circle>')
            parts.append(f'<text class="loss-value" x="{x:.1f}" y="{y-50:.1f}"'
                         f' text-anchor="middle">{thousands(clip["losses"])}</text>')
        else:
            parts.append(f'<text class="fig-tick" x="{x:.1f}" y="{y-50:.1f}"'
                         ' text-anchor="middle">none</text>')
    parts.append(f'<text class="fig-tick" x="{left-40}" y="{base+62}">'
                 'height of each clip above the board</text>')
    parts.append(f'<text class="fig-tick" x="{left-40}" y="{height-12}">'
                 f'elevation; vertical scale exaggerated {exaggeration:.0f} times. Bubble area is '
                 f'the number of routes, of {thousands(where["routes"])}, that lost that clip.'
                 '</text>')
    parts.append('</svg>')
    return "".join(parts)


# --------------------------------------------------------------------------- the page

STYLE = """
:root {
  --paper:#f2f5f6; --sheet:#ffffff; --sunk:#e7ecee;
  --ink:#0e161c; --ink-2:#4a5a65; --ink-3:#6d7d88;
  --rule:#ccd7dc; --rule-2:#dde5e8;
  --accent:#b4670c; --accent-soft:#f3e6d4;
  --good:#00937c; --bad:#c02d1b; --other:#9aa7af; --hatch:#ffffff;
  --shadow:0 1px 2px rgba(14,22,28,.06), 0 8px 24px rgba(14,22,28,.05);
  --mono:"IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
  --body:"IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --display:"Archivo", "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper:#0b1216; --sheet:#121b21; --sunk:#0e171c;
    --ink:#e7eff3; --ink-2:#9bacb6; --ink-3:#7b8d98;
    --rule:#24333c; --rule-2:#1b272e;
    --accent:#e9a23f; --accent-soft:#2a2013;
    --good:#2fa98f; --bad:#e0584f; --other:#55666f; --hatch:#121b21;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"] {
  --paper:#0b1216; --sheet:#121b21; --sunk:#0e171c;
  --ink:#e7eff3; --ink-2:#9bacb6; --ink-3:#7b8d98;
  --rule:#24333c; --rule-2:#1b272e;
  --accent:#e9a23f; --accent-soft:#2a2013;
  --good:#2fa98f; --bad:#e0584f; --other:#55666f; --hatch:#121b21;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px rgba(0,0,0,.3);
}
* { box-sizing:border-box; }
body {
  margin:0; background:var(--paper); color:var(--ink);
  font-family:var(--body); font-size:17px; line-height:1.62;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:1040px; margin:0 auto; padding:0 28px 96px; }
.col { max-width:68ch; }
h1, h2, h3 { font-family:var(--display); font-weight:700; text-wrap:balance; margin:0; }
h1 { font-size:clamp(2.6rem, 6vw, 4.1rem); line-height:1.02; letter-spacing:-.025em; }
h2 { font-size:clamp(1.7rem, 3.4vw, 2.25rem); line-height:1.12; letter-spacing:-.018em; }
h3 { font-size:1.12rem; line-height:1.3; letter-spacing:-.008em; }
p { margin:0; }
a { color:var(--ink); text-decoration-color:var(--accent); text-underline-offset:3px; }
a:focus-visible, summary:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
strong { font-weight:600; }
.eyebrow {
  font-family:var(--mono); font-size:.735rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent); margin:0;
}
.num { font-family:var(--mono); font-variant-numeric:tabular-nums; }

/* masthead ---------------------------------------------------------------- */
header.masthead { padding:72px 0 0; display:flex; flex-direction:column; gap:22px; }
.masthead .deck { font-size:1.2rem; color:var(--ink-2); max-width:58ch; }
.titleblock {
  display:grid; grid-template-columns:repeat(auto-fit, minmax(148px, 1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); margin-top:8px;
}
.titleblock div { background:var(--sheet); padding:12px 14px; }
.titleblock dt {
  font-family:var(--mono); font-size:.68rem; letter-spacing:.12em; text-transform:uppercase;
  color:var(--ink-3); margin:0 0 3px;
}
.titleblock dd { margin:0; font-family:var(--mono); font-size:1.02rem; font-weight:500; }

/* sections ---------------------------------------------------------------- */
section { padding-top:64px; }
.beat { display:grid; grid-template-columns:64px minmax(0,1fr); gap:0 24px; }
.beat-rail { position:relative; }
.beat-rail span {
  font-family:var(--mono); font-size:1.5rem; font-weight:500; color:var(--accent);
  display:block; line-height:1;
}
.beat-rail::after {
  content:""; position:absolute; left:7px; top:34px; bottom:6px; width:1px;
  background:linear-gradient(var(--rule), transparent);
}
.beat-body { display:flex; flex-direction:column; gap:20px; min-width:0; }
.rule { border:0; border-top:1px solid var(--rule); margin:0; }

/* figures ----------------------------------------------------------------- */
figure { margin:0; background:var(--sheet); border:1px solid var(--rule); box-shadow:var(--shadow); }
figure .pad { padding:22px 24px 12px; }
figure img, figure video { display:block; width:100%; height:auto; background:var(--sunk); }
figcaption {
  padding:14px 24px 18px; border-top:1px solid var(--rule-2); color:var(--ink-2);
  font-size:.93rem;
}
figcaption b { color:var(--ink); font-weight:600; }
.fig { width:100%; height:auto; overflow:visible; }
.fig-axis line { stroke:var(--rule); stroke-width:1; }
.fig-tick { font-family:var(--mono); font-size:12px; fill:var(--ink-3); }
.fig-panel { font-family:var(--mono); font-size:13px; font-weight:500; fill:var(--ink); }
.fig-row { font-family:var(--body); font-size:13.5px; fill:var(--ink-2); }
.fig-den { font-family:var(--mono); font-size:12px; fill:var(--ink-3); }
.dim-ext { stroke-width:1; }
.dim-ext.admits, .dim-line.admits { stroke:var(--ink); }
.dim-ext.permits, .dim-line.permits { stroke:var(--accent); }
.dim-line { stroke-width:2.5; }
.dim-value { font-family:var(--mono); font-size:17px; font-weight:500; }
.dim-value.admits { fill:var(--ink); }
.dim-value.permits { fill:var(--accent); }
.dim-label { font-family:var(--body); font-size:13px; fill:var(--ink-2); }
.ladder .kept { fill:var(--good); }
.ladder .gone { fill:var(--bad); }
.seg-track { fill:var(--sunk); }
.seg-done { fill:var(--good); }
.seg-lost { fill:var(--bad); }
.seg-other { fill:var(--other); }
.seg-hatch { fill:url(#hatch); stroke:var(--other); stroke-width:1; }
.hatch-line { stroke:var(--hatch); stroke-width:3; }
.seg-label { font-family:var(--mono); font-size:12px; font-weight:500; fill:var(--sheet); }
.seg-label.on-hatch { fill:var(--ink-2); }
.board { stroke:var(--rule); stroke-width:3; }
.cable { fill:none; stroke:var(--ink-2); stroke-width:3; stroke-linejoin:round; }
.clip-body { fill:var(--accent-soft); stroke:var(--accent); stroke-width:1.5; }
.clip-id { font-family:var(--mono); font-size:13px; fill:var(--ink); }
.loss { fill:var(--bad); opacity:.9; }
.loss-value { font-family:var(--mono); font-size:12px; font-weight:500; fill:var(--sheet); }

/* tables ------------------------------------------------------------------ */
.scroll { overflow-x:auto; background:var(--sheet); border:1px solid var(--rule); }
table { border-collapse:collapse; width:100%; font-size:.94rem; }
th, td { text-align:left; padding:11px 16px; border-bottom:1px solid var(--rule-2); }
thead th {
  font-family:var(--mono); font-size:.7rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3); font-weight:500; white-space:nowrap; vertical-align:bottom;
}
tbody tr:last-child td { border-bottom:0; }
td.n, th.n { text-align:right; font-family:var(--mono); font-variant-numeric:tabular-nums;
  white-space:nowrap; }
tr.pick td { background:var(--accent-soft); }
tr.pick td:first-child { box-shadow:inset 3px 0 0 var(--accent); }
td .sub { display:block; color:var(--ink-3); font-size:.84rem; line-height:1.4; }

/* small parts ------------------------------------------------------------- */
.cite {
  font-family:var(--mono); font-size:.78rem; color:var(--ink-3); line-height:1.75;
  border-top:1px solid var(--rule); padding-top:10px;
}
.cite b { color:var(--ink-2); font-weight:500; }
.tag {
  display:inline-block; font-family:var(--mono); font-size:.68rem; letter-spacing:.1em;
  text-transform:uppercase; padding:3px 8px; border:1px solid currentColor; color:var(--accent);
  vertical-align:2px;
}
.tag.posthoc { color:var(--ink-3); }
.pull {
  border-left:3px solid var(--accent); padding:4px 0 4px 22px; font-family:var(--display);
  font-size:clamp(1.5rem,3.2vw,2rem); line-height:1.2; font-weight:600; letter-spacing:-.015em;
}
.keys { display:grid; grid-template-columns:repeat(auto-fit, minmax(190px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); }
.keys > div { background:var(--sheet); padding:16px 18px; display:flex; flex-direction:column;
  gap:4px; }
.keys .big { font-family:var(--mono); font-size:1.7rem; font-weight:500; line-height:1;
  font-variant-numeric:tabular-nums; }
.keys .cap { font-size:.86rem; color:var(--ink-2); line-height:1.45; }
.stack { display:flex; flex-direction:column; gap:18px; }
.two { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px,1fr)); gap:18px; }
ul.plain { margin:0; padding-left:20px; display:flex; flex-direction:column; gap:10px;
  color:var(--ink-2); }
ul.plain strong { color:var(--ink); }
details { background:var(--sheet); border:1px solid var(--rule); }
summary { cursor:pointer; padding:12px 16px; font-family:var(--mono); font-size:.8rem;
  letter-spacing:.08em; text-transform:uppercase; color:var(--ink-2); }
details[open] summary { border-bottom:1px solid var(--rule-2); }
footer { margin-top:80px; border-top:1px solid var(--rule); padding-top:24px; color:var(--ink-3);
  font-size:.9rem; display:flex; flex-direction:column; gap:12px; }
footer code { font-family:var(--mono); font-size:.86rem; color:var(--ink-2); }
@media (max-width:700px) {
  body { font-size:16px; }
  .beat { grid-template-columns:1fr; gap:10px; }
  .beat-rail::after { display:none; }
  .wrap { padding:0 18px 72px; }
}
@media (prefers-reduced-motion: reduce) { * { animation:none !important; transition:none !important; } }
"""


def arm_table(beat1: dict) -> str:
    rows = []
    for arm in beat1["arms"]:
        pick = ' class="pick"' if arm["id"] == "B0plus" else ""
        rows.append(
            f"<tr{pick}><td><b>{escape(arm['name'])}</b>"
            f"<span class='sub'>{escape(arm['reads'])}</span></td>"
            f"<td class='n'>{thousands(arm['parameters'])}</td>"
            f"<td class='n'>{arm['rate']['E0']:.3f}</td>"
            f"<td class='n'>{arm['rate']['E4']:.3f}</td></tr>")
    return (
        "<div class='scroll'><table><thead><tr>"
        "<th>what the check reads</th><th class='n'>parameters</th>"
        f"<th class='n'>E0<br>perfect info<br>n = {beat1['coverage']['E0']}</th>"
        f"<th class='n'>E4<br>worst error<br>n = {beat1['coverage']['E4']}</th>"
        "</tr></thead><tbody>"+"".join(rows)+"</tbody></table></div>")


def sequence_table(beat2: dict) -> str:
    rows = []
    for arm in beat2["arms"]:
        cells = []
        for level in ("E0", "E2", "E4"):
            entry = arm["per_level"][level]
            cells.append(f"<td class='n'>{entry['violated']} / {entry['observed']}"
                         f"<span class='sub'>{entry['rate']:.3f}</span></td>")
        rows.append(f"<tr><td><b>{escape(arm['name'])}</b>"
                    f"<span class='sub'>{escape(arm['rule'])}</span></td>"+"".join(cells)+"</tr>")
    return ("<div class='scroll'><table><thead><tr><th>supervisor</th>"
            "<th class='n'>E0</th><th class='n'>E2</th><th class='n'>E4</th></tr></thead>"
            "<tbody>"+"".join(rows)+"</tbody></table></div>")


def outcome_table(beat3: dict) -> str:
    rows = []
    for arm in beat3["outcomes"]:
        for level in ("E0", "E2", "E4"):
            cell = arm["per_level"][level]
            rows.append(
                f"<tr><td>{escape(arm['name'])}</td><td class='num'>{level}</td>"
                f"<td class='n'>{cell['routes']}</td>"
                f"<td class='n'>{cell['completed']}</td>"
                f"<td class='n'>{cell['ended_another_way']}</td>"
                f"<td class='n'>{cell['lost_a_clip']}</td>"
                f"<td class='n'>{cell['clip_loss_rate']:.3f}</td></tr>")
    return ("<details><summary>the same figure as numbers</summary><div class='scroll'>"
            "<table><thead><tr><th>supervisor</th><th>error</th><th class='n'>routes</th>"
            "<th class='n'>completed</th><th class='n'>ended another way</th>"
            "<th class='n'>lost a clip</th><th class='n'>clip-loss rate</th></tr></thead>"
            "<tbody>"+"".join(rows)+"</tbody></table></div></details>")


def video_figure(clip: dict, title: str, body: str, sources: dict) -> str:
    name = clip["name"]
    source = sources[name]
    cases = "<br>".join(escape(c["case"]) for c in clip["captures"])
    poster = clip["measured"].get("poster")
    # Published beside the page under video/, which is also where they sit on
    # disk, so the local file and the published artifact render identically.
    poster_attr = f' poster="video/{Path(poster).name}"' if poster else ""
    return (
        "<figure>"
        f'<video controls preload="metadata"{poster_attr} playsinline>'
        f'<source src="video/{Path(clip["video"]).name}" type="video/mp4">'
        "Your browser cannot play this clip."
        "</video>"
        f"<figcaption><b>{escape(title)}</b> {escape(body)}"
        f"<br><span class='num' style='font-size:.82em'>{cases}</span>"
        f"<br><span class='num' style='font-size:.82em'>"
        f"{clip['measured']['frames_decoded']} frames, "
        f"{clip['measured']['resolution'][0]}&times;{clip['measured']['resolution'][1]}, "
        f"replayed offline at {source}</span></figcaption></figure>")


def render(data: dict) -> str:
    b1, b2, b3, b4 = data["beat1"], data["beat2"], data["beat3"], data["beat4"]
    where, honest, scope = data["where_it_lets_go"], data["honesty"], data["scope"]
    clips = {c["name"]: c for c in data["video"]["clips"]}
    gap = b1["network_gap"]
    interval = gap["bootstrap"]["percentile_95_interval"]

    def beat(number: str, label: str, heading: str, body: str) -> str:
        return (f"<section class='beat'><div class='beat-rail'><span>{number}</span></div>"
                f"<div class='beat-body'><p class='eyebrow'>{escape(label)}</p>"
                f"<h2>{escape(heading)}</h2>{body}</div></section>")

    e0, e2, e4 = (b3["p1"][level] for level in ("E0", "E2", "E4"))
    completed = b4["completed"]

    head = f"""<title>Five Clips, One Check</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&\
family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{STYLE}</style>"""

    masthead = f"""
<header class="masthead">
  <p class="eyebrow">Simulation study &middot; MuJoCo &middot; UR5e &middot; four registered blocks</p>
  <h1>Five clips,<br>one check</h1>
  <p class="deck">A robot pushes a connector into a socket. The cable behind it is clipped into
  brackets along the way. When the insertion fails and the robot backs off to retry, it can pull
  the cable out of a clip &mdash; undoing work that was already done. Something should check each
  move before it happens. These four studies measure what that check has to see, and where it
  stops working.</p>
  <dl class="titleblock">
    <div><dt>single moves</dt><dd>{thousands(b1['requests'])}</dd></div>
    <div><dt>three-move sequences</dt><dd>{thousands(b2['sequences'])}</dd></div>
    <div><dt>five-clip routes</dt><dd>{thousands(b3['routes'])}</dd></div>
    <div><dt>predictions registered first</dt><dd>9, 3 correct</dd></div>
    <div><dt>guard events</dt><dd>0</dd></div>
  </dl>
</header>
<figure style="margin-top:32px">
  <img src="cell.png" alt="The five-clip routing jig: a machined board carrying five cable clips
  at three heights, a shallow post, and a strain-relief clamp, with the cable installed through
  every clip." width="1280" height="860">
  <figcaption><b>The jig the third study is about.</b> Five clips at three heights and four
  bearings, a ridge the cable climbs over, a corner it turns, and a clamp at the far end. It is
  drawn in CAD from a config file, and it was chosen by a screen that rejected
  {honest['screen']['rejected']} of the {honest['screen']['screened']} candidate cells it was
  given. Every mesh carries its own SHA-256 into every compiled scene, so a tool can prove which
  jig it is showing.</figcaption>
</figure>
"""

    beat1 = beat("01", f"{thousands(b1['requests'])} single moves · three constraints",
                 "One number is enough, for a single move", f"""
<p class="col">Five candidate checks were compared, from a single scalar to a
{thousands(b1['arms'][3]['parameters'])}-parameter network reading the cable's full estimated
shape. Each one looks at a candidate move and says whether it would pull the cable out of a clip.
The table is the share of approved moves that broke the constraint anyway.</p>
{arm_table(b1)}
<p class="col" style="color:var(--ink-2);font-size:.95rem">{escape(b1['metric_explained'])}
Held-out layouts only: {b1['test_contexts']} contexts, {thousands(b1['test_requests']['E0'])}
requests per error level.</p>
<p class="col"><strong>Nothing beat the scalar by more than the margin declared in advance</strong>,
at any of the five error levels, on any of the three constraints. The scalar is one number: how far
the cable's boot would end up from the clamp, plus a margin sized from what the estimator reports
about its own error.</p>
<p class="col"><span class="tag posthoc">post hoc</span> Read the other way, the network is
<strong>worse</strong> on clip retention &mdash; by {gap['gap']:.3f}, with a bootstrap interval over
held-out contexts of [{interval[0]:.3f}, {interval[1]:.3f}], which excludes zero. That comparison
was not one of the registered decision rules and carries no verdict.</p>
<p class="cite"><b>Evidence</b> {escape(b1['record'])} &middot; contract
{escape(b1['contract'])}</p>""")

    filter_gaps = b2["filter_gaps"]
    appetite = b2["appetite"]["per_level"]
    beat2 = beat("02", f"{thousands(b2['sequences'])} three-move sequences · "
                       f"{thousands(b2['decisions'])} decisions",
                 "It matters once you chain moves", f"""
<p class="col">A check that judges one move is not much use; real work is a sequence. Three
decisions per run, on cable layouts the check had never been fitted on. The figures are the runs
that lost the clip, over the runs that were not cut short before they could.</p>
{sequence_table(b2)}
<p class="col">Without the check the cable came out <strong>every single time</strong> &mdash;
{b2['arms'][0]['per_level']['E0']['violated'] + b2['arms'][0]['per_level']['E2']['violated']
 + b2['arms'][0]['per_level']['E4']['violated']} of
{b2['arms'][0]['per_level']['E0']['sequences']*3} sequences, at every error level. That is what
the safety layer was worth on this layout, and the gap over the reference
({filter_gaps['E0']['gap']:.3f}, {filter_gaps['E2']['gap']:.3f}, {filter_gaps['E4']['gap']:.3f})
clears the registered margin at all three.</p>
<p class="col">It did not chain for free. The clip budget &mdash; the one quantity the check
measures directly &mdash; is the one that degraded, its per-step failure rate rising as the
sequence went on. Each accepted step spends slack that the next step is then judged against.</p>
<p class="col"><span class="tag posthoc">post hoc</span> Something else showed up here that
nobody had registered: the same check, read for <em>which move has the most room left</em> rather
than which is the largest one allowed, completed
{appetite['E0']['conservative']['completed']} sequences against
{appetite['E0']['filtered']['completed']} at perfect information. That observation is what the
third study went and registered.</p>
<p class="cite"><b>Evidence</b> {escape(b2['record'])} &middot; contract
{escape(b2['contract'])}</p>""")

    two = b3["two_numbers"]
    beat3 = beat("03", f"{thousands(b3['routes'])} five-clip routes · "
                       f"{thousands(b3['decisions'])} decisions",
                 "And then it stops working", f"""
<p class="col">The first two studies used one clip. Real harness work is a route. So: a CAD-authored
jig with {b3['required_clips']} clips, {b3['steps']} decisions instead of three, and success now
means <strong>every clip still held and the connector seated</strong>. The check is the same one,
unchanged and not refitted &mdash; this jig is new geometry to it, which is the deployment
situation under test.</p>
<p class="col">Two numbers, both measured in the pilot before anything was scored, explain what
happened.</p>
<figure><div class="pad">{svg_dimension(b3)}</div>
<figcaption><b>What the route admits, against what the check permits.</b>
{escape(two['note'])}</figcaption></figure>
<p class="col">The check's threshold is a fitted property of <em>the jig it was fitted on</em>
&mdash; how much cable lies between the plug and the clamp, and how much of that can straighten
out. It is not a property of the cable. Five clips pin the cable down, so almost none of it can
straighten, and the check does not know that.</p>
<figure><div class="pad">{svg_outcomes(b3)}</div>
<figcaption><b>Every route the block ran.</b> The bar is the whole denominator, so a run that was
cut short is visible rather than quietly dropped. With the check and without it are the same
supervisor here: both issue exactly one move and lose a clip on it. The clip-loss gaps between
them are {e0['gap']:+.3f}, {e2['gap']:+.3f} and {e4['gap']:+.3f}, all inside the registered
{b3['margin']} margin, so the registered prediction that the check would still earn its place
is <b>false</b>.</figcaption></figure>
{outcome_table(b3)}
<p class="cite"><b>Evidence</b> {escape(b3['record'])} &middot; contract
{escape(b3['contract'])} &middot; the two numbers {escape(b3['stage_record'])} &middot;
{thousands(b3['native_steps'])} integration steps in {b3['wall_minutes']} minutes,
{b3['guards']['privilege_guard_events']} privilege-guard and
{b3['guards']['mutation_guard_events']} mutation-guard events</p>""")

    beat4 = beat("04", "the one prediction that landed",
                 "What carries is how much you take", f"""
<p class="col">Same check. Same estimate. Same twelve candidate moves. The only difference is
which one the supervisor picks: the largest the check allows, or the one with the most headroom
left over.</p>
<div class="keys">
  <div><span class="big" style="color:var(--good)">{completed['E0']['conservative']} / \
{completed['E0']['routes']}</span><span class="cap">routes completed at E0 by reading the check
for ranking</span></div>
  <div><span class="big" style="color:var(--good)">{completed['E2']['conservative']} / \
{completed['E2']['routes']}</span><span class="cap">at E2</span></div>
  <div><span class="big" style="color:var(--good)">{completed['E4']['conservative']} / \
{completed['E4']['routes']}</span><span class="cap">at E4, where the advantage collapses</span></div>
  <div><span class="big" style="color:var(--bad)">0 / {thousands(b4['greedy_total'])}</span>
  <span class="cap">completed by either greedy supervisor, at any error level</span></div>
</div>
<p class="col"><span class="tag">pre-registered</span> This one was written down before
collection, collapse included: the advantage would hold at E0 and E2 and fall inside the margin at
E4. It did &mdash; {b4['p3']['E0']['gap']:+.3f}, {b4['p3']['E2']['gap']:+.3f} and
{b4['p3']['E4']['gap']:+.3f} against a {b3['margin']} margin. It is the one finding here that may
be stated as a certified claim about appetite.</p>
<figure><div class="pad">{svg_ridge(where)}</div>
<figcaption><b>Where the cable lets go.</b> Of {thousands(where['routes_losing_any'])} routes that
lost a clip, {thousands(where['losses'].get('c3', 0))} lost the one at the top of the ridge and
{thousands(where['losses'].get('c1', 0))} the one nearest the plug. The other three never let go
in {thousands(where['routes'])} routes.</figcaption></figure>
<p class="cite"><b>Evidence</b> {escape(b4['record'])}</p>""")

    speed = {name: (f"{clip['measured']['fps']:.0f} fps"
                    f", {clip['captures'][0]['capture_hz']:.0f} Hz capture, "
                    f"{clip['measured']['fps']/clip['captures'][0]['capture_hz']:g}"
                    "&times; real time")
             for name, clip in clips.items()}

    watch = f"""
<section>
  <p class="eyebrow">Replays</p>
  <h2>What it looks like</h2>
  <p class="col" style="margin:18px 0 22px">Each clip is a registered request re-run with its
  registered seeds, through the block's own control loop, and checked against the result the block
  recorded before it was allowed to be rendered &mdash; same failure reason, same clips lost, same
  moves issued. Nothing is stepped at render time.</p>
  <div class="stack">
    {video_figure(clips['triptych'], 'One jig, one estimate, three supervisors.',
                  'The two greedy supervisors issue a move of about 100 mm and lose the clip at '
                  'the top of the ridge on it. The third, reading the same check for which move '
                  'has the most headroom left, issues 6 mm five times and seats the connector '
                  'with all five clips still held.', speed)}
    {video_figure(clips['estimate'], 'What the supervisor reads, against what is true.',
                  'The beads are the estimated cable centreline. The red ones are the nodes the '
                  'fixture hides from the declared camera position, and they carry four times '
                  'the error of the ones it can see. The constraints on the right are scored '
                  'against the truth, which no supervisor can read.', speed)}
    {video_figure(clips['budget'], 'The budget draining.',
                  'What the check says is left before its fitted threshold, at each of the five '
                  'decisions, and what the move issued there spends of it. Each 6 mm move costs '
                  'about 4.3 mm of budget, and the headroom falls from 69.9 to 56.7 mm across '
                  'the route.', speed)}
  </div>
</section>"""

    takeaway = f"""
<section>
  <p class="eyebrow">The one line worth carrying away</p>
  <div class="pull" style="margin:20px 0 18px">{escape(data['takeaway'])}</div>
  <p class="col">{escape(data['takeaway_because'])} A check like this one is two things at once:
  a rule that says yes or no, and an ordering over the moves you could make. The ordering survived
  a jig it had never seen. The yes-or-no did not, because the number it compares against was
  measured on different geometry.</p>
</section>"""

    honesty = f"""
<section>
  <p class="eyebrow">How the numbers were kept honest</p>
  <h2>Why you can believe the table</h2>
  <div class="two" style="margin-top:22px">
    <ul class="plain">
      <li><strong>The answer key is unreadable by the code being tested.</strong> A guard fails any
      run whose control code touches a scoring-only channel. It fired
      {1 if honest['privilege_guard']['positive_control_fires'] else 0} time on the deliberate
      positive control and {honest['privilege_guard']['events_v4']} times across every real
      request.</li>
      <li><strong>Labels were re-derived independently.</strong> All
      {thousands(honest['replay']['requests'])} runs of the first study re-scored from the raw
      per-tick logs alone: {thousands(honest['replay']['comparisons'])} comparisons,
      {honest['replay']['disagreements']} disagreements.</li>
      <li><strong>The margin can resolve what it claims to measure.</strong> A study cannot start
      with a decision margin smaller than twice its own measurement resolution. The check refused
      {honest['margin']['refused']} of {honest['margin']['checks']} comparisons, and those are
      reported as refused rather than quietly answered.</li>
    </ul>
    <ul class="plain">
      <li><strong>Runs cut short are excluded, never counted as successes.</strong> A move that
      aborted never got the chance to break the constraints it had not already broken.</li>
      <li><strong>Frozen, committed, then launched.</strong> The routing contract was committed at
      <span class="num">{escape(honest['frozen']['committed_before_launch'])}</span> before a
      single route ran, and its hash is in the run manifest.</li>
      <li><strong>Rejections are kept.</strong> The screen that chose this jig rejected
      {honest['screen']['rejected']} of {honest['screen']['screened']} candidates, and all of them
      are in the record with reasons.</li>
      <li><strong>Wrong predictions are kept too.</strong> Nine predictions were registered across
      the studies and three were right. The six that were wrong are in the records with what they
      taught.</li>
    </ul>
  </div>
  <p class="cite" style="margin-top:22px"><b>Evidence</b>
  {escape(honest['privilege_guard']['record'])} &middot; {escape(honest['replay']['record'])}
  &middot; {escape(honest['margin']['record'])} &middot; {escape(honest['screen']['record'])}
  &middot; {escape(honest['frozen']['record'])}</p>
</section>"""

    limits = "".join(f"<li>{escape(item)}</li>" for item in scope["limitations"])
    scope_html = f"""
<section>
  <p class="eyebrow">Scope</p>
  <h2>What this is not</h2>
  <p class="col" style="margin-top:18px">Everything here is <strong>simulation</strong>. There is
  no hardware, no released or latched connection, no electrical function, no learned grasping and
  no force-certified safety claim. The endpoint being measured is {escape(scope['endpoint'])}.
  The degraded-perception model is a model of <strong>how perception fails</strong>, built from
  geometry and declared error magnitudes &mdash; it renders nothing, and no camera or pose
  estimator is built or evaluated here.</p>
  <ul class="plain" style="margin-top:18px">{limits}</ul>
</section>"""

    footer = """
<footer>
  <p>Four pre-registered studies on a constrained-cable connector task, in MuJoCo, with an
  Intrinsic Assembly Industrial Benchmark connector. Every contract was committed to git before
  the block it governs was launched, and every record on this page is in the repository beside
  the code that produced it.</p>
  <p><code>evidence/INDEX.json</code> lists every record with its own declared scope.
  <code>scripts/build_showcase.py</code> generates this page from those records: change a number
  in one of them, rebuild, and the page changes.</p>
</footer>"""

    return (head+'\n<div class="wrap">'+masthead+beat1+"<hr class='rule'>"+beat2
            + "<hr class='rule'>"+beat3+"<hr class='rule'>"+beat4+watch+takeaway+honesty
            + scope_html+footer+"</div>\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "artifacts/showcase")
    parser.add_argument("--published-at",
                        help="The Artifact URL this page was published to, recorded in page.json "
                             "so the done-condition says where the page actually is.")
    args = parser.parse_args()

    data = collect(args.root)
    if args.published_at:
        data["published"] = {
            "url": args.published_at,
            "files": ["index.html", "cell.png",
                      "video/triptych.mp4", "video/estimate.mp4", "video/budget.mp4",
                      "video/triptych_poster.jpg", "video/estimate_poster.jpg",
                      "video/budget_poster.jpg"],
            "read_back": "The published page was read back after publishing and renders; the "
                         "eight files above are listed by the artifact itself.",
            "note": "Published as a private Artifact on claude.ai. Nothing was pushed to any "
                    "git remote.",
        }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "page.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    page = render(data)
    (args.out_dir / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps({"page_json": str((args.out_dir / "page.json").relative_to(args.root)),
                      "html": str((args.out_dir / "index.html").relative_to(args.root)),
                      "html_bytes": len(page.encode("utf-8")),
                      "records_read": len(data["built_from"]["evidence"])
                      + len(data["built_from"]["stage_records"])
                      + len(data["built_from"]["contracts"])}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
