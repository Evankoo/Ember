#!/usr/bin/env python3
"""Separate historical task executors from model metadata without guessing."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import json
import re
from pathlib import Path

from .workspace_paths import shared_task_root

EXECUTOR_ALIASES = {
    "codex": "codex",
    "opencode": "opencode",
    "kimi": "opencode",
    "kimi code cli": "opencode",
    "external-mcp": "external",
}
NON_MODEL_VALUES = {"single", "single_agent", "direct", "default", "legacy-unspecified"}


def _frontmatter(text: str) -> tuple[str, str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    return text[:4], text[4:end], text[end:]


def normalize(text: str) -> tuple[str, bool, str]:
    parts = _frontmatter(text)
    if not parts:
        return text, False, "no_frontmatter"
    prefix, frontmatter, suffix = parts
    model_match = re.search(r"^execution_model:\s*(.*?)\s*$", frontmatter, re.MULTILINE)
    if not model_match:
        return text, False, "no_model"
    raw = model_match.group(1).strip().strip("\"'")
    normalized = raw.lower()
    executor = EXECUTOR_ALIASES.get(normalized)
    remove_model = bool(executor or normalized in NON_MODEL_VALUES)
    if not remove_model:
        return text, False, "model_preserved"
    updated = re.sub(
        r"^execution_model:\s*.*\n?",
        "",
        frontmatter,
        count=1,
        flags=re.MULTILINE,
    )
    if executor and not re.search(r"^executor:\s*", updated, re.MULTILINE):
        status = re.search(r"^status:\s*.*$", updated, re.MULTILINE)
        insertion = f"\nexecutor: {executor}"
        if status:
            updated = updated[: status.end()] + insertion + updated[status.end() :]
        else:
            updated += f"\nexecutor: {executor}\n"
    result = prefix + updated + suffix
    return result, result != text, "executor_moved" if executor else "placeholder_removed"


def migrate(task_root: Path, *, apply: bool) -> dict[str, object]:
    changed: list[str] = []
    reasons: dict[str, int] = {}
    for state in ("active", "completed"):
        root = task_root / state
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            original = path.read_text(encoding="utf-8", errors="replace")
            updated, did_change, reason = normalize(original)
            reasons[reason] = reasons.get(reason, 0) + 1
            if did_change:
                changed.append(str(path))
                if apply:
                    path.write_text(updated, encoding="utf-8")
    return {
        "mode": "apply" if apply else "dry_run",
        "changed": len(changed),
        "reasons": reasons,
        "paths": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=shared_task_root())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate(args.task_root, apply=args.apply),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
