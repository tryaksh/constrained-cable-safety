"""Freeze and launch the registered perception study.

Two modes, in this order and no other:

``--freeze``  Reads the executed layout screen, writes the surviving layouts, the
              held-out group split, the base-task content hash and the expanded
              request count into the contract, and stops. The contract must then
              be COMMITTED before anything is launched. Freezing refuses to run if
              the screen is missing, if fewer than the declared minimum of layouts
              survived, or if the split would leave fewer test contexts per error
              level than the contract requires.

``--shard``   Expands the frozen contract into a runnable case list and hands one
              contiguous shard to the ordinary cable launcher, so each shard gets
              the usual prelaunch provenance and fits inside the launcher's own
              deadline ceiling. Shards are cut on whole contexts, so an
              interrupted block still has whole contexts rather than fragments.

It runs no physics itself and makes no decision. A pilot is labelled as a pilot
and uses its own run id, so it can never be mistaken for the registered block.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_run import execute_run  # noqa: E402
from assembly_recovery.cable_study_v4 import (  # noqa: E402
    build_cases,
    build_contexts,
    content_sha256,
    isolation_contexts,
    merge_runtime,
    raw_sha256,
)

#: Held-out groups are assigned to splits round robin in screened order, so every
#: split gets corner routes, straight routes, both shelf heights and all three
#: service loops without anyone choosing which cell lands where. The shape of the
#: cycle - two test, three train, one dev in six - is what turns the screen's 29
#: surviving cells into the 10 test groups that give 60 test contexts per error
#: level at two mounts and three decision poses.
SPLIT_CYCLE = ("test", "train", "dev", "test", "train", "train")


def freeze(contract_path: Path, screen_path: Path, minimum_layouts: int) -> dict:
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    screen = json.loads(screen_path.read_text(encoding="utf-8-sig"))
    candidates = json.loads((ROOT / contract["candidates"]["path"]).read_text(encoding="utf-8-sig"))
    registered = screen["registered"]
    accepted_groups = set(registered["accepted_groups"])
    accepted = [layout for layout in candidates["layouts"]
                if layout["id"] in registered["accepted_layouts"]]
    if len(accepted) < minimum_layouts:
        raise SystemExit(f"Screen accepted {len(accepted)} layouts; the contract needs "
                         f"{minimum_layouts}. Rejections are in {screen_path.name}; widen the "
                         f"candidate list rather than lowering this floor.")

    loops = contract["registered_support"]["installed_loop_m"]
    every = [f"{layout['id']}_l{int(round(loop*1000))}"
             for layout in accepted for loop in loops]
    excluded = [group for group in every if group not in accepted_groups]
    surviving = [group for group in every if group in accepted_groups]
    groups = {"train": [], "dev": [], "test": []}
    for index, group in enumerate(surviving):
        groups[SPLIT_CYCLE[index % len(SPLIT_CYCLE)]].append(group)

    contract["registered_support"]["excluded_groups"] = excluded
    contract["registered_support"]["excluded_groups_note"] = (
        f"The {len(excluded)} (layout, installed loop) cells the screen rejected, of {len(every)} "
        f"expanded from the {len(accepted)} surviving layouts. They are never run and are recorded "
        f"with their reasons in {screen_path.relative_to(ROOT).as_posix()}.")
    contract["registered_support"]["layouts"] = accepted
    contract["registered_support"]["selection_note"] = (
        f"The {len(accepted)} layouts with at least one cell surviving the screen in "
        f"{screen_path.relative_to(ROOT).as_posix()}, in candidate order. "
        f"{len(candidates['layouts'])} layouts and "
        f"{registered['accepted_cells']+registered['rejected_cells']} cells were declared; "
        f"{registered['rejected_cells']} cells were rejected there. Every rejection is kept with "
        f"its reason and no rejected cell is run.")
    for key in ("train", "dev", "test"):
        contract["groups"][key] = sorted(groups[key])
    contract["groups"]["split_rule"] = (
        "Surviving (layout, installed loop) cells were ordered as screened and assigned round "
        "robin to " + ", ".join(SPLIT_CYCLE)
        + ", so every split contains corner routes, straight routes, both shelf heights and all "
          "three service loops, and nobody chose which cell landed where. Frozen before any "
          "request was launched; test groups stay closed until every method and budget is "
          "frozen.")

    base_path = ROOT / contract["base_config"]["path"]
    contract["base_config"]["content_sha256"] = content_sha256(base_path)

    mounts = len(contract["registered_support"]["port_mount"])
    poses = len(contract["registered_support"]["decision_pose"])
    test_contexts_per_level = len(contract["groups"]["test"])*mounts*poses
    required = contract["groups"]["test_context_requirement"]
    if test_contexts_per_level < required:
        raise SystemExit(f"The split gives {test_contexts_per_level} test contexts per error level; "
                         f"the contract requires {required}. Fix the split or the support, not the "
                         f"requirement.")
    cases = build_cases(contract)
    contract["expected_requests"] = len(cases)
    contract["frozen_counts"] = {
        "layouts": len(accepted), "groups": sum(len(contract["groups"][k])
                                                for k in ("train", "dev", "test")),
        "ladder_contexts": len(build_contexts(contract)),
        "isolation_contexts": len(isolation_contexts(contract)),
        "test_contexts_per_error_level": test_contexts_per_level,
        "requests": len(cases),
    }
    contract_path.write_text(json.dumps(contract, indent=1, ensure_ascii=False)+"\n",
                             encoding="utf-8")
    return contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--screen", type=Path, default=Path("evidence/cable_layout_screen_v4.json"))
    parser.add_argument("--minimum-layouts", type=int, default=12)
    parser.add_argument("--run-id")
    parser.add_argument("--shard", type=int, default=1)
    parser.add_argument("--of", type=int, default=1)
    parser.add_argument("--max-minutes", type=float, default=290)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--pilot-contexts", type=int, default=0,
                        help="Run only the first N registered contexts. A pilot, not the block.")
    parser.add_argument("--pilot-stride", type=int, default=1,
                        help="Take every Nth context for the pilot, so a pilot spans error levels.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--python", type=Path, default=ROOT / ".deps/cable-venv/Scripts/python.exe")
    args = parser.parse_args()

    if args.freeze:
        contract = freeze(ROOT / args.contract, ROOT / args.screen, args.minimum_layouts)
        print(json.dumps({"status": "frozen", "contract": args.contract.as_posix(),
                          "content_sha256": content_sha256(ROOT / args.contract),
                          **contract["frozen_counts"]}, indent=1))
        return 0

    if not args.run_id:
        parser.error("--run-id is required unless --freeze is given")
    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    if contract["expected_requests"] == "PENDING_FREEZE":
        parser.error("Contract is not frozen. Run --freeze first, then commit it, then launch.")
    base_path = ROOT / contract["base_config"]["path"]
    measured = content_sha256(base_path)
    if measured != contract["base_config"]["content_sha256"]:
        parser.error(f"Base task content hash is {measured}, contract declares "
                     f"{contract['base_config']['content_sha256']}")

    runtime = merge_runtime(json.loads(base_path.read_text(encoding="utf-8-sig")), contract)
    if len(runtime["cases"]) != contract["expected_requests"]:
        parser.error(f"Expanded {len(runtime['cases'])} requests, contract declares "
                     f"{contract['expected_requests']}")

    contexts = [c["id"] for c in build_contexts(contract)+isolation_contexts(contract)]
    if args.pilot_contexts:
        keep = set(contexts[::args.pilot_stride][:args.pilot_contexts])
        runtime["cases"] = [c for c in runtime["cases"] if c["study_context"] in keep]
        runtime["id"] = contract["id"]+"_pilot"
        runtime["pilot"] = {"contexts": sorted(keep), "stride": args.pilot_stride,
                            "note": "Pilot subset for timing and outcome spread. Not the block."}
    elif args.of > 1:
        if not 1 <= args.shard <= args.of:
            parser.error("--shard must be between 1 and --of")
        size = -(-len(contexts)//args.of)
        keep = set(contexts[(args.shard-1)*size:args.shard*size])
        runtime["cases"] = [c for c in runtime["cases"] if c["study_context"] in keep]
        runtime["shard"] = {"index": args.shard, "of": args.of, "contexts": len(keep),
                            "note": "Shards are cut on whole contexts so an interrupted block has "
                                    "whole contexts, never fragments. Every shard is fitted "
                                    "together by scripts/fit_perception_v4.py."}

    runtime_path = ROOT / "artifacts/cable" / f"{args.run_id}__runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime, indent=1), encoding="utf-8")
    summary = {
        "run_id": args.run_id, "contract": args.contract.as_posix(),
        "contract_content_sha256": content_sha256(ROOT / args.contract),
        "base_content_sha256": measured, "base_raw_sha256": raw_sha256(base_path),
        "runtime_config": runtime_path.relative_to(ROOT).as_posix(),
        "runtime_content_sha256": content_sha256(runtime_path),
        "requests": len(runtime["cases"]),
        "contexts": len({c["study_context"] for c in runtime["cases"]}),
        "shard": runtime.get("shard"), "pilot": bool(args.pilot_contexts),
    }
    if args.dry_run:
        print(json.dumps({**summary, "status": "dry_run"}, indent=1))
        return 0

    manifest = execute_run(
        root=ROOT, run_id=args.run_id,
        worker=ROOT / "scripts/evaluate_cable_perception_v4.py",
        config=runtime_path, python=ROOT / args.python, max_minutes=args.max_minutes,
        worker_args=["--workers", str(args.workers)],
    )
    print(json.dumps({**summary, "status": manifest["status"],
                      "manifest": (ROOT / "artifacts/cable" / args.run_id
                                   / "manifest.json").as_posix()}, indent=1))
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
