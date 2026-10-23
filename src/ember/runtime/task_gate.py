#!/usr/bin/env python3
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = _deployment_root()
from .path_config import archive_root
from .workspace_paths import (
    delivery_root,
    equivalent_path_strings,
    shared_workspace_root,
    task_input_snapshot_max_bytes,
    task_inputs_root,
)
from .ember_task_inputs import parse_inputs
from . import ember_agent
from . import ember_task

SHARED_WORKSPACE_ROOT = shared_workspace_root()
SHARED_TASK_ROOT = SHARED_WORKSPACE_ROOT / "tasks"
ORGANIZATION_INDEX_ROOT = SHARED_WORKSPACE_ROOT / "管理中心" / "整理记录"
LOCAL_TASK_ROOT = ROOT / "tasks"  # legacy/fallback only; iCloud is canonical.
LOCAL_OUTPUT_ROOTS = (
    ROOT / "outputs" / "drafts",
    ROOT / "outputs" / "reports",
    ROOT / "outputs" / "media",
    ROOT / "uploads",
    ROOT / "ebrain-writeback",
    ROOT / "logs",
    ROOT / "tmp",
)
DELIVERY_ROOT = delivery_root()
TASK_INPUTS_ROOT = task_inputs_root()
DRAFT_DELIVERY_ROOT = DELIVERY_ROOT / "草稿"
FINAL_DELIVERY_ROOT = DELIVERY_ROOT / "正式交付"
MEDIA_DELIVERY_ROOT = DELIVERY_ROOT / "媒体文件"
REPORT_DELIVERY_ROOT = DELIVERY_ROOT / "报告"
ARCHIVE_ROOT = archive_root()
FORBIDDEN_ROOT = ROOT / "output"
BEIJING_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+08:00$")
SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
V2_FORBIDDEN_FIELDS = (
    "assigned_agent",
    "role_lane",
    "role_assignment",
    "collaborating_agents",
    "agent_permissions",
    "workflow_lock",
)
STRICT_V2_DATE = "20260713"
SKILLS_USED_REQUIRED_FROM = "2026-07-13 13:08:41+08:00"
TASK_INPUT_POLICY_REQUIRED_FROM = "2026-07-21 23:40:38+08:00"
STRUCTURED_BODY_REQUIRED_FROM = "2026-08-22 13:01:06+08:00"
TASK_TYPES = {"gstudio_task", "media_content_task"}
ARTIFACT_MODES = {"none", "delivery", "system", "archive", "external"}
PROJECT_REGISTRY_REQUIRED_FROM = "20260720"
EXECUTOR_REQUIRED_FROM = "20260726"
EXECUTORS = {"codex", "opencode", "claude-code", "workbuddy", "qianwen-office", "doubao-work", "external", "manual"}
NON_MODEL_VALUES = {
    "codex",
    "opencode",
    "claude-code",
    "claude code",
    "workbuddy",
    "qianwen-office",
    "doubao-work",
    "kimi",
    "kimi code cli",
    "external-mcp",
    "single",
    "single_agent",
    "direct",
    "default",
    "legacy-unspecified",
}
PROJECTS_CONFIG = ROOT / "config" / "projects.json"


def registered_project_slugs() -> set[str]:
    payload = json.loads(PROJECTS_CONFIG.read_text(encoding="utf-8"))
    slugs = {
        str(item.get("slug") or "")
        for item in payload.get("projects", [])
        if isinstance(item, dict)
    }
    scope = payload.get("independent_scope")
    if isinstance(scope, dict) and scope.get("slug"):
        slugs.add(str(scope["slug"]))
    return slugs


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else text


