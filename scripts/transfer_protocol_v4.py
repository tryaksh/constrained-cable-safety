"""Publish how the fitted safety threshold moves with the cable's own properties.

There is no hardware, so no transfer CLAIM is admissible. What is admissible, and
useful, is a transfer PROTOCOL: sweep the cable's physical parameters over ranges
that cover real cable variability, refit the one-number safety threshold inside
each cell, and publish the sensitivity so an engineer who knows their cable's
bending stiffness to plus or minus thirty percent can read off how much extra
margin to carry.

The output is theta(EI, mu, rho, c) and the margin a stated parameter tolerance
implies, together with an explicit statement of what stays untested and what a
one-day hardware check would have to measure to falsify it.

This runs physics. It is a control beside the study, not part of it: it uses a
reduced support, the registered core actions only, and the zero-error level, so
the threshold it fits is the analytic budget of the v3 block measured against a
changed cable rather than a changed observation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_constraints_v4 import CENSORED, VIOLATED  # noqa: E402
from assembly_recovery.cable_study_v4 import (  # noqa: E402
    content_sha256,
    core_actions,
    feature_row,
    fit_threshold,
    level_by_id,
)
from scripts.evaluate_cable_perception_v4 import guarded_case  # noqa: E402

#: The swept properties, their nominal values and the fraction they are moved by.
#: Ranges cover ordinary variability in a small jacketed cable: jacket modulus and
#: friction vary most between compounds and with age, mass least.
SWEEP = {
    "youngs_modulus_pa": {"nominal": 1.0e7, "factors": [0.7, 1.0, 1.4],
                          "meaning": "bending stiffness EI, at fixed cross-section"},
    "friction": {"nominal": None, "factors": [0.6, 1.0, 1.6],
                 "meaning": "sliding friction mu against the shelf, clip and post"},
    "total_mass_kg": {"nominal": 0.05, "factors": [0.75, 1.0, 1.3],
                      "meaning": "linear density rho at fixed geometry"},
    "joint_damping": {"nominal": 2.0e-4, "factors": [0.4, 1.0, 2.5],
                      "meaning": "material bending damping c"},
}


def sweep_cells(base: dict) -> list[dict]:
    cells = [{"id": "nominal", "parameter": "none", "factor": 1.0, "overrides": {}}]
    for name, spec in SWEEP.items():
        nominal = base["cable"][name] if spec["nominal"] is None else spec["nominal"]
        for factor in spec["factors"]:
            if factor == 1.0:
                continue
            value = ([round(v*factor, 8) for v in nominal] if isinstance(nominal, list)
                     else round(nominal*factor, 10))
            cells.append({"id": f"{name}_x{factor}", "parameter": name, "factor": factor,
                          "meaning": spec["meaning"], "overrides": {name: value}})
    return cells


def build_requests(contract: dict, cell: dict, layouts, seed_base: int) -> list[dict]:
    actions = core_actions(contract["action_design"])
    support = contract["registered_support"]
    loop = support["installed_loop_m"][1]
    mount = next(m for m in support["port_mount"] if m["id"] == "compliant4000")
    pose = next(p for p in support["decision_pose"] if p["id"] == "near_seated")
    cases, seed = [], seed_base
    for layout in layouts:
        for index, action in enumerate(actions):
            case = {
                "id": f"transfer_{cell['id']}_{layout['id']}_core{index:02d}",
                "controller": "force_guided_insertion",
                "calibration_seed": seed, "perception_seed": seed+900000,
                "run_direction_xy": layout["run_direction_xy"],
                "outward_xy": layout["outward_xy"],
                "route_waypoints_along_across_m": layout["route_waypoints_along_across_m"],
                "fixture_overrides": {**layout.get("fixture_overrides", {}),
                                      "clip": {**layout.get("fixture_overrides", {}).get("clip", {}),
                                               "along_m": layout["clip_along_m"]}},
                "installed_loop_m": loop, "fixture_offset_m": [0.0, 0.0],
                "forced_macro": "parametric", "forced_macro_at_s": pose["at_s"],
                "repair_action": action, "error_level": "E0", "error_isolation": "all",
                "study_context": f"transfer_{cell['id']}_{layout['id']}",
                "study_group": layout["id"], "study_split": "transfer",
                "action_kind": "core", "action_index": index,
                "port_compliance": mount["compliance"],
                "gate": "transfer", "purpose": "Transfer protocol: threshold sensitivity to the "
                                               "cable's own physical properties.",
            }
            overrides = {**layout.get("cable_overrides", {}), **cell["overrides"]}
            if overrides:
                case["cable_overrides"] = overrides
            cases.append(case)
            seed += 1
    return cases


def fit_cell(results, contract: dict, layouts, retract: float) -> dict:
    """One threshold per cell, on the requests whose outcome was observed."""
    by_id = {layout["id"]: layout for layout in layouts}
    level = level_by_id(contract, "E0")
    values, labels, censored = [], [], 0
    for result in results:
        decision = result.get("decision_state")
        state = result["constraints"]["C1_clip"]["state"]
        if decision is None or state == CENSORED:
            censored += 1
            continue
        layout = by_id[result["case"]["study_group"]]
        context = {"run_direction_xy": layout["run_direction_xy"],
                   "installed_loop_m": result["case"]["installed_loop_m"]}
        row = feature_row(decision, result["case"]["repair_action"], context, retract, level)
        values.append(row["endpoint_boot_to_anchor_m"])
        labels.append(1 if state == VIOLATED else 0)
    values, labels = np.asarray(values), np.asarray(labels)
    fit = fit_threshold(values, labels) if values.size else {"threshold_m": None,
                                                             "train_balanced_accuracy": None}
    return {**fit, "requests": len(results), "observed": int(values.size), "censored": censored,
            "violation_rate": float(labels.mean()) if labels.size else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--out", type=Path, default=Path("evidence/cable_transfer_protocol_v4.json"))
    parser.add_argument("--work-dir", type=Path, default=Path("artifacts/cable/transfer-v4"))
    parser.add_argument("--layouts", type=int, default=4)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--max-cells", type=int, default=0,
                        help="Run only the first N sweep cells. A smoke check, not the sweep.")
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    base = json.loads((ROOT / contract["base_config"]["path"]).read_text(encoding="utf-8-sig"))
    retract = base["force_guided_controller"]["retract_distance_m"]
    layouts = contract["registered_support"]["layouts"][:args.layouts]
    if not layouts:
        parser.error("The contract has no registered layouts; freeze it first.")
    work = ROOT / args.work_dir
    work.mkdir(parents=True, exist_ok=True)

    runtime_base = {**base, "render_visuals": False,
                    "perception": {"camera": contract["error_model"]["camera"],
                                   "levels": contract["error_model"]["levels"],
                                   "isolation": contract["error_model"].get("isolation"),
                                   "history": contract["error_model"]["history"]},
                    "constraints": contract["constraints"]}
    cells, started = sweep_cells(base), time.monotonic()
    if args.max_cells:
        cells = cells[:args.max_cells]
    records = []
    for number, cell in enumerate(cells):
        cases = build_requests(contract, cell, layouts, seed_base=310000+number*10000)
        runtime = {**runtime_base, "id": f"transfer_{cell['id']}", "cases": cases}
        directory = work / cell["id"]
        if args.workers > 1:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                results = list(pool.map(_run, [(runtime, case, directory / case["id"])
                                               for case in cases]))
        else:
            results = [guarded_case(runtime, case, directory / case["id"]) for case in cases]
        record = {**{k: v for k, v in cell.items() if k != "overrides"},
                  "overrides": cell["overrides"], **fit_cell(results, contract, layouts, retract)}
        records.append(record)
        print(json.dumps({k: record.get(k) for k in ("id", "parameter", "factor", "threshold_m",
                                                     "violation_rate", "censored")}), flush=True)

    nominal = next(r for r in records if r["id"] == "nominal")
    sensitivity = {}
    for name in SWEEP:
        cells_for = [r for r in records if r["parameter"] == name and r["threshold_m"] is not None]
        if not cells_for or nominal["threshold_m"] is None:
            continue
        deltas = [{"factor": r["factor"],
                   "threshold_m": r["threshold_m"],
                   "delta_m": r["threshold_m"]-nominal["threshold_m"],
                   "delta_per_unit_relative_change":
                       (r["threshold_m"]-nominal["threshold_m"])/(r["factor"]-1.0)}
                  for r in cells_for]
        worst = max(abs(d["delta_m"]) for d in deltas)
        slope = float(np.mean([d["delta_per_unit_relative_change"] for d in deltas]))
        sensitivity[name] = {
            "meaning": SWEEP[name]["meaning"], "cells": deltas,
            "worst_threshold_shift_m": worst,
            "mean_slope_m_per_unit_relative_change": slope,
            "margin_for_30_percent_tolerance_m": abs(slope)*0.3,
        }

    total = sum(abs(v["margin_for_30_percent_tolerance_m"]) for v in sensitivity.values())
    report = {
        "schema": 1, "id": "cable_transfer_protocol_v4", "created_on": contract["created_on"],
        "status": "executed_transfer_protocol",
        "scope": "Sensitivity of the fitted one-number safety threshold to the cable's own physical "
                 "properties. A PROTOCOL with exposed assumptions, not a transfer claim: there is no "
                 "hardware, no connector transfer and no force-certified safety claim here.",
        "contract": {"path": args.contract.as_posix(),
                     "content_sha256": content_sha256(ROOT / args.contract)},
        "design": {
            "layouts": [layout["id"] for layout in layouts],
            "installed_loop_m": contract["registered_support"]["installed_loop_m"][1],
            "port_mount": "compliant4000", "decision_pose": "near_seated",
            "error_level": "E0",
            "actions": len(core_actions(contract["action_design"])),
            "requests_per_cell": len(layouts)*len(core_actions(contract["action_design"])),
            "cells": len(cells),
            "note": "The zero-error level is used on purpose: this control measures the threshold's "
                    "sensitivity to the CABLE, not to the observation, and mixing the two would "
                    "make neither readable.",
        },
        "nominal": nominal, "cells": records, "sensitivity": sensitivity,
        "engineering_statement": {
            "reading": "For a cable whose swept property is known only to plus or minus thirty "
                       "percent, carry at least the margin listed for that property. Carrying the "
                       "sum treats the tolerances as independent and simultaneous, which is "
                       "conservative.",
            "total_margin_all_properties_30_percent_m": total,
        },
        "what_stays_untested": [
            "Every number here is simulated. No hardware cable was measured, bent or pulled.",
            "The cable is a capsule chain with an isotropic elastic plugin: it has no jacket "
            "anisotropy, no braid, no temperature dependence, no ageing and no plastic set.",
            "Friction is Coulomb with fixed coefficients; stick-slip against a real jacket is not "
            "modelled.",
            "The connector's strain relief is a point equality constraint, not a moulded boot.",
            "The settling initialization is the registered five-second deadline, which "
            "evidence/cable_discretisation_v4.json shows is not a rest configuration.",
        ],
        "one_day_hardware_check_that_would_falsify_this": [
            "Measure the cable's bending stiffness by three-point bend or by hanging a known mass "
            "from a cantilevered length, and its jacket-on-steel friction coefficient on an "
            "inclined plane. Both are one-hour bench measurements.",
            "Install the same routed geometry with a real clip and strain relief, command the "
            "registered twelve core clearance actions at 20 mm/s, and record which ones release "
            "the clip.",
            "The protocol is falsified if the measured release boundary sits outside the fitted "
            "threshold plus the margin this table prescribes for the measured parameter "
            "tolerances.",
        ],
        "cost": {"wall_seconds": round(time.monotonic()-started, 1),
                 "requests": sum(r["requests"] for r in records)},
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"out": args.out.as_posix(),
                      "nominal_threshold_m": nominal["threshold_m"],
                      "margins": {k: v["margin_for_30_percent_tolerance_m"]
                                  for k, v in sensitivity.items()}}, indent=1))
    return 0


def _run(item):
    return guarded_case(*item)


if __name__ == "__main__":
    raise SystemExit(main())
