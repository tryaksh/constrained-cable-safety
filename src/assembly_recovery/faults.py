"""Numeric peg fault support and deterministic development cases; no simulator import."""
from __future__ import annotations

import math


def validate_fault_support(support):
    bins = support["bins"]
    ids = [b["id"] for b in bins]
    if len(ids) != len(set(ids)) or not bins:
        raise ValueError("Fault bin identifiers must be nonempty and unique")
    for item in bins:
        if item["family"] not in {"nominal", "lateral_pose_bias", "approach_offset", "friction"}:
            raise ValueError("Undeclared fault family")
        low, high = item["range"]
        if not all(math.isfinite(x) for x in (low, high, item["development_value"])) or not 0 <= low <= item["development_value"] <= high:
            raise ValueError("Development value must lie inside finite nonnegative bin")
        if item["family"] in {"lateral_pose_bias", "approach_offset"} and high > 0.01:
            raise ValueError("Fault range exceeds the declared 10 mm development envelope")
    return bins


def development_cases(study, seed):
    if seed not in study["splits"]["development_seeds"]:
        raise ValueError("Only declared development seeds may enter this validation matrix")
    support = study["fault_support"]
    cases = []
    for item in validate_fault_support(support):
        for direction, xy in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
            value = item["development_value"]
            case = {"case_id": f"dev-{seed}-{item['id']}-{direction}", "split": "development", "seed": seed,
                    "bin_id": item["id"], "family": item["family"], "direction_index": direction,
                    "fixture_bias_xy_m": [0.0, 0.0], "approach_xy_m": [0.0, 0.0],
                    "fixed_static_friction": support["nominal"]["fixed_static_friction"],
                    "fixed_dynamic_friction": support["nominal"]["fixed_dynamic_friction"]}
            if item["family"] == "lateral_pose_bias":
                case["fixture_bias_xy_m"] = [value * a for a in xy]
            elif item["family"] == "approach_offset":
                case["approach_xy_m"] = [value * a for a in xy]
            elif item["family"] == "friction":
                case["fixed_static_friction"] = value
            cases.append(case)
    return cases


def assert_training_case(study, seed, case):
    """Reject explicit development/test cases and reserved multi-fault combinations."""
    if seed not in study["training"]["seeds"] or case.get("split") != "training":
        raise ValueError("Training cannot consume development/test seeds or cases")
    if case.get("seed") != seed or not str(case.get("case_id", "")).startswith("train-"):
        raise ValueError("Training case identity does not match its declared split/seed")
    bins = {b["id"]: b for b in validate_fault_support(study["fault_support"])}
    if case.get("bin_id") not in bins:
        raise ValueError("Training case uses an undeclared bin")
    for key in ("fixture_bias_xy_m", "approach_xy_m"):
        if len(case[key]) != 2 or not all(math.isfinite(x) for x in case[key]):
            raise ValueError("Fault offsets require two finite coordinates")
    active = sum((math.hypot(*case["fixture_bias_xy_m"]) > 0,
                  math.hypot(*case["approach_xy_m"]) > 0,
                  case["fixed_static_friction"] != study["fault_support"]["nominal"]["fixed_static_friction"]))
    if active > 1:
        raise ValueError("Multi-fault combinations are reserved and unopened")
    item = bins[case["bin_id"]]
    values = {"nominal": 0.0, "lateral_pose_bias": math.hypot(*case["fixture_bias_xy_m"]),
              "approach_offset": math.hypot(*case["approach_xy_m"]), "friction": case["fixed_static_friction"]}
    value = values[item["family"]]
    if (case.get("family") != item["family"] or not math.isfinite(value)
            or not item["range"][0] <= value <= item["range"][1]
            or case["fixed_dynamic_friction"] != study["fault_support"]["nominal"]["fixed_dynamic_friction"]
            or (item["family"] == "nominal" and active != 0)
            or (item["family"] != "nominal" and active != 1)):
        raise ValueError("Case does not match its declared numeric fault bin")


def validate_development_request(plan, *, study_sha256, settings_sha256, seed,
                                 controller, seconds, gravity, velocity):
    study = plan["study"]
    expected = development_cases(study, seed)
    if ([c for c in plan["cases"] if c["seed"] == seed] != expected
            or study_sha256 != plan["study_sha256"] or settings_sha256 != plan["retry_settings_sha256"]
            or controller not in {"retry", "continue"}
            or seconds != plan["deadline_s"] or seconds != study["job_protocol"]["deadline_seconds"]
            or gravity != study["job_protocol"]["primary_held_part_gravity"] or velocity != "corrected"):
        raise ValueError("Fault validation must match the predeclared development plan and physics profile")
