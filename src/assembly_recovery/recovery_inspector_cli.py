"""Command-line interface for the offline recovery decision inspector."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assembly_recovery.recovery_inspector import InvalidRequest, RecoveryInspector, request_from_demo


def read_json(path):
    def reject_constant(value):
        raise InvalidRequest(f"JSON contains nonfinite constant {value}")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidRequest(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    text = sys.stdin.read() if str(path) == "-" else Path(path).read_text(encoding="utf-8-sig")
    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


def format_report(report):
    lines = ["Recovery decision inspector", f"Request: {report['request_id']}",
             "Policy: most remaining headroom (registered conservative supervisor)", "",
             " idx   move mm   room mm   fitted rule   clip budget spent"]
    for candidate in report["candidates"]:
        room = candidate["headroom_m"]
        fraction = candidate["budget"].get("C1_clip", {}).get("spent_fraction")
        room_text = "n/a" if room is None else f"{room * 1000:.2f}"
        fraction_text = "n/a" if fraction is None else f"{fraction:.1%}"
        lines.append(f" {candidate['index']:>3}   {candidate['magnitude_m'] * 1000:>7.2f}"
                     f"   {room_text:>7}   {candidate['rule_status']:<11}   {fraction_text:>8}")
    lines.append("")
    for name, policy in report["policies"].items():
        choice = "abstain" if policy["abstained"] else f"candidate {policy['action_index']}"
        lines.append(f"{name}: {choice} ({policy['reason']})")
    lines.extend(["", f"Fit geometry: {report['scope']['fit_geometry']}.",
                  "Advisory only. A fitted-rule pass is not a physical safety guarantee.",
                  "All budgets are metres of endpoint-distance headroom, including bend and anchor proxies."])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect a recovery decision without MuJoCo or Torch.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="inspect a committed first-decision estimate")
    group.add_argument("--input", type=str, help="request JSON path, or - for stdin")
    group.add_argument("--write-example", type=Path, help="write a complete editable request JSON")
    parser.add_argument("--level", choices=("E0", "E2", "E4"), default="E0")
    parser.add_argument("--repository", type=Path, default=Path.cwd(), help="checkout holding the evidence and configs")
    parser.add_argument("--json", action="store_true", help="emit strict JSON to stdout")
    args = parser.parse_args(argv)
    try:
        if args.input:
            request = read_json(args.input)
        else:
            demo = read_json(args.repository / "artifacts/showcase/demo.json")
            request = request_from_demo(demo, args.level)
        if args.write_example:
            # Refuse accidental overwrites of user files.
            with args.write_example.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(request, indent=2, allow_nan=False) + "\n")
            print(f"Wrote {args.write_example}")
            return 0
        report = RecoveryInspector.from_repository(args.repository).inspect(request)
        print(json.dumps(report, indent=2, allow_nan=False) if args.json else format_report(report))
        return 3 if report["status"] in ("abstained", "unscored") else 0
    except (InvalidRequest, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"schema": 1, "status": "invalid_request", "error": str(error)}, allow_nan=False)
              if args.json else f"Cannot inspect: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