def task_body_structure_errors(text: str) -> list[str]:
    """Validate the human task narrative without interpreting its semantics."""
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            body = text[end + 4:]
    headings = [match.group(1).strip() for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", body)]
    required = ("任务目标", "任务描述", "当前结果", "执行日志")
    errors: list[str] = []
    for heading in required:
        count = headings.count(heading)
        if count != 1:
            errors.append(f"task body must contain exactly one ## {heading} section")
    if errors:
        return errors
    positions = {heading: headings.index(heading) for heading in required}
    if not (
        positions["任务目标"] < positions["任务描述"]
        < positions["当前结果"] < positions["执行日志"]
    ):
        errors.append("task body sections must order 任务目标, 任务描述, 当前结果, 执行日志")
    if "下一步" in headings:
        if headings.count("下一步") != 1:
            errors.append("task body must contain at most one ## 下一步 section")
        else:
            next_position = headings.index("下一步")
            if not positions["当前结果"] < next_position < positions["执行日志"]:
                errors.append("## 下一步 must appear after 当前结果 and before 执行日志")
    if headings[-1] != "执行日志":
        errors.append("## 执行日志 must be the final level-two section")
    return errors


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def task_search_roots() -> list[Path]:
    """Return task roots in priority order.

    iCloud Documents is the canonical Ember task-card workspace. The local task directory is
    kept as a legacy/fallback runtime mirror so old cards and transition tasks
    remain readable, but new tasks should be created under SHARED_TASK_ROOT.
    """
    roots = [SHARED_TASK_ROOT]
    if LOCAL_TASK_ROOT != SHARED_TASK_ROOT:
        roots.append(LOCAL_TASK_ROOT)
    return roots


def find_task(task_id: str) -> Path | None:
    for task_root in task_search_roots():
        matches = list((task_root / "active").glob(f"{task_id}.md"))
        matches += list((task_root / "completed").glob(f"{task_id}.md"))
        if matches:
            return matches[0]
    return None


def top_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else ""


def uses_strict_v2(task_id: str) -> bool:
    """Apply newly enforceable rules without invalidating historical cards."""
    match = re.match(r"^(\d{8})-", task_id)
    return bool(match and match.group(1) >= STRICT_V2_DATE)


def nested_value(text: str, parent: str, child: str) -> str:
    block = re.search(
        rf"^{re.escape(parent)}:\s*$\n((?:  .*(?:\n|$))*)",
        text,
        re.MULTILINE,
    )
    if not block:
        return ""
    match = re.search(
        rf"^  {re.escape(child)}:\s*(.+?)\s*$",
        block.group(1),
        re.MULTILINE,
    )
    return match.group(1).strip().strip("\"'") if match else ""


def list_value(text: str, key: str) -> list[str]:
    match = re.search(
        rf"^{re.escape(key)}:\s*$\n((?:  - .*(?:\n|$))*)",
        text,
        re.MULTILINE,
    )
    if not match:
        return []
    return [
        line.strip()[2:].strip().strip("\"'")
        for line in match.group(1).splitlines()
        if line.strip().startswith("- ")
    ]


def allowed_artifact(
    path: Path,
    task_id: str,
    task_text: str,
    system_change: bool = False,
) -> tuple[bool, str]:
    resolved = path.resolve()
    if is_within(resolved, FORBIDDEN_ROOT.resolve()):
        return False, "forbidden singular output/ root"

    if system_change:
        system_roots = (
            ROOT / ".agents",
            ROOT / ".codex",
            ROOT / ".opencode" / "agents",
            ROOT / ".kimi-code",
            ROOT / "agents",
            ROOT / "scripts",
            ROOT / "skills",
            ROOT / "config",
            ROOT / "docker",
            ROOT / "templates",
            ROOT / "ui",
            ROOT / "logs",
            ROOT / "tasks",
            ROOT / "task-cards",
        )
        system_files = {
            (ROOT / ".gitignore").resolve(),
            (ROOT / "AGENTS.md").resolve(),
            (ROOT / "SOUL.md").resolve(),
            (ROOT / "MEMORY.md").resolve(),
            (ROOT / "README.md").resolve(),
            (ROOT / "requirements.txt").resolve(),
            (ROOT / "RESOLVER.md").resolve(),
            (ROOT / "SYSTEM_BOUNDARIES.md").resolve(),
            (ROOT / "WORKBENCH_DESIGN.md").resolve(),
            (ROOT / "schema.md").resolve(),
            (ROOT / "GIT_SYNC.md").resolve(),
            (ROOT / "HEALTHCHECK.md").resolve(),
            (SHARED_TASK_ROOT / "任务总览.md").resolve(),
            (SHARED_WORKSPACE_ROOT / "README.md").resolve(),
            (SHARED_WORKSPACE_ROOT / "管理中心" / "README.md").resolve(),
            (SHARED_WORKSPACE_ROOT / "历史工作区" / "README.md").resolve(),
            (Path.home() / "Library/LaunchAgents/com.ember.task-workbench.plist").resolve(),
            (Path.home() / "Library/LaunchAgents/com.ember.system-sync.plist").resolve(),
            (Path.home() / "Library/LaunchAgents/com.ember.weekly-organization.plist").resolve(),
        }
        shared_system_roots = (
            SHARED_WORKSPACE_ROOT / "项目",
            SHARED_WORKSPACE_ROOT / "管理中心" / "运行状态",
            SHARED_WORKSPACE_ROOT / "管理中心" / "归档管理",
            SHARED_WORKSPACE_ROOT / "管理中心" / "系统备份",
            ORGANIZATION_INDEX_ROOT,
            SHARED_TASK_ROOT / "项目索引",
            SHARED_TASK_ROOT / "每周整理",
        )
        if top_value(task_text, "project") != "Ember":
            # Schema v2 normalizes the project slug.
            if top_value(task_text, "project") != "gstudio":
                return False, "--system-change requires project: Ember or gstudio"
        in_system_root = any(is_within(resolved, root.resolve()) for root in system_roots)
        in_shared_system_root = any(is_within(resolved, root.resolve()) for root in shared_system_roots)
        if not in_system_root and not in_shared_system_root and resolved not in system_files:
            return False, "system artifact is outside approved governance paths"
        if not any(value in task_text for value in equivalent_path_strings(resolved)):
            return False, "system artifact path is not recorded in the task card"
        if not resolved.exists():
            return False, "system artifact does not exist"
        return True, ""

    roots = (*LOCAL_OUTPUT_ROOTS, DELIVERY_ROOT, ARCHIVE_ROOT)
    if not any(is_within(resolved, root.resolve()) for root in roots):
        return False, "path is outside Ember runtime, delivery, and archive roots"

    local_runtime = is_within(resolved, ROOT.resolve())
    if local_runtime:
        return (
            False,
            "local Ember paths are runtime state, not user delivery; "
            "copy reviewable drafts to iCloud 交付/草稿 first",
        )

    if is_within(resolved, DELIVERY_ROOT.resolve()):
        if is_within(resolved, DRAFT_DELIVERY_ROOT.resolve()):
            relative = resolved.relative_to(DRAFT_DELIVERY_ROOT.resolve())
            if not relative.parts or relative.parts[0] != task_id:
                return (
                    False,
                    "draft delivery must be under 草稿/<task_id>/ "
                    "with no date prefix, alias, or task_id suffix",
                )
        elif is_within(resolved, FINAL_DELIVERY_ROOT.resolve()):
            relative = resolved.relative_to(FINAL_DELIVERY_ROOT.resolve())
            if not relative.parts or relative.parts[0] != task_id:
                return (
                    False,
                    "formal delivery must be under 正式交付/<task_id>/ "
                    "with no date prefix or alias",
                )
        elif is_within(resolved, MEDIA_DELIVERY_ROOT.resolve()):
            return (
                False,
                "交付/媒体文件 is legacy only; new media belongs inside "
                "草稿/<task_id>/ or 正式交付/<task_id>/",
            )
        elif is_within(resolved, REPORT_DELIVERY_ROOT.resolve()):
            return (
                False,
                "交付/报告 is legacy only; new reports belong inside "
                "草稿/<task_id>/ or 正式交付/<task_id>/",
            )
        else:
            return False, "artifact must use a declared Ember delivery subfolder"

    if not any(value in task_text for value in equivalent_path_strings(resolved)):
        return False, "artifact path is not recorded in the task card"

    if not resolved.exists():
        return False, "artifact does not exist"
    return True, ""


def validate_task(task_id: str) -> tuple[Path | None, str, list[str]]:
    errors: list[str] = []
    task_path = find_task(task_id)
    if not task_path:
        searched = ", ".join(str(root) for root in task_search_roots())
        return None, "", [f"task card not found: {task_id} (searched: {searched})"]
    text = read(task_path)
    fm = frontmatter(text)

    task_type = top_value(text, "type")
    if task_type not in TASK_TYPES:
        errors.append(f"type must be one of {sorted(TASK_TYPES)!r}, got {task_type!r}")
    if top_value(text, "task_id") != task_id:
        errors.append(f"task_id must be {task_id!r}, got {top_value(text, 'task_id')!r}")

    # Schema v2 uses eight compact fields. Legacy cards remain readable during
    # migration and are identified by primary_goal/current_stage.
    if re.search(r"^  external_results:", fm, re.MULTILINE):
        from .ember_system_bridge import receipts
        try:
            receipts(text)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid outputs.external_results: {exc}")

    is_v2 = bool(top_value(text, "title") or top_value(text, "work_type") or top_value(text, "status"))
    if is_v2:
        for key in ("title", "project", "work_type", "status", "created_at", "updated_at"):
            if not top_value(text, key):
                errors.append(f"missing task field: {key}")
        if task_id[:8] >= EXECUTOR_REQUIRED_FROM:
            executor = top_value(text, "executor")
            if not executor:
                errors.append("missing task field: executor")
            elif executor not in EXECUTORS:
                errors.append(f"executor must be one of {sorted(EXECUTORS)!r}, got {executor!r}")
            execution_model = top_value(text, "execution_model")
            if execution_model.lower() in NON_MODEL_VALUES:
                errors.append(
                    "execution_model must be an actual model, not an executor or routing mode"
                )
        work_type = top_value(text, "work_type")
        if work_type not in {"text", "image", "video", "audio", "data", "system", "organize", "archive", "mixed"}:
            errors.append(f"invalid work_type: {work_type!r}")
        status = top_value(text, "status")
        if status not in {"active", "waiting_user", "blocked", "completed"}:
            errors.append(f"invalid status: {status!r}")
        title = top_value(text, "title")
        if len(title) > 20:
            errors.append(f"title must be 20 characters or fewer, got {len(title)}")
        if "…" in title or "..." in title:
            errors.append("title must be a complete semantic name without ellipsis")
        if uses_strict_v2(task_id):
            for key in ("created_at", "updated_at"):
                value = top_value(text, key)
                if value and not BEIJING_TIMESTAMP.fullmatch(value):
                    errors.append(f"{key} must use YYYY-MM-DD HH:MM:SS+08:00, got {value!r}")
            for key in V2_FORBIDDEN_FIELDS:
                if re.search(rf"^{re.escape(key)}:\s*", text, re.MULTILINE):
                    errors.append(f"v2 task cards must not persist runtime field: {key}")
        if task_id[:8] >= PROJECT_REGISTRY_REQUIRED_FROM:
            project = top_value(text, "project")
            try:
                registered = registered_project_slugs()
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"project registry unavailable: {exc}")
            else:
                if project not in registered:
                    errors.append(
                        f"project must be a registered slug or independent, got {project!r}"
                    )
        created_at = top_value(text, "created_at")
        skills_declared = bool(re.search(r"^skills_used:\s*", fm, re.MULTILINE))
        skills_used = list_value(fm, "skills_used")
        requires_skills_used = bool(
            BEIJING_TIMESTAMP.fullmatch(created_at)
            and created_at >= SKILLS_USED_REQUIRED_FROM
        )
        if requires_skills_used and not skills_declared:
            errors.append("missing task field: skills_used")
        if skills_declared:
            if not re.search(r"^skills_used:\s*$", fm, re.MULTILINE):
                errors.append("skills_used must be a non-empty YAML list")
            elif not skills_used:
                errors.append("skills_used must be a non-empty YAML list")
            if len(skills_used) != len(set(skills_used)):
                errors.append("skills_used must not contain duplicates")
            for skill in skills_used:
                if not SKILL_NAME.fullmatch(skill):
                    errors.append(f"invalid skills_used identifier: {skill!r}")
        if task_type == "gstudio_task":
            for key in ("task_kind", "artifact_mode"):
                if not top_value(text, key):
                    errors.append(f"missing task field: {key}")
            artifact_mode = top_value(text, "artifact_mode")
            if artifact_mode and artifact_mode not in ARTIFACT_MODES:
                errors.append(f"invalid artifact_mode: {artifact_mode!r}")
            if skills_used and skills_used[0] not in {"gstudio", "ember"}:
                errors.append("ember_task skills_used must start with ember (legacy gstudio is accepted)")
            if created_at >= STRUCTURED_BODY_REQUIRED_FROM:
                errors.extend(task_body_structure_errors(text))
            delivery_folder = nested_value(text, "delivery", "folder")
            delivery_state = nested_value(text, "delivery", "state")
            task_kind = top_value(text, "task_kind")
            if artifact_mode != "delivery" and (delivery_folder or delivery_state):
                errors.append("non-delivery ember_task must not declare delivery fields")
            if task_kind == "task_group":
                expected = f"交付/草稿/{task_id}/" if top_value(text, "status") != "completed" else f"交付/正式交付/{task_id}/"
                if artifact_mode != "delivery":
                    errors.append("task_group artifact_mode must be delivery")
                if delivery_folder != expected:
                    errors.append(f"task_group delivery.folder must be {expected}")
                group_folder = SHARED_WORKSPACE_ROOT / expected
                for name in ("00_任务组说明.md", "01_关联任务索引.md"):
                    if not (group_folder / name).is_file():
                        errors.append(f"task_group required file missing: {group_folder / name}")
            elif artifact_mode == "delivery" and delivery_folder:
                state = "final" if "正式交付" in delivery_folder else "draft"
                expected = f"交付/{'正式交付' if state == 'final' else '草稿'}/{task_id}/"
                if delivery_folder != expected:
                    errors.append(f"delivery.folder must be {expected}")
                if delivery_state != state:
                    errors.append(f"delivery.state must be {state}")

        created_at = top_value(text, "created_at")
        standard_inputs = bool(re.search(r"^inputs:\s*$\n(?:  .*\n)*?  items:\s*$", fm, re.MULTILINE))
        physical_input_folder = TASK_INPUTS_ROOT / task_id
        if standard_inputs:
            try:
                parsed_inputs = parse_inputs(text)
            except ValueError as exc:
                errors.append(f"invalid standard inputs block: {exc}")
            else:
                items = parsed_inputs.get("items") if isinstance(parsed_inputs, dict) else []
                items = items if isinstance(items, list) else []
                identifiers = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
                if any(not value for value in identifiers):
                    errors.append("every inputs.items entry must have an id")
                if len(identifiers) != len(set(identifiers)):
                    errors.append("inputs.items ids must be unique")
                snapshots = [item for item in items if isinstance(item, dict) and item.get("storage") == "snapshot"]
                expected_folder = f"任务资料/{task_id}/"
                if snapshots and parsed_inputs.get("folder") != expected_folder:
                    errors.append(f"inputs.folder must be {expected_folder}")
                if not snapshots and parsed_inputs.get("folder"):
                    errors.append("inputs.folder is only declared when snapshot files exist")
                for item in snapshots:
                    relative = str(item.get("path") or "")
                    expected_prefix = f"任务资料/{task_id}/"
                    if not relative.startswith(expected_prefix):
                        errors.append(f"snapshot path must be below {expected_prefix}: {relative!r}")
                        continue
                    candidate = (SHARED_WORKSPACE_ROOT / relative).resolve()
                    if not candidate.is_file():
                        errors.append(f"required snapshot file missing: {candidate}")
                        continue
                    if candidate.stat().st_size > task_input_snapshot_max_bytes():
                        errors.append(f"snapshot exceeds configured size limit: {candidate}")
                    if int(item.get("size") or 0) != candidate.stat().st_size:
                        errors.append(f"snapshot size mismatch: {candidate}")
                    expected_hash = str(item.get("sha256") or "")
                    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                        errors.append(f"snapshot sha256 is missing or invalid: {candidate}")
        elif BEIJING_TIMESTAMP.fullmatch(created_at) and created_at >= TASK_INPUT_POLICY_REQUIRED_FROM:
            if re.search(r"^inputs:\s*", fm, re.MULTILINE):
                errors.append("new task inputs must use inputs.folder plus inputs.items standard")
            if physical_input_folder.exists():
                errors.append("task input folder exists but the task card has no standard inputs block")
            delivery_folder = nested_value(text, "delivery", "folder")
            if delivery_folder:
                delivery_path = SHARED_WORKSPACE_ROOT / delivery_folder
                for legacy_name in ("输入资料", "01_输入资料", "input", "inputs"):
                    if (delivery_path / legacy_name).exists():
                        errors.append("new task inputs must not be stored inside the delivery folder")
    else:
        for key in ("assigned_agent", "role_lane", "primary_goal"):
            if not top_value(text, key):
                errors.append(f"missing legacy task field: {key}")

    allowed_values = {
        "execution_mode": {"ledger_only", "lightweight", "standard", "full_pipeline", "custom"},
        "system_boundary": {"gstudio", "ebrain", "llm", "mixed"},
        "writeback_status": {"not_required", "pending", "deferred", "done", "failed"},
        "delivery_state": {"none", "runtime_only", "draft_delivered", "final_delivered", "archived"},
    }
    for key, values in allowed_values.items():
        actual = top_value(text, key)
        if actual and actual not in values:
            allowed = ", ".join(sorted(values))
            errors.append(f"{key} must be one of [{allowed}], got {actual!r}")

    if not is_v2:
        if nested_value(text, "workflow_lock", "require_task_card_read") != "true":
            errors.append("workflow_lock.require_task_card_read must be true")
        if not nested_value(text, "workflow_lock", "last_read_at"):
            errors.append("workflow_lock.last_read_at must be set")
        if not nested_value(text, "workflow_lock", "last_action"):
            errors.append("workflow_lock.last_action must be set")

    return task_path, text, errors


