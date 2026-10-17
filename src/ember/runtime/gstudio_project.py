#!/usr/bin/env python3
"""Controlled project registry and project-card management for GStudio."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .workspace_paths import shared_workspace_root

ROOT = _deployment_root()
REGISTRY_PATH = ROOT / "config" / "projects.json"
PROJECT_TYPES_PATH = ROOT / "config" / "project-types.json"
PRIORITIES_PATH = ROOT / "config" / "project-priorities.json"
PROJECT_CARD_ROOT = shared_workspace_root() / "项目"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROJECT_TYPE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
ALLOWED_CAPABILITIES = {
    "task_groups", "gstudio_delivery", "publishing", "archive", "copy_board",
    "ebrain_context", "system_changes", "skills", "task_gate",
    "dual_mac_sync", "tests", "system_health", "external_results",
    "knowledge_jobs",
}
ALLOWED_OWNERS = {"gstudio", "ebrain", "external"}
ALLOWED_MODES = {"none", "delivery", "system", "archive", "external"}
REQUIRED_SECTIONS = ("时间线", "运行身份", "说明正本", "运行边界", "成果策略", "系统入口", "整理记录")


def now_beijing() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S+08:00")


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_project_types(path: Path = PROJECT_TYPES_PATH) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("project_types"), list):
        raise ValueError("project-types.json must use schema_version 1 and project_types list")
    result: dict[str, dict[str, object]] = {}
    for raw in payload["project_types"]:
        if not isinstance(raw, dict) or not PROJECT_TYPE_RE.fullmatch(str(raw.get("slug") or "")):
            raise ValueError("project-types.json contains an invalid project type")
        slug = str(raw["slug"])
        if slug in result:
            raise ValueError(f"duplicate project type: {slug}")
        result[slug] = raw
    return result


def load_work_categories(path: Path = PROJECT_TYPES_PATH) -> dict[str, dict[str, object]]:
    """Read business categories independently of executable project-type rules."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("work_categories"), list):
        raise ValueError("project-types.json must use schema_version 1 and work_categories list")
    result: dict[str, dict[str, object]] = {}
    for raw in payload["work_categories"]:
        if (not isinstance(raw, dict)
                or not isinstance(raw.get("slug"), str)
                or not PROJECT_TYPE_RE.fullmatch(raw["slug"])
                or not isinstance(raw.get("title"), str)
                or not raw["title"].strip()):
            raise ValueError("project-types.json contains an invalid work category")
        slug = raw["slug"]
        if slug in result:
            raise ValueError(f"duplicate work category: {slug}")
        result[slug] = raw
    return result


def project_card_path(item: dict[str, object]) -> Path:
    relative = str(item.get("project_card") or "")
    return shared_workspace_root() / relative


