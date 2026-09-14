"""Every headline number in the documents must still match the record behind it.

The expensive failure here is not a wrong measurement. It is a *right*
measurement that stopped being true and stayed in the prose. Every number in
`README.md` and `ROADMAP.md` is a hand-typed copy of a number that lives in a
JSON file, and nothing stops the two drifting apart.

So this reads the figures out of `evidence/`, `configs/` and the committed stage
records, and asserts the documents still quote them. Change a number in a record
and one of these fails and names the document.

It is deliberately narrow. Only the claims a reader takes away and a reviewer
would check are pinned, because a test that pinned every number in 40 KB of
prose would fail constantly and end up switched off.

Source-level and CPU-only: no simulator, no GPU.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def flowed(relative: str) -> str:
    """One document with its line wrapping removed.

    These files are hard-wrapped at 80 columns, so a phrase worth pinning is as
    likely as not to straddle a line break. Searching the wrapped text would
    make every check depend on where the wrap happened to fall.
    """
    return " ".join((ROOT / relative).read_text(encoding="utf-8-sig").split())


README = flowed("README.md")
ROADMAP = flowed("ROADMAP.md")
PEG = flowed("docs/PEG_INSERTION.md")


def record(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def quoted(text: str, document: str, label: str) -> None:
    assert text in document, f"{label} no longer quotes {text!r}"


# --------------------------------------------------------------------------
# Study 1 (v4): how much a check has to see
# --------------------------------------------------------------------------

#: Each row of the README's "Five ways to build the check" table: the arm as the
#: record names it, the size the table gives it, and the two false-approval rates
#: the table quotes, at perfect information and at large error.
ARMS = [
    ("B0plus", "1 number", "13%", "22%"),
    ("B2", "10 numbers", "12%", "20%"),
    ("B1", "19 numbers", "14%", "19%"),
    ("M", "28,033 numbers", "21%", "29%"),
    ("Mh", "34,689 numbers", "23%", "31%"),
]


@pytest.mark.parametrize(("arm", "size", "at_e0", "at_e4"), ARMS)
def test_the_false_approval_rates_are_quoted_as_measured(arm, size, at_e0, at_e4):
    """A check that approves a move and loses the clip anyway is the headline number."""
    levels = record("evidence/cable_perception_v4.json")["results"]["C1_clip"]["per_level"]
    for level, expected in (("E0", at_e0), ("E4", at_e4)):
        rate = levels[level]["arms"][arm]["false_safe_matched_coverage"]["rate"]
        assert f"{rate * 100:.0f}%" == expected, (
            f"{arm} at {level} now measures {rate * 100:.1f}%, and the README says {expected}"
        )
        quoted(expected, README, "README.md")
    quoted(size, README, "README.md")


def test_the_parameter_counts_are_the_ones_the_record_declares():
    """The whole comparison is cheap against expensive, so the sizes carry the point."""
    cost = record("evidence/cable_perception_v4.json")["cost_axis"]
    assert cost["B0plus"]["parameters"] == 1
    assert cost["B2"]["parameters"] == 10
    assert cost["B1"]["parameters"] == 19
    quoted(f"{cost['M']['parameters']:,} numbers", README, "README.md")
    quoted(f"{cost['Mh']['parameters']:,} numbers", README, "README.md")


def test_the_first_study_reports_the_size_it_actually_had():
    """Two columns of the table are two different denominators, and they differ."""
    v4 = record("evidence/cable_perception_v4.json")
    levels = v4["results"]["C1_clip"]["per_level"]
    quoted(f"{v4['denominator']['requests']:,} runs", README, "README.md")
    quoted(f"{levels['E0']['test_requests']:,} moves", README, "README.md")
    quoted(f"{levels['E4']['test_requests']} in the large-error column", README, "README.md")


def test_no_crossover_was_found_at_any_error_level():
    """'Nothing beats the simple one by enough' is a verdict, not a reading of a table."""
    crossover = record("evidence/cable_perception_v4.json")["crossover"]
    for constraint, block in crossover.items():
        assert block["crossover_found"] is False, constraint
        assert not any(block["force_only_beats_B0plus_by_level"].values()), constraint
    quoted("Nothing beats the simple one by enough", README, "README.md")


def test_the_network_being_worse_is_quoted_with_its_uncertainty():
    """A post-hoc difference reported without its interval would be a claim."""
    e0 = record("evidence/cable_perception_v4.json")["results"]["C1_clip"]["per_level"]["E0"]
    bootstrap = e0["bootstrap_B0plus_minus_best_rich"]
    low, high = (abs(bound) for bound in reversed(bootstrap["percentile_95_interval"]))
    assert bootstrap["mean_difference"] < 0, "the network is no longer the worse arm"
    quoted(f"about {abs(bootstrap['mean_difference']) * 100:.0f} percentage points", README,
           "README.md")
    quoted(f"plausible range {low * 100:.0f} to {high * 100:.0f}", README, "README.md")
    assert high < 1.0 and low > 0.0, "the interval now includes zero, so the wording is wrong"


def test_a_study_that_could_not_resolve_a_comparison_says_so():
    checks = record("evidence/cable_perception_v4.json")["margin_resolution_checks"]
    refused = sum(1 for check in checks.values()
                  if check["verdict"] == "refused_margin_below_resolution")
    for document, label in ((README, "README.md"), (ROADMAP, "ROADMAP.md")):
        quoted(f"{refused} of {len(checks)}", document, label)


# --------------------------------------------------------------------------
# Study 2 (v5): the same check used several times in a row
# --------------------------------------------------------------------------

#: Each cell of the README's second table is "violated of observed", so both
#: halves have to be pinned: a rate alone hides how much was censored.
SEQUENCE_ROWS = [
    ("unfiltered", "no check"),
    ("filtered", "biggest move it allows"),
    ("conservative", "most room left"),
]


@pytest.mark.parametrize(("arm", "description"), SEQUENCE_ROWS)
def test_the_sequence_table_is_quoted_as_measured(arm, description):
    results = record("evidence/cable_sequence_v5.json")["results"]
    for level in ("E0", "E2", "E4"):
        cumulative = results[f"{arm}:{level}"]["C1_clip"]["cumulative"]
        cell = f"{cumulative['violated']} of {cumulative['observed']}"
        assert cell in README, f"README.md does not quote {cell} for the {description} row"


def test_the_unfiltered_arm_lost_the_cable_every_time():
    """The one unambiguous win in the project, so it is stated as a count."""
    results = record("evidence/cable_sequence_v5.json")["results"]
    total = sum(results[f"unfiltered:{level}"]["C1_clip"]["cumulative"]["violated"]
                for level in ("E0", "E2", "E4"))
    assert total == 240
    for document, label in ((README, "README.md"), (ROADMAP, "ROADMAP.md")):
        quoted(f"{total} runs", document, label)


def test_the_second_study_reports_its_size():
    denominator = record("evidence/cable_sequence_v5.json")["denominator"]
    quoted(f"{denominator['requests']} runs", README, "README.md")
    quoted(f"{denominator['decisions_offered']:,} decisions", README, "README.md")


def test_the_clip_budget_decay_is_quoted_where_it_is_claimed():
    """v5's only registered prediction that came out wrong in a useful direction."""
    verdicts = record("evidence/cable_sequence_v5.json")["verdicts"]
    rise = verdicts["C1_clip"]["per_level"]["E4"]["rise"]
    assert verdicts["C1_clip"]["per_level"]["E4"]["rises_by_more_than_margin"] is True
    quoted(f"{rise:.3f}", ROADMAP, "ROADMAP.md")