def sync_workbench_index(*task_paths: Path) -> str:
    """Incrementally refresh selected canonical cards after a successful gate."""
    try:
        from . import ember_task_index_sync

        ember_task_index_sync.refresh_tasks(list(task_paths))
    except Exception as exc:  # pragma: no cover - exact OS/filesystem errors vary.
        return f"workbench sync failed: {type(exc).__name__}: {exc}"
    return ""


def _replace_top_value(text: str, key: str, value: str) -> str:
    return re.sub(rf"^{re.escape(key)}:\s*.*$", f"{key}: {value}", text, count=1, flags=re.MULTILINE)


def _set_completed_at(text: str, timestamp: str) -> str:
    """Record when a lifecycle gate closed the task; the daily report counts completions by it."""
    if re.search(r"^completed_at:", text, flags=re.MULTILINE):
        return _replace_top_value(text, "completed_at", timestamp)
    return re.sub(r"^(updated_at:.*)$", rf"\g<1>\ncompleted_at: {timestamp}", text, count=1, flags=re.MULTILINE)


def _clear_completed_at(text: str) -> str:
    return re.sub(r"^completed_at:.*\n", "", text, count=1, flags=re.MULTILINE)


def _replace_nested_value(text: str, parent: str, child: str, value: str) -> str:
    pattern = rf"(^\s*{re.escape(parent)}:\s*$\n(?:^  .*\n)*?^  {re.escape(child)}:)\s*.*$"
    return re.sub(pattern, rf"\g<1> {value}", text, count=1, flags=re.MULTILINE)