def validate_registry(payload: dict[str, object], *, require_cards: bool = True) -> list[str]:
    errors: list[str] = []
    try:
        project_types = load_project_types()
        work_categories = load_work_categories()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid project type registry: {exc}"]
    if payload.get("schema_version") != 3:
        errors.append("projects.json schema_version must be 3")
    scope = payload.get("independent_scope")
    if not isinstance(scope, dict) or scope.get("slug") != "independent" or scope.get("is_project") is not False:
        errors.append("independent_scope must define independent as a non-project")
    projects = payload.get("projects")
    if not isinstance(projects, list):
        return errors + ["projects must be a list"]
    slugs: set[str] = set()
    aliases: dict[str, str] = {}
    for index, raw in enumerate(projects):
        if not isinstance(raw, dict):
            errors.append(f"projects[{index}] must be an object")
            continue
        slug = str(raw.get("slug") or "")
        title = str(raw.get("title") or "")
        if not SLUG_RE.fullmatch(slug):
            errors.append(f"invalid project slug: {slug!r}")
        if slug == "independent":
            errors.append("independent must not be registered as a project")
        if slug in slugs:
            errors.append(f"duplicate project slug: {slug}")
        slugs.add(slug)
        if not title:
            errors.append(f"project {slug!r} has no title")
        project_type = str(raw.get("project_type") or "")
        type_rule = project_types.get(project_type)
        if not type_rule:
            errors.append(f"project {slug!r} has invalid project_type: {project_type!r}")
        work_category = raw.get("work_category")
        if work_category is not None and (not isinstance(work_category, str) or work_category not in work_categories):
            errors.append(f"project {slug!r} has invalid work_category: {work_category!r}")
        for alias in [slug, *raw.get("aliases", [])]:
            key = str(alias).strip().casefold()
            if not key:
                errors.append(f"project {slug!r} has an empty alias")
            elif key in aliases and aliases[key] != slug:
                errors.append(f"alias {alias!r} is shared by {aliases[key]} and {slug}")
            else:
                aliases[key] = slug
        capabilities = raw.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(f"project {slug!r} must declare capabilities")
        else:
            unknown = sorted(set(map(str, capabilities)) - ALLOWED_CAPABILITIES)
            if unknown:
                errors.append(f"project {slug!r} has unknown capabilities: {unknown}")
            if type_rule:
                required = set(map(str, type_rule.get("required_capabilities") or []))
                missing = sorted(required - set(map(str, capabilities)))
                if missing:
                    errors.append(f"project {slug!r} is missing {project_type} capabilities: {missing}")
        policy = raw.get("artifact_policy")
        if not isinstance(policy, dict):
            errors.append(f"project {slug!r} must declare artifact_policy")
        else:
            owner, mode = policy.get("owner"), policy.get("default_mode")
            if owner not in ALLOWED_OWNERS:
                errors.append(f"project {slug!r} has invalid artifact owner: {owner!r}")
            if mode not in ALLOWED_MODES:
                errors.append(f"project {slug!r} has invalid default mode: {mode!r}")
            if type_rule and mode not in set(map(str, type_rule.get("allowed_artifact_modes") or [])):
                errors.append(f"project {slug!r} mode {mode!r} is not allowed for {project_type}")
        card = str(raw.get("project_card") or "")
        expected = f"项目/{slug}/项目看板.md"
        if card != expected:
            errors.append(f"project {slug!r} project_card must be {expected}")
        elif require_cards:
            path = project_card_path(raw)
            if not path.is_file():
                errors.append(f"project card missing: {path}")
            else:
                errors.extend(validate_project_card(path, slug, title))
    if payload.get("default_project") != "independent":
        errors.append("default_project must be independent")
    return errors


def validate_project_card(path: Path, slug: str, title: str) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    expected = {
        "type": "gstudio_project", "project": slug, "title": title,
    }
    for key, value in expected.items():
        if not re.search(rf"^{re.escape(key)}:\s*['\"]?{re.escape(value)}['\"]?\s*$", text, re.MULTILINE):
            errors.append(f"{path}: expected {key}: {value}")
    for key in ("created_at", "updated_at"):
        if not re.search(rf"^{key}:\s*['\"]?\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}}\+08:00['\"]?\s*$", text, re.MULTILINE):
            errors.append(f"{path}: invalid or missing {key}")
    if not re.search(r"^## (?:项目总览|当前概况)\s*$", text, re.MULTILINE):
        errors.append(f"{path}: missing project overview")
    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in text:
            errors.append(f"{path}: missing section {section}")
    # Historical cards remain valid; explicit maintenance adopts the new reading
    # structure without requiring a registry-wide migration.
    if not re.search(r"^## (?:当前阶段|当前重点)\s*$", text, re.MULTILINE):
        errors.append(f"{path}: missing section 当前阶段 or 当前重点")
    return errors


def render_project_card(slug: str, title: str, project_type: str, timestamp: str) -> str:
    current_heading = "当前概况" if project_type == "ai_system" else "项目总览"
    return f'''---
type: gstudio_project
project: {slug}
title: {title}
created_at: "{timestamp}"
updated_at: "{timestamp}"
---

# {title}

## {current_heading}

暂无已确认的项目说明；按已确认目标、对象、范围和真实资料补充，不编造事实。

## 工作位置与入口

| 类型 | 环境 | 路径或网址 | 用途与访问说明 |
|---|---|---|---|
| 主要工作位置与资料入口 | 待确认 | 待确认 | 按已登记的业务类别核对真实入口、适用环境、用途及启动或访问条件。 |

## 范围与要求

待确认。按注册的 `work_category` 读取 `skills/gstudio/references/project-category-standard.md` 对应指导，补充有依据的工作范围与项目个性要求。

## 当前阶段

待确认当前阶段；逐项任务进度由任务卡记录。

## 时间线

- {timestamp}：确认 余烬 · Ember 正式项目登记。

## 运行身份

`{slug}` 是 余烬 · Ember 正式项目，类型为 `{project_type}`。

## 说明正本

本卡是 余烬 · Ember 项目说明正本，登记路径为 `项目/{slug}/项目看板.md`。

## 运行边界

余烬 · Ember 独立维护项目说明和任务入口；专业源码、业务数据及发布正本留在所属系统。

## 成果策略

以 `projects.json` 的 `artifact_policy` 为准，本卡不复制机器配置。

## 系统入口

- 余烬 · Ember 项目视图：`/projects/{slug}`

## 整理记录

- {timestamp}：按通用项目标准初始化。
'''


