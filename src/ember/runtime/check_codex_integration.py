#!/usr/bin/env python3
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import json
import sys
from pathlib import Path

from . import ember_agent

ROOT = _deployment_root()
MANIFEST = ROOT / "skills" / "manifest.json"
CODEX_SKILLS = ROOT / ".agents" / "skills"


def main() -> int:
    errors: list[str] = []

    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Ember Codex integration: FAIL\n- cannot read skill manifest: {exc}")
        return 1

    expected: set[str] = set()
    for entry in manifest.get("skills", []):
        name = entry.get("name", "")
        path = entry.get("path", "")
        if not name or not path:
            errors.append(f"invalid manifest entry: {entry!r}")
            continue

        source = ROOT / "skills" / path
        if source.name != "SKILL.md":
            errors.append(f"manifest path must end in SKILL.md: {path}")
            continue

        expected.add(name)
        link = CODEX_SKILLS / name
        if not link.is_symlink():
            errors.append(f"missing skill symlink: {link}")
            continue
        if link.resolve() != source.parent.resolve():
            errors.append(f"wrong skill target: {link} -> {link.resolve()}")

    if CODEX_SKILLS.is_dir():
        extra = {
            item.name
            for item in CODEX_SKILLS.iterdir()
            if item.name not in expected
        }
        for name in sorted(extra):
            errors.append(f"unregistered Codex skill entry: {CODEX_SKILLS / name}")
    else:
        errors.append(f"missing Codex skill directory: {CODEX_SKILLS}")

    agent_registry = ROOT / "config" / "agents.json"
    try:
        runtime_agents = json.loads(agent_registry.read_text(encoding="utf-8")).get("runtime_agents", {})
    except (OSError, json.JSONDecodeError) as exc:
        runtime_agents = {}
        errors.append(f"cannot read runtime Agent registry: {exc}")
    for agent_id in runtime_agents:
        errors.extend(ember_agent.validate_agent(agent_id))

    if errors:
        print("Ember Codex integration: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Ember Codex integration: PASS")
    print(f"- {len(expected)} canonical Ember skills exposed to Codex")
    print(f"- {len(runtime_agents)} canonical Ember runtime Agents validated")
    print(f"- source of truth: {ROOT / 'skills'}")
    print(f"- discovery layer: {CODEX_SKILLS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
