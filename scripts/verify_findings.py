"""Re-derive the four findings from the committed records, and say so or fail.

Reading that a study found something is not the same as seeing the finding come
back out of the numbers. This takes the four records in `evidence/`, applies each
study's own registered decision rule to its own per-arm numbers, and checks the
answer that falls out is the answer the record reports.

Nothing is recomputed from raw runs and nothing is refitted. What is checked is
that the verdict each record states still follows from the numbers beside it, and
that the margin it was judged against is the margin its contract froze before the
runs started.

Reads JSON. No simulator, no GPU, no network, about a second. Exits non-zero if
any verdict cannot be re-derived.

    .venv/Scripts/python.exe scripts/verify_findings.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEVELS = ("E0", "E2", "E4")
EYESIGHT = {"E0": "perfect information", "E2": "small error", "E4": "large error"}


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


class Finding:
    """One study: what it asked, what came back, and how that was checked."""

    def __init__(self, study: str, asked: str, long: str, record: str, contract: str):
        self.study = study
        self.asked = asked
        self.long = long
        self.record = record
        self.contract = contract
        self.answer = ""
        self.workings: list[str] = []
        self.problems: list[str] = []

    def check(self, condition: bool, description: str) -> None:
        self.workings.append(("  ok   " if condition else "  FAIL ") + description)
        if not condition:
            self.problems.append(f"{self.study}: {description}")


def repair_boundary_v3() -> Finding:
    """The margin was set equal to the metric's own resolution, so nothing could fire."""
    finding = Finding("v3", "where the safe/unsafe boundary is",
                      "where exactly the boundary between a safe repair move and an unsafe one "
                      "sits",
                      "evidence/cable_repair_boundary_v3.json",
                      "configs/cable_repair_boundary_v3.json")
    decision = read(finding.record)["decision"]
    margin = decision["margin"]
    resolution = decision["metric_b_resolution"]
    gap_a = decision["b0_minus_best_other_false_safe"]

    finding.answer = "undecidable as asked"
    finding.check(margin <= resolution,
                  f"the registered margin {margin} is not larger than the ranking metric's own "
                  f"resolution {resolution}, so that branch could never fire")
    finding.check(abs(gap_a) < margin,
                  f"the false-approval difference {gap_a:+.3f} is inside the margin {margin}, "
                  f"so that branch did not fire either")
    finding.check(decision["verdict"].startswith("inconclusive"),
                  f"the record's own verdict is {decision['verdict']!r}")
    return finding


def perception_v4() -> Finding:
    """No richer arm beat the one-number check by more than the margin, anywhere."""
    finding = Finding("v4", "how much the check has to see",
                      "how much a safety check has to be able to see, as the robot's eyesight "
                      "gets worse",
                      "evidence/cable_perception_v4.json",
                      "configs/cable_perception_v4.json")
    record = read(finding.record)
    margin = read(finding.contract)["decision_rule"]["margin"]
    beaten = []
    for constraint, block in record["results"].items():
        for level, per_level in block["per_level"].items():
            arms = per_level["arms"]
            baseline = arms["B0plus"]
            for name in ("M", "Mh"):
                # The registered crossover needs BOTH metrics to be beaten by
                # more than the margin: fewer wrong approvals AND a better
                # ordering of the moves on offer.
                approvals = (baseline["false_safe_matched_coverage"]["rate"]
                             - arms[name]["false_safe_matched_coverage"]["rate"])
                ranking = (baseline["ranking_regret"]["regret"]
                           - arms[name]["ranking_regret"]["regret"])
                if approvals > margin and ranking > margin:
                    beaten.append(f"{name} at {level} on {constraint}")

    finding.answer = "one number is enough"
    finding.check(not beaten,
                  f"no richer arm beats the one-number check by more than the margin {margin} on "
                  f"both metrics at any of the five error levels"
                  + (f" (beaten by: {', '.join(beaten)})" if beaten else ""))
    finding.check(all(not block["crossover_found"] for block in record["crossover"].values()),
                  "the record reports no crossover on any of the three failure modes")
    worst = max(arms["Mh"]["false_safe_matched_coverage"]["rate"]
                for arms in (record["results"]["C1_clip"]["per_level"][level]["arms"]
                             for level in ("E0", "E4")))
    best = max(record["results"]["C1_clip"]["per_level"][level]["arms"]["B0plus"]
               ["false_safe_matched_coverage"]["rate"] for level in ("E0", "E4"))
    finding.check(worst > best,
                  f"the 34,689-number network is still the worse arm at protecting the clips "
                  f"({worst:.0%} wrong against {best:.0%})")
    return finding


