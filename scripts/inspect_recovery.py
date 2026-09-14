"""Run the recovery inspector directly from a checkout."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from assembly_recovery.recovery_inspector_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["--repository", str(ROOT), *sys.argv[1:]]))
