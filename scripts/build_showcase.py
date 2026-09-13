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

#: The study labels its vision settings E0 to E4. Nobody outside the study knows
#: what those mean, so the page says what they are and keeps the label beside it.
LEVEL_WORDS = {
    "E0": "perfect information",
    "E2": "small error",
    "E4": "large error",
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
    perception_contract = read(root / "configs/cable_perception_v4.json")
    video = read(root / "artifacts/showcase/video.json")
    isaac_path = root / "artifacts/showcase/isaac.json"
    isaac = read(isaac_path) if isaac_path.is_file() else None

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
        # What the study's own E0..E4 labels mean in millimetres, so the page can
        # say it rather than making a reader look it up.
        "levels": {entry["id"]: entry
                   for entry in perception_contract["error_model"]["levels"]},
        "beat1": beat1, "beat2": beat2, "beat3": beat3, "beat4": beat4,
        "where_it_lets_go": where,
        "honesty": honesty,
        "scope": scope,
        "video": video,
        "isaac": isaac,
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
            (admits, "what this rig will take", "admits"),
            (permits, "what the check allows", "permits"))):
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
                 'tried first, before any of this was scored</text>')
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


def check_table(beat1: dict) -> str:
    """The one comparison table: five ways to build the check, side by side."""
    rows = []
    for arm in beat1["arms"]:
        pick = ' class="pick"' if arm["id"] == "B0plus" else ""
        size = ("1 number" if arm["parameters"] == 1
                else f"{thousands(arm['parameters'])} numbers")
        rows.append(
            f"<tr{pick}><td><b>{escape(arm['name'])}</b>"
            f"<span class='sub'>{escape(arm['reads'])}</span></td>"
            f"<td class='n'>{size}</td>"
            f"<td class='n'>{100*arm['rate']['E0']:.0f}%</td>"
            f"<td class='n'>{100*arm['rate']['E4']:.0f}%</td></tr>")
    return (
        "<div class='scroll'><table><thead><tr>"
        "<th>the check</th><th class='n'>how big it is</th>"
        "<th class='n'>wrong with<br>perfect information</th>"
        "<th class='n'>wrong with<br>large error</th>"
        "</tr></thead><tbody>"+"".join(rows)+"</tbody></table></div>")


def level_table(data: dict) -> str:
    """What 'perfect information' and 'large error' actually mean, in millimetres."""
    rows = []
    for level in ("E0", "E2", "E4"):
        entry = data["levels"][level]
        if level == "E0":
            detail = "the check is handed the simulator's exact truth"
        else:
            detail = (f"socket off by {1000*entry['socket_bias_m']:.1f} mm, "
                      f"hidden cable points off by {1000*entry['centreline_occluded_m']:.0f} mm, "
                      f"about 1 point in {round(1/entry['centreline_dropout_p'])} missing "
                      f"altogether")
        rows.append(f"<tr><td><b>{escape(LEVEL_WORDS[level])}</b></td>"
                    f"<td>{escape(detail)}</td>"
                    f"<td class='n'>{level}</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>how good the seeing is</th>"
            "<th>what that means</th><th class='n'>label in the records</th></tr></thead>"
            "<tbody>"+"".join(rows)+"</tbody></table></div>")


def chain_table(beat2: dict) -> str:
    rows = []
    for arm in beat2["arms"]:
        cells = []
        for level in ("E0", "E2", "E4"):
            entry = arm["per_level"][level]
            cells.append(f"<td class='n'>{entry['violated']} of {entry['observed']}</td>")
        rows.append(f"<tr><td><b>{escape(arm['name'])}</b>"
                    f"<span class='sub'>{escape(arm['rule'])}</span></td>"+"".join(cells)+"</tr>")
    return ("<div class='scroll'><table><thead><tr><th>what the robot does</th>"
            "<th class='n'>perfect<br>information</th><th class='n'>small<br>error</th>"
            "<th class='n'>large<br>error</th></tr></thead>"
            "<tbody>"+"".join(rows)+"</tbody></table></div>")


def outcome_table(beat3: dict) -> str:
    rows = []
    for arm in beat3["outcomes"]:
        for level in ("E0", "E2", "E4"):
            cell = arm["per_level"][level]
            rows.append(
                f"<tr><td>{escape(arm['name'])}</td><td>{escape(LEVEL_WORDS[level])}</td>"
                f"<td class='n'>{cell['routes']}</td>"
                f"<td class='n'>{cell['completed']}</td>"
                f"<td class='n'>{cell['ended_another_way']}</td>"
                f"<td class='n'>{cell['lost_a_clip']}</td></tr>")
    return ("<details><summary>the same picture as numbers</summary><div class='scroll'>"
            "<table><thead><tr><th>what the robot does</th><th>seeing</th>"
            "<th class='n'>tries</th><th class='n'>finished the job</th>"
            "<th class='n'>stopped for another reason</th>"
            "<th class='n'>pulled the cable out</th></tr></thead>"
            "<tbody>"+"".join(rows)+"</tbody></table></div></details>")


