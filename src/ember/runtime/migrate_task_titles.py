#!/usr/bin/env python3
"""Apply approved <=20-character semantic titles to active v2 task cards."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import json
import re
from pathlib import Path

from .workspace_paths import shared_workspace_root

ROOT = _deployment_root()
ACTIVE = shared_workspace_root() / "tasks" / "active"
MAPPING = ROOT / "config" / "task-title-overrides.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    invalid = {key: value for key, value in mapping.items() if len(value) > 20 or "…" in value or "..." in value}
    if invalid:
        raise SystemExit(f"invalid short titles: {invalid}")

    changed = 0
    missing: list[str] = []
    for path in sorted(ACTIVE.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        task_match = re.search(r"^task_id:\s*['\"]?([^'\"\n]+)", text, re.M)
        title_match = re.search(r"^title:\s*(.+?)\s*$", text, re.M)
        if not task_match or not title_match:
            continue
        task_id = task_match.group(1).strip()
        current = title_match.group(1).strip().strip("'\"")
        if len(current) <= 20 and "…" not in current and "..." not in current:
            continue
        replacement = mapping.get(task_id)
        if not replacement:
            missing.append(task_id)
            continue
        quoted = json.dumps(replacement, ensure_ascii=False)
        new_text = text[: title_match.start()] + f"title: {quoted}" + text[title_match.end() :]
        if new_text != text:
            changed += 1
            if not args.dry_run:
                path.write_text(new_text, encoding="utf-8")
    print(json.dumps({"dry_run": args.dry_run, "changed": changed, "missing": missing}, ensure_ascii=False, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
