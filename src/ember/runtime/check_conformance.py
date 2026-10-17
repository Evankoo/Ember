#!/usr/bin/env python3
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import json
import re
import sys
from pathlib import Path

from . import gstudio_agent

ROOT = _deployment_root()
SKILL_CATEGORIES = {
    "archive", "content-production", "core-governance", "research-knowledge",
    "social-data", "system-maintenance", "video-processing", "voice-multimodal",
    "feishu-integration",
}
SKILL_KINDS = {
    "backend-adapter", "foundation", "governance", "intake-router",
    "pipeline-step", "provider-adapter", "reporting", "router", "user-entry",
}
SKILL_VISIBILITY = {"primary", "secondary", "component", "disabled", "system"}
SKILL_CATALOG_KEYS = {
    "display_name", "category", "kind", "parent_skill", "visibility", "health_profile",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def frontmatter(text: str) -> tuple[dict[str, str], bool]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, False
    keys: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return keys, True
        if line and not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            keys[key.strip()] = value.strip().strip('"')
    return keys, False


def has_nested_key(text: str, parent: str, child: str) -> bool:
    pattern = re.compile(rf"^{re.escape(parent)}:\s*$\n(?:(?:  .*\n)*)", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return False
    return re.search(rf"^  {re.escape(child)}:", match.group(0), re.MULTILINE) is not None


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    required_root = [
        "AGENTS.md",
        "README.md",
        "RESOLVER.md",
        "SYSTEM_BOUNDARIES.md",
        "schema.md",
        "HEALTHCHECK.md",
        "GIT_SYNC.md",
        "config/README.md",
        "config/agents.json",
        "config/task-routing.json",
        "agents/AGENT_STANDARD.md",
        "skills/manifest.json",
        "skills/RESOLVER.md",
        "scripts/check_conformance.py",
        "scripts/check_codex_integration.py",
        "scripts/doctor.py",
        "scripts/gstudio_task.py",
        "scripts/gstudio_agent.py",
        "scripts/task_gate.py",
    ]
    for rel in required_root:
        if not (ROOT / rel).exists():
            errors.append(f"missing root file: {rel}")

    required_readmes = [
        "tasks/README.md",
        "task-cards/README.md",
        "handoffs/README.md",
        "outputs/README.md",
        "ebrain-writeback/README.md",
        "logs/README.md",
        "templates/README.md",
        "uploads/README.md",
        "tmp/README.md",
    ]
    for rel in required_readmes:
        if not (ROOT / rel).exists():
            errors.append(f"missing directory README: {rel}")

    forbidden_output = ROOT / "output"
    if forbidden_output.exists() and any(forbidden_output.iterdir()):
        errors.append(
            "forbidden non-empty directory: output/ "
            "(use outputs/drafts/<task_id>/ or the iCloud GStudio delivery root)"
        )

    manifest_path = ROOT / "skills/manifest.json"
    resolver_path = ROOT / "skills/RESOLVER.md"
    local_skill_names: set[str] = set()
    if manifest_path.exists():
        try:
            manifest = json.loads(read(manifest_path))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid skills/manifest.json: {exc}")
            manifest = {"skills": []}
        resolver = read(resolver_path) if resolver_path.exists() else ""
        for skill in manifest.get("skills", []):
            path = skill.get("path", "")
            name = skill.get("name", "")
            if name:
                local_skill_names.add(name)
            if not path:
                errors.append(f"manifest skill missing path: {name}")
                continue
            missing_catalog = sorted(SKILL_CATALOG_KEYS - set(skill))
            if missing_catalog:
                errors.append(f"manifest skill missing catalog fields: {name} -> {', '.join(missing_catalog)}")
            if skill.get("category") not in SKILL_CATEGORIES:
                errors.append(f"manifest skill has invalid category: {name} -> {skill.get('category')}")
            if skill.get("kind") not in SKILL_KINDS:
                errors.append(f"manifest skill has invalid kind: {name} -> {skill.get('kind')}")
            if skill.get("visibility") not in SKILL_VISIBILITY:
                errors.append(f"manifest skill has invalid visibility: {name} -> {skill.get('visibility')}")
            if not str(skill.get("display_name") or "").strip():
                errors.append(f"manifest skill missing display_name: {name}")
            if not str(skill.get("health_profile") or "").strip():
                errors.append(f"manifest skill missing health_profile: {name}")
            skill_path = ROOT / "skills" / path
            if not skill_path.exists():
                errors.append(f"manifest path missing: skills/{path}")
                continue
            skill_text = read(skill_path)
            skill_frontmatter, closed = frontmatter(skill_text)
            if not closed:
                errors.append(f"skill frontmatter not closed: skills/{path}")
            elif skill_frontmatter.get("name") != name:
                errors.append(f"skill frontmatter name mismatch: {name} -> {skill_frontmatter.get('name')}")
            if closed:
                required_frontmatter = {"name", "version", "description", "triggers", "tools", "mutating", "writes_pages"}
                missing_frontmatter = sorted(required_frontmatter - set(skill_frontmatter))
                required_headings = ("Contract", "When to Use", "References", "Phases", "Output Format", "Anti-Patterns", "Tools Used")
                missing_headings = [heading for heading in required_headings if not re.search(rf"^## {re.escape(heading)}\s*$", skill_text, re.MULTILINE)]
                if missing_frontmatter or missing_headings:
                    details = []
                    if missing_frontmatter:
                        details.append("frontmatter=" + ",".join(missing_frontmatter))
                    if missing_headings:
                        details.append("sections=" + ",".join(missing_headings))
                    warnings.append(f"skill structure pending: {name} ({'; '.join(details)})")
            resolver_ref = f"skills/{path}"
            parent = str(skill.get("parent_skill") or "")
            grouped_route = bool(parent and f"skills/{parent}/SKILL.md" in resolver)
            if resolver_ref not in resolver and not grouped_route:
                errors.append(f"resolver missing manifest skill: {resolver_ref}")
        for skill in manifest.get("skills", []):
            name = str(skill.get("name") or "")
            parent = skill.get("parent_skill")
            if parent and parent not in local_skill_names:
                errors.append(f"manifest skill references unknown parent: {name} -> {parent}")
            if parent == name:
                errors.append(f"manifest skill cannot parent itself: {name}")

    codex_skill_root = ROOT / ".agents" / "skills"
    if not codex_skill_root.is_dir():
        errors.append("missing Codex repo skill root: .agents/skills")
    else:
        for name in sorted(local_skill_names):
            link = codex_skill_root / name
            expected = ROOT / "skills" / name
            if not link.is_symlink():
                errors.append(f"Codex skill entry is not a symlink: .agents/skills/{name}")
                continue
            if link.resolve() != expected.resolve():
                errors.append(
                    f"Codex skill symlink target mismatch: .agents/skills/{name} "
                    f"-> {link.resolve()}"
                )

    agents: dict = {}
    runtime_agents: dict = {}
    routing: dict = {}
    for rel, target in [
        ("config/agents.json", "agents"),
        ("config/task-routing.json", "routing"),
    ]:
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            parsed = json.loads(read(path))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid {rel}: {exc}")
            continue
        if target == "agents":
            agents = parsed.get("routing_roles", {})
            runtime_agents = parsed.get("runtime_agents", {})
        else:
            routing = parsed.get("task_types", {})

    for role, policy in agents.items():
        profile = policy.get("hermes_profile")
        lanes = policy.get("allowed_lanes", [])
        if not profile:
            errors.append(f"agent role missing hermes_profile: {role}")
        if not lanes:
            errors.append(f"agent role missing allowed_lanes: {role}")
        for skill_name in policy.get("local_skills", []):
            if skill_name not in local_skill_names:
                errors.append(f"agent role references unknown local skill: {role} -> {skill_name}")

    for agent_id in runtime_agents:
        errors.extend(gstudio_agent.validate_agent(agent_id))

    for task_type, route in routing.items():
        owner = route.get("owner")
        lane = route.get("lane")
        if owner not in agents:
            errors.append(f"task route references unknown owner: {task_type} -> {owner}")
            continue
        if lane not in agents[owner].get("allowed_lanes", []):
            errors.append(f"task route lane not allowed for owner: {task_type} -> {owner}/{lane}")
        for collaborator in route.get("collaborators", []):
            if collaborator not in agents:
                errors.append(f"task route references unknown collaborator: {task_type} -> {collaborator}")
        for skill_name in route.get("skills", []):
            if skill_name not in local_skill_names:
                errors.append(f"task route references unknown local skill: {task_type} -> {skill_name}")
        runtime_agent = route.get("runtime_agent")
        if runtime_agent and runtime_agent not in runtime_agents:
            errors.append(f"task route references unknown runtime Agent: {task_type} -> {runtime_agent}")
        for external_skill in route.get("external_skills", []):
            if not re.fullmatch(r"[a-z0-9-]+:[a-z0-9-]+", str(external_skill)):
                errors.append(f"task route has invalid external Skill reference: {task_type} -> {external_skill}")

    if errors:
        print("GStudio conformance: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("GStudio conformance: PASS")
    print("Checked root specs, routing roles, runtime Agents, adapters, and Skill catalog.")
    if warnings:
        print(f"Skill structure warnings: {len(warnings)}")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
