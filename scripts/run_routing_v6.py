"""Freeze and launch the routing block: does the check earn its place over five clips?

Expands the frozen contract into one request per (registered cell group, port
mount, error level, supervisor, perception draw), checks that the base task it
merges onto is the one the contract declares, checks that the cell it routes
through is the one the screen registered and the CAD drew, checks that the safety
filter it will load exists, and hands the list to the ordinary cable launcher so
the run gets the usual prelaunch provenance.

It runs no physics and makes no decision. It refuses to expand if the screen has
not registered a cell, because there is nothing to route through, and it refuses
to freeze a size whose metric resolution the declared margin cannot beat.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from assembly_recovery.cable_cell_v6 import cell_case  # noqa: E402
from assembly_recovery.cable_run import execute_run  # noqa: E402
from assembly_recovery.cable_safety_filter_v4 import SafetyFilter  # noqa: E402
from assembly_recovery.cable_study_v4 import content_sha256, raw_sha256  # noqa: E402


def registered_groups(screen: dict, cell: str) -> list[tuple[str, float]]:
    """Every (group, installed loop) the screen accepted for the registered cell."""
    return [(entry["group"], entry["installed_loop_m"])
            for entry in screen["accepted_cell_detail"] if entry["layout"] == cell]


def build_cases(contract: dict, candidates: dict, base: dict, screen: dict, cad: dict,
                perception: dict) -> list[dict]:
    """One request per registered group, mount, error level, supervisor and draw."""
    cell = contract["cell"]["registered_cell"]
    layout = next(e for e in candidates["layouts"] if e["id"] == cell)
    support = perception["registered_support"]
    registered = contract["registered_support"]
    mounts = [m for m in support["port_mount"] if m["id"] in registered["port_mount"]]
    supervisors = [s["id"] for s in contract["route"]["supervisors"]]
    repeats = registered["repeats_by_error_level"]
    offsets = registered["mount_offsets_m"]
    cases, seed = [], contract["first_calibration_seed"]
    for group, loop in registered_groups(screen, cell):
        for mount in mounts:
            for offset_index, offset in enumerate(offsets):
                for level in registered["error_levels"]:
                    for supervisor in supervisors:
                        for repeat in range(int(repeats[level])):
                            cases.append(cell_case(
                                layout, loop, candidates, base, cad,
                                id=(f"{group}_{mount['id']}_m{offset_index}_{level}"
                                    f"_{supervisor}_r{repeat}"),
                                controller="route_supervisor",
                                calibration_seed=seed,
                                perception_seed=seed+contract["perception_seed_offset"],
                                port_compliance=mount["compliance"],
                                fixture_offset_m=list(offset),
                                mount_offset_index=offset_index,
                                error_level=level, error_isolation="all",
                                supervisor=supervisor, repeat=repeat,
                                cell=cell, study_group=group, study_split="routing_cell",
                                gate="S3",
                                purpose="Routing study: five decisions over a five-clip route."))
                            seed += 1
    return cases


def cell_size(contract: dict, screen: dict, level: str) -> int:
    """How many routes land in one (error level, supervisor) cell.

    At E0 the estimate a supervisor reads IS the truth, exactly, so extra
    perception draws would be byte-identical repeats of the same request and are
    not taken. The independent n at E0 is therefore the number of PHYSICAL
    contexts, and the metric resolution there is computed from that and not from
    an inflated count.
    """
    registered = contract["registered_support"]
    groups = registered_groups(screen, contract["cell"]["registered_cell"])
    return (len(groups)*len(registered["port_mount"])*len(registered["mount_offsets_m"])
            * int(registered["repeats_by_error_level"][level]))


def merge_runtime(base: dict, contract: dict, candidates: dict, screen: dict, cad: dict,
                  perception: dict) -> dict:
    runtime = json.loads(json.dumps(base))
    for key, value in contract["runtime_overrides"].items():
        if isinstance(value, dict) and isinstance(runtime.get(key), dict):
            runtime[key] = {**runtime[key], **value}
        else:
            runtime[key] = value
    runtime["id"] = contract["id"]
    runtime["scope"] = contract["scope"]
    runtime["perception"] = {"camera": perception["error_model"]["camera"],
                             "levels": perception["error_model"]["levels"],
                             "isolation": perception["error_model"].get("isolation"),
                             "history": perception["error_model"]["history"]}
    runtime["constraints"] = perception["constraints"]
    runtime["safety_filter"] = contract["safety_filter"]
    runtime["route"] = contract["route"]
    runtime["cell"] = contract["cell"]
    runtime["cases"] = build_cases(contract, candidates, base, screen, cad, perception)
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_routing_v6.json"))
    parser.add_argument("--perception", type=Path,
                        default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--max-minutes", type=float, default=290)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--shard", type=int)
    parser.add_argument("--of", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pilot", type=int, default=0,
                        help="Expand only this many requests, spread over the support, and "
                             "write them to a runtime config without launching.")
    parser.add_argument("--python", type=Path, default=ROOT / ".deps/cable-venv/Scripts/pythonw.exe")
    args = parser.parse_args()

    contract_path = ROOT / args.contract
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    perception = json.loads((ROOT / args.perception).read_text(encoding="utf-8-sig"))
    base_path = ROOT / contract["base_config"]["path"]
    base = json.loads(base_path.read_text(encoding="utf-8-sig"))
    candidates = json.loads((ROOT / contract["cell"]["candidates"]).read_text(encoding="utf-8-sig"))
    screen = json.loads((ROOT / contract["cell"]["screen"]).read_text(encoding="utf-8"))
    cad = json.loads((ROOT / contract["cell"]["cad"]).read_text(encoding="utf-8"))

    cell = contract["cell"]["registered_cell"]
    if screen.get("registered_cell") != cell:
        parser.error(f"The screen registered {screen.get('registered_cell')!r}, the contract "
                     f"declares {cell!r}. The cell under test is the screen's output.")
    if cad["authored_from"]["cell"] != cell:
        parser.error(f"The CAD was authored for {cad['authored_from']['cell']!r}, not {cell!r}.")
    groups = registered_groups(screen, cell)
    if not groups:
        parser.error(f"The screen accepted no cell for {cell}. There is nothing to route through.")

    fit_path = ROOT / contract["safety_filter"]["fit"]
    if not fit_path.is_file():
        parser.error(f"The filter under test comes from {fit_path.name}, which does not exist.")
    loaded = SafetyFilter.from_evidence(fit_path, ROOT / contract["safety_filter"]["contract"],
                                        ROOT / contract["safety_filter"]["base"])
    if not loaded.rules:
        parser.error("The perception record carries no fitted threshold for any constraint.")

    if args.freeze:
        contract["base_config"]["content_sha256"] = content_sha256(base_path)
        contract["cell"]["candidates_content_sha256"] = content_sha256(
            ROOT / contract["cell"]["candidates"])
        contract["cell"]["screen_content_sha256"] = content_sha256(ROOT / contract["cell"]["screen"])
        contract["cell"]["cad_content_sha256"] = content_sha256(ROOT / contract["cell"]["cad"])
        contract["cell"]["asset_sha256"] = {p["part"]: p["content_sha256"] for p in cad["parts"]}
        contract["registered_support"]["groups"] = [g for g, _ in groups]
        cases = build_cases(contract, candidates, base, screen, cad, perception)
        registered = contract["registered_support"]
        sizes = {level: cell_size(contract, screen, level)
                 for level in registered["error_levels"]}
        per_cell = min(sizes.values())
        contract["frozen_counts"] = {
            "registered_groups": len(groups),
            "port_mounts": len(registered["port_mount"]),
            "mount_offsets": len(registered["mount_offsets_m"]),
            "repeats_by_error_level": registered["repeats_by_error_level"],
            "routes_per_cell_by_error_level": sizes,
            "error_levels": len(registered["error_levels"]),
            "supervisors": len(contract["route"]["supervisors"]),
            "steps_per_request": len(contract["route"]["decision_times_s"]),
            "required_clips": len([c for c in next(
                e for e in candidates["layouts"] if e["id"] == cell)["clips"]
                if c.get("required", True)]),
            "routes_per_level_and_supervisor": per_cell,
            "per_step_metric_resolution": 1/per_cell if per_cell else None,
            "requests": len(cases),
            "decisions": len(cases)*len(contract["route"]["decision_times_s"]),
        }
        # The coarsest cell in play decides, and it is checked level by level so a
        # well-sized E4 cannot hide an unresolvable E0.
        margin = contract["decision_rule"]["margin"]
        for level, size in sizes.items():
            if not size or 1/size > margin/2:
                raise SystemExit(
                    f"A per-step rate over {size} routes at {level} resolves to "
                    f"{1/max(size,1):.4f}, which the registered margin of {margin} cannot beat. "
                    f"Add routes; do not lower the margin.")
        contract["expected_requests"] = len(cases)
        contract["safety_filter"]["loaded_at_freeze"] = loaded.report()
        contract["status"] = "frozen_study_contract"
        contract_path.write_text(json.dumps(contract, indent=1, ensure_ascii=False)+"\n",
                                 encoding="utf-8")
        print(json.dumps({"status": "frozen", "contract": args.contract.as_posix(),
                          "content_sha256": content_sha256(contract_path),
                          **contract["frozen_counts"]}, indent=1))
        return 0

    if contract["expected_requests"] == "PENDING_FREEZE" and not args.pilot:
        parser.error("Contract is not frozen. Run --freeze first, then commit it, then launch.")
    measured = content_sha256(base_path)
    if not args.pilot and measured != contract["base_config"]["content_sha256"]:
        parser.error(f"Base task content hash is {measured}, contract declares "
                     f"{contract['base_config']['content_sha256']}")

    runtime = merge_runtime(base, contract, candidates, screen, cad, perception)
    if args.pilot:
        # Spread the pilot over the support rather than taking the first N, so the
        # measured cost is not the cost of one corner of it.
        cases = runtime["cases"]
        stride = max(1, len(cases)//args.pilot)
        runtime["cases"] = cases[::stride][:args.pilot]
        runtime["id"] = contract["id"]+"_pilot"
    elif len(runtime["cases"]) != contract["expected_requests"]:
        parser.error(f"Expanded {len(runtime['cases'])} requests, contract declares "
                     f"{contract['expected_requests']}")

    if args.shard and args.of:
        # Shard on whole GROUPS, so a shard is a complete set of contexts and the
        # fitter can put the shards back together without splitting a cell.
        groups_in_order = [g for g, _ in groups]
        mine = {g for i, g in enumerate(groups_in_order) if i % args.of == args.shard-1}
        runtime["cases"] = [c for c in runtime["cases"] if c["study_group"] in mine]
        runtime["shard"] = {"index": args.shard, "of": args.of, "groups": sorted(mine)}

    suffix = "_pilot" if args.pilot else ""
    run_id = args.run_id or (contract["id"]+suffix)
    runtime_path = ROOT / "artifacts/cable" / f"{run_id}__runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime, indent=1), encoding="utf-8")
    summary = {
        "run_id": run_id, "contract": args.contract.as_posix(),
        "contract_content_sha256": content_sha256(contract_path),
        "perception_fit_sha256": content_sha256(fit_path),
        "screen_sha256": content_sha256(ROOT / contract["cell"]["screen"]),
        "cad_sha256": content_sha256(ROOT / contract["cell"]["cad"]),
        "base_content_sha256": measured, "base_raw_sha256": raw_sha256(base_path),
        "runtime_config": runtime_path.relative_to(ROOT).as_posix(),
        "requests": len(runtime["cases"]),
        "decisions": len(runtime["cases"])*len(contract["route"]["decision_times_s"]),
    }
    if args.dry_run:
        print(json.dumps({**summary, "status": "dry_run"}, indent=1))
        return 0

    manifest = execute_run(
        root=ROOT, run_id=run_id,
        worker=ROOT / "scripts/evaluate_cable_routing_v6.py",
        config=runtime_path, python=ROOT / args.python, max_minutes=args.max_minutes,
        worker_args=["--workers", str(args.workers)],
    )
    print(json.dumps({**summary, "status": manifest["status"]}, indent=1))
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
