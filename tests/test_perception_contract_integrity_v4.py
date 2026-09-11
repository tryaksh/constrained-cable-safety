"""The frozen contract must agree with the screen it was frozen from.

A contract can drift from the evidence that produced it in ways nothing else
catches: a layout kept that the screen rejected, a group in two splits at once, a
count that no longer matches what the request list expands to. These check that,
and they run without a simulator, a GPU or an ignored artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

from assembly_recovery.cable_study_v4 import (
    build_cases,
    build_contexts,
    check_margin_resolution,
    isolation_contexts,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "configs/cable_perception_v4.json").read_text(encoding="utf-8-sig"))
SCREEN = json.loads((ROOT / "evidence/cable_layout_screen_v4.json").read_text(encoding="utf-8-sig"))
SUPPORT = CONTRACT["registered_support"]
GROUPS = CONTRACT["groups"]


def declared_groups():
    return [f"{layout['id']}_l{int(round(loop*1000))}"
            for layout in SUPPORT["layouts"] for loop in SUPPORT["installed_loop_m"]]


def test_the_contract_is_frozen():
    assert CONTRACT["expected_requests"] != "PENDING_FREEZE"
    assert CONTRACT["base_config"]["content_sha256"] != "PENDING_FREEZE"
    assert SUPPORT["layouts"], "a frozen contract must carry its registered layouts"
    assert "PENDING_FREEZE" not in SUPPORT["selection_note"]


def test_every_registered_layout_survived_the_screen():
    accepted = set(SCREEN["registered"]["accepted_layouts"])
    for layout in SUPPORT["layouts"]:
        assert layout["id"] in accepted, layout["id"]


def test_excluded_groups_are_exactly_the_cells_the_screen_rejected():
    rejected = {row["group"] for row in SCREEN["registered"]["rejected_groups"]}
    excluded = set(SUPPORT["excluded_groups"])
    declared = set(declared_groups())
    # Every excluded group is one the screen rejected, and every rejected cell of
    # a registered layout is excluded. A rejected cell of a layout that lost all
    # its cells never reaches the contract at all.
    assert excluded <= rejected
    assert excluded == rejected & declared


def test_every_surviving_group_is_in_exactly_one_split():
    surviving = [g for g in declared_groups() if g not in set(SUPPORT["excluded_groups"])]
    splits = [set(GROUPS[key]) for key in ("train", "dev", "test")]
    union = set().union(*splits)
    assert union == set(surviving)
    for i, left in enumerate(splits):
        for right in splits[i+1:]:
            assert not left & right
    assert all(splits), "no split may be empty"


def test_the_split_delivers_the_declared_test_contexts_per_error_level():
    mounts = len(SUPPORT["port_mount"])
    poses = len(SUPPORT["decision_pose"])
    per_level = len(GROUPS["test"])*mounts*poses
    assert per_level == CONTRACT["frozen_counts"]["test_contexts_per_error_level"]
    assert per_level >= GROUPS["test_context_requirement"]
    assert check_margin_resolution(CONTRACT["decision_rule"]["margin"],
                                   [1/per_level])["verdict"] == "usable"


def test_the_frozen_counts_match_what_the_contract_expands_to():
    counts = CONTRACT["frozen_counts"]
    ladder = build_contexts(CONTRACT)
    isolation = isolation_contexts(CONTRACT)
    cases = build_cases(CONTRACT)
    assert counts["layouts"] == len(SUPPORT["layouts"])
    assert counts["ladder_contexts"] == len(ladder)
    assert counts["isolation_contexts"] == len(isolation)
    assert counts["requests"] == len(cases) == CONTRACT["expected_requests"]
    assert counts["groups"] == sum(len(GROUPS[k]) for k in ("train", "dev", "test"))


def test_no_excluded_cell_is_ever_expanded_into_a_request():
    excluded = set(SUPPORT["excluded_groups"])
    assert excluded, "the screen rejected cells, so some must be excluded"
    assert not {case["study_group"] for case in build_cases(CONTRACT)} & excluded


def test_every_error_level_appears_in_every_split():
    by_split: dict[str, set] = {}
    for context in build_contexts(CONTRACT):
        by_split.setdefault(context["split"], set()).add(context["error_level"])
    levels = {level["id"] for level in CONTRACT["error_model"]["levels"]}
    for split, seen in by_split.items():
        assert seen == levels, (split, sorted(levels-seen))


def test_the_settling_initialization_is_the_registered_one():
    # evidence/cable_discretisation_v4.json is why: a longer settle walks the
    # cable onto the retention predicate's own boundary instead of away from it.
    overrides = CONTRACT["runtime_overrides"]
    assert "settle_seconds" not in overrides
    assert "settle_gravity_ramp_s" not in overrides
    assert "settle_acceptance" not in overrides
    assert overrides["settle_note"]


def test_the_c2_spec_is_cleared_by_every_registered_cell():
    spec = CONTRACT["constraints"]["C2_bend"]["spec_m"]
    accepted = {row["group"]: row for row in SCREEN["registered"]["accepted_cell_detail"]}
    surviving = [g for g in declared_groups() if g not in set(SUPPORT["excluded_groups"])]
    for group in surviving:
        installed = accepted[group]["installed_min_bend_radius_m"]
        assert installed > spec, (group, installed)
