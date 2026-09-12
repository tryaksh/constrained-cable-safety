"""The workbench: open the measured cell, change it, and see what happens.

The routing study is a statement about one five-clip jig. This is the tool for
asking what happens to a different one. It loads the registered cell, lets you
move a clip or change the installed service loop, pick a perception error level
and a supervisor, ask the shipped safety layer what it would permit over the
whole action space, and route through the cell once with the block's own worker.

    # what is loaded, and what can be changed
    .deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py

    # what the safety layer permits on the registered cell at 2 mm error
    .deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py --level E4 --allowed

    # raise the ridge clip by 3 mm, re-screen, and route through it
    .deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py --move c3:up_m=0.009 --run

    # the same, with MuJoCo's viewer open on it
    .deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py --run --view

Everything except the window is ``WorkbenchSession`` in
``src/assembly_recovery/cable_workbench_v7.py``, which is headless and unit
tested. This file is the command line and one call to ``launch_passive``.

Nothing here measures anything. A cell you have changed is a DIFFERENT CELL from
the one the study measured, every report says so, and no number out of a changed
cell belongs beside a published one.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_workbench_v7 import SUPERVISORS, WorkbenchSession  # noqa: E402

#: The registered request the self-check reproduces. It is one of the matched
#: triples whose per-tick ledger was kept, and its outcome is committed.
SELF_CHECK_REQUEST = "RC1_l15_compliant4000_m0_E0_conservative_r0"


def parse_move(text: str) -> tuple[str, dict]:
    """``c3:up_m=0.009`` or ``c3:along_m=0.15,up_m=0.009``."""
    clip, _, rest = text.partition(":")
    if not clip or not rest:
        raise argparse.ArgumentTypeError(
            f"--move wants CLIP:FIELD=VALUE, for example c3:up_m=0.009; got {text!r}")
    fields = {}
    for piece in rest.split(","):
        key, _, value = piece.partition("=")
        try:
            fields[key.strip()] = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{piece!r} is not FIELD=VALUE") from exc
    return clip.strip(), fields


def emit(label: str, payload) -> None:
    print(f"--- {label}", flush=True)
    print(json.dumps(payload, indent=1, default=float), flush=True)


def view_observer():
    """A per-tick observer that keeps MuJoCo's own viewer in step with the run.

    The one part of this tool that cannot be tested here, because there is no
    display on the machine it was written on. It opens on the first servo tick,
    which is after the cable has settled, and closes when the route ends.
    """
    import mujoco.viewer

    state: dict = {}

    def observe(tick: dict) -> None:
        if "viewer" not in state:
            scene = tick["scene"]
            state["viewer"] = mujoco.viewer.launch_passive(scene.model, scene.data)
        state["viewer"].sync()

    def close() -> None:
        if "viewer" in state:
            state["viewer"].close()

    return observe, close


def self_check(session_root: Path, out: Path | None) -> dict:
    """Prove the tool is showing the cell that was measured, not a lookalike.

    Four checks, in order of what they would catch: the request this tool expands
    is the request the block ran; the screen re-run here reproduces the committed
    screen record to the digit; the route re-run here reproduces the committed
    result; and a moved clip is refused until it has been screened again.
    """
    started = time.monotonic()
    checks = []
    session = WorkbenchSession.open(session_root, loop_m=0.0015, error_level="E0",
                                    supervisor="conservative")

    case = session.case()
    committed = json.loads(
        (session_root / "artifacts/cable/routing-v6-s1" / SELF_CHECK_REQUEST / "result.json")
        .read_text(encoding="utf-8"))
    differing = sorted(k for k in committed["case"] if case.get(k) != committed["case"][k])
    checks.append({
        "check": "the expanded request is the registered one",
        "request": case["id"], "expected": SELF_CHECK_REQUEST,
        "fields_differing": differing,
        "passes": case["id"] == SELF_CHECK_REQUEST and not differing,
    })

    screened = session.run_screen()
    reference = next(e for e in session.screen["accepted_cell_detail"]
                     if e["group"] == f"{session.cell_id}_l15")
    fields = ("worst_lateral_wall_gap_m", "installed_min_bend_radius_m", "boot_to_anchor_m",
              "solved_anchor_along_m")
    reproduced = {name: {"here": screened[name], "record": reference[name],
                         "same": screened[name] == reference[name]} for name in fields}
    checks.append({
        "check": "re-screening the unmutated cell reproduces evidence/cable_cell_screen_v6.json",
        "passes": screened["passes"] and all(v["same"] for v in reproduced.values()),
        "fields": reproduced,
        "record": "evidence/cable_cell_screen_v6.json",
    })

    report = session.run()
    expected = {
        "outcome": committed["job"]["failure_reason"] or "completed",
        "route_completed": committed["route_completed"],
        "seated": committed["seated"],
        "steps_issued": committed["steps_issued"],
        "terminal_required_clips": committed["terminal_clips"]["required_retained"],
        "c1_headroom_series_m": [round(r["budget"]["C1_clip"]["headroom_at_decision_m"], 9)
                                 for r in committed["issued"] if r.get("budget")],
    }
    measured = {
        "outcome": report["outcome"],
        "route_completed": report["route_completed"],
        "seated": report["seated"],
        "steps_issued": report["steps_issued"],
        "terminal_required_clips": report["terminal_clips"]["required_retained"],
        "c1_headroom_series_m": [round(step["spent"]["C1_clip"]["headroom_at_decision_m"], 9)
                                 for step in report["per_step"] if step["spent"]],
    }
    checks.append({
        "check": "re-running the unmutated route reproduces the committed result",
        "passes": measured == expected,
        "expected": expected, "measured": measured,
        "record": f"artifacts/cable/routing-v6-s1/{SELF_CHECK_REQUEST}/result.json",
    })

    moved = WorkbenchSession.open(session_root, loop_m=0.0015, error_level="E0",
                                  supervisor="conservative")
    moved.move_clip("c3", up_m=0.009)
    refused = None
    try:
        moved.case()
    except RuntimeError as exc:
        refused = str(exc)
    mutated_screen = moved.run_screen()
    checks.append({
        "check": "a moved clip is refused until the screen has been re-run",
        "passes": refused is not None and moved.mutated,
        "refusal": refused,
        "after_rescreening": {
            "passes": mutated_screen["passes"],
            "reason_rejected": mutated_screen["reason_rejected"],
            "required_retained": (mutated_screen.get("summary") or {}).get("required_retained"),
            "installed_min_bend_radius_m": mutated_screen.get("installed_min_bend_radius_m"),
            "worst_lateral_wall_gap_m": mutated_screen.get("worst_lateral_wall_gap_m"),
        },
        "note": "Raising the ridge clip 3 mm is a DIFFERENT CELL. Whether it installs is "
                "measured here, not assumed.",
    })

    record = {
        "schema": 1, "id": "showcase_tool_v7", "stage": "C",
        "created_on": "2026-09-12",
        "status": "verified" if all(c["passes"] for c in checks) else "FAILED",
        "what_this_is": "scripts/workbench.py plus WorkbenchSession in "
                        "src/assembly_recovery/cable_workbench_v7.py: a local tool for opening "
                        "the measured cell, changing it, and running it again. Not a study "
                        "result and not a hardware claim.",
        "the_untested_line": "The interactive MuJoCo window. This machine has no display, so "
                             "launch_passive was never executed in the session that wrote it. "
                             "Everything it wraps is headless and unit tested.",
        "checks": checks,
        "wall_seconds": round(time.monotonic()-started, 1),
        "commands": {
            "show": ".deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py",
            "allowed": ".deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py "
                       "--level E4 --allowed",
            "move and run": ".deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py "
                            "--move c3:up_m=0.009 --run",
            "watch it": ".deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py --run --view",
            "self check": ".deps/cable-venv/Scripts/pythonw.exe scripts/workbench.py "
                          "--self-check",
        },
    }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2, default=float), encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--cell", help="A declared cell id; default the registered one.")
    parser.add_argument("--loop", type=float, help="Installed service loop, metres.")
    parser.add_argument("--level", default="E2", help="Perception error level, E0 to E4.")
    parser.add_argument("--supervisor", default="conservative", choices=sorted(SUPERVISORS))
    parser.add_argument("--move", action="append", type=parse_move, default=[],
                        metavar="CLIP:FIELD=VALUE",
                        help="Move a clip, for example c3:up_m=0.009. Repeatable.")
    parser.add_argument("--screen", action="store_true",
                        help="Settle a cable into the cell and say whether it installs.")
    parser.add_argument("--allowed", action="store_true",
                        help="What the shipped safety layer permits over the action space.")
    parser.add_argument("--run", action="store_true", help="Route through the cell once.")
    parser.add_argument("--view", action="store_true",
                        help="Open MuJoCo's viewer on the run. Needs a display.")
    parser.add_argument("--out", type=Path, help="Write the report to this JSON file.")
    parser.add_argument("--self-check", action="store_true",
                        help="Prove the tool reproduces committed results, then write "
                             "artifacts/showcase/tool.json.")
    args = parser.parse_args()

    if args.self_check:
        record = self_check(args.root, args.out or args.root / "artifacts/showcase/tool.json")
        emit("self check", {"status": record["status"],
                            "checks": [{"check": c["check"], "passes": c["passes"]}
                                       for c in record["checks"]],
                            "wall_seconds": record["wall_seconds"]})
        return 0 if record["status"] == "verified" else 1

    session = WorkbenchSession.open(args.root, cell=args.cell, loop_m=args.loop,
                                    error_level=args.level, supervisor=args.supervisor)
    for clip, fields in args.move:
        emit("moved", session.move_clip(clip, **fields))

    emit("loaded", session.describe())

    # A changed cell has to be settled before anything else is worth asking. The
    # registered screen rejected 19 of 28 declared cells, so "it compiled" is not
    # an answer.
    if session.needs_screening and (args.screen or args.allowed or args.run):
        emit("screening", {"why": "the cell has changed, so the screen no longer applies",
                           "cost": "about six seconds"})
        screened = session.run_screen()
        emit("screen", {k: v for k, v in screened.items() if k != "per_clip"})
        if not screened["passes"]:
            emit("stopped", {"reason": screened["reason_rejected"],
                             "meaning": "the cable does not install in this cell, so there is "
                                        "nothing to route through"})
            return 1
    elif args.screen:
        emit("screen", session.run_screen() | {"per_clip": None})

    report: dict = {"loaded": session.describe()}
    if args.allowed:
        allowed = session.allowed()
        report["allowed"] = allowed
        emit("what the safety layer permits", allowed)
    if args.run:
        observe = close = None
        if args.view:
            observe, close = view_observer()
        try:
            result = session.run(observer=observe)
        finally:
            if close:
                close()
        report["run"] = result
        emit("route", result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
        print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
