#!/usr/bin/python3
"""Read-only audit of the installed menu against compatibility.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import menu_adapter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("/usr/share/omarchy/default/omarchy/omarchy-menu.jsonc"),
    )
    parser.add_argument(
        "--compatibility", type=Path, default=PROJECT_ROOT / "compatibility.json"
    )
    args = parser.parse_args()

    source = menu_adapter.load_source(args.source)
    compatibility = json.loads(args.compatibility.read_text(encoding="utf-8"))
    report = menu_adapter.audit_inventory(source, compatibility)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
