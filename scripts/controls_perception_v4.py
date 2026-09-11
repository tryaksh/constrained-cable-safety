"""Run the controls the perception contract declares, including the positive one.

Four checks, three of which can fail:

``privilege_guard_positive``  A registered request that deliberately reads a
                              scoring-only channel from inside the control window.
                              The guard must detect it and the request must fail
                              with ``privilege_violation``. A guard that never
                              fires is not evidence of anything, which is why this
                              control exists.
``privilege_guard_negative``  The same request without the probe. The guard must
                              stay silent and the request must run normally.
``v3_anchor``                 At the zero error level the estimate a controller
                              reads must be the truth, exactly, so the anchor is a
                              reproduction of the v3 interface rather than a claim
                              about one.
``declared_error_realised``   At the top level the realised socket-pose error and
                              occluded-node fraction must match what the contract
                              declares, measured against truth in the compiled
                              scene rather than asserted in prose.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from assembly_recovery.cable_constrained_v2 import build_scene, cable_centerline  # noqa: E402
from assembly_recovery.cable_perception_v4 import (  # noqa: E402
    EpisodePerception,
    PerceptionLevel,
)
from assembly_recovery.cable_study_v4 import build_cases, level_by_id, merge_runtime  # noqa: E402
from scripts.evaluate_cable_perception_v4 import guarded_case  # noqa: E402
from scripts.evaluate_cable_recovery_v2 import settle  # noqa: E402


def pick_case(runtime: dict, level_id: str) -> dict:
    return next(case for case in runtime["cases"]
                if case["error_level"] == level_id and case["error_isolation"] == "all"
                and case["action_kind"] == "core" and case["action_index"] == 5)


def privilege_controls(runtime: dict, work: Path) -> dict:
    case = dict(pick_case(runtime, "E2"))
    negative = {**case, "id": case["id"]+"__privilege_negative"}
    positive = {**case, "id": case["id"]+"__privilege_positive",
                "probe_truth_read_s": float(case["forced_macro_at_s"])+0.5}
    out = {}
    for name, selected in (("privilege_guard_negative", negative),
                           ("privilege_guard_positive", positive)):
        result = guarded_case(runtime, selected, work / selected["id"])
        guard = result["privilege_guard"]
        fired = guard["events"] > 0
        expected = name.endswith("positive")
        out[name] = {
            "case": selected["id"],
            "probe_truth_read_s": selected.get("probe_truth_read_s"),
            "privilege_guard": guard,
            "job_status": result["job"]["status"],
            "failure_reason": result["job"]["failure_reason"],
            "guard_fired": fired,
            "verdict": "pass" if fired == expected
                       and (not expected or result["job"]["failure_reason"] == "privilege_violation")
                       else "fail",
        }
    out["note"] = ("The positive control is the evidence that the guard can fire at all. A clean "
                   "guard across a whole block means nothing without it.")
    return out


def estimate_controls(runtime: dict, contract: dict, work: Path) -> dict:
    """Measure the estimate against truth in the compiled scene, per level."""
    case = pick_case(runtime, "E0")
    with tempfile.TemporaryDirectory() as directory:
        scene = build_scene(ROOT, runtime, case, Path(directory))
        # Settle first: the constructed chain is not the configuration a request
        # ever observes, and occlusion is a property of where the cable ends up.
        settle(scene, runtime)
        truth_line = np.asarray(cable_centerline(scene))
        truth_socket = np.asarray(scene.data.site_xpos[scene.port_site]).copy()
        truth_axis = np.asarray(scene.insertion_axis)
        servo_dt = 1.0/runtime["clocks"]["servo_hz"]
        camera = contract["error_model"]["camera"]
        out = {}
        for level_id in [level["id"] for level in contract["error_model"]["levels"]]:
            level = PerceptionLevel.from_dict(level_by_id(contract, level_id))
            offsets, weights = [], None
            for seed in range(24):
                perception = EpisodePerception(level, scene.fixture, camera, 91000+seed,
                                               servo_dt, len(truth_line))
                perception.advance()
                offsets.append(float(np.linalg.norm(
                    perception.socket_position(truth_socket)-truth_socket)))
                estimate, weights = perception.centreline(truth_line)
                node_error = np.linalg.norm(estimate-truth_line, axis=1)
                hidden = np.asarray(weights) > 0.5
                axis_angle = float(np.degrees(np.arccos(np.clip(
                    perception.insertion_axis(truth_axis) @ truth_axis, -1, 1))))
                record = {
                    "socket_offset_m": offsets[-1],
                    "axis_error_deg": axis_angle,
                    "occluded_node_fraction": float(hidden.mean()),
                    "occluded_node_error_m": float(node_error[hidden].mean()) if hidden.any() else 0.0,
                    "visible_node_error_m": float(node_error[~hidden].mean()) if (~hidden).any() else 0.0,
                }
            exact = (level.is_anchor
                     and np.array_equal(perception.centreline(truth_line)[0], truth_line)
                     and np.array_equal(perception.socket_position(truth_socket), truth_socket))
            out[level_id] = {
                **record,
                "declared_socket_bias_m": level.socket_bias_m,
                "declared_orientation_deg": level.socket_orientation_deg,
                "declared_occluded_m": level.centreline_occluded_m,
                "mean_socket_offset_over_24_seeds_m": float(np.mean(offsets)),
                "estimate_is_exactly_truth": bool(exact),
            }
        anchor = out["E0"]
        top = out[contract["error_model"]["levels"][-1]["id"]]
        return {
            "per_level": out,
            "v3_anchor": {
                "verdict": "pass" if anchor["estimate_is_exactly_truth"] else "fail",
                "note": "At E0 the estimate is the truth, exactly, so the anchor reproduces the v3 "
                        "privileged interface rather than approximating it.",
            },
            "declared_error_realised": {
                "verdict": "pass" if (
                    abs(top["mean_socket_offset_over_24_seeds_m"]
                        - top["declared_socket_bias_m"]) < 0.15*max(top["declared_socket_bias_m"], 1e-9)
                    and top["occluded_node_error_m"] > 3*max(top["visible_node_error_m"], 1e-12)
                    and 0.0 < top["occluded_node_fraction"] < 1.0) else "fail",
                "note": "The socket offset at the top level must match the declared bias, the "
                        "occluded nodes must carry several times the visible nodes' error, and the "
                        "occluded region must be a proper part of the cable. Occlusion is derived "
                        "from geometry, so the fraction is a property of the fixture and the "
                        "declared camera, not a tuned number.",
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs/cable_perception_v4.json"))
    parser.add_argument("--out", type=Path, default=Path("evidence/cable_perception_controls_v4.json"))
    parser.add_argument("--work-dir", type=Path, default=Path("artifacts/cable/perception-controls-v4"))
    args = parser.parse_args()

    contract = json.loads((ROOT / args.contract).read_text(encoding="utf-8-sig"))
    base = json.loads((ROOT / contract["base_config"]["path"]).read_text(encoding="utf-8-sig"))
    runtime = merge_runtime(base, contract)
    runtime["cases"] = build_cases(contract)
    work = ROOT / args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    report = {
        "schema": 1, "id": "cable_perception_controls_v4", "created_on": contract["created_on"],
        "status": "executed_controls_for_the_perception_study",
        "scope": "Controls the perception contract declares. Not a study result and not a hardware "
                 "claim.",
        "contract": args.contract.as_posix(),
        **privilege_controls(runtime, work),
        "estimate": estimate_controls(runtime, contract, work),
        "cost": {"wall_seconds": None},
    }
    report["cost"]["wall_seconds"] = round(time.monotonic()-started, 1)
    verdicts = [report["privilege_guard_positive"]["verdict"],
                report["privilege_guard_negative"]["verdict"],
                report["estimate"]["v3_anchor"]["verdict"],
                report["estimate"]["declared_error_realised"]["verdict"]]
    report["verdict"] = "pass" if all(v == "pass" for v in verdicts) else "fail"
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=float), encoding="utf-8")
    print(json.dumps({"out": args.out.as_posix(), "verdict": report["verdict"],
                      "checks": verdicts}, indent=1))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
