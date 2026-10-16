"""Copy a pre-0.11 single-folder workspace into the system folder + document library layout.

The old folder is only read. Nothing is moved or deleted there; a failure leaves the
new folders in place for inspection and the old workspace unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .store import (DRAFT, FORMAL, INBOX, INBOX_LEDGER, INPUTS, REPORTS, VIEWS, Workspace, WorkspaceError,
                    _parse_markdown, _render_markdown, _sections, _tree, project_card, visible)

LEGACY_PREFIXES = (("delivery/draft", DRAFT), ("delivery/formal", FORMAL), ("inputs", INPUTS),
                   ("inbox", INBOX), ("reports", REPORTS))
# Product rules and Skills are reinstalled from this version; their old copies name old paths.
REGENERATED = ("AGENTS.md", "SOUL.md", "RESOLVER.md", "WORKBENCH_DESIGN.md", "templates", "skills", ".agents")
SKIPPED = (".ember/service.lock", ".ember/projects.lock")


def legacy_path(value):
    """New library-relative name of an old workspace-relative locator; other text is returned unchanged."""
    if not isinstance(value, str):
        return value
    for old, new in LEGACY_PREFIXES:
        if value == old or value.startswith(old + "/"):
            return new + value[len(old):]
    return value


def target_name(relative: str) -> str | None:
    """Where an old file belongs in the new layout; None for files this version regenerates."""
    parts = relative.split("/")
    if relative in SKIPPED or parts[0] in REGENERATED:
        return None
    if relative == ".ember/views.json":
        return VIEWS
    if relative == ".ember/inbox.json":
        return INBOX_LEDGER
    if parts[0] == "projects" and len(parts) == 2 and relative.endswith(".md"):
        return project_card(parts[1][:-3])
    if relative in ("MEMORY.md", "config/projects.json", "config/workspace.json") or parts[0] in ("tasks", "archive"):
        return relative
    moved = legacy_path(relative)
    if moved != relative:
        return moved
    raise WorkspaceError(f"旧工作区含未识别的文件，未迁移：{relative}。请先人工核对。")


def _task_card(text: str, source: str) -> str:
    metadata, body = _parse_markdown(text, source)
    delivery = metadata.get("delivery")
    if isinstance(delivery, dict) and "folder" in delivery:
        delivery["folder"] = legacy_path(delivery["folder"])
    if isinstance(metadata.get("outputs"), list):
        metadata["outputs"] = [legacy_path(item) for item in metadata["outputs"]]
    inputs = metadata.get("inputs")
    if isinstance(inputs, dict):
        if "folder" in inputs:
            inputs["folder"] = legacy_path(inputs["folder"])
        for item in inputs.get("items", []) if isinstance(inputs.get("items"), list) else []:
            if isinstance(item, dict):
                for key in ("path", "source_locator"):
                    if key in item:
                        item[key] = legacy_path(item[key])
    navigation = _sections(body).get("Quick Navigation")
    if navigation:
        updated = re.sub(r"\(<\.\./\.\./([^>]+)>\)", lambda match: f"(<../../{legacy_path(match.group(1))}>)", navigation)
        body = body.replace(navigation, updated, 1)
    return _render_markdown(metadata, body)


def migrate_layout(old, system, documents=None) -> dict:
    old = Path(old).expanduser().resolve()
    if not (old / "tasks").is_dir() or not (old / "config/projects.json").is_file():
        raise WorkspaceError(f"不是旧版单目录工作区：{old}")
    workspace = Workspace(system, documents)
    if old in (workspace.path, workspace.docs) or old in workspace.path.parents or old in workspace.docs.parents \
            or workspace.path in old.parents or workspace.docs in old.parents:
        raise WorkspaceError("新系统目录、文档库与旧工作区不能互相包含。")
    plan = []
    for path in _tree(old):
        if path.is_dir() or not visible(path):
            continue
        relative = path.relative_to(old).as_posix()
        target = target_name(relative)
        if target is not None:
            plan.append((path, relative, target))
    old_manifest = json.loads((old / "skills/manifest.json").read_text(encoding="utf-8")) if (old / "skills/manifest.json").is_file() else {}
    with workspace._lock:
        workspace.initialize()
        for path, relative, target in plan:
            if target in ("config/projects.json", VIEWS, INBOX_LEDGER):
                workspace._atomic_text(target, path.read_text(encoding="utf-8"))
            elif target == "config/workspace.json":
                name = json.loads(path.read_text(encoding="utf-8")).get("name", "余烬")
                workspace._write_json(target, {**workspace._json(target), "name": name, "migrated_from": str(old)})
            elif target == "MEMORY.md":
                workspace._atomic_text(target, path.read_text(encoding="utf-8"))
            elif relative.startswith("tasks/") and relative.endswith(".md"):
                workspace._atomic_text(target, _task_card(path.read_text(encoding="utf-8"), relative), new=True)
            else:
                destination = workspace._safe(target)
                if destination.exists():
                    raise WorkspaceError(f"迁移目标已存在：{target}", 409)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(path.read_bytes())
        completion = old_manifest.get("onboarding_completion")
        if completion:
            # Keep the user's finished onboarding: drop the init Skill exactly as acceptance did.
            import shutil
            from .onboarding_completion import DOCUMENTS, INIT, _updated_documents
            updated = _updated_documents({name: workspace._text(name) for name in DOCUMENTS}, completion)
            shutil.rmtree(workspace._safe(INIT, exists=True))
            for name, text in updated.items():
                workspace._atomic_text(name, text)
        from .bootstrap import verify_workspace_contract
        verify_workspace_contract(workspace)
        state = workspace.snapshot()
    return {"old": str(old), "workspace": str(workspace.path), "documents": str(workspace.docs),
            "projects": len(state["projects"]), "tasks": len(state["tasks"]), "files": len(state["files"]),
            "next": f"确认无误后运行 ember use {workspace.path} --replace，让 AI 与工作台改用新位置；旧目录未改动，可在核对后自行处理。"}