def project_item(args: argparse.Namespace) -> dict[str, object]:
    capabilities = list(dict.fromkeys(value.strip() for value in args.capabilities.split(",") if value.strip()))
    return {
        "slug": args.slug,
        "title": args.title,
        "project_type": args.project_type,
        "work_category": getattr(args, "work_category", None),
        "aliases": list(dict.fromkeys([args.title, args.slug, *args.alias])),
        "legacy_aliases": [],
        "project_card": f"项目/{args.slug}/项目看板.md",
        "capabilities": capabilities,
        "artifact_policy": {"owner": args.owner, "default_mode": args.default_mode},
        "current_focus": "暂无明确推进主线",
        "focus_updated_at": now_beijing(),
    }


def proposed_create(args: argparse.Namespace) -> tuple[dict[str, object], dict[str, object], Path, str]:
    payload = load_registry()
    item = project_item(args)
    payload["projects"] = [*payload.get("projects", []), item]
    errors = validate_registry(payload, require_cards=False)
    card = project_card_path(item)
    if card.exists():
        errors.append(f"project card already exists: {card}")
    if errors:
        raise ValueError("\n".join(errors))
    return payload, item, card, render_project_card(
        args.slug, args.title, args.project_type, str(item["focus_updated_at"])
    )


def proposed_priorities(payload: dict[str, object], slug: str, path: Path | None = None) -> dict[str, object]:
    """Append a project to tracked defaults without touching machine-local ordering."""
    path = path or PRIORITIES_PATH
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1}
    projects = current.get("projects") if isinstance(current.get("projects"), dict) else {}
    projects = {str(key): list(value) for key, value in projects.items() if isinstance(value, list)}
    projects.setdefault(slug, [])
    registered = [str(item.get("slug") or "") for item in payload.get("projects", []) if item.get("slug")]
    saved = current.get("project_order")
    ordered = [str(value) for value in saved if str(value) in registered] if isinstance(saved, list) else []
    return {
        **current,
        "version": 1,
        "projects": {key: projects.get(key, []) for key in registered},
        "project_order": list(dict.fromkeys([*ordered, *registered])),
    }


def require_creation_authority(task_id: str, slug: str) -> Path:
    """Require the existing GStudio system-task and shared-lease boundary."""
    from . import gstudio_system_sync
    from . import task_gate

    task_path, task_text, errors = task_gate.validate_task(task_id)
    if errors:
        raise RuntimeError("project creation task preflight failed:\n" + "\n".join(errors))
    expected = {
        "project": "gstudio",
        "work_type": "system",
        "artifact_mode": "system",
        "status": "active",
    }
    mismatches = [
        f"{key} must be {value!r}"
        for key, value in expected.items()
        if task_gate.top_value(task_text, key) != value
    ]
    if mismatches:
        raise RuntimeError("project creation requires an active GStudio system task: " + "; ".join(mismatches))
    if sync_error := task_gate.sync_workbench_index(task_path):
        raise RuntimeError(f"project creation task preflight failed: {sync_error}")
    gstudio_system_sync.require_owned_lock(task_id)
    allowed = gstudio_system_sync.system_file_allowlist(task_path, ROOT)
    required = {"config/projects.json", "config/project-priorities.json"}
    if missing := required - allowed:
        raise RuntimeError("project creation task scope is missing: " + ", ".join(sorted(missing)))
    card_reference = f"项目/{slug}/项目看板.md"
    if card_reference not in task_text:
        raise RuntimeError(f"project creation task scope is missing: {card_reference}")
    return task_path


def atomic_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False)
    try:
        with handle:
            handle.write(text)
        return Path(handle.name)
    except Exception:
        Path(handle.name).unlink(missing_ok=True)
        raise