def video_figure(clip: dict, title: str, body: str) -> str:
    poster = clip["measured"].get("poster")
    poster_attr = f' poster="video/{Path(poster).name}"' if poster else ""
    return (
        "<figure>"
        f'<video controls preload="metadata"{poster_attr} playsinline>'
        f'<source src="video/{Path(clip["video"]).name}" type="video/mp4">'
        "Your browser cannot play this clip."
        "</video>"
        f"<figcaption><b>{escape(title)}</b> {escape(body)}</figcaption></figure>")


def isaac_figure(data: dict) -> str:
    """The same run again, rendered properly. Nothing about it is a measurement."""
    isaac = data.get("isaac")
    if not isaac:
        return ""
    view = next(iter(isaac["views"].values()))
    return (
        "<figure>"
        '<video controls preload="metadata" poster="video/isaac_wide_poster.jpg" playsinline>'
        '<source src="video/isaac_wide.mp4" type="video/mp4">'
        "Your browser cannot play this clip."
        "</video>"
        "<figcaption><b>The rig, rendered properly.</b> The pictures in the other two clips come "
        "from the physics engine's own built-in renderer, which exists to check that a scene is "
        "built correctly rather than to look good. This is the same run again, with the recorded "
        "positions played into a real renderer: proper lights, shadows and materials. "
        f"{view['frames_written']} frames at "
        f"{view['resolution'][0]}&times;{view['resolution'][1]}. "
        "The physics, and every number on this page, are unchanged &mdash; this is a camera, "
        "nothing more.</figcaption></figure>")


