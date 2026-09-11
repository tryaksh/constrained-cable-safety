"""Build evidence/INDEX.json so an agent can pick one record without reading many.

Each entry carries the file's own declared id, status and scope, truncated. The
index is derived from the files, never hand-written, so it cannot drift into
claiming something a record does not say.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
FIELDS = ("id", "audit_id", "status", "decision", "verdict", "summary", "scope", "next_action")
LIMIT = 320


def short(value, limit: int = LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def entry(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"file": path.name, "unreadable": f"{type(exc).__name__}: {exc}"}
    record = {"file": path.name, "bytes": path.stat().st_size}
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
    index = {
        "schema": 1,
        "generated_by": "scripts/index_evidence.py",
        "purpose": ("Pick the one evidence record a question needs. Entries are derived from each file, so read the "
                    "file itself before quoting any number, and read its scope before reusing its result."),
        "count": len(files),
        "records": [entry(p) for p in files],
        "figures": sorted(p.name for p in EVIDENCE.iterdir() if p.suffix in {".png", ".pdf", ".svg", ".jpg"}),
    }
    (EVIDENCE / "INDEX.json").write_text(json.dumps(index, indent=1, allow_nan=False), encoding="utf-8")
    print(json.dumps({"records": len(files), "bytes": (EVIDENCE / "INDEX.json").stat().st_size}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