# --------------------------------------------------------------------------
# Study 3 (v6): the five-clip rig
# --------------------------------------------------------------------------

ROUTING_ROWS = [
    ("unfiltered", "no check"),
    ("filtered", "biggest move it allows"),
    ("conservative", "most room left"),
]


@pytest.mark.parametrize(("arm", "description"), ROUTING_ROWS)
def test_the_routing_table_is_quoted_as_measured(arm, description):
    """Each cell is three error levels in order, and the jobs finished beside them."""
    results = record("evidence/cable_routing_v6.json")["results"]
    shares, finished, routes = [], [], 0
    for level in ("E0", "E2", "E4"):
        block = results[f"{arm}:{level}"]
        shares.append(f"{block['clips']['routes_losing_any_required_clip'] / block['routes']:.3f}")
        finished.append(str(block["routes_completed"]))
        routes += block["routes"]
    assert " / ".join(shares) in README, (
        f"README.md does not quote the clip-loss shares for the {description} row: "
        f"{' / '.join(shares)}"
    )
    assert " / ".join(finished) in README, (
        f"README.md does not quote the jobs finished for the {description} row: "
        f"{' / '.join(finished)}"
    )
    quoted(f"{routes} jobs per row", README, "README.md")


def test_the_check_made_no_difference_by_the_margin_fixed_in_advance():
    """The three gaps are the finding, so they are quoted with their signs."""
    verdict = record("evidence/cable_routing_v6.json")["verdicts"]
    p1 = verdict["p1_filter_earns_its_place_over_a_route"]
    assert p1["held"] is False and not any(p1["by_level"].values())
    for level, sign in (("E0", "+"), ("E2", "+"), ("E4", "−")):
        quoted(f"{sign}{abs(p1['gaps'][level]):.3f}", README, "README.md")
        quoted(f"{sign}{abs(p1['gaps'][level]):.3f}", ROADMAP, "ROADMAP.md")
    margin = record("configs/cable_routing_v6.json")["decision_rule"]["margin"]
    assert all(abs(gap) < margin for gap in p1["gaps"].values()), (
        "a gap now exceeds the registered margin, so 'no difference' is the wrong reading"
    )