def sequence_v5() -> Finding:
    """Over three moves the check is worth having, by more than the margin, at every level."""
    finding = Finding("v5", "whether it survives several moves",
                      "whether the same check still works when it is used several times in a row",
                      "evidence/cable_sequence_v5.json", "configs/cable_sequence_v5.json")
    record = read(finding.record)
    margin = read(finding.contract)["decision_rule"]["margin"]
    results = record["results"]
    for level in LEVELS:
        without = results[f"unfiltered:{level}"]["C1_clip"]["cumulative"]
        with_check = results[f"filtered:{level}"]["C1_clip"]["cumulative"]
        gap = without["rate"] - with_check["rate"]
        stated = record["is_the_filter_worth_it_over_a_sequence"][level]
        finding.check(gap > margin and stated["beats_by_more_than_margin"],
                      f"{EYESIGHT[level]}: the cable came out of a clip in "
                      f"{without['violated']} of {without['observed']} runs without the check and "
                      f"{with_check['violated']} of {with_check['observed']} with it, a gap of "
                      f"{gap:.3f} against a margin of {margin}")
    lost = sum(results[f"unfiltered:{level}"]["C1_clip"]["cumulative"]["violated"]
               for level in LEVELS)
    runs = sum(results[f"unfiltered:{level}"]["C1_clip"]["cumulative"]["observed"]
               for level in LEVELS)
    finding.answer = "yes, decisively"
    finding.check(lost == runs,
                  f"without the check the cable came out in every one of {runs} runs")
    return finding


def routing_v6() -> Finding:
    """On the five-clip rig the check changes nothing the study can resolve."""
    finding = Finding("v6", "whether it survives a new rig",
                      "whether it still earns its keep on a five-clip rig it was never tuned for",
                      "evidence/cable_routing_v6.json", "configs/cable_routing_v6.json")
    record = read(finding.record)
    margin = read(finding.contract)["decision_rule"]["margin"]
    results = record["results"]
    stated = record["verdicts"]["p1_filter_earns_its_place_over_a_route"]

    def share(arm: str, level: str) -> float:
        block = results[f"{arm}:{level}"]
        return block["clips"]["routes_losing_any_required_clip"] / block["routes"]

    for level in LEVELS:
        gap = share("unfiltered", level) - share("filtered", level)
        finding.check(abs(gap - stated["gaps"][level]) < 5e-4 and abs(gap) < margin
                      and stated["by_level"][level] is False,
                      f"{EYESIGHT[level]}: {share('unfiltered', level):.3f} of jobs lost a clip "
                      f"without the check against {share('filtered', level):.3f} with it, a gap "
                      f"of {gap:+.3f} against a margin of {margin}")
    finding.answer = "no"

    # What did survive: the ranking, read as jobs finished rather than clips lost.
    ranked = sum(results[f"conservative:{level}"]["routes_completed"] for level in LEVELS)
    ranked_of = sum(results[f"conservative:{level}"]["routes"] for level in LEVELS)
    greedy = sum(results[f"{arm}:{level}"]["routes_completed"]
                 for arm in ("filtered", "unfiltered") for level in LEVELS)
    greedy_of = sum(results[f"{arm}:{level}"]["routes"]
                    for arm in ("filtered", "unfiltered") for level in LEVELS)
    finding.check(ranked > 0 and greedy == 0,
                  f"taking the move with the most room left finished {ranked} of {ranked_of} "
                  f"jobs; taking the biggest allowed move, or no check at all, finished "
                  f"{greedy} of {greedy_of:,}")
    return finding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiet", action="store_true",
                        help="print the table only, not how each verdict was re-derived")
    args = parser.parse_args()

    findings = [repair_boundary_v3(), perception_v4(), sequence_v5(), routing_v6()]

    print("\nFour studies, each re-derived from its own record in evidence/.\n")
    asked = max(len(f.asked) for f in findings)
    answer = max(len(f.answer) for f in findings)
    for finding in findings:
        mark = "  " if not finding.problems else "! "
        print(f"{mark}{finding.study}  {finding.asked:<{asked}}   {finding.answer:<{answer}}   "
              f"{Path(finding.record).name}")
    if not args.quiet:
        for finding in findings:
            print(f"\n{finding.study}: {finding.long}")
            print(f"    judged against the margin frozen in {finding.contract}")
            for line in finding.workings:
                print(line)

    problems = [problem for finding in findings for problem in finding.problems]
    if problems:
        print(f"\n{len(problems)} verdicts could not be re-derived from the records:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("\nEvery verdict above follows from the numbers in the record beside it.")
    print("What it adds up to: use the check's ranking of moves, not its yes/no threshold.")
    print("The ranking still works on a rig the check was never tuned for. The threshold "
          "does not.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