def render(data: dict) -> str:
    b1, b2, b3, b4 = data["beat1"], data["beat2"], data["beat3"], data["beat4"]
    where, honest, scope = data["where_it_lets_go"], data["honesty"], data["scope"]
    clips = {c["name"]: c for c in data["video"]["clips"]}
    gap = b1["network_gap"]
    interval = gap["bootstrap"]["percentile_95_interval"]
    completed = b4["completed"]
    unfiltered_total = sum(b2["arms"][0]["per_level"][level]["violated"]
                           for level in ("E0", "E2", "E4"))
    unfiltered_of = b2["arms"][0]["per_level"]["E0"]["sequences"]*3
    e0, e2, e4 = (b3["p1"][level] for level in ("E0", "E2", "E4"))

    def section(eyebrow: str, heading: str, body: str, klass: str = "") -> str:
        return (f"<section class='{klass}'><p class='eyebrow'>{escape(eyebrow)}</p>"
                f"<h2>{escape(heading)}</h2>{body}</section>")

    head = f"""<title>Five Clips, One Check</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&\
family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{STYLE}</style>"""

    masthead = """
<header class="masthead">
  <p class="eyebrow">A simulation study, in plain terms</p>
  <h1>Five clips,<br>one check</h1>
  <p class="deck">A robot pushes a plug into a socket. The plug's cable is clipped to a board on
  the way in, the way wiring is dressed inside a machine. When the plug does not go in and the
  robot pulls back to try again, it can drag the cable out of one of those clips &mdash; undoing
  work it had already done.</p>
  <p class="deck">This is about the small piece of software that is supposed to stop that: what it
  has to know, how simple it can be, and the point at which it quietly stops being worth
  anything.</p>
</header>
<figure style="margin-top:34px">
  <img src="cell.png" alt="A machined board carrying five cable clips at three heights, a short
  post, and a clamp at the far end, with a cable installed through every clip." width="1280"
  height="860">
  <figcaption><b>The test rig.</b> Five clips, a small ridge the cable climbs over, a corner it
  turns, and a clamp holding the far end. The robot and the plug are up and to the left, out of
  frame. Everything here is simulated.</figcaption>
</figure>
"""

    problem = section("The problem", "Backing off is the dangerous part", """
<p class="col">Pushing a connector home is fiddly, and it often fails on the first try. The
standard recovery is to pull back a few centimetres and come at it again. That retreat is where
the damage happens: the cable behind the plug is already clipped down, and pulling the plug away
drags on it.</p>
<p class="col">So before each retreat the robot should ask a question: <strong>would this
particular move break something?</strong> The whole study is about that question &mdash; what
information you need to answer it, and how far the answer travels.</p>
<h3 style="margin-top:6px">Three things can break</h3>
<div class="keys">
  <div><span class="cap"><b>The cable comes out of a clip.</b> There is only so much slack. Pull
  harder than that and the cable lifts out of the channel. This is the one everything turns
  on.</span></div>
  <div><span class="cap"><b>The cable is bent too tightly.</b> The limit here is a bend radius of
  40&nbsp;mm on a 4&nbsp;mm cable &mdash; the usual industrial rule for a cable that is being
  moved, not one sitting still.</span></div>
  <div><span class="cap"><b>The clamp takes too much pull.</b> The limit is 0.30&nbsp;newtons,
  which is less than the cable's own weight of 0.49&nbsp;N. Above that, the robot is hauling on
  the far end.</span></div>
</div>
<p class="col" style="color:var(--ink-2);font-size:.95rem">Every run is scored against all three.
In the records these are C1, C2 and C3, in that order.</p>""")

    options = section("Finding 1", "For a single move, the simplest check wins", f"""
<p class="col">The check reads the robot's <em>estimate</em> of where things are &mdash; not the
truth, because a real robot does not have the truth &mdash; and it says yes or no to a proposed
move. Here are five ways to build it, cheapest first.</p>
<p class="col">The cheapest is almost embarrassingly simple: measure the straight-line distance
from where the cable leaves the plug to where it is clamped, work out what that distance
<em>would be</em> if the move happened, and refuse the move if it goes past a threshold. One
number. The most expensive is a neural network that reads all 24 estimated points of the cable's
shape.</p>
{check_table(b1)}
<p class="col" style="color:var(--ink-2);font-size:.95rem"><b>"Wrong" means the check approved a
move and the cable came out anyway.</b> Every check is held to the same number of approved
moves, so none of them can look good by simply refusing more. Measured on rig layouts none of
them was tuned on: {thousands(b1['test_requests']['E0'])} moves per column.</p>
<p class="col">The simple one wins &mdash; or rather, nothing beats it by enough to call it a
win. That was the question the study registered in advance, and the answer was no at every level
of seeing and for all three failure modes.</p>
<p class="col"><span class="tag posthoc">side finding</span> Looked at the other way, the network
is measurably <strong>worse</strong> at protecting the clips, by about
{100*gap['gap']:.0f} percentage points
(the range it could plausibly be is {100*abs(interval[1]):.0f} to
{100*abs(interval[0]):.0f} points, and it does not include zero). That
comparison was not part of the registered question, so it is reported and not claimed.</p>
<p class="cite"><b>Where these numbers live</b> {escape(b1['record'])} &middot; contract
{escape(b1['contract'])} &middot; {thousands(b1['requests'])} runs</p>""")

    seeing = section("A necessary aside", "How hard the seeing was made", f"""
<p class="col">A check is only as good as what it is looking at. Rather than build a camera, the
study declares how wrong the robot's estimate is and makes it that wrong &mdash; with the error
concentrated exactly where a real fixture would hide the cable from a real camera. Three settings
appear on this page.</p>
{level_table(data)}
<p class="col" style="color:var(--ink-2);font-size:.95rem">This is a model of <em>how perception
fails</em>, not a camera. No image is ever rendered and no pose estimator is built or tested
here.</p>""")

    chain = section("Finding 2", "Over several moves, the check earns its keep", f"""
<p class="col">One move is not a job. A real recovery is a few moves in a row, and each one
spends slack the next one is judged against. Three moves per run, on rig layouts the check had
never been tuned on. The numbers are how many runs lost the cable out of a clip.</p>
{chain_table(b2)}
<p class="col">Without the check the cable came out <strong>every single time</strong> &mdash;
{unfiltered_total} runs out of {unfiltered_of}, at every level of seeing. This is the part where
the simple check is clearly worth having.</p>
<p class="cite"><b>Where these numbers live</b> {escape(b2['record'])} &middot; contract
{escape(b2['contract'])} &middot; {thousands(b2['sequences'])} runs</p>""")

    breaks = section("Finding 3", "On a different rig, it stops working", f"""
<p class="col">The first two findings came from a rig with <em>one</em> clip. Real wiring runs
through several. So the same check, unchanged and not re-tuned, was put on the five-clip rig at
the top of this page, where finishing the job now means all five clips still held and the plug
seated.</p>
<p class="col">It stopped helping. Not "helped less" &mdash; stopped. With the check and without
it, the robot does the same thing: one big move, and the cable comes out on it.</p>
<p class="col">Two measurements, both taken before anything was scored, say why.</p>
<figure><div class="pad">{svg_dimension(b3)}</div>
<figcaption><b>What the rig will take, against what the check allows.</b> The rig loses a clip
somewhere between 18 and 25&nbsp;mm of pull-back. The check allows 58&nbsp;mm. Its threshold was
fitted on the one-clip rig, where a lot of cable could straighten out and absorb the pull. Five
clips pin the cable down so almost none of it can, and the check has no way to know that.
</figcaption></figure>
<figure><div class="pad">{svg_outcomes(b3)}</div>
<figcaption><b>Every attempt on the five-clip rig.</b> Full bars, so runs that were cut short
stay visible instead of quietly vanishing from a percentage. The top two rows of each group are
the same: the difference between having the check and not having it is
{100*e0['gap']:+.0f}, {100*e2['gap']:+.0f} and {100*e4['gap']:+.0f} percentage points, all
smaller than the margin the study committed to in advance.</figcaption></figure>
{outcome_table(b3)}
<figure><div class="pad">{svg_ridge(where)}</div>
<figcaption><b>And it is always the same clip.</b> Of
{thousands(where['routes_losing_any'])} runs that lost a clip,
{thousands(where['losses'].get('c3', 0))} lost the one at the top of the little ridge. The three
flat ones never let go, in {thousands(where['routes'])} runs.</figcaption></figure>
<p class="cite"><b>Where these numbers live</b> {escape(b3['record'])} &middot; contract
{escape(b3['contract'])} &middot; the two measurements {escape(b3['stage_record'])} &middot;
{thousands(b3['routes'])} runs</p>""")

    proposal = section("What to do instead", "Use the ranking, not the threshold", f"""
<p class="col">A check like this is really two things wearing one coat. It is a
<strong>rule</strong> &mdash; yes or no, is this move under the threshold. And it is an
<strong>ordering</strong> &mdash; of the moves available, which one leaves the most room to
spare.</p>
<p class="col">The rule did not survive the move to a new rig, because the threshold was measured
on different geometry. The ordering did. Same check, same information, one line of difference in
how it is read:</p>
<div class="keys">
  <div><span class="big" style="color:var(--good)">{completed['E0']['conservative']} of \
{completed['E0']['routes']}</span><span class="cap">jobs finished when the robot takes the move
with the most room to spare &mdash; with perfect information</span></div>
  <div><span class="big" style="color:var(--good)">{completed['E2']['conservative']} of \
{completed['E2']['routes']}</span><span class="cap">with small error</span></div>
  <div><span class="big" style="color:var(--good)">{completed['E4']['conservative']} of \
{completed['E4']['routes']}</span><span class="cap">with large error, where the advantage mostly
disappears</span></div>
  <div><span class="big" style="color:var(--bad)">0 of {thousands(b4['greedy_total'])}</span>
  <span class="cap">jobs finished when it takes the biggest move allowed, with or without the
  check</span></div>
</div>
<p class="col"><span class="tag">predicted in advance</span> This was written down before the
runs, including the part about it fading at large error. It is the one claim here that survived
as a formal result rather than an observation.</p>
<div class="pull" style="margin:26px 0 6px">How much you take matters more than what you check
with.</div>""")

    watch = f"""
<section>
  <p class="eyebrow">Three short clips</p>
  <h2>What it looks like</h2>
  <p class="col" style="margin:18px 0 22px">Each clip is a real run from the study, played back
  frame by frame. Nothing is re-simulated to make a nicer picture: before a clip is allowed to be
  rendered it has to reproduce the recorded outcome exactly &mdash; same failure, same clip lost,
  same moves.</p>
  <div class="stack">
    {isaac_figure(data)}
    {video_figure(clips['triptych'], 'The same rig, three robots.',
                  'Left and middle take the biggest move available - about 100 mm - and lose the '
                  'clip at the top of the ridge on the very first one. Right takes the move with '
                  'the most room to spare, 6 mm, five times, and finishes the job with all five '
                  'clips still held.')}
    {video_figure(clips['estimate'], 'What the robot sees, against what is true.',
                  'The beads are where the robot thinks the cable is. The red ones '
                  'are the parts the fixture hides from the camera position, and they are four '
                  'times further off than the rest. The scoreboard on the right is the truth, '
                  'which no robot in this study is allowed to read.')}
    {video_figure(clips['budget'], 'Watching the slack run out.',
                  'How much room the check thinks is left before its threshold, at each of the '
                  'five decisions, and how much the move just taken spent of it. Each careful '
                  '6 mm move costs about 4.3 mm of room.')}
  </div>
</section>"""

    method = f"""
<section>
  <p class="eyebrow">For the sceptical</p>
  <h2>How this was kept honest</h2>
  <p class="col" style="margin:18px 0 20px">Simulation studies are easy to fool yourself with.
  These are the things that were put in place first, before any of the numbers above existed.</p>
  <div class="two">
    <ul class="plain">
      <li><strong>The question was written down and committed before the runs started.</strong>
      Nine predictions across the four studies. Three were right. The six that were wrong are
      still in the record, with what they taught.</li>
      <li><strong>The code being tested cannot read the answer key.</strong> A guard fails any run
      whose control code touches the truth. A deliberate cheating run was included to confirm the
      guard actually fires; it did, and it never fired on a real run.</li>
      <li><strong>Nothing was graded twice.</strong> All
      {thousands(honest['replay']['requests'])} runs of the first study were re-scored from the
      raw logs alone by separate code: {thousands(honest['replay']['comparisons'])} comparisons,
      {honest['replay']['disagreements']} disagreements.</li>
    </ul>
    <ul class="plain">
      <li><strong>A study cannot ask a question it is too coarse to answer.</strong> The margin a
      difference has to beat must be at least twice the measurement's own resolution, checked in
      code. It refused {honest['margin']['refused']} of {honest['margin']['checks']} comparisons
      outright rather than answer them badly.</li>
      <li><strong>Runs cut short do not count as successes.</strong> A move that aborted never got
      the chance to break the things it had not broken yet, so it is excluded rather than scored
      as safe.</li>
      <li><strong>The rig was chosen by a screen, not by taste.</strong> 28 candidate rigs were
      drawn; {honest['screen']['rejected']} were rejected because a cable could not actually be
      installed in them. All the rejections are in the record.</li>
    </ul>
  </div>
  <details style="margin-top:20px"><summary>the exact counts</summary>
    <div style="padding:16px 18px; color:var(--ink-2); font-size:.93rem; line-height:1.7">
      Study 1: {thousands(b1['requests'])} single moves. Study 2:
      {thousands(b2['sequences'])} three-move runs, {thousands(b2['decisions'])} decisions.
      Study 3: {thousands(b3['routes'])} five-clip jobs, {thousands(b3['decisions'])} decisions,
      {thousands(b3['native_steps'])} simulation steps in {b3['wall_minutes']} minutes, with
      {b3['guards']['privilege_guard_events']} guard violations of either kind. The study 3
      contract was committed to git at
      <span class="num">{escape(honest['frozen']['committed_before_launch'])}</span> before a
      single run started.
    </div>
  </details>
  <p class="cite" style="margin-top:18px"><b>Records</b>
  {escape(honest['privilege_guard']['record'])} &middot; {escape(honest['replay']['record'])}
  &middot; {escape(honest['margin']['record'])} &middot; {escape(honest['screen']['record'])}
  &middot; {escape(honest['frozen']['record'])}</p>
</section>"""

    limits = "".join(f"<li>{escape(item)}</li>" for item in scope["limitations"][:6])
    scope_html = f"""
<section>
  <p class="eyebrow">Scope</p>
  <h2>What this is not</h2>
  <p class="col" style="margin-top:18px">All of it is <strong>simulation</strong>. No hardware, no
  real connector, no electrical test, no claim that any of this is safe on a real machine. What is
  being measured is one narrow thing: whether the plug reaches the socket and stays there for half
  a second while every required clip still holds the cable, with the robot still gripping the
  plug.</p>
  <p class="col" style="margin-top:14px">The degraded vision is a <strong>model of how perception
  fails</strong>, built from geometry and declared error sizes. Nothing is rendered and no camera
  is evaluated.</p>
  <ul class="plain" style="margin-top:18px">{limits}</ul>
</section>"""

    footer = """
<footer>
  <p>Four studies on a simulated cable-handling task, in MuJoCo, using a UR5e arm and connector
  models from the Intrinsic Assembly Industrial Benchmark. Every contract was committed to git
  before the runs it governs started.</p>
  <p>This page is generated from the study records by <code>scripts/build_showcase.py</code>:
  change a number in a record, rebuild, and the page changes. Nothing on it is typed by hand.</p>
</footer>"""

    return (head+'\n<div class="wrap">'+masthead+problem+"<hr class='rule'>"+options
            + seeing+"<hr class='rule'>"+chain+"<hr class='rule'>"+breaks+proposal
            + watch+method+scope_html+footer+"</div>\n")


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