def test_the_ranking_result_is_quoted_with_both_denominators():
    """The one v6 prediction that held, and the one claim that survived transfer."""
    results = record("evidence/cable_routing_v6.json")["results"]
    conservative = 0
    for level in ("E0", "E2", "E4"):
        block = results[f"conservative:{level}"]
        quoted(f"{block['routes_completed']} of {block['routes']}", README, "README.md")
        conservative += block["routes_completed"]
    greedy = sum(results[f"{arm}:{level}"]["routes"]
                 for arm in ("filtered", "unfiltered") for level in ("E0", "E2", "E4"))
    assert sum(results[f"{arm}:{level}"]["routes_completed"]
               for arm in ("filtered", "unfiltered") for level in ("E0", "E2", "E4")) == 0
    quoted(f"0 of {greedy:,}", README, "README.md")
    assert conservative > 0, "nothing finished at all, so there is no ranking result to report"


def test_the_clip_that_lets_go_is_named_with_its_count():
    clips = record("evidence/cable_routing_v6.json")["clips"]
    for document, label in ((README, "README.md"), (ROADMAP, "ROADMAP.md")):
        quoted(f"{clips['losses_by_clip']['c3']:,} of "
               f"{clips['routes_losing_any_required_clip']:,}", document, label)
        quoted(str(clips["losses_by_clip"]["c1"]), document, label)


def test_the_gap_the_block_was_launched_on_is_quoted_from_the_stage_record():
    """18 mm and 58 mm are pre-launch measurements and live in the block record."""
    block = record("artifacts/cell/block.json")["the_two_numbers_the_block_turns_on"]
    for document, label in ((README, "README.md"), (ROADMAP, "ROADMAP.md")):
        quoted(f"{block['what_the_cell_admits_m'] * 1000:.0f} mm", document, label)
        quoted(f"{block['what_the_filter_permits_m'] * 1000:.0f} mm", document, label)
    assert "eleven of the twelve" in block["note"], (
        "the block record no longer says how many candidate motions the filter approved"
    )
    quoted("11 of its 12", README, "README.md")


def test_the_third_study_reports_its_size_and_its_cost():
    executed = record("artifacts/cell/block.json")["executed"]
    denominator = record("evidence/cable_routing_v6.json")["denominator"]
    assert executed["routes"] == denominator["registered_routes"]
    steps = f"{executed['native_steps'] / 1e6:.1f}"
    for document, label in ((README, "README.md"), (ROADMAP, "ROADMAP.md")):
        quoted(f"{executed['routes']:,} ", document, label)
        quoted(f"{executed['decisions_offered']:,} decisions", document, label)
        quoted(f"{executed['wall_minutes']} minutes", document, label)
        assert f"{steps}M" in document or f"{steps} million" in document, (
            f"{label} does not quote the {steps} million simulation steps the block ran"
        )
    assert executed["guards"]["privilege_guard_events"] == 0
    assert executed["guards"]["mutation_guard_events"] == 0


# --------------------------------------------------------------------------
# The three limits, and what the instrument is known to do
# --------------------------------------------------------------------------


