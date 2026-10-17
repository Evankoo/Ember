#!/usr/bin/env python3
"""Normalize task-card Quick Navigation to one canonical NAS link."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import json
import re
from pathlib import Path

from .workspace_paths import shared_task_root, shared_workspace_root

QUICK_NAV = re.compile(
    r"^## Quick Navigation\s*\n.*?(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
DELIVERY_FOLDER = re.compile(
    r"^delivery:\s*\n(?:(?:  .*)\n)*?  folder:\s*[\"']?([^\"'\n]+?)[\"']?\s*$",
    re.MULTILINE,
)


def normalize(text: str, workspace: Path) -> tuple[str, bool]:
    match = DELIVERY_FOLDER.search(text)
    if not match:
        return text, False
    folder = match.group(1).strip()
    target = workspace / folder
    link = f"- [打开任务文件夹](<{target.as_posix().rstrip('/')}/>)"
    section = f"## Quick Navigation\n\n{link}\n\n"
    current = QUICK_NAV.search(text)
    if current:
        updated = text[: current.start()] + section + text[current.end() :]
    else:
        heading = re.search(r"^# .+\n", text, re.MULTILINE)
        if not heading:
            return text, False
        updated = text[: heading.end()] + "\n" + section + text[heading.end() :]
    return updated, updated != text


def migrate(task_root: Path, workspace: Path, *, apply: bool) -> dict[str, object]:
    changed: list[str] = []
    skipped = 0
    for state in ("active", "completed"):
        root = task_root / state
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            original = path.read_text(encoding="utf-8", errors="replace")
            updated, did_change = normalize(original, workspace)
            if did_change:
                changed.append(str(path))
                if apply:
                    path.write_text(updated, encoding="utf-8")
            elif not DELIVERY_FOLDER.search(original):
                skipped += 1
    return {
        "mode": "apply" if apply else "dry_run",
        "changed": len(changed),
        "skipped_without_delivery": skipped,
        "paths": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=shared_task_root())
    parser.add_argument("--workspace-root", type=Path, default=shared_workspace_root())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate(args.task_root, args.workspace_root, apply=args.apply),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
