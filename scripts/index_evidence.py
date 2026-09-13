"""Build evidence/INDEX.json so an agent can pick one record without reading many.

Each entry carries the file's own declared id, status and scope, truncated. The
index is derived from the files, never hand-written, so it cannot drift into
claiming something a record does not say.

Records here come from two campaigns that ran on two different simulators, and
mixing their numbers up would be a serious mistake, so every entry says which
one it belongs to. The rule is mechanical and is stated in ``campaign_of``
below: filenames tell you, because the two campaigns never shared a prefix.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
FIELDS = ("id", "audit_id", "status", "decision", "verdict", "summary", "scope", "next_action")
LIMIT = 320

# Records whose names do not follow the prefix rule, listed here rather than
# guessed at. Both of these span the two campaigns: they are archives of
# documentation that described the cable and peg work together.
SHARED_RECORDS = {
    "claude_handover_v1.json",
    "roadmap_history_v1.json",
    # Named `cable_*` but it is the whole-cycle verification: it lists and hashes
    # every file in the tree at the time, which was a tree holding both projects.
    # That is why it names 178 code paths this repository does not have.
    "cable_cycle_verification_v1.json",
}

CAMPAIGNS = {
    "cable": (
        "The constrained-cable safety studies. MuJoCo, a UR5e arm, a plug whose "
        "cable is clipped to a board. This is what the repository is about; see "
        "README.md."
    ),
    "peg": (
        "The retired peg-insertion campaign. Isaac Lab and NVIDIA's FORGE, a "
        "Franka arm, a peg and a hole. Closed on 2026-09-10 by rejecting its own "
        "premise; kept because a closed negative result is still a result. See "
        "docs/PEG_INSERTION.md. Peg numbers are never cable numbers."
    ),
    "shared": "Describes both campaigns; usually an archive of retired documentation.",
}


def campaign_of(name: str) -> str:
    """Which campaign a record belongs to, from its filename alone.

    Every cable record is named ``cable_*`` or ``cell_*``; no peg record is. The
    two exceptions are listed in ``SHARED_RECORDS``.
    """
    if name in SHARED_RECORDS:
        return "shared"
    if name.startswith(("cable_", "cell_")):
        return "cable"
    return "peg"


def short(value, limit: int = LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def entry(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"file": path.name, "campaign": campaign_of(path.name), "unreadable": f"{type(exc).__name__}: {exc}"}
    record = {"file": path.name, "campaign": campaign_of(path.name), "bytes": path.stat().st_size}
    if not isinstance(data, dict):
        record["shape"] = type(data).__name__
        return record
    for field in FIELDS:
        if field in data:
            record[field] = short(data[field])
    record["top_level_keys"] = sorted(data)[:24]
    return record


def main() -> int:
    files = sorted(p for p in EVIDENCE.glob("*.json") if p.name != "INDEX.json")
    records = [entry(p) for p in files]
    counts: dict[str, int] = {}
    for record in records:
        counts[record["campaign"]] = counts.get(record["campaign"], 0) + 1
    index = {
        "schema": 2,
        "generated_by": "scripts/index_evidence.py",
        "purpose": ("Pick the one evidence record a question needs. Entries are derived from each file, so read the "
                    "file itself before quoting any number, and read its scope before reusing its result."),
        "count": len(files),
        "campaigns": CAMPAIGNS,
        "count_by_campaign": dict(sorted(counts.items())),
        "records": records,
        "figures": sorted(p.name for p in EVIDENCE.iterdir() if p.suffix in {".png", ".pdf", ".svg", ".jpg"}),
    }
    (EVIDENCE / "INDEX.json").write_text(json.dumps(index, indent=1, allow_nan=False), encoding="utf-8")
    print(json.dumps({"records": len(files), "by_campaign": index["count_by_campaign"],
                      "bytes": (EVIDENCE / "INDEX.json").stat().st_size}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