def test_the_three_limits_are_quoted_from_the_frozen_contract():
    """A limit that drifts from its contract is a limit nobody agreed to."""
    constraints = record("configs/cable_perception_v4.json")["constraints"]
    quoted(f"{constraints['C2_bend']['spec_m'] * 1000:.0f} mm", README, "README.md")
    quoted(f"{constraints['C3_anchor']['limit_n']:.2f} N", README, "README.md")
    assert "0.49 N" in constraints["C3_anchor"]["rationale"], (
        "the contract no longer states the cable's own weight, which is what 0.30 N is set against"
    )
    quoted("0.49 N", README, "README.md")


def test_the_cable_model_refines_for_the_quantity_the_threshold_uses():
    """4x refinement, the settled plug-to-clamp distance, in micrometres."""
    agreement = record("evidence/cable_discretisation_v4.json")["agreement"]
    reference_segments = agreement["reference"][0]
    row = next(r for r in agreement["rows"]
               if r["segments"] == 4 * reference_segments
               and r["physics_hz"] == agreement["reference"][1])
    assert agreement["boot_to_anchor_verdict"] == "pass"
    assert agreement["min_bend_radius_verdict"] == "fail"
    quoted(f"{row['boot_to_anchor_delta_m'] * 1e6:.1f} µm", ROADMAP, "ROADMAP.md")


def test_the_cable_is_not_at_rest_at_the_settling_deadline():
    """A definition, not an approximation, and the number says how far past it is."""
    probe = record("evidence/cable_discretisation_v4.json")["long_settle_probe"][0]
    assert probe["at_v3_five_second_deadline"]["clip_retained"] is True
    assert probe["lateral_wall_gap_m"] < 0, "the cable now settles inside the test, not past it"
    quoted(f"{abs(probe['lateral_wall_gap_m']) * 1e6:.1f} µm", ROADMAP, "ROADMAP.md")


def test_nothing_was_graded_twice_without_the_comparison_count():
    replay = record("evidence/cable_perception_replay_v4.json")
    comparisons = replay["C1_clip"]["tested"] + replay["C3_anchor"]["tested"]
    assert replay["C1_clip"]["disagree"] == 0 and replay["C3_anchor"]["disagree"] == 0
    for document, label in ((README, "README.md"), (ROADMAP, "ROADMAP.md")):
        quoted(f"{comparisons:,} comparisons", document, label)
        quoted(f"{replay['requests_replayed']:,}", document, label)


def test_the_throughput_numbers_come_from_the_pilot_that_measured_them():
    """ROADMAP owns what the instrument does, so only it quotes these."""
    measured = record("evidence/cable_perception_pilot_v4.json")["throughput_finding"]["measured"]
    for number in ("44,966", "28,086"):
        assert number in measured, f"the pilot record no longer measures {number}"
        quoted(number, ROADMAP, "ROADMAP.md")


def test_the_friction_sensitivity_is_quoted_with_the_threshold_it_moves():
    transfer = record("evidence/cable_transfer_protocol_v4.json")
    nominal_mm = transfer["nominal"]["threshold_m"] * 1000
    friction_mm = transfer["sensitivity"]["friction"]["margin_for_30_percent_tolerance_m"] * 1000
    bending_mm = (transfer["sensitivity"]["youngs_modulus_pa"]
                  ["margin_for_30_percent_tolerance_m"] * 1000)
    quoted(f"{nominal_mm:.1f} mm", ROADMAP, "ROADMAP.md")
    quoted(f"{friction_mm:.1f} mm", ROADMAP, "ROADMAP.md")
    quoted(f"{bending_mm:.1f} mm", ROADMAP, "ROADMAP.md")


def test_the_rig_was_chosen_by_a_screen_that_kept_its_rejections():
    screen = record("evidence/cable_cell_screen_v6.json")
    assert screen["accepted_cells"] + screen["rejected_cells"] == screen["screened_cells"]
    quoted(f"{screen['rejected_cells']} of {screen['screened_cells']}", README, "README.md")
    quoted(f"{screen['accepted_cells']} accepted, {screen['rejected_cells']} rejected",
           ROADMAP, "ROADMAP.md")
    quoted(str(screen["screened_cells"]), ROADMAP, "ROADMAP.md")