def command_create(args: argparse.Namespace, *, dry_run: bool = False) -> int:
    payload, item, card, card_text = proposed_create(args)
    priorities = proposed_priorities(payload, args.slug)
    if dry_run:
        print(json.dumps({
            "project": item,
            "project_card": str(card),
            "default_project_order": priorities["project_order"],
            "writes": False,
        }, ensure_ascii=False, indent=2))
        return 0
    task_path = require_creation_authority(args.task_id, args.slug)
    registry_before = REGISTRY_PATH.read_text(encoding="utf-8")
    priorities_existed = PRIORITIES_PATH.exists()
    priorities_before = PRIORITIES_PATH.read_text(encoding="utf-8") if priorities_existed else ""
    index_path = shared_workspace_root() / "tasks" / "项目索引" / f"{args.slug}-任务索引.md"
    index_existed = index_path.exists()
    index_before = index_path.read_text(encoding="utf-8") if index_existed else ""
    staged: list[Path] = []
    try:
        registry_tmp = atomic_text(REGISTRY_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        staged.append(registry_tmp)
        priorities_tmp = atomic_text(PRIORITIES_PATH, json.dumps(priorities, ensure_ascii=False, indent=2) + "\n")
        staged.append(priorities_tmp)
        card_tmp = atomic_text(card, card_text)
        staged.append(card_tmp)
        os.replace(card_tmp, card)
        os.replace(registry_tmp, REGISTRY_PATH)
        os.replace(priorities_tmp, PRIORITIES_PATH)
        errors = validate_registry(load_registry(), require_cards=True)
        if errors:
            raise RuntimeError("\n".join(errors))
        # Imports stay local so validation and dry-run remain lightweight.
        from . import gstudio_task
        from . import gstudio_workbench
        # Registration changes no business card: reuse parsed records and mirror
        # only the control task and the newly created shared project card.
        gstudio_task.sync_changed_task_records([task_path], publish_shared=True)
        cache_card = gstudio_task.SOURCE_CACHE_ROOT / "projects" / args.slug / "项目看板.md"
        cache_tmp = atomic_text(cache_card, card_text)
        staged.append(cache_tmp)
        os.replace(cache_tmp, cache_card)
        if args.slug not in gstudio_workbench.project_items():
            raise RuntimeError(f"workbench project entry missing: {args.slug}")
        if gstudio_workbench.render_project_tasks(args.slug, "project-create-validation") is None:
            raise RuntimeError(f"workbench project view failed: {args.slug}")
    except Exception:
        REGISTRY_PATH.write_text(registry_before, encoding="utf-8")
        if priorities_existed:
            PRIORITIES_PATH.write_text(priorities_before, encoding="utf-8")
        else:
            PRIORITIES_PATH.unlink(missing_ok=True)
        card.unlink(missing_ok=True)
        try:
            card.parent.rmdir()
        except OSError:
            pass
        if index_existed:
            index_path.write_text(index_before, encoding="utf-8")
        else:
            index_path.unlink(missing_ok=True)
        try:
            from . import gstudio_task
            gstudio_task.sync_changed_task_records([task_path], publish_shared=True)
            cache_card = gstudio_task.SOURCE_CACHE_ROOT / "projects" / args.slug / "项目看板.md"
            cache_card.unlink(missing_ok=True)
            try:
                cache_card.parent.rmdir()
            except OSError:
                pass
        except Exception:
            # Preserve the original creation error; canonical registry/card/order
            # have already been restored and generated cache is best-effort.
            pass
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
    print(json.dumps({"project": item, "project_card": str(card), "created": True}, ensure_ascii=False, indent=2))
    return 0


def command_validate(_: argparse.Namespace) -> int:
    errors = validate_registry(load_registry(), require_cards=True)
    if errors:
        print("PROJECT VALIDATION FAILED")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("PROJECT VALIDATION PASS")
    return 0


def command_show(args: argparse.Namespace) -> int:
    payload = load_registry()
    if args.slug == "independent":
        item = payload.get("independent_scope")
    else:
        item = next((value for value in payload.get("projects", []) if value.get("slug") == args.slug), None)
    if not item:
        raise ValueError(f"unknown project: {args.slug}")
    print(json.dumps(item, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("create", "dry-run"):
        command = sub.add_parser(name)
        if name == "create":
            command.add_argument("--task-id", required=True)
        command.add_argument("--slug", required=True)
        command.add_argument("--title", required=True)
        command.add_argument("--project-type", required=True, choices=sorted(load_project_types()))
        command.add_argument("--work-category", choices=sorted(load_work_categories()), help="Explicit business category; omitted projects remain unclassified")
        command.add_argument("--alias", action="append", default=[])
        command.add_argument("--capabilities", required=True)
        command.add_argument("--owner", required=True, choices=sorted(ALLOWED_OWNERS))
        command.add_argument("--default-mode", required=True, choices=sorted(ALLOWED_MODES))
    sub.add_parser("validate")
    show = sub.add_parser("show")
    show.add_argument("slug")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "create":
        return command_create(args)
    if args.command == "dry-run":
        return command_create(args, dry_run=True)
    if args.command == "validate":
        return command_validate(args)
    return command_show(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