def _beijing_now() -> str:
    zone = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S+08:00")


def command_promote_delivery(args: argparse.Namespace) -> int:
    task_path, text, errors = validate_task(args.task_id)
    organization_path, organization_text, organization_errors = validate_task(args.organization_task_id)
    errors.extend(f"organization task: {error}" for error in organization_errors)
    draft_folder = DRAFT_DELIVERY_ROOT / args.task_id
    formal_folder = FINAL_DELIVERY_ROOT / args.task_id
    completed_card = SHARED_TASK_ROOT / "completed" / f"{args.task_id}.md"

    if task_path and task_path.parent.name != "active":
        errors.append("target task card must currently be under tasks/active")
    if top_value(text, "status") != "active":
        errors.append("target task status must be active")
    if nested_value(text, "delivery", "state") != "draft":
        errors.append("target delivery.state must be draft")
    expected_draft = f"交付/草稿/{args.task_id}/"
    if nested_value(text, "delivery", "folder") != expected_draft:
        errors.append(f"target delivery.folder must be {expected_draft}")
    if organization_path and organization_path.parent.name != "active":
        errors.append("organization task must currently be active")
    if top_value(organization_text, "work_type") != "organize":
        errors.append("organization task work_type must be organize")
    if top_value(organization_text, "status") != "active":
        errors.append("organization task status must be active")
    if nested_value(organization_text, "confirmations", "promotions_confirmed") != "true":
        errors.append("organization task confirmations.promotions_confirmed must be true")
    if top_value(organization_text, "task_kind") == "weekly_organization":
        marker = rf"^- confirmed-promotion:\s*{re.escape(args.task_id)}\s*\|"
        if not re.search(marker, organization_text, re.MULTILINE):
            errors.append("weekly organization task must record an exact confirmed-promotion line for the target")
    elif args.task_id not in organization_text:
        errors.append("organization task must record the target task ID")
    if not draft_folder.is_dir():
        errors.append(f"draft delivery folder does not exist: {draft_folder}")
    if formal_folder.exists():
        errors.append(f"formal destination already exists; refusing to merge or overwrite: {formal_folder}")
    if completed_card.exists():
        errors.append(f"completed task card already exists; refusing to overwrite: {completed_card}")

    if errors:
        print("Ember task gate: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1

    timestamp = _beijing_now()
    revised = _replace_top_value(text, "status", "completed")
    revised = _replace_top_value(revised, "updated_at", timestamp)
    revised = _set_completed_at(revised, timestamp)
    revised = _replace_nested_value(revised, "delivery", "state", "final")
    revised = _replace_nested_value(revised, "delivery", "folder", f"交付/正式交付/{args.task_id}/")
    revised = revised.replace(f"/交付/草稿/{args.task_id}/", f"/交付/正式交付/{args.task_id}/")
    revised = ember_task.prepend_execution_log_entry(
        revised,
        f"{timestamp}：由整理任务 `{args.organization_task_id}` 执行草稿晋级正式交付并完成任务。",
    )

    original_text = text
    try:
        formal_folder.parent.mkdir(parents=True, exist_ok=True)
        completed_card.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(draft_folder), str(formal_folder))
        task_path.write_text(revised, encoding="utf-8")
        shutil.move(str(task_path), str(completed_card))
        if sync_error := sync_workbench_index(completed_card):
            raise RuntimeError(sync_error)
    except Exception as exc:
        if completed_card.exists() and task_path and not task_path.exists():
            shutil.move(str(completed_card), str(task_path))
        if task_path:
            task_path.write_text(original_text, encoding="utf-8")
        if formal_folder.exists() and not draft_folder.exists():
            shutil.move(str(formal_folder), str(draft_folder))
        print("Ember task gate: BLOCKED")
        print(f"- promotion rolled back: {type(exc).__name__}: {exc}")
        return 1

    print("Ember task gate: PROMOTE PASS")
    print(f"- organization task: {organization_path}")
    print(f"- completed task: {completed_card}")
    print(f"- formal delivery: {formal_folder}")
    return 0