def test_the_drawn_rig_is_quoted_from_the_cad_record():
    cad = record("evidence/cable_cell_cad_v6.json")
    assert cad["all_watertight"] and cad["all_single_solid"]
    quoted(f"{len(cad['parts'])} parts", ROADMAP, "ROADMAP.md")
    quoted(f"{cad['total_facets']:,} facets", ROADMAP, "ROADMAP.md")


def test_the_undecided_study_is_still_reported_as_undecided():
    decision = record("evidence/cable_repair_boundary_v3.json")["decision"]
    text = json.dumps(decision).lower()
    assert "unresolvable" in text or "undecid" in text, decision
    quoted("Undecidable as asked", ROADMAP, "ROADMAP.md")


#: The three studies that registered predictions, and the ROADMAP row each one
#: keeps its score in. v3 registered none: it asked where a boundary sat, not
#: what the answer would be.
SCORED_STUDIES = ("v4", "v5", "v6")


def test_the_prediction_scoreboard_adds_up():
    """Nine predictions, three right — three studies at one of three each.

    Only v6 records its own score in a machine-readable field, so that one is
    checked against the record and the other two against the rows that carry
    them. What this defends is the arithmetic: change a row to 2 of 3 and the
    README's "nine predictions, three right" stops being true, and this fails.
    """
    routing = record("evidence/cable_routing_v6.json")["verdicts"]
    assert (routing["correct"], routing["of"]) == (1, 3), routing
    for study in SCORED_STUDIES:
        assert f"| **{study}** |" in ROADMAP, f"ROADMAP.md has no row for {study}"
    scored = ROADMAP.count("1 of 3")
    assert scored == len(SCORED_STUDIES), (
        f"{scored} study rows say 1 of 3, so the scoreboard is no longer "
        f"{len(SCORED_STUDIES)} of {3 * len(SCORED_STUDIES)}")
    quoted("Nine", README, "README.md")
    quoted("three were right", README, "README.md")
    wrong = 3 * len(SCORED_STUDIES) - len(SCORED_STUDIES)
    assert f"The {wrong} that were wrong" in README or "The six that were wrong" in README, (
        f"README.md does not say that {wrong} predictions were wrong")


def test_the_captions_quote_the_numbers_their_figures_were_drawn_from():
    """A caption is prose next to a picture, and drifts exactly like any other."""
    v2 = record("evidence/cable_recovery_block_v2.json")["measured_task_constants"]
    quoted(f"{v2['clip_release_travel_m'] * 1000:.1f} mm of travel", README, "README.md")
    quoted(f"{v2['anchor_reaction_at_release_n']:.2f} N", README, "README.md")

    v3 = record("evidence/cable_repair_boundary_v3.json")
    quoted(f"all {v3['denominator']['requests']:,} runs", README, "README.md")

    retention = record("evidence/cable_retention_v1.json")["summary"]
    assert retention["positive_load_extraction_contact_exactly_zero_in_all_native_"
                     "and_forward_samples"] is True
    quoted(f"{retention['seating_passed']} trials seated", README, "README.md")
    quoted(f"{retention['positive_load_trials']} that were then pulled", README, "README.md")
    for load in retention["net_extraction_loads_n"]:
        if load:
            quoted(f"{load:g} N", README, "README.md")
    quoted(f"{retention['seating_tolerance_m'] * 1000:.0f} mm seating region",
           README, "README.md")


def test_the_cable_itself_is_described_as_the_contract_describes_it():
    """Its diameter sets the bend limit and its node count sets what a network reads."""
    contract = record("configs/cable_perception_v4.json")
    assert "4 mm OD" in contract["constraints"]["C2_bend"]["rationale"]
    quoted("4 mm across", README, "README.md")
    nodes = len(record("artifacts/showcase/demo.json")["levels"]["E0"]["decision"]
                ["insertion_axis"]) * 8
    assert nodes == 24, "the centreline node count is no longer 24"
    quoted(f"all {nodes} estimated points", README, "README.md")