def command_complete_task(args: argparse.Namespace) -> int:
    task_path, text, errors = validate_task(args.task_id)
    organization_path, organization_text, organization_errors = validate_task(args.organization_task_id)
    errors.extend(f"organization task: {error}" for error in organization_errors)
    artifact_mode = top_value(text, "artifact_mode") or ("delivery" if nested_value(text, "delivery", "folder") else "none")
    completed_card = SHARED_TASK_ROOT / "completed" / f"{args.task_id}.md"
    if artifact_mode == "delivery":
        errors.append("delivery tasks must complete through promote-delivery")
    if task_path and task_path.parent.name != "active":
        errors.append("target task card must currently be under tasks/active")
    if top_value(text, "status") != "active":
        errors.append("target task status must be active")
    if organization_path and organization_path.parent.name != "active":
        errors.append("organization task must currently be active")
    if top_value(organization_text, "work_type") != "organize":
        errors.append("organization task work_type must be organize")
    if top_value(organization_text, "status") != "active":
        errors.append("organization task status must be active")
    if nested_value(organization_text, "confirmations", "completions_confirmed") != "true":
        errors.append("organization task confirmations.completions_confirmed must be true")
    if top_value(organization_text, "task_kind") == "weekly_organization":
        marker = rf"^- confirmed-completion:\s*{re.escape(args.task_id)}\s*\|"
        if not re.search(marker, organization_text, re.MULTILINE):
            errors.append("weekly organization task must record an exact confirmed-completion line for the target")
    elif args.task_id not in organization_text:
        errors.append("organization task must record the target task ID")
    if completed_card.exists():
        errors.append(f"completed task card already exists; refusing to overwrite: {completed_card}")
    if errors:
        print("Ember task gate: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1
    timestamp = _beijing_now()
    revised = _replace_top_value(text, "status", "completed")
    revised = _replace_top_value(revised, "updated_at", timestamp)
    revised = _set_completed_at(revised, timestamp)
    revised = ember_task.prepend_execution_log_entry(
        revised,
        f"{timestamp}：由整理任务 `{args.organization_task_id}` 确认 `{artifact_mode}` 成果验证完成并收口。",
    )
    original_text = text
    try:
        completed_card.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text(revised, encoding="utf-8")
        shutil.move(str(task_path), str(completed_card))
        if sync_error := sync_workbench_index(completed_card):
            raise RuntimeError(sync_error)
    except Exception as exc:
        if completed_card.exists() and task_path and not task_path.exists():
            shutil.move(str(completed_card), str(task_path))
        if task_path:
            task_path.write_text(original_text, encoding="utf-8")
        print("Ember task gate: BLOCKED")
        print(f"- completion rolled back: {type(exc).__name__}: {exc}")
        return 1
    print("Ember task gate: COMPLETE PASS")
    print(f"- organization task: {organization_path}")
    print(f"- completed task: {completed_card}")
    return 0


def _weekly_confirmation_fingerprint(item: dict[str, object]) -> str:
    candidate_values = item.get("candidate_task_ids")
    payload = {
        "item_id": str(item.get("item_id") or ""),
        "confirmation_key": str(item.get("confirmation_key") or ""),
        "task_id": str(item.get("task_id") or ""),
        "action_code": str(item.get("action_code") or ""),
        "candidate_task_ids": [str(value) for value in candidate_values if str(value)] if isinstance(candidate_values, list) else [],
        "details": item.get("details") if isinstance(item.get("details"), dict) else {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def command_finalize_weekly_organization(args: argparse.Namespace) -> int:
    """Complete one weekly organization task from its frozen revision and exact receipts."""
    task_path, text, errors = validate_task(args.task_id)
    draft_folder = DRAFT_DELIVERY_ROOT / args.task_id
    formal_folder = FINAL_DELIVERY_ROOT / args.task_id
    completed_card = SHARED_TASK_ROOT / "completed" / f"{args.task_id}.md"
    already_completed = bool(
        task_path and task_path == completed_card and completed_card.is_file() and formal_folder.is_dir()
    )
    folder = formal_folder if already_completed else draft_folder
    execution_state = folder / "03_任务整理执行状态.json"
    completion_report = folder / "03_任务整理完成报告.md"

    try:
        run = ember_agent.require_run(
            run_id=args.run_id, mode="task_organization", task_id=args.task_id,
        )
        authorization = run.get("authorization") if isinstance(run.get("authorization"), dict) else {}
        authorized_executor = str(authorization.get("executor") or "")
        if not authorized_executor:
            errors.append("authorized Agent run has no executor identity")
    except ember_agent.AgentError as exc:
        authorized_executor = ""
        errors.append(str(exc))

    expected_status = "completed" if already_completed else "active"
    if task_path and task_path.parent.name != expected_status:
        errors.append(f"weekly organization task must currently be {expected_status}")
    if top_value(text, "status") != expected_status:
        errors.append(f"weekly organization task status must be {expected_status}")
    if top_value(text, "work_type") != "organize" or top_value(text, "task_kind") != "weekly_organization":
        errors.append("target must be a weekly organization task")
    if not already_completed and top_value(text, "current_stage") != "ready_to_finalize":
        errors.append("weekly organization current_stage must be ready_to_finalize")
    expected_delivery_state = "final" if already_completed else "draft"
    expected_delivery_folder = f"交付/{'正式交付' if already_completed else '草稿'}/{args.task_id}/"
    if nested_value(text, "delivery", "state") != expected_delivery_state:
        errors.append(f"weekly organization delivery.state must be {expected_delivery_state}")
    if nested_value(text, "delivery", "folder") != expected_delivery_folder:
        errors.append("weekly organization delivery folder is not canonical")
    if not folder.is_dir():
        errors.append(f"weekly organization delivery folder does not exist: {folder}")
    if not already_completed and formal_folder.exists():
        errors.append(f"formal destination already exists; refusing to merge or overwrite: {formal_folder}")
    if not already_completed and completed_card.exists():
        errors.append(f"completed task card already exists; refusing to overwrite: {completed_card}")

    card_revision = nested_value(text, "organization", "revision_id")
    match = re.search(r"-R(\d+)$", card_revision)
    snapshot_path = folder / f"{int(match.group(1)):02d}_任务整理报告_R{int(match.group(1)):02d}.json" if match else None
    frozen: dict[str, object] = {}
    if not card_revision or snapshot_path is None:
        errors.append("weekly organization task has no exact frozen revision ID")
    elif not snapshot_path.is_file():
        errors.append(f"exact frozen weekly revision is missing: {snapshot_path}")
    else:
        try:
            value = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value:
                frozen = value
            else:
                errors.append("exact frozen weekly revision has an invalid shape")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"exact frozen weekly revision is invalid: {exc}")
    if frozen:
        if str(frozen.get("organization_task_id") or "") != args.task_id:
            errors.append("frozen weekly revision task ID does not match")
        if str(frozen.get("revision_id") or "") != card_revision:
            errors.append("frozen weekly revision does not match the task card")

    payload: dict[str, object] = {}
    if not execution_state.is_file():
        errors.append(f"weekly execution state is missing: {execution_state}")
    else:
        try:
            value = json.loads(execution_state.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value:
                payload = value
            else:
                errors.append("weekly execution state has an invalid shape")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"weekly execution state is invalid: {exc}")
    if payload:
        if str(payload.get("organization_task_id") or "") != args.task_id:
            errors.append("weekly execution state task ID does not match")
        allowed_states = {"completed"} if already_completed else {"ready_to_finalize"}
        if str(payload.get("state") or "") not in allowed_states:
            errors.append("weekly execution state must be ready_to_finalize")
        if str(payload.get("revision_id") or "") != card_revision:
            errors.append("weekly execution state revision does not match the task card")
        receipts = payload.get("receipts") if isinstance(payload.get("receipts"), dict) else {}
        decisions = frozen.get("decisions") if isinstance(frozen.get("decisions"), dict) else {}
        confirmed = [
            value for value in decisions.values()
            if isinstance(value, dict) and value.get("decision") == "confirm"
        ]
        close_round = frozen.get("close_round") if isinstance(frozen.get("close_round"), dict) else {}
        if not confirmed and close_round.get("decision") != "close":
            errors.append("zero confirmed items require an explicit frozen close_round decision")
        if close_round.get("decision") == "close":
            if str(close_round.get("run_id") or "") != args.run_id:
                errors.append("close_round is not bound to the authorized run")
            if str(close_round.get("executor") or "") != authorized_executor:
                errors.append("close_round executor does not match the authorized run")
        for item in confirmed:
            key = str(item.get("confirmation_key") or "")
            expected_fingerprint = _weekly_confirmation_fingerprint(item)
            if str(item.get("confirmation_fingerprint") or "") != expected_fingerprint:
                errors.append(f"confirmed weekly item has an invalid fingerprint: {key}")
            receipt = receipts.get(key)
            if not isinstance(receipt, dict):
                errors.append(f"confirmed weekly item has no receipt: {key}")
                continue
            for field in ("item_id", "confirmation_key", "task_id", "action_code"):
                if str(receipt.get(field) or "") != str(item.get(field) or ""):
                    errors.append(f"weekly receipt {key} has mismatched {field}")
            if str(receipt.get("confirmation_fingerprint") or "") != expected_fingerprint:
                errors.append(f"weekly receipt {key} has a mismatched confirmation fingerprint")
            if receipt.get("state") != "succeeded":
                errors.append(f"weekly receipt {key} has not succeeded")
            if str(receipt.get("run_id") or "") != args.run_id:
                errors.append(f"weekly receipt {key} is not bound to the authorized run")
            if str(receipt.get("executor") or "") != authorized_executor:
                errors.append(f"weekly receipt {key} executor does not match the authorized run")
            action = str(item.get("action_code") or "")
            if action in {"promote_delivery", "complete_task"}:
                target_id = str(item.get("task_id") or "")
                target_path = find_task(target_id) if target_id else None
                expected_target = SHARED_TASK_ROOT / "completed" / f"{target_id}.md"
                if target_path != expected_target:
                    errors.append(f"automatic weekly target is not the canonical completed task: {target_id}")
                else:
                    target_text = read(target_path)
                    if top_value(target_text, "status") != "completed":
                        errors.append(f"automatic weekly target status is not completed: {target_id}")
                    if action == "promote_delivery":
                        expected_folder = f"交付/正式交付/{target_id}/"
                        if nested_value(target_text, "delivery", "state") != "final":
                            errors.append(f"promoted weekly target delivery.state is not final: {target_id}")
                        if nested_value(target_text, "delivery", "folder") != expected_folder:
                            errors.append(f"promoted weekly target delivery folder is not canonical: {target_id}")
                        if not (FINAL_DELIVERY_ROOT / target_id).is_dir():
                            errors.append(f"promoted weekly target final delivery folder is missing: {target_id}")
                        if (DRAFT_DELIVERY_ROOT / target_id).exists():
                            errors.append(f"promoted weekly target has reopened as draft: {target_id}")
                    else:
                        artifact_mode = top_value(target_text, "artifact_mode")
                        if artifact_mode not in {"none", "system", "archive", "external"}:
                            errors.append(f"completed weekly target has invalid non-delivery artifact_mode: {target_id}")
            if action not in {"promote_delivery", "complete_task", "merge"}:
                errors.append(f"semantic weekly receipt {key} has no canonical success validator")
            if action == "merge":
                if not isinstance(receipt.get("verification"), dict) or not receipt.get("verification"):
                    errors.append(f"semantic weekly receipt {key} has no structured verification")
                if not isinstance(receipt.get("result_refs"), list) or not receipt.get("result_refs"):
                    errors.append(f"semantic weekly receipt {key} has no result references")
                details = item.get("details") if isinstance(item.get("details"), dict) else {}
                candidate_values = item.get("candidate_task_ids")
                candidates = [str(value) for value in candidate_values if str(value)] if isinstance(candidate_values, list) else []
                survivor = str(details.get("survivor_task_id") or "")
                source_values = details.get("source_task_ids")
                sources = [str(value) for value in source_values if str(value)] if isinstance(source_values, list) else []
                artifact_plan = details.get("artifact_plan")
                disposition_values = details.get("source_lifecycle_dispositions")
                dispositions = disposition_values if isinstance(disposition_values, dict) else {}
                if (
                    len(candidates) < 2 or survivor not in candidates
                    or sorted(sources) != sorted(value for value in candidates if value != survivor)
                    or artifact_plan != {"mode": "references"}
                    or not isinstance(disposition_values, dict) or set(dispositions) != set(sources)
                    or any(str(value) not in {"retired_active", "retired_completed"} for value in dispositions.values())
                ):
                    errors.append(f"merge confirmation {key} lacks exact structured details")
                survivor_path = find_task(survivor) if survivor else None
                if not survivor_path or not sources:
                    errors.append(f"merge receipt {key} lacks a canonical survivor or sources")
                for source in sources:
                    source_path = find_task(source)
                    if not source_path or top_value(read(source_path), "merged_into") != survivor:
                        errors.append(f"merge source {source} does not link to survivor {survivor}")
                        continue
                    disposition = str(dispositions.get(source) or "")
                    expected_state = {
                        "retired_active": "active", "retired_completed": "completed",
                    }.get(disposition)
                    source_text = read(source_path)
                    expected_path = SHARED_TASK_ROOT / str(expected_state) / f"{source}.md"
                    if source_path != expected_path or top_value(source_text, "status") != expected_state:
                        errors.append(f"merge source {source} lifecycle does not match {disposition}")
    if not completion_report.is_file():
        errors.append(f"weekly completion report is missing: {completion_report}")

    if errors:
        print("Ember task gate: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1

    if already_completed:
        print("Ember task gate: WEEKLY ORGANIZATION FINALIZE PASS (already completed)")
        print(f"- completed task: {completed_card}")
        print(f"- formal delivery: {formal_folder}")
        print(f"- completion report: {completion_report}")
        return 0

    timestamp = _beijing_now()
    revised = _replace_top_value(text, "status", "completed")
    revised = _replace_top_value(revised, "updated_at", timestamp)
    revised = _set_completed_at(revised, timestamp)
    revised = _replace_top_value(revised, "current_stage", "completed")
    revised = _replace_nested_value(revised, "delivery", "state", "final")
    revised = _replace_nested_value(revised, "delivery", "folder", f"交付/正式交付/{args.task_id}/")
    revised = revised.replace(f"/交付/草稿/{args.task_id}/", f"/交付/正式交付/{args.task_id}/")
    revised = ember_task.prepend_execution_log_entry(
        revised,
        f"{timestamp}：已校验全部确认项执行回执，生成完成报告并收口本周整理。",
    )

    original_text = text
    original_state = execution_state.read_text(encoding="utf-8")
    try:
        formal_folder.parent.mkdir(parents=True, exist_ok=True)
        completed_card.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(draft_folder), str(formal_folder))
        task_path.write_text(revised, encoding="utf-8")
        shutil.move(str(task_path), str(completed_card))
        final_state_path = formal_folder / execution_state.name
        final_payload = json.loads(final_state_path.read_text(encoding="utf-8"))
        final_payload["state"] = "completed"
        final_payload["completed_at"] = timestamp
        final_state_path.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if sync_error := sync_workbench_index(completed_card):
            raise RuntimeError(sync_error)
    except Exception as exc:
        if completed_card.exists() and task_path and not task_path.exists():
            shutil.move(str(completed_card), str(task_path))
        if task_path:
            task_path.write_text(original_text, encoding="utf-8")
        if formal_folder.exists() and not draft_folder.exists():
            shutil.move(str(formal_folder), str(draft_folder))
        execution_state.parent.mkdir(parents=True, exist_ok=True)
        execution_state.write_text(original_state, encoding="utf-8")
        print("Ember task gate: BLOCKED")
        print(f"- weekly organization finalization rolled back: {type(exc).__name__}: {exc}")
        return 1

    print("Ember task gate: WEEKLY ORGANIZATION FINALIZE PASS")
    print(f"- completed task: {completed_card}")
    print(f"- formal delivery: {formal_folder}")
    print(f"- completion report: {formal_folder / completion_report.name}")
    return 0


def command_reopen_for_revision(args: argparse.Namespace) -> int:
    task_path, text, errors = validate_task(args.task_id)
    formal_folder = FINAL_DELIVERY_ROOT / args.task_id
    draft_folder = DRAFT_DELIVERY_ROOT / args.task_id
    active_card = SHARED_TASK_ROOT / "active" / f"{args.task_id}.md"
    expected_folder = f"交付/正式交付/{args.task_id}/"

    if task_path and task_path.parent.name != "completed":
        errors.append("task card must currently be under tasks/completed")
    if top_value(text, "status") != "completed":
        errors.append("task status must be completed")
    if top_value(text, "work_type") == "organize":
        errors.append("completed organization tasks do not reopen automatically; create a new organizing round after Evan confirmation")
    artifact_mode = top_value(text, "artifact_mode") or ("delivery" if nested_value(text, "delivery", "folder") else "none")
    if artifact_mode == "delivery":
        if nested_value(text, "delivery", "state") != "final":
            errors.append("delivery.state must be final")
        if nested_value(text, "delivery", "folder") != expected_folder:
            errors.append(f"delivery.folder must be {expected_folder}")
        if not formal_folder.is_dir():
            errors.append(f"formal delivery folder does not exist: {formal_folder}")
        if draft_folder.exists():
            errors.append(f"draft destination already exists; refusing to merge or overwrite: {draft_folder}")
    if active_card.exists():
        errors.append(f"active task card already exists; refusing to overwrite: {active_card}")
    if artifact_mode == "delivery" and not args.artifact:
        errors.append("at least one --artifact inside the formal delivery folder is required")
    for raw_path in args.artifact:
        target = Path(raw_path).expanduser().resolve(strict=False)
        if artifact_mode == "delivery" and (not is_within(target, formal_folder.resolve(strict=False)) or target == formal_folder.resolve(strict=False)):
            errors.append(f"revision target must be a delivery artifact inside {formal_folder}: {target}")

    if errors:
        print("Ember task gate: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1

    timestamp = _beijing_now()
    revised = _replace_top_value(text, "status", "active")
    revised = _replace_top_value(revised, "updated_at", timestamp)
    revised = _clear_completed_at(revised)
    if artifact_mode == "delivery":
        revised = _replace_nested_value(revised, "delivery", "state", "draft")
        revised = _replace_nested_value(revised, "delivery", "folder", f"交付/草稿/{args.task_id}/")
        revised = revised.replace(f"/交付/正式交付/{args.task_id}/", f"/交付/草稿/{args.task_id}/")
    revised = ember_task.prepend_execution_log_entry(
        revised,
        f"{timestamp}：正式交付因实质修改重开为草稿。原因：{args.reason.strip()}",
    )

    original_text = text
    try:
        active_card.parent.mkdir(parents=True, exist_ok=True)
        if artifact_mode == "delivery":
            draft_folder.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(formal_folder), str(draft_folder))
        task_path.write_text(revised, encoding="utf-8")
        shutil.move(str(task_path), str(active_card))
        if sync_error := sync_workbench_index(active_card):
            raise RuntimeError(sync_error)
    except Exception as exc:
        if active_card.exists() and task_path and not task_path.exists():
            shutil.move(str(active_card), str(task_path))
        if task_path:
            task_path.write_text(original_text, encoding="utf-8")
        if artifact_mode == "delivery" and draft_folder.exists() and not formal_folder.exists():
            shutil.move(str(draft_folder), str(formal_folder))
        print("Ember task gate: BLOCKED")
        print(f"- reopen rolled back: {type(exc).__name__}: {exc}")
        return 1

    print("Ember task gate: REOPEN PASS")
    print(f"- task: {active_card}")
    if artifact_mode == "delivery":
        print(f"- delivery: {draft_folder}")
    for raw_path in args.artifact:
        target = Path(raw_path).expanduser().resolve(strict=False)
        print(f"- revision target: {draft_folder / target.relative_to(formal_folder.resolve(strict=False))}")
    return 0


def command_preflight(args: argparse.Namespace) -> int:
    task_path, text, errors = validate_task(args.task_id)
    if getattr(args, "continuation", False) and task_path and top_value(text, "type") == "gstudio_task":
        errors.extend(error for error in task_body_structure_errors(text) if error not in errors)
    if not errors:
        if sync_error := sync_workbench_index(task_path):
            errors.append(sync_error)
    if errors:
        print("Ember task gate: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Ember task gate: PREFLIGHT PASS")
    print(f"- task: {task_path}")
    return 0


def command_finalize(args: argparse.Namespace) -> int:
    task_path, text, errors = validate_task(args.task_id)
    if FORBIDDEN_ROOT.exists() and any(FORBIDDEN_ROOT.iterdir()):
        errors.append(f"forbidden directory is non-empty: {FORBIDDEN_ROOT}")

    if not args.artifact:
        errors.append("at least one --artifact is required")
    for raw_path in args.artifact:
        path = Path(raw_path).expanduser()
        ok, reason = allowed_artifact(
            path,
            args.task_id,
            text,
            system_change=args.system_change,
        )
        if not ok:
            errors.append(f"{path}: {reason}")

    if errors:
        print("Ember task gate: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1

    if sync_error := sync_workbench_index(task_path):
        print("Ember task gate: BLOCKED")
        print(f"- {sync_error}")
        return 1

    print("Ember task gate: FINALIZE PASS")
    print(f"- task: {task_path}")
    for artifact in args.artifact:
        print(f"- artifact: {artifact}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ember task-card execution gate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--task-id", required=True)
    preflight.add_argument(
        "--continuation",
        action="store_true",
        help="require the current structured body before continuing an existing task",
    )
    preflight.set_defaults(func=command_preflight)

    reopen = subparsers.add_parser("reopen-for-revision")
    reopen.add_argument("--task-id", required=True)
    reopen.add_argument("--artifact", action="append", default=[])
    reopen.add_argument("--reason", required=True)
    reopen.set_defaults(func=command_reopen_for_revision)

    promote = subparsers.add_parser("promote-delivery")
    promote.add_argument("--task-id", required=True)
    promote.add_argument("--organization-task-id", required=True)
    promote.set_defaults(func=command_promote_delivery)

    complete = subparsers.add_parser("complete-task")
    complete.add_argument("--task-id", required=True)
    complete.add_argument("--organization-task-id", required=True)
    complete.set_defaults(func=command_complete_task)

    finish_weekly = subparsers.add_parser("finalize-weekly-organization")
    finish_weekly.add_argument("--task-id", required=True)
    finish_weekly.add_argument("--run-id", required=True)
    finish_weekly.set_defaults(func=command_finalize_weekly_organization)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--task-id", required=True)
    finalize.add_argument("--artifact", action="append", default=[])
    finalize.add_argument("--system-change", action="store_true")
    finalize.set_defaults(func=command_finalize)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