def test_what_was_built_is_reported_as_the_build_records_measured_it():
    clips = record("artifacts/showcase/video.json")["clips"]
    assert all(clip["measured"]["frames_decoded"] == clip["declared_frames"]
               for clip in clips), "a clip no longer decodes to the frame count it declares"
    frames = [str(clip["measured"]["frames_decoded"]) for clip in clips]
    quoted(", ".join(frames[:-1]) + f" and {frames[-1]} frames", ROADMAP, "ROADMAP.md")

    built = record("artifacts/showcase/page.json")["built_from"]
    assert sum(len(group) for group in built.values()) == 10
    quoted("ten committed records", ROADMAP, "ROADMAP.md")

    usd = record("artifacts/showcase/usd.json")
    assert usd["export"]["stepped_at_export_time"] is False
    quoted(f"**{usd['export']['frames_written']} frames**", ROADMAP, "ROADMAP.md")
    quoted(f"{usd['read_back']['prims']} prims", ROADMAP, "ROADMAP.md")

    isaac = record("artifacts/showcase/isaac.json")["views"]["wide"]
    quoted(f"{isaac['frames_written']} frames at "
           f"{isaac['resolution'][0]}×{isaac['resolution'][1]}", ROADMAP, "ROADMAP.md")


def test_the_workbench_test_count_is_the_number_of_tests_it_has(request):
    collected = [item for item in request.session.items
                 if "test_cable_workbench_v7" in str(item.fspath)]
    if not collected:
        pytest.skip("the workbench tests were not collected in this run")
    quoted(f"**{len(collected)} headless tests**", ROADMAP, "ROADMAP.md")


def test_the_winning_rig_won_by_the_margin_the_screen_recorded():
    screen = record("evidence/cable_cell_screen_v6.json")
    survivals = {}
    for entry in screen["accepted_cell_detail"]:
        survivals[entry["layout"]] = survivals.get(entry["layout"], 0) + 1
    best = max(survivals.values())
    others = sorted((count for layout, count in survivals.items()
                     if count != best or layout != screen["registered_cell"]), reverse=True)
    ladder = len(screen["candidates"]) if isinstance(screen["candidates"], list) else None
    assert ladder is None or best <= ladder
    quoted(f"{best} of 7 slack settings", ROADMAP, "ROADMAP.md")
    assert others, "only one candidate survived, so there is nothing to compare it against"


# --------------------------------------------------------------------------
# The peg campaign, whose numbers must never be read as cable numbers
# --------------------------------------------------------------------------


def test_the_peg_campaign_stopped_where_its_stopping_rule_said_it_would():
    comparison = record("evidence/approach_slew_comparison_v1.json")
    text = json.dumps(comparison)
    assert "8" in text, "the registered support floor is no longer in the comparison record"
    quoted("never trained and never evaluated", PEG, "docs/PEG_INSERTION.md")


def test_the_peg_policy_result_is_quoted_with_its_denominator():
    overall = record("evidence/uniform_unclipped_v4.json")
    text = json.dumps(overall)
    assert "81" in text and "84" in text, "the development result moved"
    quoted("81 of 84", PEG, "docs/PEG_INSERTION.md")


# --------------------------------------------------------------------------
# The test suite counts itself, so the README cannot quote a stale size
# --------------------------------------------------------------------------


def test_the_readme_opening_stands_on_its_own():
    """The first 150 words have to work as a summary somebody could lift whole.

    That means they must carry all four things a reader needs before they decide
    whether to keep reading: the problem, what the repository is, that it is
    simulation and not hardware, and what the studies concluded.
    """
    import re

    body = README.split("![", 1)[0]
    body = re.sub(r"^#[^A-Za-z]*Constrained-cable safety", "", body)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"[*_`]", "", body)
    words = [word for word in body.split() if any(c.isalnum() for c in word)]
    assert len(words) <= 150, (
        f"{len(words)} words run before the first figure; the opening is meant to be "
        "liftable as a 150-word summary")
    opening = " ".join(words).lower()
    for phrase, why in (
        ("clip", "the problem"),
        ("repository", "what this is"),
        ("simulation", "the one caveat that must never be dropped"),
        ("ranking", "what the studies concluded"),
    ):
        assert phrase in opening, f"the opening drops {why}"


def test_the_documents_quote_the_number_of_tests_there_actually_are(request):
    """Both documents put a test count next to the command that runs them."""
    collected = len(request.session.items)
    if collected < 100:
        pytest.skip("only part of the suite was collected, so the total is not known here")
    for relative in ("README.md", "AGENTS.md"):
        assert f"{collected} tests" in flowed(relative), (
            f"{relative} does not say there are {collected} tests"
        )
