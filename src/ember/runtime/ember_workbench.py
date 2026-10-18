#!/usr/bin/env python3
"""Read-only views and allowlisted local actions for the Ember workbench."""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root

import datetime
import difflib
import base64
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlsplit

from . import ember_task as tasks
from .ember_project import load_work_categories
from . import ember_system_bridge as system_bridge
from . import ember_archive_index as archive_index
from . import ember_archive_backup_audit as archive_backup_audit
from . import ember_archive_inbox as archive_inbox
from . import ember_archive_queue as archive_queue
from . import ember_agent
from . import ember_executor_settings as executor_settings
from . import ember_opencode
from . import ember_organization
from . import ember_publish
from . import ember_review_views as review_views
from .ember_prompt_catalog import render_prompt as render_catalog_prompt
from . import weekly_task_review
from . import check_skill_health
from .ember_workbench_assets import ARCHIVE_CSS, ARCHIVE_JS, BRAND_MARK_PATH, BRAND_MARK_SVG, CSS, EMBER_FAVICON_SVG, EMBER_MARK_PATH, EXECUTION_CONFIRM_JS, PROJECT_NAVIGATION_JS, SIDEBAR_STATE_JS, STATIC_ASSETS, STATIC_CONTENT_TYPES, TASK_DETAIL_CSS, TASK_DETAIL_JS, asset_version
from .time_format import format_display_time, parse_sort_datetime
from .workspace_paths import archive_inbox_root, current_environment, current_environment_name, delivery_root, downloads_root, equivalent_path_strings, local_config_root, shared_workspace_root, task_inputs_root, workspace_inbox_root
from .ember_task_inputs import parse_inputs
from ..ember_ui.markdown import inline as _inline, markdown_to_html
from ..ember_ui.marks import brand_mark_svg, execution_confirm_button
from ..ember_ui.pages import home as home_page, library as library_page, project as project_page, projects as projects_page, review as review_page, settings as settings_page, shell as shell_page, system as system_page, task_detail

ROOT = _deployment_root()
EXECUTION_REGISTRY_PATH = ROOT / "config" / "mcp-integrations" / "registry.json"


CONFIG_PATH = ROOT / "config" / "ember-workbench.json"
DEFAULT_PROJECT_PRIORITIES_PATH = ROOT / "config" / "project-priorities.json"
PROJECT_PRIORITIES_PATH = Path(ember_env("EMBER_PROJECT_VIEW_CONFIG") or local_config_root() / "project-view.json").expanduser()
PROJECT_BOARD_ROOT = shared_workspace_root() / "项目"
ARCHIVE_OPERATION_LOG = shared_workspace_root() / "管理中心" / "归档管理" / "归档记录" / "资料归档记录.md"
WORKSPACE_INBOX_FOLDERS = ("可删除",)
EXTERNAL_DRIVE_ROOT = Path(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("external_drive_root", str(ROOT / "external-inputs")))
SOURCE_CACHE_ROOT = ROOT / "task-cards" / "source-cache"
DOCUMENT_PREVIEW_CACHE_ROOT = SOURCE_CACHE_ROOT / "document-previews"
DOCUMENT_PREVIEW_LOCK = threading.Lock()
WORKSPACE_INBOX_CACHE = SOURCE_CACHE_ROOT / "workspace-inbox-root.json"
HOME_SEARCH_INDEX_PATH = local_config_root() / "home-search-index.json"
HOME_SEARCH_INDEX_SCHEMA = 3
HOME_SEARCH_INDEX_LOCK = threading.RLock()
HOME_SEARCH_INDEX_BUILD_LOCK = threading.Lock()
_HOME_SEARCH_INDEX_CACHE: dict[str, object] | None = None
_HOME_SEARCH_INDEX_REFRESHING = False
STATUS_LABEL = {"active": "进行中", "waiting_user": "待确认", "blocked": "阻塞", "completed": "已完成"}
TYPE_LABEL = {"text": "文字", "image": "图片", "video": "视频", "audio": "音频", "data": "数据", "system": "系统", "organize": "整理", "archive": "归档", "mixed": "混合"}
NEW_TASK_LABEL = {"qa": "问答", "document": "文档", "image": "图片", "video": "视频", "workflow": "工作流", "task_group": "任务主线", "generic": "开始任务"}
NEW_TASK_DESCRIPTION = {
    "qa": "讨论、判断和方案建议；是否建卡由任务门禁决定。",
    "document": "文案、脚本、报告、表格、演示与翻译。",
    "image": "海报、封面、长图、生成图片与改图。",
    "video": "下载、转写、分析、分镜和视频制作。",
    "workflow": "跨多个阶段的采集、制作、交付或归档流程。",
    "task_group": "从已发生的零散任务中提炼持续任务主线；以后默认从主线继续。",
    "generic": "通用任务入口；具体类型由 AI 根据需求判断。",
}
NEW_TASK_SHORT_DESCRIPTION = {
    "qa": "提问与判断",
    "document": "文案与报告",
    "image": "海报与长图",
    "video": "分析与制作",
    "workflow": "多阶段流程",
    "task_group": "提炼任务主线",
    "generic": "AI 根据需求判断类型",
}


def config() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def executor_config() -> dict[str, dict[str, object]]:
    configured = ember_env("EMBER_EXECUTOR_CONFIG")
    path = Path(configured).expanduser() if configured else local_config_root() / "executors.json"
    if not path.exists():
        path = ROOT / "config" / "ember-executors.example.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def executor_status() -> dict[str, dict[str, object]]:
    if ember_env("EMBER_CENTRAL_MODE") == "1":
        return {
            "codex": {"label": "Codex", "configured": True, "resolved": "默认复制提示词；可选远程执行桥"},
            "opencode": {"label": "OpenCode", "configured": True, "resolved": "默认复制提示词；可选远程执行桥"},
        }
    settings = executor_config()
    try:
        defaults = json.loads((ROOT / "config" / "ember-executors.example.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        defaults = {}
    result: dict[str, dict[str, object]] = {}
    codex = {**(defaults.get("codex", {}) if isinstance(defaults.get("codex"), dict) else {}), **settings.get("codex", {})}
    candidates = codex.get("application_candidates") if isinstance(codex.get("application_candidates"), list) else []
    if not candidates and str(codex.get("bundle_id") or "") == "com.openai.codex":
        candidates = ["/Applications/Codex.app", "/Applications/ChatGPT.app"]
    if codex.get("path"):
        try:
            codex_path = str(executor_settings.validate_software_path("codex", codex["path"]))
        except executor_settings.SettingsError:
            codex_path = ""
    else:
        codex_path = next((str(Path(str(value)).expanduser()) for value in candidates if Path(str(value)).expanduser().exists()), "")
    result["codex"] = {**codex, "configured": bool(codex_path), "resolved": codex_path or "未检测到 Codex 应用"}
    opencode = {**(defaults.get("opencode", {}) if isinstance(defaults.get("opencode"), dict) else {}), **settings.get("opencode", {})}
    try:
        command = str(ember_opencode.opencode_command())
        configured = True
    except ember_opencode.OpenCodeIntegrationError as exc:
        command, configured = str(exc), False
    result["opencode"] = {**opencode, "configured": configured, "resolved": command}
    for entry in executor_settings.read_settings().get("executors", []):
        try:
            actual = executor_settings.executor_definition(entry["id"])
            result[entry["id"]] = {"label": actual["label"], "configured": True, "resolved": actual["path"]}
        except executor_settings.SettingsError:
            result[entry["id"]] = {"label": entry["label"], "configured": False, "resolved": "已登记的软件路径不可用"}
    return result


def executor_model_label(executor: str) -> str:
    item = executor_config().get(executor, {})
    return str(item.get("model_label") or "未配置模型名称")


def execution_environment(fixed_executor: str = "") -> dict[str, object]:
    """Read a saved local route without authentication probes or execution."""
    settings = executor_settings.read_settings()
    executor = fixed_executor or str(settings.get("default_executor") or "")
    ready = bool(fixed_executor) or bool(settings.get("ready"))
    error = "" if fixed_executor else str(settings.get("error") or "")
    entries = {entry["id"]: entry for entry in settings.get("executors", [])}
    if not fixed_executor and executor not in entries:
        executor, ready = "", False
    status = executor_status().get(executor, {}) if executor else {}
    if executor and not status.get("configured"):
        ready, error = False, "默认执行器尚未安装或路径不可用，请在设置页核对。"
    label = str(status.get("label") or entries.get(executor, {}).get("label") or "未配置")
    path = str(status.get("resolved") or "") if fixed_executor else str(entries.get(executor, {}).get("path") or "")
    return {
        "executor": executor, "executor_label": label, "executor_path": path,
        "executor_ready": ready, "executor_error": error, "executor_fixed": bool(fixed_executor),
    }


def valid_executor(executor: str) -> bool:
    """Known governed adapters or an explicitly registered local program."""
    if executor in {"codex", "opencode", "kimi"}:
        return True
    try:
        executor_settings.executor_definition(executor)
        return True
    except executor_settings.SettingsError:
        return False


def collect_records() -> list[dict[str, object]]:
    # The workbench is a metadata consumer.  Its local index is refreshed by
    # task preflight/finalize and must be the primary read path, especially on
    # the MacBook where live task cards sit behind the NAS SMB mount. A live scan
    # remains only as a bootstrap fallback for a missing or empty index.
    #
    # The central service is different: /data is the NAS-local canonical
    # workspace, while /app/task-cards is only the image build snapshot.  Never
    # let that snapshot hide task changes made after the image was built.
    if ember_env("EMBER_CENTRAL_MODE") == "1":
        records = [tasks.task_record(root, state, path) for root, state, path in tasks.task_files()]
        records.extend(tasks.parse_ledger_records())
        return records
    indexed = tasks.load_index()
    if indexed:
        return indexed
    records = [tasks.task_record(root, state, path) for root, state, path in tasks.task_files()]
    records.extend(tasks.parse_ledger_records())
    return records


def skill_catalog() -> list[dict[str, object]]:
    try:
        payload = json.loads(check_skill_health.MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return [item for item in payload.get("skills", []) if isinstance(item, dict) and item.get("name")]


def native_execution_registry() -> dict[str, list[dict[str, object]]]:
    """Load only integrations explicitly registered by Ember.

    Client-owned MCP/plugin inventories are deliberately not discovery sources.
    """
    try:
        payload = json.loads(EXECUTION_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"mcp_integrations": [], "tool_integrations": []}
    result: dict[str, list[dict[str, object]]] = {}
    for key in ("mcp_integrations", "tool_integrations"):
        values = payload.get(key)
        result[key] = [dict(item) for item in values if isinstance(item, dict) and item.get("id")] if isinstance(values, list) else []
    return result


def health_presentation(
    state: dict[str, object] | None,
    *,
    health_profile: str = "",
) -> dict[str, str]:
    """Translate machine health facts into consistent user-facing states."""
    item = state if isinstance(state, dict) else {}
    raw_status = str(item.get("status") or "")
    missing = [str(value) for value in item.get("missing", [])] if isinstance(item.get("missing"), list) else []
    note = str(item.get("note") or "").strip()
    if not raw_status:
        return {
            "key": "unverified",
            "label": "未检测",
            "detail": "健康检查尚未返回结果",
        }
    if raw_status == "available":
        key, label = "available", "可用"
    elif raw_status == "conditional" and health_profile == "imagegen":
        key, label = "executor-provided", "随执行器提供"
    elif raw_status == "conditional":
        key, label = "needs-config", "需配置"
    else:
        key, label = "unavailable", "不可用"
    if missing:
        detail = f"缺少依赖：{'、'.join(missing)}"
    elif note:
        detail = note
    else:
        detail = "依赖已就绪"
    return {"key": key, "label": label, "detail": detail}


def snapshot_health_state(
    snapshot: dict[str, object],
    *,
    health_profile: str,
    skill_name: str = "",
) -> dict[str, object] | None:
    """Resolve one health fact from a previously collected local snapshot."""
    profiles = snapshot.get("profiles")
    if isinstance(profiles, dict):
        state = profiles.get(health_profile)
        if isinstance(state, dict):
            return state
    entries = snapshot.get("entries")
    if isinstance(entries, dict) and skill_name:
        state = entries.get(skill_name)
        if isinstance(state, dict):
            return state
    return None


def skill_usage_stats(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    now = datetime.datetime.now(datetime.timezone.utc)
    result: dict[str, dict[str, object]] = {}
    for record in records:
        used = record.get("skills_used")
        if isinstance(used, str):
            used = [value.strip() for value in used.strip("[]").split(",") if value.strip()]
        if not isinstance(used, list):
            continue
        updated = _parse_record_datetime(record)
        for raw_name in used:
            name = str(raw_name).strip().strip("'\"")
            if not name:
                continue
            item = result.setdefault(name, {"total": 0, "days_30": 0, "last_used": None, "last_task": ""})
            item["total"] = int(item["total"]) + 1
            if updated and now - updated <= datetime.timedelta(days=30):
                item["days_30"] = int(item["days_30"]) + 1
            if updated and (item["last_used"] is None or updated > item["last_used"]):
                item["last_used"] = updated
                item["last_task"] = str(record.get("task_id") or "")
    return result


def _safe_nonnegative_int(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def skill_usage_index() -> tuple[list[dict[str, object]], dict[str, object]]:
    """Read Skill usage from the local task index without an SMB fallback."""
    status = task_index_sync_status()
    expected = _safe_nonnegative_int(status.get("record_count"))
    try:
        records = [record for record in tasks.load_index() if isinstance(record, dict)]
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError):
        return [], {
            "state": "repairing",
            "message": "本地任务索引暂时无法读取；关联任务统计暂不显示，后台同步将自动重建。",
            "record_count": 0,
            "expected_count": expected,
        }
    actual = len(records)
    sync_state = str(status.get("state") or "")
    if not records and expected > 0:
        state = "repairing"
        message = "本地任务索引与同步记录不一致；关联任务统计暂不显示，后台同步将自动重建。"
    elif sync_state == "error":
        if records:
            state = "stale"
            message = "任务索引最近同步异常；当前显示上一次成功缓存中的关联任务统计。"
        else:
            state = "unavailable"
            message = "任务索引最近同步异常且没有可用缓存；关联任务统计暂不显示。"
    elif records and expected and actual != expected:
        state = "stale"
        message = f"任务索引正在校准；当前缓存 {actual} 条，同步记录 {expected} 条。"
    elif records:
        state = "ready"
        message = f"关联任务统计来自本地任务索引，共 {actual} 条记录。"
    else:
        state = "empty"
        message = "本地任务索引暂无记录；当前没有可统计的 Skill 关联任务。"
    return records, {
        "state": state,
        "message": message,
        "record_count": actual,
        "expected_count": expected,
    }


def skill_is_standardized(skill: dict[str, object]) -> bool:
    path = ROOT / "skills" / str(skill.get("path") or "")
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeError):
        return False
    frontmatter, closed = text.partition("\n---\n")[0], "\n---\n" in text
    required_keys = ("name:", "version:", "description:", "triggers:", "tools:", "mutating:", "writes_pages:")
    required_headings = ("## Contract", "## When to Use", "## References", "## Phases", "## Output Format", "## Anti-Patterns", "## Tools Used")
    return closed and all(key in frontmatter for key in required_keys) and all(heading in text for heading in required_headings)


def task_index_sync_status() -> dict[str, object]:
    path = tasks.TASK_INDEX_ROOT / "task-index-sync-status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def task_index_sync_badge(status: dict[str, object] | None = None) -> str:
    status = task_index_sync_status() if status is None else status
    if not status:
        return '<span class="sync-state pending" title="任务索引自动刷新尚未安装或还未完成首次检查">索引待检查</span>'
    state = str(status.get("state") or "")
    checked = html.escape(format_display_time(status.get("last_check_at")) or "未记录")
    count = _safe_nonnegative_int(status.get("record_count"))
    if state == "error":
        error = html.escape(str(status.get("error") or "共享任务目录暂时不可用"))
        detail = f"任务索引刷新异常 · 最近检查 {checked} · {error}"
        return f'<span class="sync-state error" title="{detail}">索引异常</span>'
    detail = f"任务索引已自动同步 · {count} 条记录 · 最近检查 {checked}"
    return f'<span class="sync-state" title="{detail}">索引已同步 · {count}</span>'


def task_index_sync_alert(status: dict[str, object] | None = None) -> str:
    status = task_index_sync_status() if status is None else status
    if str(status.get("state") or "") != "error":
        return ""
    checked = html.escape(format_display_time(status.get("last_check_at")) or "未记录")
    error = html.escape(str(status.get("error") or "共享任务目录暂时不可用"))
    return f'<div class="notice error">任务索引刷新异常 · 保留最近成功缓存 · 最近检查 {checked} · {error}</div>'


def record_map() -> dict[str, dict[str, object]]:
    return {str(record["task_id"]): record for record in collect_records()}


def project_items() -> dict[str, dict[str, object]]:
    registry, _ = tasks.project_registry()
    return registry


def task_scope_title(project: str, fallback: str = "") -> str:
    """Label task scopes without promoting independent into a formal project."""
    if project == "independent":
        scope = tasks.load_projects().get("independent_scope", {})
        if isinstance(scope, dict):
            return str(scope.get("title") or "独立任务")
        return "独立任务"
    item = project_items().get(project, {})
    return str(item.get("title") or fallback or project)


def project_entry_target(project: str, entry: str) -> tuple[str, str] | None:
    """Resolve only a registry-declared project entry; never accept a raw path."""
    item = project_items().get(project)
    entries = item.get("entries") if isinstance(item, dict) and isinstance(item.get("entries"), dict) else {}
    raw = entries.get(entry)
    if isinstance(raw, dict):
        environments = raw.get("environments") if isinstance(raw.get("environments"), dict) else {}
        value = str(raw.get("value") or environments.get(current_environment_name()) or "")
        declared_type = str(raw.get("type") or "")
    else:
        value, declared_type = str(raw or ""), ""
    if not value:
        return None
    if declared_type == "url" or value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:"):
        if not (value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:")):
            return None
        return "url", value
    path = Path(value).expanduser().resolve()
    return ("path", str(path)) if path.exists() else None


def formal_project_slugs() -> list[str]:
    """Return registered projects in registry order; independent is excluded."""
    return list(project_items())


def project_overview_scope_slugs() -> list[str]:
    """Return task scopes that own cards and focus labels in the project view."""
    scopes = formal_project_slugs()
    independent = tasks.load_projects().get("independent_scope", {})
    if isinstance(independent, dict) and independent.get("is_project") is False:
        slug = str(independent.get("slug") or "")
        if slug:
            scopes.append(slug)
    return list(dict.fromkeys(scopes))


def project_view_state() -> dict[str, object]:
    """Read manually curated project ordering and important-task state."""
    for path in (PROJECT_PRIORITIES_PATH, DEFAULT_PROJECT_PRIORITIES_PATH):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _write_project_view_state(payload: dict[str, object]) -> None:
    tasks.atomic_write(PROJECT_PRIORITIES_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _project_view_state_for_update() -> dict[str, object]:
    if not PROJECT_PRIORITIES_PATH.exists():
        return project_view_state()
    try:
        payload = json.loads(PROJECT_PRIORITIES_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    raise ValueError("本机项目偏好不可读，未覆盖现有数据。")


def project_favorites() -> list[str]:
    saved = project_view_state().get("favorite_project_ids", [])
    projects = project_items()
    return list(dict.fromkeys(slug for slug in saved if isinstance(slug, str) and slug in projects)) if isinstance(saved, list) else []


def set_project_favorite(project: str, favorite: bool) -> None:
    """Change only this machine's project shortcuts, never task priority or order."""
    if project not in project_items():
        raise ValueError("只能收藏已登记的具体项目。")
    from .ember_central_store import _locked
    with _locked(PROJECT_PRIORITIES_PATH):
        payload = _project_view_state_for_update()
        saved = payload.get("favorite_project_ids", [])
        favorites = list(dict.fromkeys(slug for slug in saved if isinstance(slug, str) and slug in project_items())) if isinstance(saved, list) else []
        if favorite and project not in favorites:
            favorites.append(project)
        elif not favorite:
            favorites = [slug for slug in favorites if slug != project]
        payload["favorite_project_ids"] = favorites
        _write_project_view_state(payload)


def project_priorities() -> dict[str, list[str]]:
    """Return shared current-focus task ids grouped by their canonical project."""
    state = review_view_state()
    records = record_map()
    result: dict[str, list[str]] = {}
    for task_id in state.get("focus_task_ids", []):
        record = records.get(str(task_id))
        if not record:
            continue
        project = str(record.get("project") or "")
        if project:
            result.setdefault(project, []).append(str(task_id))
    return result


def review_view_state() -> dict[str, object]:
    """Load shared task views after importing this machine's legacy focus once."""
    return review_views.migrate_local_focus(PROJECT_PRIORITIES_PATH, current_environment_name())


def review_custom_views() -> list[dict[str, object]]:
    state = review_view_state()
    return [dict(view) for view in state.get("views", []) if isinstance(view, dict)]


def project_display_order() -> list[str]:
    """Preserve local card order for formal projects plus independent tasks."""
    registered = list(dict.fromkeys(formal_project_slugs() + project_overview_scope_slugs()))
    saved = project_view_state().get("project_order")
    ordered = [str(slug) for slug in saved if str(slug) in registered] if isinstance(saved, list) else []
    return list(dict.fromkeys(ordered + registered))


def set_project_display_order(project_order: list[str]) -> None:
    """Persist overview-card order without promoting independent to a project."""
    normalized = list(dict.fromkeys(str(slug) for slug in project_order))
    registered = project_overview_scope_slugs()
    if set(normalized) != set(registered) or len(normalized) != len(registered):
        raise ValueError("卡片排序不完整或包含无效范围。")
    from .ember_central_store import _locked
    with _locked(PROJECT_PRIORITIES_PATH):
        payload = _project_view_state_for_update()
        payload.update({"version": 1, "project_order": normalized})
        _write_project_view_state(payload)


def set_project_task_priority(project: str, task_id: str, important: bool) -> None:
    """Persist manual priority without changing the task lifecycle state."""
    record = record_map().get(task_id)
    if not record or str(record.get("project") or "") != project:
        raise ValueError("任务与提交范围不匹配。")
    review_views.set_focus_task(task_id, important)


def _replace_frontmatter_list(text: str, key: str, values: list[str]) -> str:
    block = f"{key}:\n" + "".join(f"  - {value}\n" for value in values)
    pattern = rf"^{re.escape(key)}:\s*$\n(?:  - .*\n)*"
    if re.search(pattern, text, re.MULTILINE):
        return re.sub(pattern, block, text, count=1, flags=re.MULTILINE)
    marker = "\n---\n"
    return text.replace(marker, "\n" + block + "---\n", 1)


def _group_delivery_folder(record: dict[str, object]) -> Path:
    folder = str(record.get("delivery_folder") or "")
    target = (shared_workspace_root() / folder).resolve()
    expected_root = delivery_root().resolve()
    if not folder or not _within(target, expected_root) or target.name != str(record.get("task_id") or ""):
        raise ValueError("任务主线交付目录无效。")
    return target


def related_task_summary(record: dict[str, object]) -> str:
    """Summarize what a related task did without adding group-role metadata."""
    source = Path(str(record.get("canonical_path") or ""))
    if source.is_file():
        text = source.read_text(encoding="utf-8", errors="replace")
        _, body = tasks.frontmatter(text)
        match = re.search(
            r"^##\s+(?:任务结果|完成结果|执行结果|合并结果|产出物|结果)\s*$\n(.*?)(?=^##\s+|\Z)",
            body,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            for line in match.group(1).splitlines():
                value = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line.strip())
                value = re.sub(r"[`*_]", "", value)
                value = re.sub(r"\s+", " ", value).strip()
                if value and not re.match(r"^(?:https?://|/Volumes/|/Users/)", value):
                    return value[:240].rstrip() + ("…" if len(value) > 240 else "")
    return re.sub(
        r"\s+", " ", str(record.get("description") or record.get("title") or record.get("task_id") or "")
    ).strip()


def refresh_task_group_files(task_id: str) -> None:
    records = record_map()
    group = records.get(task_id)
    if not group or group.get("task_kind") != "task_group":
        raise ValueError("目标不是任务主线。")
    folder = _group_delivery_folder(group)
    folder.mkdir(parents=True, exist_ok=True)
    source = tasks.find_task(task_id)
    if not source:
        raise ValueError("任务主线卡不存在。")
    text = source[2].read_text(encoding="utf-8", errors="replace")
    _, body = tasks.frontmatter(text)
    description = tasks.first_section_paragraph(body) or str(group.get("description") or group.get("title") or task_id)
    explanation = (
        f"# {group.get('title') or task_id}\n\n"
        f"- 任务主线 ID：`{task_id}`\n"
        f"- 项目：{group.get('project_title') or group.get('project')}\n"
        f"- 状态：{group.get('status')}\n\n"
        f"## 任务主线说明\n\n{description}\n\n"
        "本卡是以后继续该任务的默认入口；相关任务保留原卡、生命周期和交付，本目录只保存主线说明、相关索引和主线汇总成果。\n"
    )
    lines = [
        f"# {group.get('title') or task_id}｜相关任务索引", "",
        f"更新时间：{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}", "",
        "| 相关任务 | 做了什么 | 状态 | 任务入口 | 交付入口 |", "|---|---|---|---|---|",
    ]
    for related_id in group.get("related_task_ids") or []:
        related = records.get(str(related_id))
        if not related:
            lines.append(f"| `{related_id}` | 任务卡缺失 | 缺失 | - | - |")
            continue
        card = str(related.get("canonical_path") or "")
        delivery = resolve_delivery_folder(related)
        delivery_link = f"[打开](<{delivery}>)" if delivery else "无独立交付文件"
        summary = related_task_summary(related)
        summary = summary.replace("|", "\\|")
        lines.append(
            f"| {related.get('task_name') or related.get('title') or related_id} | {summary} | "
            f"{related.get('status')} | [查看](<{card}>) | {delivery_link} |"
        )
    if len(lines) == 7:
        lines.append("| _暂无相关任务_ | - | - | - | - |")
    (folder / "00_任务组说明.md").write_text(explanation, encoding="utf-8")
    (folder / "01_关联任务索引.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_task_group_relations(task_id: str, related_task_ids: list[str], action: str) -> None:
    found = tasks.find_task(task_id)
    if not found or found[1] != "active":
        raise ValueError("只能修改进行中的任务主线。")
    records = record_map()
    group = records.get(task_id)
    if not group or group.get("task_kind") != "task_group":
        raise ValueError("目标不是任务主线。")
    valid = []
    for related_id in related_task_ids:
        related_id = related_id.strip()
        if not related_id or related_id == task_id:
            continue
        related = records.get(related_id)
        if not related or related.get("record_type") != "task_card":
            raise ValueError(f"任务不存在：{related_id}")
        if related.get("task_kind") == "task_group":
            raise ValueError("任务主线不能关联另一条任务主线。")
        if action in {"add", "replace"} and str(related.get("project") or "") != str(group.get("project") or ""):
            raise ValueError("相关任务与任务主线必须属于同一项目。")
        other_groups = [
            str(candidate.get("task_id") or "") for candidate in records.values()
            if candidate.get("task_kind") == "task_group"
            and str(candidate.get("task_id") or "") != task_id
            and related_id in [str(value) for value in candidate.get("related_task_ids") or []]
        ]
        if action in {"add", "replace"} and other_groups:
            raise ValueError(f"任务已关联其他任务主线：{', '.join(other_groups)}")
        valid.append(related_id)
    current = [str(value) for value in group.get("related_task_ids") or []]
    if action == "add":
        updated = list(dict.fromkeys(current + valid))
    elif action == "remove":
        remove = set(valid)
        updated = [value for value in current if value not in remove]
    elif action == "replace":
        updated = list(dict.fromkeys(valid))
    else:
        raise ValueError("不支持的任务主线操作。")
    path = found[2]
    text = path.read_text(encoding="utf-8", errors="replace")
    text = _replace_frontmatter_list(text, "related_task_ids", updated)
    text = re.sub(r"^member_task_ids:\s*$\n(?:  - .*\n)*", "", text, count=1, flags=re.MULTILINE)
    timestamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds").replace("T", " ")
    text = re.sub(r"^updated_at:\s*.*$", f'updated_at: "{timestamp}"', text, count=1, flags=re.MULTILINE)
    action_label = {"add": "增加", "remove": "移除", "replace": "更新"}[action]
    text = tasks.prepend_execution_log_entry(
        text,
        f"{timestamp}：相关任务已{action_label}：{', '.join(updated) or '无'}。",
    )
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    tasks.sync_index_records()
    refresh_task_group_files(task_id)
    tasks.sync_index_records()


def task_source(task_id: str) -> Path | None:
    if ember_env("EMBER_CENTRAL_MODE") == "1":
        found = tasks.find_task(task_id)
        if found:
            return found[2].resolve()
    for state in ("active", "completed"):
        cached = SOURCE_CACHE_ROOT / "tasks" / state / f"{task_id}.md"
        if cached.exists():
            return cached.resolve()
    found = tasks.find_task(task_id)
    if found:
        return found[2].resolve()
    return None


def project_source(project: str) -> Path | None:
    path = (PROJECT_BOARD_ROOT / project / "项目看板.md").resolve()
    if _readable_file(path, PROJECT_BOARD_ROOT.resolve()):
        return path
    cached = (SOURCE_CACHE_ROOT / "projects" / project / "项目看板.md").resolve()
    return cached if _readable_file(cached, SOURCE_CACHE_ROOT.resolve()) else None


def project_description_source(project: str) -> Path | None:
    """Resolve the readable shared Ember description; never return a cache."""
    path = allowed_source("project", project)
    return path if path and _readable_file(path, PROJECT_BOARD_ROOT) else None


def project_intro_source(project: str) -> Path | None:
    """Read the registered Ember card or its read-only metadata mirror."""
    return project_source(project) if project in project_items() else None


def project_intro_history_path(project: str) -> Path:
    """Return the sidecar JSON path that stores organization history for a project intro."""
    return PROJECT_BOARD_ROOT / project / "organization_history.json"


def project_intro_history_cache_path(project: str) -> Path:
    """Return the read-only runtime mirror used when LaunchAgent TCC blocks Documents."""
    return SOURCE_CACHE_ROOT / "projects" / project / "organization_history.json"


def project_intro_maintenance_task_id(project: str) -> str:
    """Stable long-running task that owns project-intro maintenance rounds."""
    return f"20260713-{project}-project-intro-maintenance"


def load_project_intro_history(project: str) -> list[dict[str, object]]:
    canonical = project_intro_history_path(project).resolve()
    cached = project_intro_history_cache_path(project).resolve()
    for path, root in ((canonical, PROJECT_BOARD_ROOT.resolve()), (cached, SOURCE_CACHE_ROOT.resolve())):
        if not _readable_file(path, root):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return payload
        except (json.JSONDecodeError, OSError):
            continue
    return []


def save_project_intro_history(project: str, history: list[dict[str, object]]) -> None:
    path = project_intro_history_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_markdown_sections(body: str) -> dict[str, str]:
    """Split Markdown body into sections keyed by heading text (without #)."""
    sections: dict[str, str] = {}
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    cursor = 0
    current_title = ""
    for match in pattern.finditer(body):
        if current_title:
            sections[current_title] = body[cursor:match.start()].strip()
        current_title = match.group(1).strip()
        cursor = match.end()
    if current_title:
        sections[current_title] = body[cursor:].strip()
    return sections


def _context_managed_block(value: str, name: str) -> str:
    match = re.search(
        rf"<!--\s*ebrain:{re.escape(name)}:begin\s*-->(.*?)"
        rf"<!--\s*ebrain:{re.escape(name)}:end\s*-->",
        str(value or ""), flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _context_current_markdown(value: str, *, project: bool=False) -> str:
    from .pages.common import _context_current_markdown as _present
    return _present(value, project=project)


def _context_timeline_markdown(value: str) -> str:
    from .pages.common import _context_timeline_markdown as _present
    return _present(value)


def parse_project_intro(path: Path) -> dict[str, object]:
    """Parse a project introduction Markdown file into structured parts."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = tasks.frontmatter(text)
    sections = _parse_markdown_sections(body)
    page_type_match = re.search(r"^type:\s*([^\s#]+)", fm, flags=re.MULTILINE)
    layout_match = re.search(r"^layout_id:\s*([^\s#]+)", fm, flags=re.MULTILINE)
    page_type = page_type_match.group(1).strip("'\"") if page_type_match else ""
    layout_id = layout_match.group(1).strip("'\"") if layout_match else ""
    if page_type == "gstudio_project":
        current_heading = next((heading for heading in ("项目总览", "当前概况") if heading in sections), "")
        entry_heading = next((heading for heading in ("工作位置与入口", "系统入口") if heading in sections), "")
        return {
            "frontmatter_text": fm, "body": body, "sections": sections,
            "page_type": page_type, "layout_id": "ember-project",
            "supported": bool(current_heading), "current_heading": current_heading,
            "current_state": sections.get(current_heading, "").strip(),
            "entry_heading": entry_heading,
            "entries": sections.get(entry_heading, "").strip(),
            "scope": sections.get("范围与要求", "").strip(),
            "stage": sections.get("当前阶段", "").strip(),
            "timeline": sections.get("时间线", "").strip(),
        }
    # Reader-only parsing of historical Context evidence remains available;
    # project routing and maintenance never resolve an EBrain page.
    expected_layout = {"project": "project-v3", "program": "program-v2"}.get(page_type, "")
    current_heading = "项目总览" if page_type == "project" else "当前概况" if page_type == "program" else ""
    supported = bool(expected_layout and layout_id == expected_layout)
    current_source = sections.get(current_heading, "") if supported else ""
    return {
        "frontmatter_text": fm,
        "body": body,
        "sections": sections,
        "page_type": page_type,
        "layout_id": layout_id,
        "supported": supported,
        "current_heading": current_heading,
        "current_state": _context_current_markdown(current_source, project=page_type == "project"),
        "timeline": _context_timeline_markdown(sections.get("时间线", "")) if supported else "",
    }


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _readable_file(path: Path, root: Path) -> bool:
    """Check containment and real readability, not only path visibility.

    macOS LaunchAgents may see a Documents path while TCC still denies reads.
    """
    if not path.exists() or not _within(path, root):
        return False
    try:
        with path.open("rb") as handle:
            handle.read(1)
        return True
    except OSError:
        return False


def resolve_delivery_folder(record: dict[str, object]) -> Path | None:
    folder = str(record.get("delivery_folder") or "").strip()
    candidates: list[Path] = []
    if folder:
        raw = Path(folder).expanduser()
        candidates.append(raw if raw.is_absolute() else shared_workspace_root() / raw)
    for value in record.get("paths", []) or []:
        raw = Path(str(value)).expanduser()
        candidates.append(raw if raw.is_dir() else raw.parent)
    for candidate in candidates:
        for value in equivalent_path_strings(candidate):
            local = Path(value).expanduser()
            if local.exists() and local.is_dir() and _within(local, delivery_root()):
                return local.resolve()
    return None


def allowed_source(kind: str, identifier: str) -> Path | None:
    if kind == "task":
        record = record_map().get(identifier)
        path = Path(str(record.get("canonical_path") or "")).expanduser().resolve() if record else None
        return path if path and _within(path, shared_workspace_root()) else None
    if kind == "project":
        path = (PROJECT_BOARD_ROOT / identifier / "项目看板.md").resolve()
        return path if identifier in project_items() and _within(path, PROJECT_BOARD_ROOT) else None
    return None


def continuation_prompt(
    record: dict[str, object],
    source: Path,
    selections: list[str] | None = None,
    create_new_task: bool = False,
    user_supplement: str = "",
) -> str:
    task_id = str(record.get("task_id") or "")
    selected: list[str] = []
    for raw in selections or []:
        try:
            item = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise ValueError("交付文件选择数据无效。") from None
        if str(item.get("task_id") or "") != task_id:
            raise ValueError("所选交付文件不属于当前任务。")
        delivery_key = str(item.get("delivery") or "")
        relative_path = str(item.get("path") or "")
        path = canonical_library_delivery_path(task_id, delivery_key, relative_path)
        if not path or not path.is_file():
            raise ValueError("选择中包含无效的交付文件。")
        if str(path) not in selected:
            selected.append(str(path))
    files = "\n".join(f"  - {path}" for path in selected) if selected else "  - 未选择交付文件，本轮从任务卡本身继续。"
    project = str(record.get("project_title") or record.get("project") or "")
    focus = str(record.get("task_name") or record.get("title") or "")
    mode = "基于当前任务建立一项新的后续任务" if create_new_task else "继续当前任务"
    mode_boundary = (
        "收到要求后明确允许创建新任务卡，并把当前任务卡与所选文件登记为只读来源。"
        if create_new_task else
        "收到要求后继续当前任务，不创建新任务卡；先通过 continuation preflight，再按成果类型执行。"
    )
    success = (
        "已准确读取当前任务与全部所选文件；收到要求后，新任务保留完整来源记录，新产物进入新任务的草稿交付目录，来源文件未被覆盖或移动。"
        if create_new_task else
        "已准确读取当前任务与全部所选文件；收到要求后，同步更新当前任务卡，使实际改动、验证结果、输出路径、交付状态和执行日志都有记录。"
    )
    return render_catalog_prompt(
        "task-continuation",
        focus=focus or task_id,
        mode=mode,
        project=project or "未记录",
        task_id=task_id,
        task_card=source,
        selected_files=files,
        user_material=(f"- Evan 补充材料：\n{quote_prompt_input(user_supplement)}" if user_supplement.strip() else ""),
        mode_boundary=mode_boundary,
        success=success,
    )


def _strip_first_heading_if_title(body_html: str, title: str) -> str:
    """Remove the first H1-H3 from the preview body when it repeats the task title."""
    title_compact = "".join(title.split())
    match = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", body_html, re.DOTALL | re.IGNORECASE)
    if not match:
        return body_html
    heading_text = match.group(1)
    heading_text = re.sub(r"<[^>]+>", "", heading_text)
    heading_text = html.unescape(heading_text)
    heading_compact = "".join(heading_text.split())
    if title_compact in heading_compact or heading_compact in title_compact:
        return body_html[:match.start()] + body_html[match.end():]
    if difflib.SequenceMatcher(None, title_compact, heading_compact).ratio() >= 0.6:
        return body_html[:match.start()] + body_html[match.end():]
    return body_html


def task_preview_payload(task_id: str) -> dict[str, object] | None:
    """Return a sanitized, read-only task-card preview for the homepage."""
    record = record_map().get(task_id)
    source = task_source(task_id)
    if not record or not source:
        return None
    text = source.read_text(encoding="utf-8", errors="replace")
    _, body = tasks.frontmatter(text)
    status = str(record.get("status") or "")
    delivery = library_task_delivery(record) or {}
    related_tasks: list[dict[str, object]] = []
    if record.get("task_kind") == "task_group":
        records = record_map()
        for related_id in record.get("related_task_ids", []) or []:
            related = records.get(str(related_id))
            if not related:
                continue
            related_delivery = library_task_delivery(related) or {}
            related_tasks.append({
                "task_id": str(related_id),
                "title": str(related.get("task_name") or related.get("title") or related_id),
                "delivery_key": str(related_delivery.get("key") or ""),
                "delivery_name": str(related_delivery.get("name") or ""),
            })
    return {
        "task_id": task_id,
        "title": str(record.get("task_name") or record.get("title") or task_id),
        "description": str(record.get("description") or ""),
        "project": str(record.get("project_title") or record.get("project") or ""),
        "status": status,
        "status_label": STATUS_LABEL.get(status, status),
        "updated_at": format_display_time(record.get("updated_at")) or "未记录",
        "body_html": _strip_first_heading_if_title(
            markdown_to_html(markdown_for_html(body)),
            str(record.get("task_name") or record.get("title") or task_id),
        ),
        "detail_url": f"/tasks/{quote(task_id)}",
        "has_delivery": bool(resolve_delivery_folder(record)),
        "delivery_key": str(delivery.get("key") or ""),
        "delivery_name": str(delivery.get("name") or ""),
        "task_kind": str(record.get("task_kind") or "task"),
        "related_tasks": related_tasks,
    }


LIBRARY_DELIVERY_KINDS = {"draft": "草稿", "final": "正式交付"}
LIBRARY_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}
LIBRARY_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
LIBRARY_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
LIBRARY_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".log", ".json", ".yaml", ".yml", ".csv"}
LIBRARY_WORD_SUFFIXES = {".doc", ".docx", ".docm", ".odt", ".rtf"}
LIBRARY_SHEET_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".ods"}
LIBRARY_SLIDE_SUFFIXES = {".ppt", ".pptx", ".pptm", ".odp"}
LIBRARY_OFFICE_SUFFIXES = LIBRARY_WORD_SUFFIXES | LIBRARY_SHEET_SUFFIXES | LIBRARY_SLIDE_SUFFIXES
LIBRARY_HTML_SUFFIXES = {".html", ".htm"}


def task_input_root(task_id: str) -> Path | None:
    """Resolve one task's shared input root without accepting arbitrary paths."""
    if task_id not in record_map():
        return None
    root = (task_inputs_root() / task_id).resolve()
    allowed = task_inputs_root().resolve()
    return root if root.is_dir() and root.name == task_id and _within(root, allowed) else None


def task_input_path(task_id: str, relative_path: str = "") -> Path | None:
    root = task_input_root(task_id)
    if not root:
        return None
    relative = Path(relative_path or ".")
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (root / relative).resolve()
    return candidate if candidate.exists() and _within(candidate, root) else None


def _task_input_rows(task_id: str, task_text: str, token: str, return_to: str) -> list[dict[str, object]]:
    """Input materials for the task page; previewable snapshots get a Finder action."""
    try:
        parsed = parse_inputs(task_text)
    except ValueError:
        parsed = {"items": []}
    items = parsed.get("items") if isinstance(parsed, dict) else []
    items = items if isinstance(items, list) else []
    root = task_input_root(task_id)
    rows: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("source_locator") or "输入资料")
        storage = str(item.get("storage") or "reference")
        purpose = str(item.get("purpose") or "")
        size = int(item.get("size") or 0)
        meta = "快照" if storage == "snapshot" else "归档引用" if storage == "archive" else "外部引用"
        if size:
            meta += f" · {max(1, round(size / 1024)):,} KB"
        row: dict[str, object] = {"name": name, "meta": meta + (f" · {purpose}" if purpose else "")}
        if storage == "snapshot" and root:
            relative = str(item.get("path") or "").split(f"任务资料/{task_id}/", 1)[-1]
            if task_input_path(task_id, relative):
                row["preview"] = relative
                row["control"] = {"label": "Finder", "form": {"action": "/actions/open-task-input", "hidden": [
                    ("csrf", token), ("task_id", task_id), ("path", relative), ("return_to", return_to)]}}
        rows.append(row)
    return rows


def _task_input_panel(task_id: str, task_text: str, token: str, return_to: str) -> str:
    return task_detail.input_panel(_task_input_rows(task_id, task_text, token, return_to))


def _library_delivery_key(path: Path) -> str:
    """Return the logical delivery state for an allowlisted task folder."""
    root = delivery_root().resolve()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return ""
    if not relative.parts:
        return ""
    return "draft" if relative.parts[0] == "草稿" else "final" if relative.parts[0] == "正式交付" else ""


def library_task_delivery(record: dict[str, object]) -> dict[str, str] | None:
    """Resolve one task's current delivery folder without guessing by title."""
    task_id = str(record.get("task_id") or "")
    declared = str(record.get("delivery_folder") or "")
    preferred = "final" if "正式交付" in declared or str(record.get("delivery_state") or "") == "final" else "draft"
    cached = (SOURCE_CACHE_ROOT / "deliveries" / preferred / task_id).resolve()
    if ember_env("EMBER_CENTRAL_MODE") != "1" and cached.is_dir():
        return {"key": preferred, "name": task_id, "path": str(cached)}
    delivery_state = str(record.get("delivery_state") or "")
    if not declared and delivery_state not in {"draft", "final", "draft_delivered", "final_delivered"}:
        return None
    folder = resolve_delivery_folder(record)
    if folder and folder.name == task_id:
        key = _library_delivery_key(folder)
        if key:
            return {"key": key, "name": folder.name, "path": str(folder)}
    candidate = (delivery_root() / LIBRARY_DELIVERY_KINDS[preferred] / task_id).resolve()
    if candidate.is_dir() and _within(candidate, delivery_root()):
        return {"key": preferred, "name": candidate.name, "path": str(candidate)}
    return None


def library_delivery_file_count(delivery: dict[str, str]) -> int | None:
    """Use local metadata, or scan the NAS-local volume in central mode."""
    raw_path = str(delivery.get("path") or "")
    if not raw_path:
        return 0
    manifest = Path(raw_path) / ".gstudio-metadata.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if ember_env("EMBER_CENTRAL_MODE") != "1":
            return None
        try:
            root = Path(raw_path)
            return sum(
                1
                for path in root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and not any(part.startswith(".") for part in path.relative_to(root).parts)
            )
        except OSError:
            return None
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return None
    return sum(1 for entry in entries if isinstance(entry, dict) and not bool(entry.get("is_dir")))


def library_delivery_file_search_clues(delivery: dict[str, str]) -> str:
    """Return searchable file names from metadata or the NAS-local volume."""
    raw_path = str(delivery.get("path") or "")
    if not raw_path:
        return ""
    manifest = Path(raw_path) / ".gstudio-metadata.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if ember_env("EMBER_CENTRAL_MODE") != "1":
            return ""
        try:
            root = Path(raw_path)
            clues: list[str] = []
            for path in root.rglob("*"):
                relative = path.relative_to(root)
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or any(part.startswith(".") for part in relative.parts)
                ):
                    continue
                for value in (path.name, relative.as_posix()):
                    if value not in clues:
                        clues.append(value)
            return " ".join(clues)
        except OSError:
            return ""
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return ""
    clues: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or bool(entry.get("is_dir")):
            continue
        for key in ("name", "relative_path"):
            value = str(entry.get(key) or "").strip()
            if value and value not in clues:
                clues.append(value)
    return " ".join(clues)


def library_task_records() -> list[dict[str, object]]:
    """Build the task-centric, read-only library index."""
    records: list[dict[str, object]] = []
    for record in launcher_task_records(collect_records()):
        if record.get("record_type") != "task_card":
            continue
        task_id = str(record.get("task_id") or "")
        source = task_source(task_id)
        if not source:
            continue
        delivery = library_task_delivery(record)
        records.append({
            **record,
            "library_source_name": source.name,
            "library_delivery": delivery or {},
        })
    return records


def library_delivery_root(task_id: str, delivery_key: str) -> Path | None:
    """Resolve a task delivery root through the task relationship and allowlist."""
    if delivery_key == "input":
        return task_input_root(task_id)
    if delivery_key not in LIBRARY_DELIVERY_KINDS:
        return None
    record = record_map().get(task_id)
    if not record:
        return None
    delivery = library_task_delivery(record)
    if not delivery or delivery.get("key") != delivery_key:
        return None
    path = Path(str(delivery.get("path") or "")).resolve()
    cache_root = (SOURCE_CACHE_ROOT / "deliveries").resolve()
    allowed = _within(path, delivery_root()) or _within(path, cache_root)
    return path if path.is_dir() and allowed and path.name == task_id else None


def canonical_library_delivery_path(task_id: str, delivery_key: str, relative_path: str = "") -> Path | None:
    """Resolve an open/edit action only against the shared delivery source."""
    if delivery_key == "input":
        return task_input_path(task_id, relative_path)
    if delivery_key not in LIBRARY_DELIVERY_KINDS:
        return None
    record = record_map().get(task_id)
    folder = resolve_delivery_folder(record) if record else None
    if not folder or folder.name != task_id or not _within(folder, delivery_root()):
        return None
    if _library_delivery_key(folder) != delivery_key:
        return None
    relative = Path(relative_path or ".")
    if relative.is_absolute():
        return None
    candidate = (folder / relative).resolve()
    return candidate if candidate.exists() and _within(candidate, folder) else None


def library_delivery_path(task_id: str, delivery_key: str, relative_path: str = "") -> Path | None:
    """Resolve a path below one task delivery root and reject traversal."""
    root = library_delivery_root(task_id, delivery_key)
    if not root:
        return None
    relative = Path(relative_path or ".")
    if relative.is_absolute():
        return None
    candidate = (root / relative).resolve()
    if candidate.exists() and _within(candidate, root):
        return candidate
    return canonical_library_delivery_path(task_id, delivery_key, relative_path)


def _library_metadata_entries(task_id: str, delivery_key: str) -> list[dict[str, object]] | None:
    """Load the metadata-only delivery manifest when one is available."""
    root = library_delivery_root(task_id, delivery_key)
    if not root:
        return None
    manifest = root / ".gstudio-metadata.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = payload.get("entries") if isinstance(payload, dict) else None
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else None


def _library_delivery_metadata_entries(delivery: dict[str, object]) -> list[dict[str, object]] | None:
    """Read a manifest from an already resolved local delivery cache."""
    raw_path = str(delivery.get("path") or "")
    if not raw_path:
        return None
    try:
        payload = json.loads((Path(raw_path) / ".gstudio-metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = payload.get("entries") if isinstance(payload, dict) else None
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else None


def _library_flat_metadata_payload(
    task_id: str, delivery_key: str, metadata: list[dict[str, object]]
) -> dict[str, object]:
    entries = [{
        "name": str(entry.get("name") or Path(str(entry.get("relative_path") or "")).name),
        "relative_path": str(entry.get("relative_path") or ""),
        "is_dir": False,
        "size": int(entry.get("size") or 0),
        "updated_at": datetime.datetime.fromtimestamp(float(entry.get("mtime") or 0)).strftime("%Y-%m-%d %H:%M"),
        "suffix": str(entry.get("suffix") or ""),
    } for entry in metadata if not bool(entry.get("is_dir"))]
    entries.sort(key=lambda entry: (str(entry["name"]).casefold(), str(entry["relative_path"]).casefold()))
    return {"task_id": task_id, "delivery_key": delivery_key, "current_path": "", "entries": entries, "metadata_only": True}


def library_directory_payload(task_id: str, delivery_key: str, relative_path: str = "") -> dict[str, object] | None:
    metadata = _library_metadata_entries(task_id, delivery_key)
    if metadata is not None:
        current = Path(relative_path or ".")
        if current.is_absolute() or ".." in current.parts:
            return None
        current_text = "" if current.as_posix() == "." else current.as_posix().rstrip("/")
        prefix = f"{current_text}/" if current_text else ""
        entries: list[dict[str, object]] = []
        for entry in metadata:
            relative = str(entry.get("relative_path") or "")
            if not relative.startswith(prefix):
                continue
            remainder = relative[len(prefix):]
            if not remainder or "/" in remainder:
                continue
            entries.append({
                "name": str(entry.get("name") or Path(relative).name),
                "relative_path": relative,
                "is_dir": bool(entry.get("is_dir")),
                "size": int(entry.get("size") or 0),
                "updated_at": datetime.datetime.fromtimestamp(float(entry.get("mtime") or 0)).strftime("%Y-%m-%d %H:%M"),
                "suffix": str(entry.get("suffix") or ""),
            })
        entries.sort(key=lambda entry: (not bool(entry["is_dir"]), str(entry["name"]).casefold()))
        return {"task_id": task_id, "delivery_key": delivery_key, "current_path": current_text, "entries": entries, "metadata_only": True}
    path = library_delivery_path(task_id, delivery_key, relative_path)
    if not path or not path.is_dir():
        return None
    entries: list[dict[str, object]] = []
    try:
        children = sorted(
            (child for child in path.iterdir() if not child.name.startswith(".")),
            key=lambda child: (not child.is_dir(), child.name.casefold()),
        )
    except OSError:
        return None
    root = library_delivery_root(task_id, delivery_key)
    if not root:
        return None
    for child in children:
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append({
            "name": child.name,
            "relative_path": child.relative_to(root).as_posix(),
            "is_dir": child.is_dir(),
            "size": stat.st_size,
            "updated_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "suffix": child.suffix.lower(),
        })
    current = path.relative_to(root).as_posix()
    return {
        "task_id": task_id,
        "delivery_key": delivery_key,
        "current_path": "" if current == "." else current,
        "entries": entries,
    }


def library_flat_files_payload(task_id: str, delivery_key: str) -> dict[str, object] | None:
    """Return every file below a task delivery root without folder rows."""
    metadata = _library_metadata_entries(task_id, delivery_key)
    if metadata is not None:
        return _library_flat_metadata_payload(task_id, delivery_key, metadata)
    root = library_delivery_root(task_id, delivery_key)
    if not root:
        return None
    entries: list[dict[str, object]] = []
    try:
        paths = sorted(
            (path for path in root.rglob("*") if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts)),
            key=lambda path: (path.name.casefold(), path.relative_to(root).as_posix().casefold()),
        )
    except OSError:
        return None
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append({
            "name": path.name,
            "relative_path": path.relative_to(root).as_posix(),
            "is_dir": False,
            "size": stat.st_size,
            "updated_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "suffix": path.suffix.lower(),
        })
    return {"task_id": task_id, "delivery_key": delivery_key, "current_path": "", "entries": entries}


def _validated_library_sources(selections: list[str]) -> list[dict[str, object]]:
    """Resolve browser selections to canonical task cards and delivery files."""
    sources: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    records = record_map()
    for raw in selections:
        try:
            item = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise ValueError("交付文件选择数据无效。") from None
        task_id = str(item.get("task_id") or "")
        delivery = str(item.get("delivery") or "")
        relative_path = str(item.get("path") or "")
        key = (task_id, delivery, relative_path)
        if key in seen:
            continue
        seen.add(key)
        record = records.get(task_id)
        task_card = task_source(task_id)
        canonical = canonical_library_delivery_path(task_id, delivery, relative_path)
        if not record or not task_card or not canonical or not canonical.is_file():
            raise ValueError("选择中包含失效文件或伪造的任务来源。")
        recorded_folder = str(record.get("delivery_folder") or "").rstrip("/")
        sources.append({
            "task_id": task_id,
            "delivery": delivery,
            "delivery_label": LIBRARY_DELIVERY_KINDS.get(delivery, delivery),
            "relative_path": relative_path,
            "canonical": canonical,
            "task_card": task_card,
            "recorded_path": f"{recorded_folder}/{relative_path}" if recorded_folder else relative_path,
            "record": record,
        })
    if not sources:
        raise ValueError("请至少选择一个交付文件。")
    return sources


def _library_sources_context(sources: list[dict[str, object]]) -> str:
    rows: list[str] = []
    grouped: dict[str, list[dict[str, object]]] = {}
    for source in sources:
        grouped.setdefault(str(source["task_id"]), []).append(source)
    for task_id, items in grouped.items():
        first = items[0]
        record = first["record"]
        rows.extend([
            f"- 来源任务：{task_id}｜{record.get('task_name') or record.get('title') or task_id}",
            f"  - canonical 任务卡：{first['task_card']}",
        ])
        for item in items:
            rows.append(
                f"  - {item['delivery_label']}｜记录路径：{item['recorded_path']}｜canonical 文件：{item['canonical']}"
            )
    return "\n".join(rows)


def library_revision_prompt(task_id: str, delivery_key: str, relative_paths: list[str]) -> str:
    """Build one structured prompt for a follow-up task over selected deliveries."""
    selections = [
        json.dumps({"task_id": task_id, "delivery": delivery_key, "path": value}, ensure_ascii=False)
        for value in relative_paths
    ]
    return library_multi_revision_prompt(selections)


def library_multi_revision_prompt(selections: list[str]) -> str:
    """Build a single executor-neutral follow-up prompt from selected files."""
    sources = _validated_library_sources(selections)
    return render_catalog_prompt(
        "library-revision",
        selected_count=len(sources),
        sources=_library_sources_context(sources),
    )


def create_task_from_deliveries_prompt(selections: list[str]) -> str:
    """Build a validated AI handoff for creating a task from delivery files."""
    sources = _validated_library_sources(selections)
    projects: dict[str, str] = {}
    for source in sources:
        record = source["record"]
        project = str(record.get("project") or "independent")
        projects[project] = task_scope_title(project, str(record.get("project_title") or ""))
    if len(projects) == 1:
        project, title = next(iter(projects.items()))
        routing = f"- 项目判断：全部来源属于同一项目；新任务候选项目为：{title}（{project}）。收到具体目标后按该项目执行门禁。"
    else:
        project_list = "、".join(f"{title}（{project}）" for project, title in projects.items())
        routing = f"- 项目判断：来源跨越多个项目：{project_list}。必须先询问 Evan 新任务归属的目标项目并得到确认；确认前不得创建任务卡。"
    return render_catalog_prompt(
        "library-create-delivery",
        routing=routing.removeprefix("- 项目判断："),
        selected_count=len(sources),
        sources=_library_sources_context(sources),
    )


def _viewer_markdown_html(markdown: str, task_id: str, delivery_key: str, relative_path: str) -> str:
    from .pages.common import _viewer_markdown_html as _present
    return _present(markdown, task_id, delivery_key, relative_path)


def _document_preview_key(path: Path) -> str:
    stat = path.stat()
    identity = f"{path.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:24]


def _document_family(suffix: str) -> str:
    if suffix == ".pdf":
        return "pdf"
    if suffix in LIBRARY_WORD_SUFFIXES:
        return "word"
    if suffix in LIBRARY_SHEET_SUFFIXES:
        return "sheet"
    if suffix in LIBRARY_SLIDE_SUFFIXES:
        return "slides"
    return "document"


def _document_family_label(family: str) -> str:
    return {
        "pdf": "PDF",
        "word": "Word",
        "sheet": "Excel",
        "slides": "PowerPoint",
    }.get(family, "文档")


def _ensure_document_preview_pdf(path: Path) -> tuple[Path | None, str]:
    """Return the source PDF or a local, fingerprinted Office-to-PDF cache."""
    if path.suffix.lower() == ".pdf":
        return path, ""
    if path.suffix.lower() not in LIBRARY_OFFICE_SUFFIXES:
        return None, "暂不支持把这种文件转换为分页预览。"
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None, "本机缺少文档转换组件，请使用系统应用打开。"
    cache_dir = DOCUMENT_PREVIEW_CACHE_ROOT / _document_preview_key(path)
    target = cache_dir / "document.pdf"
    if target.is_file() and target.stat().st_size:
        return target, ""
    with DOCUMENT_PREVIEW_LOCK:
        if target.is_file() and target.stat().st_size:
            return target, ""
        (ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="document-preview-", dir=ROOT / "tmp") as raw_temp:
                temp_root = Path(raw_temp)
                profile = temp_root / "libreoffice-profile"
                output = temp_root / "output"
                profile.mkdir()
                output.mkdir()
                command = [
                    soffice,
                    f"-env:UserInstallation={profile.resolve().as_uri()}",
                    "--headless",
                    "--safe-mode",
                    "--nologo",
                    "--nodefault",
                    "--nolockcheck",
                    "--norestore",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output),
                    str(path),
                ]
                completed = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
                converted = next(output.glob("*.pdf"), None)
                if completed.returncode != 0 or not converted or not converted.stat().st_size:
                    detail = (completed.stderr or completed.stdout or "转换未生成 PDF").strip().splitlines()[-1]
                    return None, f"文档转换失败：{detail[:160]}"
                temporary_target = cache_dir / "document.pdf.pending"
                shutil.copy2(converted, temporary_target)
                os.replace(temporary_target, target)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"文档转换失败：{str(exc)[:160]}"
    return target, ""


def _prepare_quicklook_bundle(path: Path, target: Path) -> None:
    """Normalize Quick Look output for Chromium without altering source files."""
    marker = target / ".ember-preview-v4"
    if marker.is_file():
        return
    preview = target / "Preview.html"
    if path.suffix.lower() in LIBRARY_SLIDE_SUFFIXES and preview.is_file():
        source = preview.read_text(encoding="utf-8", errors="replace")
        # Quick Look emits PDF fragments as <img> elements for PowerPoint shapes.
        # WebKit renders those fragments, while Chromium shows broken-image icons;
        # the accompanying positioned HTML already carries the readable content.
        normalized = re.sub(
            r'<img\s+src="Attachment[^"/]*\.pdf"[^>]*>',
            "",
            source,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r'<style id="ember-slide-fit">.*?</script>',
            "",
            normalized,
            flags=re.DOTALL,
        )
        if 'id="ember-slide-fit"' not in normalized:
            fit_assets = '''<style id="ember-slide-fit">
*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden}body.ember-deck{display:flex;min-height:0;flex-direction:column;background:#e9edf2;color:#111827;font:13px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}.ember-toolbar{z-index:2;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;min-height:46px;padding:7px 10px;border-bottom:1px solid #d8dee7;background:rgba(255,255,255,.97);box-shadow:0 1px 4px rgba(15,23,42,.06)}.ember-controls{display:flex;align-items:center;gap:5px}.ember-controls:last-child{justify-content:flex-end}.ember-toolbar button{display:inline-flex;min-width:30px;height:30px;align-items:center;justify-content:center;padding:0 8px;border:1px solid transparent;border-radius:6px;background:transparent;color:#374151;font:inherit;font-size:12px;font-weight:750;cursor:pointer}.ember-toolbar button:hover:not(:disabled){border-color:#e5e7eb;background:#f3f4f6;color:#111827}.ember-toolbar button:disabled{opacity:.28;cursor:not-allowed}.ember-counter{min-width:58px;color:#6b7280;font-size:10px;font-variant-numeric:tabular-nums;text-align:center}.ember-kind{display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border-radius:999px;background:#fff1ed;color:#9f341e;font-size:9px;font-weight:800;letter-spacing:.04em}.ember-kind::before{content:"";width:5px;height:5px;border-radius:50%;background:#e35d3f}.ember-canvas{display:grid;min-height:0;flex:1;place-items:center;overflow:hidden;padding:20px 24px;outline:none}.ember-stage{position:relative;flex:none;background:#fff;box-shadow:0 7px 24px rgba(15,23,42,.16)}.ember-stage>div.slide,.ember-stage>div.loading-slide{display:none!important;margin:0!important;transform-origin:top left}.ember-stage>div.ember-active{display:block!important}@media(max-width:640px){.ember-toolbar{grid-template-columns:1fr auto}.ember-kind{display:none}.ember-canvas{padding:12px 10px}.ember-toolbar button{min-width:28px;padding:0 6px}}
</style><script id="ember-slide-fit-script">
(()=>{let slides=[],active=0,canvas,stage,counter,prev,next;function fit(){const slide=slides[active];if(!slide||!canvas)return;slide.style.zoom='1';const width=slide.offsetWidth||slide.getBoundingClientRect().width,height=slide.offsetHeight||slide.getBoundingClientRect().height;if(!width||!height)return;const style=getComputedStyle(canvas),availableWidth=canvas.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),availableHeight=canvas.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom),scale=Math.max(.1,Math.min(1,availableWidth/width,availableHeight/height));slide.style.zoom=String(scale);stage.style.width=Math.round(width*scale)+'px';stage.style.height=Math.round(height*scale)+'px'}function show(index){active=Math.max(0,Math.min(slides.length-1,index));slides.forEach((slide,i)=>slide.classList.toggle('ember-active',i===active));counter.textContent=`${active+1} / ${slides.length}`;prev.disabled=active===0;next.disabled=active===slides.length-1;requestAnimationFrame(fit)}function init(){slides=[...document.querySelectorAll('div.slide,div.loading-slide')];if(!slides.length)return;document.body.classList.add('ember-deck');const toolbar=document.createElement('div');toolbar.className='ember-toolbar';toolbar.innerHTML='<div class="ember-controls"><button type="button" data-prev aria-label="上一页">‹</button><span class="ember-counter"></span><button type="button" data-next aria-label="下一页">›</button></div><span class="ember-kind">PowerPoint</span><div class="ember-controls"><button type="button" data-fit>适合页面</button></div>';canvas=document.createElement('div');canvas.className='ember-canvas';canvas.tabIndex=0;stage=document.createElement('div');stage.className='ember-stage';canvas.append(stage);slides.forEach(slide=>stage.append(slide));document.body.replaceChildren(toolbar,canvas);counter=toolbar.querySelector('.ember-counter');prev=toolbar.querySelector('[data-prev]');next=toolbar.querySelector('[data-next]');prev.onclick=()=>show(active-1);next.onclick=()=>show(active+1);toolbar.querySelector('[data-fit]').onclick=fit;canvas.onkeydown=event=>{if(event.key==='ArrowLeft'){event.preventDefault();show(active-1)}else if(event.key==='ArrowRight'){event.preventDefault();show(active+1)}};new ResizeObserver(fit).observe(canvas);show(0)}addEventListener('DOMContentLoaded',init,{once:true})})();
</script>'''
            normalized = normalized.replace("</head>", fit_assets + "</head>", 1) if "</head>" in normalized else fit_assets + normalized
        if normalized != source:
            temporary = preview.with_suffix(".html.pending")
            temporary.write_text(normalized, encoding="utf-8")
            os.replace(temporary, preview)
    marker.write_text("gstudio quicklook preview v4\n", encoding="utf-8")


def _ensure_quicklook_preview(path: Path) -> tuple[str, Path | None, str]:
    """Build a high-fidelity, local macOS Quick Look bundle for Office files."""
    key = _document_preview_key(path)
    if path.suffix.lower() not in LIBRARY_OFFICE_SUFFIXES:
        return key, None, "Quick Look 仅用于 Office 文档。"
    qlmanage = shutil.which("qlmanage") or "/usr/bin/qlmanage"
    if not Path(qlmanage).is_file():
        return key, None, "本机缺少 Quick Look 预览组件。"
    target = DOCUMENT_PREVIEW_CACHE_ROOT / key / "quicklook"
    preview = target / "Preview.html"
    if preview.is_file():
        if not (target / ".ember-preview-v4").is_file():
            with DOCUMENT_PREVIEW_LOCK:
                if preview.is_file():
                    _prepare_quicklook_bundle(path, target)
        return key, preview, ""
    with DOCUMENT_PREVIEW_LOCK:
        if preview.is_file():
            return key, preview, ""
        (ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="quicklook-preview-", dir=ROOT / "tmp") as raw_temp:
                output = Path(raw_temp) / "output"
                output.mkdir()
                completed = subprocess.run(
                    [qlmanage, "-p", "-o", str(output), str(path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                bundle = next(output.glob("*.qlpreview"), None)
                generated = bundle / "Preview.html" if bundle else None
                if completed.returncode != 0 or not generated or not generated.is_file():
                    detail = (completed.stderr or completed.stdout or "Quick Look 未生成预览").strip().splitlines()[-1]
                    return key, None, f"Quick Look 预览失败：{detail[:160]}"
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(bundle, target)
                _prepare_quicklook_bundle(path, target)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return key, None, f"Quick Look 预览失败：{str(exc)[:160]}"
    return key, preview if preview.is_file() else None, "" if preview.is_file() else "Quick Look 预览文件缺失。"


def library_quicklook_asset_path(key: str, relative_path: str) -> Path | None:
    if not re.fullmatch(r"[a-f0-9]{24}", key):
        return None
    root = (DOCUMENT_PREVIEW_CACHE_ROOT / key / "quicklook").resolve()
    candidate = (root / relative_path).resolve()
    if not _within(candidate, root) or not candidate.is_file():
        return None
    return candidate


def library_quicklook_url(key: str) -> str:
    return f"/api/library/office-preview/{quote(key, safe='')}/Preview.html?v=4"


def _pdf_page_count(path: Path) -> tuple[int, str]:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return 0, "本机缺少 PDF 读取组件。"
    try:
        completed = subprocess.run([pdfinfo, str(path)], capture_output=True, text=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 0, f"无法读取 PDF：{str(exc)[:160]}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "PDF 信息读取失败").strip().splitlines()[-1]
        return 0, f"无法读取 PDF：{detail[:160]}"
    match = re.search(r"^Pages:\s+(\d+)\s*$", completed.stdout, re.MULTILINE)
    pages = int(match.group(1)) if match else 0
    return (pages, "") if pages else (0, "PDF 没有可显示的页面。")


def pdf_preview_dependency_status() -> dict[str, object]:
    """Report the command availability required by paged PDF previews."""
    commands = {
        name: {"available": bool(shutil.which(name))}
        for name in ("pdfinfo", "pdftoppm")
    }
    return {
        "state": "ready" if all(item["available"] for item in commands.values()) else "unavailable",
        "commands": commands,
    }


def library_preview_page_path(task_id: str, delivery_key: str, relative_path: str, page: int) -> Path | None:
    """Render one allowlisted PDF/Office page into the local preview cache."""
    source = library_delivery_path(task_id, delivery_key, relative_path)
    if not source or not source.is_file() or source.suffix.lower() not in ({".pdf"} | LIBRARY_OFFICE_SUFFIXES):
        return None
    preview_pdf, error = _ensure_document_preview_pdf(source)
    if error or not preview_pdf:
        return None
    page_count, error = _pdf_page_count(preview_pdf)
    if error or page < 1 or page > page_count:
        return None
    cache_dir = DOCUMENT_PREVIEW_CACHE_ROOT / _document_preview_key(source)
    target = cache_dir / f"page-{page:04d}.png"
    if target.is_file() and target.stat().st_size:
        return target
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return None
    with DOCUMENT_PREVIEW_LOCK:
        if target.is_file() and target.stat().st_size:
            return target
        cache_dir.mkdir(parents=True, exist_ok=True)
        prefix = cache_dir / f"page-{page:04d}.pending"
        try:
            completed = subprocess.run(
                [pdftoppm, "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", "144", str(preview_pdf), str(prefix)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        rendered = Path(str(prefix) + ".png")
        if completed.returncode != 0 or not rendered.is_file() or not rendered.stat().st_size:
            rendered.unlink(missing_ok=True)
            return None
        os.replace(rendered, target)
    return target


def library_content_url(task_id: str, delivery_key: str, relative_path: str) -> str:
    return "/api/library/content/" + "/".join((
        quote(task_id, safe=""),
        quote(delivery_key, safe=""),
        quote(relative_path.lstrip("/"), safe="/"),
    ))


def library_html_asset_path(task_id: str, relative_path: str) -> Path | None:
    """Resolve an HTML preview asset only inside that task's registered input folder."""
    path = task_input_path(task_id, relative_path)
    return path if path and path.is_file() else None


def _library_html_asset_url(task_id: str, locator: str) -> str | None:
    parsed = urlsplit(locator)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    root = task_input_root(task_id)
    if not root:
        return None
    try:
        candidate = Path(unquote(parsed.path)).resolve()
        relative = candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if not candidate.is_file():
        return None
    return "/api/library/html-asset?" + urlencode({"task_id": task_id, "path": relative.as_posix()})


def library_html_preview_content(task_id: str, delivery_key: str, relative_path: str) -> str | None:
    """Read one delivery HTML file and map allowlisted local assets to same-origin URLs."""
    path = library_delivery_path(task_id, delivery_key, relative_path)
    if not path or not path.is_file() or path.suffix.lower() not in LIBRARY_HTML_SUFFIXES:
        return None
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    def replace(match: re.Match[str]) -> str:
        mapped = _library_html_asset_url(task_id, match.group("locator"))
        return match.group(0) if not mapped else match.group(0).replace(match.group("locator"), mapped)

    return re.sub(
        r'(?P<prefix>\b(?:src|href)\s*=\s*)(?P<quote>["\'])(?P<locator>file://[^"\']+)(?P=quote)',
        replace,
        source,
        flags=re.IGNORECASE,
    )


def library_document_viewer_url(task_id: str, delivery_key: str, relative_path: str) -> str:
    return "/api/library/document-viewer?" + urlencode({
        "task_id": task_id,
        "delivery": delivery_key,
        "path": relative_path,
    })


def library_document_viewer_html(task_id: str, delivery_key: str, relative_path: str) -> str | None:
    from .pages.library import library_document_viewer_html as _present
    return _present(task_id, delivery_key, relative_path)


def library_file_preview_payload(task_id: str, delivery_key: str, relative_path: str) -> dict[str, object] | None:
    path = library_delivery_path(task_id, delivery_key, relative_path)
    if not path or not path.is_file():
        return None
    suffix = path.suffix.lower()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    stat = path.stat()
    raw_url = "/api/library/raw?" + urlencode({"task_id": task_id, "delivery": delivery_key, "path": relative_path})
    threshold = int(config().get("large_file_transfer", {}).get("recommended_threshold_bytes", 52_428_800))
    kind = "image" if suffix in LIBRARY_IMAGE_SUFFIXES else "video" if suffix in LIBRARY_VIDEO_SUFFIXES else "audio" if suffix in LIBRARY_AUDIO_SUFFIXES else "document" if suffix == ".pdf" or suffix in LIBRARY_OFFICE_SUFFIXES else "html" if suffix in LIBRARY_HTML_SUFFIXES else "markdown" if suffix in {".md", ".markdown"} else "text" if suffix in LIBRARY_TEXT_SUFFIXES else "file"
    body_html = ""
    if kind in {"markdown", "text"} and stat.st_size <= 2_000_000:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            body_html = _viewer_markdown_html(text, task_id, delivery_key, relative_path) if kind == "markdown" else f"<pre><code>{html.escape(text)}</code></pre>"
        except OSError:
            body_html = ""
    payload: dict[str, object] = {
        "task_id": task_id,
        "delivery_key": delivery_key,
        "name": path.name,
        "relative_path": relative_path,
        "kind": kind,
        "mime": mime,
        "size": stat.st_size,
        "updated_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "body_html": body_html,
        "raw_url": raw_url,
        "large_file": stat.st_size >= threshold,
    }
    if kind == "document" and suffix in LIBRARY_OFFICE_SUFFIXES:
        quicklook_key, quicklook_preview, quicklook_error = _ensure_quicklook_preview(path)
        if quicklook_preview:
            payload.update({
                "kind": "pdf",
                "preview_kind": "office",
                "document_family": _document_family(suffix),
                "document_label": _document_family_label(_document_family(suffix)),
                "raw_url": library_quicklook_url(quicklook_key),
                "preview_engine": "quicklook",
                "preview_error": "",
            })
            return payload
        payload["quicklook_error"] = quicklook_error
    if kind == "document":
        family = _document_family(suffix)
        preview_pdf, preview_error = _ensure_document_preview_pdf(path)
        page_count = 0
        if preview_pdf and not preview_error:
            page_count, preview_error = _pdf_page_count(preview_pdf)
        payload.update({
            "kind": "pdf",
            "preview_kind": "document",
            "document_family": family,
            "document_label": _document_family_label(family),
            "page_count": page_count,
            "page_url": "/api/library/preview-page?" + urlencode({
                "task_id": task_id,
                "delivery": delivery_key,
                "path": relative_path,
            }) + "&page=",
            "preview_error": preview_error,
            "raw_url": library_document_viewer_url(task_id, delivery_key, relative_path),
        })
    elif kind == "html":
        payload.update({
            "kind": "pdf",
            "preview_kind": "html",
            "content_url": library_content_url(task_id, delivery_key, relative_path),
            "raw_url": library_content_url(task_id, delivery_key, relative_path),
            "preview_note": "安全预览：脚本、表单提交和外部资源已停用。",
        })
    return payload


def organization_report_path(record: dict[str, object]) -> Path | None:
    """Resolve the best available report for one ordinary organizing task."""
    candidates: list[tuple[int, Path]] = []
    cached = SOURCE_CACHE_ROOT / "organization-reports" / f"{record.get('task_id')}.md"
    if cached.is_file():
        candidates.append((120, cached.resolve()))

    def consider(raw: str | Path, base_score: int = 0) -> None:
        raw_path = Path(str(raw)).expanduser()
        for translated in equivalent_path_strings(raw_path):
            path = Path(translated).expanduser()
            if not path.is_file() or path.suffix.lower() != ".md":
                continue
            name = path.name.lower()
            score = base_score
            if name == "整理报告.md":
                score += 100
            elif "completion-report" in name or "完成报告" in name:
                score += 90
            elif "整理报告" in name:
                score += 85
            elif "整理建议" in name or "weekly" in name:
                score += 65
            candidates.append((score, path.resolve()))

    for value in record.get("paths", []) or []:
        consider(str(value), 10)
    folder = resolve_delivery_folder(record)
    if folder:
        for path in folder.glob("*.md"):
            consider(path, 20)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)
    return candidates[0][1]


def organization_report_records(*, resolve_reports: bool = True) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for record in collect_records():
        if record.get("record_type") != "task_card" or record.get("work_type") != "organize":
            continue
        cached = SOURCE_CACHE_ROOT / "organization-reports" / f"{record.get('task_id')}.md"
        report_path = organization_report_path(record) if resolve_reports else (cached.resolve() if cached.is_file() else None)
        mode, scope = ember_organization.organization_metadata(record)
        records.append({**record, "organization_mode": mode, "organization_scope": scope, "report_path": str(report_path or "")})
    return sorted(records, key=lambda item: parse_sort_datetime(str(item.get("updated_at") or "")), reverse=True)


def weekly_organization_task(records: list[dict[str, object]], week: str) -> dict[str, object] | None:
    """Return the latest ordinary weekly-organization task for *week*.

    The proposal sidecar describes suggestion generation, while the ordinary
    organization task card owns the real execution lifecycle.  Once a task
    exists for the same weekly scope, its state must take precedence so the UI
    cannot offer a duplicate start after the round has already begun or ended.
    """
    if not week:
        return None
    for record in records:
        if str(record.get("organization_mode") or "") != "weekly":
            continue
        scope = str(record.get("organization_scope") or "")
        if scope == week:
            return record
        match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", scope)
        if match:
            try:
                scope_week = weekly_task_review.week_id(
                    datetime.date(int(match[1]), int(match[2]), int(match[3]))
                )
            except ValueError:
                scope_week = ""
            if scope_week == week:
                return record
        identity = " ".join(
            [
                str(record.get("task_id") or ""),
                str(record.get("title") or ""),
                *(str(value) for value in record.get("paths", []) or []),
            ]
        )
        if re.search(rf"(?i)(?<!\d){re.escape(week)}(?!\d)", identity):
            return record
    return None


def organization_report_preview_payload(task_id: str) -> dict[str, object] | None:
    record = next((item for item in organization_report_records() if str(item.get("task_id") or "") == task_id), None)
    if not record:
        return None
    report_value = str(record.get("report_path") or "")
    report_path = Path(report_value) if report_value else None
    body_html = ""
    if report_path and report_path.is_file():
        try:
            body_html = markdown_to_html(report_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            body_html = ""
    task_card = task_preview_payload(task_id) if not body_html else None
    mode = str(record.get("organization_mode") or "")
    status = str(record.get("status") or "")
    return {
        "task_id": task_id,
        "title": str(record.get("task_name") or record.get("title") or task_id),
        "mode": mode,
        "mode_label": "按任务整理" if mode != "weekly" else "按周整理",
        "scope": str(record.get("organization_scope") or ""),
        "status": status,
        "status_label": STATUS_LABEL.get(status, status),
        "updated_at": format_display_time(record.get("updated_at")) or "未记录",
        "body_html": body_html,
        "task_body_html": str(task_card.get("body_html") or "") if task_card else "",
        "report_available": bool(body_html),
        "has_delivery": bool(resolve_delivery_folder(record)),
        "detail_url": f"/tasks/{quote(task_id)}",
    }


def shared_prompt_contract(
    task: str,
    context: str,
    *,
    input_data: str = "-本轮没有额外输入；按上下文中列出的真源继续。",
    authorization: str,
    success: str,
    output: str = "回复时先给结论，再列出关键证据、实际改动、验证结果与待确认项。",
    user_supplement: str = "",
) -> str:
    """Wrap a task in the executor-neutral Ember prompt contract."""
    sections = [
        "## 余烬 · Ember 共享任务提示", "",
        "### 任务", "", task.strip(), "",
        "### 上下文", "", context.strip(), "",
    ]
    supplement = user_supplement.strip()
    inputs = input_data.strip()
    if supplement:
        inputs = f"{inputs}\n\n- Evan 补充材料：\n{quote_prompt_input(supplement)}"
    sections.extend(["### 输入与真源", "", inputs, ""])
    sections.extend([
        "### 授权边界", "", authorization.strip() + "\n" + system_bridge.PROMPT_BOUNDARY, "",
        "### 成功标准", "", success.strip(), "",
        "### 输出", "", output.strip(),
    ])
    return "\n".join(sections)


def quote_prompt_input(value: str) -> str:
    """Render user-provided material as data, not as prompt structure."""
    return "\n".join(f"> {line}" if line else ">" for line in value.strip().splitlines())


SHARED_PROMPT_TASK_MARKER = "\n### 任务\n\n"
SHARED_PROMPT_CONTEXT_MARKER = "\n\n### 上下文\n"
SHARED_PROMPT_RESERVED_HEADINGS = {
    "任务", "上下文", "输入与真源", "授权边界", "成功标准", "输出",
}


def shared_prompt_editable_parts(prompt: str) -> dict[str, str]:
    """Split a canonical prompt into one editable task and locked remainder."""
    task_marker = prompt.find(SHARED_PROMPT_TASK_MARKER)
    if task_marker < 0:
        raise ValueError("当前提示词不符合 余烬 · Ember 共享结构。")
    task_start = task_marker + len(SHARED_PROMPT_TASK_MARKER)
    context_start = prompt.find(SHARED_PROMPT_CONTEXT_MARKER, task_start)
    if context_start < 0:
        raise ValueError("当前提示词缺少固定的上下文段。")
    prefix = prompt[:task_start]
    suffix = prompt[context_start:]
    heading = prompt[:task_marker].strip()
    fixed_prompt = f"{heading}{suffix}" if heading else suffix.lstrip()
    return {
        "task": prompt[task_start:context_start].strip(),
        "prompt_prefix": prefix,
        "prompt_suffix": suffix,
        "fixed_prompt": fixed_prompt,
    }


def normalize_prompt_task(value: str) -> str:
    """Validate the only user-editable segment in a shared prompt."""
    task = value.strip()
    if not task:
        raise ValueError("任务提示词不能为空。")
    if len(task) > 4000:
        raise ValueError("任务提示词不能超过 4000 字。")
    for line in task.splitlines():
        match = re.fullmatch(r"\s*###\s+(.+?)\s*", line)
        if match and match.group(1) in SHARED_PROMPT_RESERVED_HEADINGS:
            raise ValueError("任务输入不能重定义 余烬 · Ember 固定结构标题。")
    return task


def apply_prompt_task_override(prompt: str, task_override: str | None) -> str:
    """Rebuild a canonical prompt while keeping all locked sections intact."""
    if task_override is None:
        return prompt
    parts = shared_prompt_editable_parts(prompt)
    return f"{parts['prompt_prefix']}{normalize_prompt_task(task_override)}{parts['prompt_suffix']}"


def editable_prompt_preview(prompt: str) -> dict[str, str]:
    """Return the fields required by both execution-confirmation surfaces."""
    parts = shared_prompt_editable_parts(prompt)
    return {
        "prompt": prompt,
        **parts,
        "fixed_prompt_html": markdown_to_html(parts["fixed_prompt"]),
    }


def material_manager_prompt(
    mode: str,
    *,
    task_id: str = "",
    selections: list[str] | None = None,
) -> str:
    if mode not in ember_agent.ALLOWED_MODES:
        raise ValueError("不支持的资料管理员模式。")
    labels = {
        "file_management": "普通文件管理",
        "project_archive": "项目归档",
        "ebrain_raw_registration": "EBrain 来源原始入库",
        "task_organization": "已确认任务整理",
    }
    sources = selections or []
    return render_catalog_prompt(
        "material-manager",
        mode=mode,
        mode_label=labels[mode],
        task_line=f"- 关联任务：`{task_id}`" if task_id else "- 关联任务：未指定",
        sources="\n".join(f"- `{value}`" for value in sources) if sources else "- 本轮没有预选来源。",
    )


def attach_material_manager_run(
    prompt: str,
    *,
    run_id: str,
    executor: str,
    model: str,
    reasoning: str,
    mode: str,
) -> str:
    header = "\n".join([
        "## 资料管理员运行绑定", "",
        f"- run_id：`{run_id}`",
        f"- executor：`{executor}`",
        f"- model：`{model}`",
        f"- reasoning：`{reasoning}`",
        f"- mode：`{mode}`", "",
        "不得另建 Agent 运行记录或改用执行器默认模型。若本轮无法完成，也必须用上述 run_id 写回最终状态。",
    ])
    return f"{header}\n\n{prompt}"


def task_overview_source() -> Path:
    return shared_workspace_root() / "tasks" / "任务总览.md"


def new_task_prompt(
    task_type: str = "",
    project: str = "",
    source: Path | None = None,
    delivery_mode: str = "gate",
    related_task_ids: list[str] | None = None,
    user_supplement: str = "",
) -> str:
    label = NEW_TASK_LABEL.get(task_type, task_type)
    task_entry = label or "未指定"
    if task_type == "generic":
        task_entry = f"{label}（通用入口；根据我的具体需求判断问答 / 文档 / 图片 / 视频 / 工作流，不要提前假设）"
    project_title = (
        "独立任务（不属于任何项目）"
        if project == "independent"
        else str(project_items().get(project, {}).get("title") or project)
    )
    page = f"{project_title}任务视图" if project_title else "任务总览"
    delivery_hint = {
        "delivery": "本任务有独立交付物；按 余烬 · Ember 门禁创建或更新任务卡，并使用草稿交付目录。",
        "none": "本任务目前没有独立交付物；先按任务门禁判断是否需要任务卡，不要为了形式强行建卡。",
        "gate": "是否有独立交付物、是否需要任务卡尚未预设；先按 余烬 · Ember 任务门禁判断。",
    }.get(delivery_mode, "先按 余烬 · Ember 任务门禁判断是否需要任务卡。")
    related = [value for value in (related_task_ids or []) if value]
    related_hint = "、".join(related) if related else "未指定"
    project_hint = (
        "独立任务（不属于任何项目）"
        if project == "independent"
        else "未预设；收到需求后按门禁判断"
        if not project
        else project_title
    )
    group_input: list[str] = []
    special_rules = (
        "若需建卡，必须使用 `project: independent`，不得猜入正式项目。"
        if project == "independent" else ""
    )
    if task_type == "task_group":
        special_rules = (
            "任务主线要求：必须使用 `task_kind: task_group`、`artifact_mode: delivery` 和 `related_task_ids`，"
            "生成非空草稿目录、`00_任务组说明.md` 与 `01_关联任务索引.md`；相关任务卡不得修改、复制或移动。"
        )
    if user_supplement.strip():
        group_input.extend(["- Evan 补充：", quote_prompt_input(user_supplement), "", "补充内容只作为本轮输入，不自动扩大授权。"])
    return render_catalog_prompt(
        "new-task",
        page=page,
        source=source or task_overview_source() or "任务总览（待解析）",
        task_entry=task_entry,
        project=project_hint,
        delivery=delivery_hint,
        related_tasks=related_hint,
        group_input="\n".join(group_input),
        special_rules=special_rules,
    )


def route_task_prompt(
    route_mode: str,
    request_text: str,
    *,
    task_id: str = "",
    user_supplement: str = "",
    extra_context: list[str] | None = None,
) -> str:
    """Build a homepage handoff without copying the raw task card."""
    mode_label = {
        "new": "新建任务",
        "continue": "继续所选任务",
        "derive": "基于所选任务新建",
    }.get(route_mode, "新建任务")
    context: list[str] = []
    inputs: list[str] = []
    if route_mode == "new":
        context.extend([
            "- 项目归属：未预设。",
            "- 工作台状态：尚未创建空任务卡，也尚未修改任务状态。",
        ])
    inputs.extend(line for line in (extra_context or []) if str(line).strip())
    authorization = (
        "先读取真源，再按用户要求走任务门禁。"
        "外部写入、删除、覆盖、付费或扩大范围必须先确认。"
    )
    if route_mode == "new":
        authorization += " 如需建卡，新卡正文必须使用任务目标、任务描述、当前结果、按需下一步，并以执行日志结尾；日志按时间倒序，新记录插在标题下方。"
    success = "已按首页输入形成正确上下文；建卡或续接通过门禁，没有提前产生空任务或空交付。"
    if route_mode in {"continue", "derive"}:
        record = record_map().get(task_id)
        source = task_source(task_id)
        if not record or not source:
            raise ValueError("请先选择要继续或作为来源的任务。")
        title = str(record.get("task_name") or record.get("title") or task_id)
        project = task_scope_title(str(record.get("project") or ""), str(record.get("project_title") or ""))
        if route_mode == "continue":
            inputs.extend([
                f"- 所选任务：{title}",
                f"- 任务 ID：{task_id}",
                f"- 所属项目：{project}",
                f"- canonical 任务卡：{source}",
            ])
            authorization += (
                " 继续所选任务，不得另建任务卡。执行前使用 `task_gate.py preflight --continuation`；"
                "若旧卡缺少当前正文结构，先依据原卡证据和本轮要求补齐任务目标、任务描述、当前结果、按需下一步，"
                "并保留原执行日志，禁止自动猜测或改写历史；后续日志按时间倒序，新记录插在标题下方。"
            )
            success = "已继续所选任务；任务卡、执行日志、验证结果和交付状态保持更新，没有另建重复任务。"
        else:
            inputs.extend([
                f"- 来源任务：{title}",
                f"- 来源任务 ID：{task_id}",
                f"- 来源所属项目：{project}",
                f"- 来源任务卡：{source}",
                "- 新任务项目：未锁定；按本次要求和任务门禁判断，不默认沿用来源项目。",
            ])
            authorization += (
                " 原任务和材料只作只读来源；必须另建新任务卡。新卡正文必须使用任务目标、任务描述、当前结果、"
                "按需下一步，并以执行日志结尾；日志按时间倒序，新记录插在标题下方。"
            )
            success = "已基于来源任务建立新任务；原任务与材料保持只读，新产物进入新任务的正确交付位置。"
    if user_supplement.strip():
        inputs.extend(["- Evan 补充材料：", quote_prompt_input(user_supplement)])
    return render_catalog_prompt(
        "home-route",
        task=normalize_prompt_task(request_text),
        route_label=mode_label,
        context="\n".join(context) or "- 项目归属和任务关系按本轮选择确定。",
        input="\n".join(inputs) or "- 本轮没有额外材料。",
        authorization=authorization,
        success=success,
    )


def archive_item_prompt(project_name: str, remote_path: str, item_name: str) -> str:
    if item_name == "发布归档":
        return publish_archive_prompt(project_name, remote_path)
    return render_catalog_prompt(
        "archive-item",
        project=project_name,
        item=item_name,
        target=remote_path,
        log=ARCHIVE_OPERATION_LOG,
    )


def publish_archive_prompt(project_name: str, remote_path: str) -> str:
    return render_catalog_prompt(
        "archive-publish",
        project=project_name,
        target=remote_path,
        log=ARCHIVE_OPERATION_LOG,
    )


def publish_record_archive_prompt(record: dict[str, object]) -> str:
    """Build the shared-contract prompt for one existing publish record."""
    material = str(record.get("material_path") or "")
    if not material:
        raise ValueError("请先关联发布资料。")
    project = str(record.get("project") or "")
    project_title = ember_publish.PROJECT_TITLES.get(project, project)
    release_id = str(record.get("release_id") or "")
    topic = str(record.get("topic") or "")
    platform = str(record.get("platform") or "未记录")
    account = str(record.get("account") or "未记录")
    status = str(record.get("status") or "")
    status_label = ember_publish.STATUS_LABELS.get(status, status)
    return render_catalog_prompt(
        "archive-publish-record",
        release_id=release_id,
        topic=topic or "未命名主题",
        project=project_title,
        platform_account=f"{platform} / {account}",
        status=status_label,
        material=material,
        log=ARCHIVE_OPERATION_LOG,
    )


def archive_open_target(remote_path: str) -> Path | None:
    """Resolve a canonical NAS archive path for Finder opening."""
    candidate = archive_remote_path(remote_path)
    return Path(candidate) if candidate else None


def archive_remote_path(raw_path: str) -> str | None:
    """Allow only paths beneath the canonical NAS project archive root."""
    root = str(archive_index.config().get("display_root") or archive_index.archive_root()).rstrip("/")
    candidate = str(raw_path or "").rstrip("/")
    return candidate if candidate == root or candidate.startswith(root + "/") else None


def _archive_directory_from_remote(path: str) -> dict[str, object] | None:
    """Fetch one canonical NAS directory level live."""
    try:
        children = archive_index.list_remote(path)
    except archive_index.ArchiveIndexError:
        return None
    preview_limit = 500
    children = sort_archive_directory_children(path, children)
    return {"path": path, "children": children[:preview_limit], "truncated": len(children) > preview_limit, "preview_limit": preview_limit}


def sort_archive_directory_children(path: str, children: list[dict[str, object]]) -> list[dict[str, object]]:
    """Sort flat publish packages newest-first by YYYYMM and monthly sequence."""
    if not str(path).rstrip("/").endswith("/发布归档"):
        return list(children)

    def key(item: dict[str, object]) -> tuple[int, int, int, str, str]:
        name = str(item.get("name") or "")
        match = re.match(r"^(20\d{4})_(\d{2})(?:_|$)", name)
        return (
            1 if match else 0,
            int(match.group(1)) if match else 0,
            int(match.group(2)) if match else 0,
            str(item.get("modified_at") or ""),
            name.casefold(),
        )

    return sorted(children, key=key, reverse=True)


def archive_directory_payload(raw_path: str) -> dict[str, object] | None:
    """Read one additional NAS level on demand for the archive tree.

    Prefer the cached index when it already contains children for the path.
    A cached ``child_count: 0`` is an authoritative empty directory; only a
    legacy/shallow entry with no child count requires a background refresh.
    """
    path = archive_remote_path(raw_path)
    if not path:
        return None
    payload = archive_index.load_index()
    stack: list[dict[str, object]] = []
    if isinstance(payload, dict):
        for project in payload.get("projects", []) or []:
            if isinstance(project, dict):
                stack.extend(item for item in project.get("children", []) or [] if isinstance(item, dict))
    while stack:
        item = stack.pop()
        children = [child for child in item.get("children", []) or [] if isinstance(child, dict)]
        if str(item.get("remote_path") or "") == path:
            if children or str(item.get("type")) != "directory":
                children = sort_archive_directory_children(path, children)
                preview_limit = 500
                return {"path": path, "children": children[:preview_limit], "truncated": len(children) > preview_limit, "preview_limit": preview_limit}
            if item.get("child_count") == 0:
                return {
                    "path": path,
                    "children": [],
                    "status": "empty",
                    "retryable": False,
                }
            return {
                "path": path,
                "children": [],
                "status": "not_indexed",
                "retryable": True,
                "error": "当前目录尚未进入本机索引，请使用“后台刷新当前目录”后重试。",
            }
        stack.extend(children)
    return {
        "path": path,
        "children": [],
        "status": "not_indexed",
        "retryable": True,
        "error": "当前路径不在本机索引中，请后台刷新对应项目后重试。",
    }


def project_archive_path(project: str) -> str:
    """Return the canonical NAS archive path for a project slug."""
    try:
        settings = archive_index.config()
    except Exception:
        return ""
    remote_root = str(settings.get("display_root") or archive_index.archive_root()).rstrip("/")
    mappings = settings.get("project_mappings") if isinstance(settings.get("project_mappings"), dict) else {}
    for name, slug in mappings.items():
        if slug == project:
            return f"{remote_root}/{name}"
    return ""


def project_category_prompt_context(item: dict[str, object] | None) -> dict[str, str]:
    """Pass the registered category and its single guide without guessing a type."""
    slug = str((item or {}).get("work_category") or "")
    category = load_work_categories().get(slug)
    return {
        "work_category": f"{category['title']}（{slug}）" if category else "未分类（不得根据项目名称或所用工具推断）",
        "category_guidance": str(ROOT / "skills/ember/references/project-category-standard.md"),
    }


def organize_project_intro_prompt(executor: str, project: str) -> str:
    """Generate a prompt for Codex/OpenCode to merge new tasks into the project intro page."""
    del executor
    item = project_items().get(project)
    title = str(item.get("title") or project) if item else project
    source = allowed_source("project", project)
    history = load_project_intro_history(project)
    candidates = collect_project_intro_tasks(project, history)

    history_text = ""
    if history:
        latest = history[-1]
        history_text = (
            f"- 上一次整理：{latest.get('timestamp', '未知时间')}\n"
            f"- 轮次：R{latest.get('round', 0):02d}\n"
            f"- 来源任务：{', '.join(str(t) for t in latest.get('source_tasks', []) or [])}\n"
            f"- 摘要：{latest.get('summary', '')}"
        )
    else:
        history_text = "- 暂无整理记录，这是第一次整理。"

    candidate_text = ""
    if candidates:
        lines = []
        for record in candidates:
            lines.append(
                f"- {record['task_id']}｜{record['task_name']}｜{record['status']}｜{record['updated_at']}"
            )
        candidate_text = "\n".join(lines)
    else:
        candidate_text = "- 没有待整理的新任务。"

    next_round = 1
    if history:
        try:
            next_round = max(int(str(entry.get("round") or 0)) for entry in history) + 1
        except ValueError:
            next_round = len(history) + 1

    return render_catalog_prompt(
        "project-intro-organize",
        project=title,
        **project_category_prompt_context(item),
        round=f"R{next_round:02d}",
        history=history_text,
        source=source or f"项目/{project}/项目看板.md（待创建）",
        sidecar=project_intro_history_path(project),
        candidates=candidate_text,
    )


def organize_project_intro_chat_prompt(executor: str, project: str, user_input: str) -> str:
    """Generate a prompt for Codex/OpenCode to merge user-provided updates into the project intro."""
    del executor
    item = project_items().get(project)
    title = str(item.get("title") or project) if item else project
    source = allowed_source("project", project)
    history = load_project_intro_history(project)

    next_round = 1
    if history:
        try:
            next_round = max(int(str(entry.get("round") or 0)) for entry in history) + 1
        except ValueError:
            next_round = len(history) + 1

    return render_catalog_prompt(
        "project-intro-chat",
        project=title,
        **project_category_prompt_context(item),
        round=f"R{next_round:02d}",
        source=source or f"项目/{project}/项目看板.md（待创建）",
        sidecar=project_intro_history_path(project),
        user_input=quote_prompt_input(user_input),
    )


def maintain_project_intro_prompt(project: str, user_input: str = "") -> str:
    """Generate a unified prompt for Codex/OpenCode to maintain the project intro.

    The prompt carries both unorganized tasks and any user follow-up so that a
    single agent entry can handle task merging and conversational updates.
    """
    item = project_items().get(project)
    title = str(item.get("title") or project) if item else project
    source = allowed_source("project", project)
    history = load_project_intro_history(project)
    candidates = collect_project_intro_tasks(project, history)

    history_text = ""
    if history:
        latest = history[-1]
        reviewed_count = len(latest.get("source_tasks", []) or [])
        history_text = (
            f"- 上一次整理：{latest.get('timestamp', '未知时间')}\n"
            f"- 轮次：R{latest.get('round', 0):02d}\n"
            f"- 已审阅来源：{reviewed_count} 项（完整列表见 sidecar）\n"
            f"- 摘要：{latest.get('summary', '')}"
        )
    else:
        history_text = "- 暂无整理记录，这是第一次整理。"

    candidate_text = ""
    if candidates:
        lines = []
        for record in candidates:
            lines.append(
                f"- {record['task_id']}｜{record['task_name']}｜{record['status']}｜{record['updated_at']}"
            )
        candidate_text = "\n".join(lines)
    else:
        candidate_text = "- 没有待整理的新任务。"

    next_round = 1
    if history:
        try:
            next_round = max(int(str(entry.get("round") or 0)) for entry in history) + 1
        except ValueError:
            next_round = len(history) + 1

    return render_catalog_prompt(
        "project-intro-maintain",
        project=title,
        **project_category_prompt_context(item),
        project_slug=project,
        round=f"R{next_round:02d}",
        history=history_text,
        source=source or "当前注册指针不可读",
        sidecar=project_intro_history_path(project),
        candidates=candidate_text,
        user_input=f"- Evan 补充：\n{quote_prompt_input(user_input)}" if user_input.strip() else "- 本轮没有额外补充。",
    )


def weekly_confirmation_prompt(executor: str, *, new_round: bool = False, project_name: str = "") -> str:
    if not valid_executor(executor):
        raise ValueError("不支持的执行工具。")
    today = weekly_task_review.review_day(__import__("datetime").date.today())
    current_round = weekly_task_review.cached_round(today)
    target_round = current_round + 1 if new_round else current_round
    report = weekly_task_review.report_path(today, target_round)
    previous = weekly_task_review.load_weekly_view(today)
    previous_status = previous.get("status") if isinstance(previous.get("status"), dict) else {}
    previous_report_value = str(previous_status.get("report_path") or "") if new_round else ""
    previous_report = str(weekly_task_review.local_equivalent_path(Path(previous_report_value))) if previous_report_value else ""
    complete_command = f'python3 scripts/weekly_task_review.py --date {today.isoformat()} --complete --executor <codex|opencode> --summary "本周整理已完成" --report "<正式完成汇总报告.md的绝对路径>"'
    project_scope = f"项目「{project_name}」" if project_name else "全部项目"
    window_start, window_end = weekly_task_review.review_window(today)
    scope_instruction = (
        f"- 只关注{project_scope}在本周内更新的任务、交付与归档，不跨项目。"
        if project_name else
        "- 逐项确认草稿晋级、完成收口和任务合并；不做任务拆分判断或小项目升级评估。"
    )
    round_instruction = scope_instruction
    if new_round:
        round_instruction += (
            f"\n- 先运行 `python3 scripts/weekly_task_review.py --date {today.isoformat()} "
            f"--write --new-round` 生成 R{target_round:02d} 建议。"
        )
    return render_catalog_prompt(
        "weekly-organization",
        project_scope=project_scope,
        week_id=weekly_task_review.week_id(today),
        window=f"{window_start.isoformat()} 00:00 至 {(window_end + datetime.timedelta(days=1)).isoformat()} 00:00",
        round=f"R{target_round:02d}",
        report=report,
        previous_report=f"- 上一轮完成报告：`{previous_report}`" if previous_report else "",
        round_instruction=round_instruction,
        complete_command=complete_command,
    )


def organization_prompt(executor: str, mode: str, scope: str = "") -> str:
    """Build the handoff for one ordinary task-card-based organization round."""
    if not valid_executor(executor):
        raise ValueError("不支持的执行工具。")
    if mode not in ember_organization.MODES:
        raise ValueError("不支持的整理模式。")
    if mode != "weekly" and not scope:
        raise ValueError("该整理模式必须选择范围。")
    labels = ember_organization.MODE_LABELS
    project = scope if mode == "project" else "gstudio"
    scope_label = scope or "上一完整自然周"
    if mode == "weekly":
        day = weekly_task_review.review_day(datetime.date.today())
        start, end = weekly_task_review.review_window(day)
        command = "python3 scripts/weekly_task_review.py --write"
        boundary = f"{start.isoformat()} 00:00 含至 {(end + datetime.timedelta(days=1)).isoformat()} 00:00 不含"
    else:
        command = f'python3 scripts/ember_organization.py --mode {mode} --scope "{scope}" --task-id <task_id> --write'
        boundary = "按所选范围扫描普通任务卡，不跨范围自动扩展"
    return render_catalog_prompt(
        "organization-round",
        scope_label=scope_label,
        mode_label=labels[mode],
        mode=mode,
        project=project,
        boundary=boundary,
        command=command,
    )


def selected_tasks_organization_prompt(executor: str, task_ids: list[str]) -> str:
    """Carry selected task-card context into a new executor session without acting."""
    if not valid_executor(executor):
        raise ValueError("不支持的执行工具。")
    unique_ids = list(dict.fromkeys(task_id for task_id in task_ids if task_id))
    if not unique_ids:
        raise ValueError("请至少选择一张任务卡。")
    if len(unique_ids) > 50:
        raise ValueError("单次最多选择 50 张任务卡。")
    records = record_map()
    missing = [task_id for task_id in unique_ids if task_id not in records]
    if missing:
        raise ValueError("包含无效的任务卡。")
    lines = []
    for task_id in unique_ids:
        record = records[task_id]
        lines.append(
            f"- {task_id}｜{record.get('task_name') or record.get('title')}｜"
            f"{record.get('project_title')}｜{STATUS_LABEL.get(str(record.get('status') or ''), record.get('status'))}｜"
            f"{TYPE_LABEL.get(str(record.get('work_type') or ''), record.get('work_type'))}｜{record.get('canonical_path')}"
        )
    return render_catalog_prompt(
        "organization-selected",
        task="接收所选任务的整理上下文，等待 Evan 说明本轮整理目标。",
        selected_count=len(unique_ids),
        tasks="\n".join(lines),
        authorization=(
            "在 Evan 给出明确整理要求前，不创建、关闭、移动、合并或改写任务卡。"
            "收到要求后先形成建议和逐项确认清单，实际变更走 `ember-organization` 门禁。"
        ),
    )


def material_manager_task_organization_prompt(task_ids: list[str]) -> str:
    """Carry selected tasks into the material-manager confirmation/execution path."""
    unique_ids = list(dict.fromkeys(task_id for task_id in task_ids if task_id))
    records = record_map()
    if not unique_ids or any(task_id not in records for task_id in unique_ids):
        raise ValueError("包含无效的任务卡。")
    lines = [
        f"- {task_id}｜{records[task_id].get('task_name') or records[task_id].get('title')}｜"
        f"{records[task_id].get('canonical_path')}"
        for task_id in unique_ids
    ]
    return render_catalog_prompt(
        "organization-selected",
        task="以 `task_organization` 模式接收所选任务；等待 Evan 逐项确认后再执行精确变更。",
        selected_count=len(unique_ids),
        tasks="\n".join(lines),
        authorization=(
            "当前只读交接。逐项确认后，建立或复用 `work_type: organize` 控制任务并记录精确确认行，"
            "再通过 `ember-organization` 的确定性门禁执行；未确认项不变。"
        ),
    )


def selected_tasks_task_group_prompt(task_ids: list[str]) -> str:
    """Build a task-line creation handoff from selected ordinary tasks."""
    unique_ids = list(dict.fromkeys(task_id for task_id in task_ids if task_id))
    if len(unique_ids) < 2:
        raise ValueError("提炼任务主线至少需要选择两张普通任务卡。")
    records = record_map()
    if any(task_id not in records for task_id in unique_ids):
        raise ValueError("包含无效的关联任务卡。")
    if any(records[task_id].get("task_kind") == "task_group" for task_id in unique_ids):
        raise ValueError("任务主线不能嵌套，请只选择普通任务卡。")
    projects = {str(records[task_id].get("project") or "") for task_id in unique_ids} - {""}
    if len(projects) != 1:
        raise ValueError("提炼任务主线请选择同一项目下的普通任务卡。")
    project = projects.pop()
    source = allowed_source("project", project) or task_overview_source()
    return new_task_prompt("task_group", project, source, "gate", unique_ids)


def task_history_records(work_type: str) -> list[dict[str, object]]:
    return [record for record in collect_records() if record.get("record_type") == "task_card" and record.get("work_type") == work_type]


def task_history_context(work_type: str, project_name: str = "") -> str:
    records = sorted(task_history_records(work_type), key=lambda item: parse_sort_datetime(str(item.get("updated_at") or "")), reverse=True)
    if project_name:
        matching = [r for r in records if project_name in str(r.get("project_title") or "") or project_name in str(r.get("description") or "")]
        records = matching or records
    if not records:
        return "- 暂无历史任务。"
    return "\n".join(f"- {r.get('task_name') or r.get('title')}｜{r.get('status')}｜{r.get('canonical_path')}" for r in records[:20])


def collect_project_intro_tasks(project: str, history: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return project tasks not yet recorded in organization history, newest first."""
    organized: set[str] = set()
    for entry in history:
        for task_id in entry.get("source_tasks", []) or []:
            organized.add(str(task_id))
    records = [
        record for record in collect_records()
        if record.get("record_type") == "task_card" and record.get("project") == project
    ]
    records.sort(key=lambda record: parse_sort_datetime(str(record.get("updated_at") or "")), reverse=True)
    result: list[dict[str, object]] = []
    for record in records:
        task_id = str(record.get("task_id") or "")
        if task_id == project_intro_maintenance_task_id(project):
            continue
        if task_id in organized:
            continue
        source = task_source(task_id)
        excerpt = ""
        if source:
            try:
                fm, body = tasks.frontmatter(source.read_text(encoding="utf-8", errors="replace"))
                excerpt = tasks.first_section_paragraph(body) or str(record.get("description") or "")
            except OSError:
                excerpt = str(record.get("description") or "")
        result.append({
            "task_id": task_id,
            "task_name": str(record.get("task_name") or record.get("title") or task_id),
            "status": str(record.get("status") or ""),
            "updated_at": str(record.get("updated_at") or ""),
            "canonical_path": str(record.get("canonical_path") or ""),
            "excerpt": excerpt,
        })
    return result


def history_task_panel(work_type: str, title: str, search_id: str) -> str:
    records = sorted(task_history_records(work_type), key=lambda item: parse_sort_datetime(str(item.get("updated_at") or "")), reverse=True)
    rows = []
    for record in records:
        label = html.escape(str(record.get("task_name") or record.get("title") or record.get("task_id") or ""))
        search = html.escape((label + " " + str(record.get("description") or "") + " " + str(record.get("project_title") or "")).lower(), quote=True)
        executor = str(record.get("executor") or "未记录")
        model = str(record.get("execution_model") or "未报告")
        execution = html.escape(f"执行器 {executor} · 模型 {model}")
        rows.append(f'<article class="history-card" data-history-search="{search}" data-history-status="{html.escape(str(record.get("status") or ""), quote=True)}"><div><a href="/tasks/{quote(str(record.get("task_id") or ""))}">{label}</a><div class="meta">{html.escape(format_display_time(record.get("updated_at")))} · {html.escape(str(record.get("project_title") or ""))} · {execution}</div></div><span class="badge {html.escape(str(record.get("status") or ""))}">{STATUS_LABEL.get(str(record.get("status") or ""), str(record.get("status") or ""))}</span></article>')
    return f'<details class="history-panel"><summary class="section-head"><div><div class="eyebrow">HISTORY</div><h2>{html.escape(title)}</h2></div><span class="meta">{len(records)} 条 · 展开查看</span></summary><div class="history-controls"><input id="{search_id}" type="search" aria-label="搜索{html.escape(title)}" placeholder="搜索任务、项目或模型…"><select id="{search_id}Status" aria-label="筛选历史任务状态"><option value="">全部状态</option><option value="active">进行中</option><option value="waiting_user">待确认</option><option value="completed">已完成</option></select></div><div id="{search_id}List" class="history-grid">{"".join(rows) if rows else "<div class=subtitle>暂无历史任务</div>"}</div></details><script>(()=>{{const subseq=(q,s)=>{{let i=0,j=0;q=q.toLowerCase();s=s.toLowerCase();while(i<q.length&&j<s.length){{if(q[i]===s[j])i++;j++;}}return i===q.length;}};const q=document.getElementById("{search_id}"),s=document.getElementById("{search_id}Status");function f(){{const text=q.value.trim().toLowerCase(),status=s.value;document.querySelectorAll("#{search_id}List [data-history-search]").forEach(x=>x.style.display=(!text||subseq(text,x.dataset.historySearch))&&(!status||x.dataset.historyStatus===status)?"":"none")}}q?.addEventListener("input",f);s?.addEventListener("change",f)}})();</script>'


def publish_month_board(records: list[dict[str, object]]) -> str:
    today = __import__("datetime").date.today()
    current = today.strftime("%Y-%m")
    previous_day = (today.replace(day=1) - __import__("datetime").timedelta(days=1))
    previous = previous_day.strftime("%Y-%m")
    months = [(current, "本月"), (previous, "上月")]
    ledgers = [record for record in records if record.get("record_type") == "ledger_row"]
    panels = []
    tabs = []
    for index, (month, label) in enumerate(months):
        items = [r for r in ledgers if str(r.get("publish_date") or r.get("seq") or "").startswith(month.replace("-", "")) or str(r.get("publish_date") or "").startswith(month)]
        tabs.append(f'<button class="month-tab{" active" if index == 0 else ""}" data-month="{month}">{label} · {month}</button>')
        groups = []
        for slug in ("personal-blogger", "yoga-platform", "kesun-new-energy", "small-project-pool"):
            project_items_for_month = [r for r in items if r.get("project") == slug]
            if not project_items_for_month:
                continue
            rows = ''.join(f'<tr><td>{html.escape(str(r.get("seq") or ""))}</td><td>{html.escape(str(r.get("publish_date") or ""))}</td><td>{html.escape(str(r.get("platform") or ""))}</td><td>{html.escape(str(r.get("title") or ""))}</td><td>{html.escape(str(r.get("status") or ""))}</td></tr>' for r in project_items_for_month)
            pending = sum(1 for r in project_items_for_month if r.get("status") not in {"已归档", "已复盘"})
            title = str(project_items().get(slug, {}).get("title") or slug)
            groups.append(f'<div class="publish-project"><h3>{html.escape(title)} <span class="badge">{len(project_items_for_month)} 条</span> <span class="meta">待归档 {pending}</span></h3><div class="table-wrap"><table class="archive-table"><thead><tr><th>序号</th><th>发布日期</th><th>平台</th><th>主题</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table></div></div>')
        body = ''.join(groups) if groups else '<div class="subtitle">本月尚无发布登记。</div>'
        panels.append(f'<div class="publish-month{" active" if index == 0 else ""}" data-publish-month="{month}">{body}</div>')
    return f'<section class="panel publish-board"><div class="section-head"><div><div class="eyebrow">PUBLISH LEDGER</div><h2>月度发布记录</h2></div><span class="meta">各项目月度账本聚合</span></div><div class="month-tabs">{"".join(tabs)}</div>{"".join(panels)}</section><script>document.querySelectorAll(".month-tab").forEach(button=>button.addEventListener("click",()=>{{document.querySelectorAll(".month-tab").forEach(x=>x.classList.toggle("active",x===button));document.querySelectorAll(".publish-month").forEach(x=>x.classList.toggle("active",x.dataset.publishMonth===button.dataset.month))}}));</script>'


def _release_meta(item: dict[str, object], projects: dict[str, object]) -> tuple[str, str, str, str, str]:
    release_id = str(item.get("release_id") or "")
    project = str(item.get("project") or "")
    project_title = str(projects.get(project, {}).get("title") or ember_publish.PROJECT_TITLES.get(project, project))
    material = str(item.get("material_path") or "")
    material_name = Path(material).name if material else "未关联资料"
    return release_id, project, project_title, material, material_name


def _release_card_head(item: dict[str, object], projects: dict[str, object]) -> str:
    release_id, project, project_title, _, _ = _release_meta(item, projects)
    status = str(item.get("status") or "copy_review")
    return f'''<div class="release-card-head"><div><strong>{html.escape(str(item.get("topic") or "未命名发布"))}</strong><small>{html.escape(release_id)} · {html.escape(project_title)} · {html.escape(str(item.get("platform") or "未记录平台"))} · {html.escape(str(item.get("account") or "未记录账号"))}</small></div><span class="release-status {html.escape(status, quote=True)}">{html.escape(ember_publish.STATUS_LABELS.get(status, status))}</span></div>'''


def _release_hidden(item: dict[str, object], token: str) -> str:
    return (
        f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}">'
        f'<input type="hidden" name="return_to" value="/archive">'
        f'<input type="hidden" name="project" value="{html.escape(str(item.get("project") or ""), quote=True)}">'
        f'<input type="hidden" name="release_id" value="{html.escape(str(item.get("release_id") or ""), quote=True)}">'
    )


def _record_package_options(packages: list[dict[str, object]], current: str) -> str:
    options = ['<option value="">暂不关联资料</option>']
    if current and not any(str(package.get("path") or "") == current for package in packages):
        options.append(
            f'<option value="{html.escape(current, quote=True)}" selected>'
            f'{html.escape(Path(current).name or current)}</option>'
        )
    for package in packages:
        path = str(package.get("path") or "")
        name = str(package.get("name") or "")
        if len(name) > 30:
            name = f"{name[:18]}…{name[-10:]}"
        selected = path == current
        disabled = bool(package.get("linked")) and not selected
        options.append(
            f'<option value="{html.escape(path, quote=True)}"'
            f'{" selected" if selected else ""}{" disabled" if disabled else ""}>'
            f'{html.escape(name)}{" · 已关联" if package.get("linked") else ""}</option>'
        )
    return ''.join(options)


def publish_packages_payload() -> dict[str, object]:
    """Load processing packages only when a release drawer needs the picker."""
    packages = ember_publish.processing_packages()
    return {"packages": [
        {
            "name": str(item.get("name") or ""),
            "path": str(item.get("path") or ""),
            "linked": bool(item.get("linked")),
        }
        for item in packages
    ]}


def _release_detail_template(item: dict[str, object], projects: dict[str, object], token: str, packages: list[dict[str, object]]) -> str:
    release_id, project, project_title, material, _ = _release_meta(item, projects)
    status = str(item.get("status") or "copy_review")
    hidden = _release_hidden(item, token)
    options = _record_package_options(packages, material)
    confirm_actions = ''
    if status in {"copy_review", "published"}:
        primary_action = ''
        if status == "copy_review":
            primary_action = f'''<form method="post" action="/actions/publish-confirm">{hidden}<button class="button primary" type="submit">确认文案</button></form>'''
        confirm_actions = f'''<div class="release-drawer-actions"><form method="post" action="/actions/publish-status">{hidden}<input type="hidden" name="status" value="rejected"><button class="button ghost" type="submit">不采用</button></form>{primary_action}</div>'''
    return f'''<template id="release-detail-{html.escape(project, quote=True)}-{html.escape(release_id, quote=True)}"><div class="release-drawer-title"><div><span>{html.escape(release_id)} · {html.escape(project_title)}</span><h3>{html.escape(str(item.get("topic") or ""))}</h3></div><button type="button" class="release-drawer-close" aria-label="关闭记录详情">×</button></div><form method="post" action="/actions/publish-edit" class="release-drawer-form">{hidden}<label>主题<input name="topic" value="{html.escape(str(item.get("topic") or ""), quote=True)}" maxlength="80" required></label><div class="release-form-row"><label>平台<input name="platform" value="{html.escape(str(item.get("platform") or ""), quote=True)}" maxlength="40"></label><label>账号<input name="account" value="{html.escape(str(item.get("account") or ""), quote=True)}" maxlength="80"></label></div><label>关联资料<select name="material_path">{options}</select></label><label>文案正文<textarea name="copy_text" rows="8">{html.escape(str(item.get("copy_text") or ""))}</textarea></label><button class="button" type="submit">保存修改</button></form>{confirm_actions}</template>'''


def _workflow_card(item: dict[str, object], projects: dict[str, object], token: str) -> str:
    release_id, project, _, material, material_name = _release_meta(item, projects)
    status = str(item.get("status") or "copy_review")
    hidden = _release_hidden(item, token)
    drawer_id = f"release-detail-{project}-{release_id}"
    if status == "copy_review":
        actions = f'<button type="button" class="button primary tiny release-detail-open" data-release-template="{html.escape(drawer_id, quote=True)}">查看并确认</button>'
    elif status == "ready":
        actions = f'''<button type="button" class="button ghost tiny release-detail-open" data-release-template="{html.escape(drawer_id, quote=True)}">查看详情</button><form method="post" action="/actions/publish-status">{hidden}<input type="hidden" name="status" value="published"><button class="button primary tiny" type="submit">确认已发布</button></form>'''
    elif material:
        actions = f'''<button type="button" class="button ghost tiny release-detail-open" data-release-template="{html.escape(drawer_id, quote=True)}">查看详情</button><form method="post" action="/actions/publish-archive" data-execution-confirm data-execution-label="发布资料归档">{hidden}{execution_confirm_button("核对发布归档提示词并确认执行")}</form>'''
    else:
        actions = f'<button type="button" class="button primary tiny release-detail-open" data-release-template="{html.escape(drawer_id, quote=True)}">关联资料</button>'
    return f'''<article class="release-card workflow" data-release-status="{html.escape(status, quote=True)}">{_release_card_head(item, projects)}<div class="release-material"><span>资料：{html.escape(material_name)}</span></div><div class="release-card-actions">{actions}</div></article>'''


def publish_workbench(token: str, records: list[dict[str, object]] | None = None) -> str:
    """Render a left-to-right publishing state board with drawer-based editing."""
    records = ember_publish.list_records() if records is None else records
    packages: list[dict[str, object]] = []
    projects = {slug: item for slug, item in project_items().items() if slug in ember_publish.PROJECTS}
    counts = {status: sum(1 for item in records if item.get("status") == status) for status in ember_publish.STATUS_LABELS}
    project_options = '<option value="" selected disabled>请选择项目</option>' + ''.join(f'<option value="{html.escape(slug, quote=True)}">{html.escape(str(projects.get(slug, {}).get("title") or ember_publish.PROJECT_TITLES.get(slug, slug)))}</option>' for slug in ember_publish.PROJECTS)
    package_options = _record_package_options(packages, "")
    lanes = (
        ("copy_review", "待确认", "检查主题、文案和资料"),
        ("ready", "待发布", "文案已确认，等待实际发布"),
        ("published", "已发布·待归档", "确认资料并完成可靠归档"),
    )
    lane_html = []
    for status, title, subtitle in lanes:
        items = [item for item in records if str(item.get("status")) == status]
        cards = ''.join(_workflow_card(item, projects, token) for item in items)
        if not cards:
            cards = f'<div class="release-empty compact"><h3>暂无{html.escape(title)}内容</h3><p>{html.escape(subtitle)}</p></div>'
        lane_html.append(f'<section class="release-lane {status}"><div class="release-lane-head"><div><h3>{html.escape(title)}</h3><p>{html.escape(subtitle)}</p></div><b>{len(items)}</b></div><div class="release-lane-list">{cards}</div></section>')
    archived = [item for item in records if str(item.get("status")) in ("archived", "rejected")]
    archived_cards = ''.join(f'<article class="release-card history">{_release_card_head(item, projects)}</article>' for item in archived)
    templates = ''.join(_release_detail_template(item, projects, token, packages) for item in records if str(item.get("status")) not in ("archived", "rejected"))
    workbench = f'''<section class="panel publish-workbench">
      <div class="publish-workbench-head"><div><div class="eyebrow">PUBLISH WORKBENCH</div><h2>发布工作台</h2><p>待确认 → 待发布 → 已发布·待归档</p></div><div class="release-head-actions"><div class="release-overview"><span><b>{counts['copy_review']}</b> 待确认</span><span><b>{counts['ready']}</b> 待发布</span><span><b>{counts['published']}</b> 待归档</span><span><b>{counts['archived']}</b> 已归档</span></div><button type="button" class="button primary" id="releaseCreateOpen">登记发布</button></div></div>
      <div class="publish-workbench-layout">{''.join(lane_html)}</div>
      <details class="release-history"><summary><span>已归档与不采用</span><b>{len(archived)}</b></summary><div>{archived_cards or '<div class="inbox-empty">暂无历史记录。</div>'}</div></details>
      <div class="release-drawer-overlay" id="releaseDrawerOverlay"></div><aside class="release-drawer" id="releaseDetailDrawer" aria-label="发布记录详情"><div id="releaseDetailBody"></div></aside>
      <aside class="release-drawer" id="releaseCreateDrawer" aria-label="登记发布"><div class="release-drawer-title"><div><span>NEW RELEASE</span><h3>登记发布</h3></div><button type="button" class="release-drawer-close" aria-label="关闭登记发布">×</button></div><form class="release-drawer-form" id="releaseCreate" method="post" action="/actions/publish-create"><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="/archive"><label>项目<select name="project" required>{project_options}</select></label><label>发布主题<input name="topic" maxlength="80" required placeholder="这条内容讲什么"></label><label>关联资料<select name="material_path">{package_options}</select></label><div class="release-form-row"><label>平台<input name="platform" maxlength="40" placeholder="选填"></label><label>账号<input name="account" maxlength="80" placeholder="选填"></label></div><label>文案正文<textarea name="copy_text" rows="7" placeholder="可以不记录文案"></textarea></label><button class="button primary" type="submit">保存并进入待确认</button></form></aside>{templates}
    </section><script></script>'''
    workbench = workbench.replace('id="releaseDetailDrawer" aria-label=', 'id="releaseDetailDrawer" role="dialog" aria-modal="true" aria-label=', 1)
    workbench = workbench.replace('id="releaseCreateDrawer" aria-label=', 'id="releaseCreateDrawer" role="dialog" aria-modal="true" aria-label=', 1)
    workbench = workbench.rsplit("<script>", 1)[0] + r'''<script>(()=>{
      const overlay=document.getElementById('releaseDrawerOverlay'),detail=document.getElementById('releaseDetailDrawer'),create=document.getElementById('releaseCreateDrawer'),body=document.getElementById('releaseDetailBody');
      let activeDrawer=null,returnFocus=null,initialState='',submitting=false,drawerDirty=false,packagePromise=null;
      const focusables=drawer=>[...drawer.querySelectorAll('button,input,select,textarea,a[href]')].filter(node=>!node.disabled&&node.offsetParent!==null);
      const formState=drawer=>{const form=drawer.querySelector('form');return form?new URLSearchParams(new FormData(form)).toString():''};
      const dirty=()=>Boolean(activeDrawer&&!submitting&&(drawerDirty||formState(activeDrawer)!==initialState));
      const packageLabel=item=>{const name=String(item.name||'');return (name.length>30?`${name.slice(0,18)}…${name.slice(-10)}`:name)+(item.linked?' · 已关联':'')};
      async function hydratePackages(drawer){const selects=[...drawer.querySelectorAll('select[name="material_path"]')];if(!selects.length)return;try{packagePromise??=fetch('/api/publish/packages',{headers:{Accept:'application/json'}}).then(response=>{if(!response.ok)throw new Error();return response.json()});const data=await packagePromise;selects.forEach(select=>{const current=select.value;select.replaceChildren(new Option('暂不关联资料',''));(data.packages||[]).forEach(item=>{const option=new Option(packageLabel(item),item.path);option.disabled=Boolean(item.linked&&item.path!==current);option.selected=item.path===current;select.add(option)});if(current&&![...select.options].some(option=>option.value===current)){const option=new Option(current.split('/').pop()||current,current,true,true);select.add(option)};initialState=formState(drawer)})}catch(error){selects.forEach(select=>select.title='暂时无法读取资料')}}
      function close(force=false){if(!activeDrawer)return true;if(!force&&dirty()&&!window.confirm('尚有未保存内容，确定关闭吗？'))return false;overlay.classList.remove('open');detail.classList.remove('open');create.classList.remove('open');document.body.classList.remove('drawer-open');body.replaceChildren();activeDrawer=null;initialState='';const target=returnFocus;returnFocus=null;target?.focus();return true}
      function open(drawer,trigger){activeDrawer=drawer;returnFocus=trigger||document.activeElement;submitting=false;drawerDirty=false;overlay.classList.add('open');drawer.classList.add('open');document.body.classList.add('drawer-open');initialState=formState(drawer);hydratePackages(drawer);requestAnimationFrame(()=>focusables(drawer)[0]?.focus())}
      document.getElementById('releaseCreateOpen')?.addEventListener('click',event=>open(create,event.currentTarget));
      document.querySelectorAll('.release-detail-open').forEach(button=>button.addEventListener('click',()=>{const template=document.getElementById(button.dataset.releaseTemplate);if(!template)return;body.replaceChildren(template.content.cloneNode(true));open(detail,button)}));
      document.addEventListener('click',event=>{if(event.target.closest('.release-drawer-close')||event.target===overlay)close()});
      document.addEventListener('input',event=>{if(activeDrawer?.contains(event.target))drawerDirty=true});
      document.addEventListener('change',event=>{if(activeDrawer?.contains(event.target))drawerDirty=true});
      document.addEventListener('keydown',event=>{if(!activeDrawer)return;if(event.key==='Escape'){event.preventDefault();close();return}if(event.key!=='Tab')return;const nodes=focusables(activeDrawer);if(!nodes.length)return;const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}});
      document.addEventListener('submit',event=>{if(!event.target.closest('.release-drawer'))return;submitting=true;event.target.querySelector('button[type=submit]')?.setAttribute('disabled','disabled')});
    })();</script>'''
    return workbench


def project_continuation_prompt(project: str, source: Path) -> str:
    title = str(project_items().get(project, {}).get("title") or project)
    return render_catalog_prompt(
        "project-continuation",
        project=title,
        source=source,
    )


def markdown_for_html(markdown: str) -> str:
    from .pages.common import markdown_for_html as _present
    return _present(markdown)




CSS_VERSION = asset_version("workbench.css")
EXECUTION_CONFIRM_VERSION = asset_version("execution-confirm.js")
EMBER_UI_VERSION = asset_version("ember-ui.js")
SIDEBAR_VERSION = asset_version("sidebar.js")
TASK_DETAIL_VERSION = asset_version("task-detail.js")
HOME_VERSION = asset_version("home.js")
TASK_OVERVIEW_VERSION = asset_version("task-overview.js")
PROJECT_VERSION = asset_version("project.js")
PROJECTS_VERSION = asset_version("projects.js")
SYSTEM_VERSION = asset_version("system.js")
REVIEW_VERSION = asset_version("review.js")
LIBRARY_VERSION = asset_version("library.js")
SETTINGS_VERSION = asset_version("settings.js")
EXECUTOR_SETTINGS_VERSION = asset_version("executor-settings.js")
PROJECT_NAVIGATION_VERSION = hashlib.sha256(PROJECT_NAVIGATION_JS.encode("utf-8")).hexdigest()[:12]
BRAND_FAVICON = "data:image/svg+xml;base64," + base64.b64encode(EMBER_FAVICON_SVG.encode("utf-8")).decode("ascii")


def flash_message(notice: str = "", error: str = "") -> str:
    """Stage page-level action feedback for the shared top-right toast."""
    if error:
        return f'<div class="notice flash error" role="alert" hidden>{html.escape(error)}</div>'
    if notice:
        return f'<div class="notice flash" role="status" hidden>{html.escape(notice)}</div>'
    return ""

def _aria_current(active: bool) -> str:
    return ' aria-current="page"' if active else ""


def _sidebar_project_row(slug: str, item: dict[str, object], active_project: str, favorites: list[str]) -> dict[str, object]:
    category = str(item.get("work_category") or "other")
    return {"slug": slug, "title": str(item.get("title") or slug), "href": f"/projects/{quote(slug)}",
            "category": category if category in load_work_categories() else "other",
            "active": active_project == slug, "saved": slug in favorites}


def _sidebar_project_link(slug: str, item: dict[str, object], active_project: str, favorites: list[str]) -> str:
    return shell_page.project_row(_sidebar_project_row(slug, item, active_project, favorites))


def _layout(
    title: str,
    content: str,
    token: str,
    active_project: str = "",
    nav_prefix: str = "",
    active_review_view: str = "",
    page_kind: str = "",
) -> str:
    projects = project_items()
    if ember_env("EMBER_CENTRAL_MODE") == "1":
        replacements = (
            ("在 Finder 中显示", "浏览 NAS 文件夹"),
            ("Finder 中显示", "浏览 NAS 文件夹"),
            ("在 Finder 打开交付", "浏览 NAS 交付"),
            ("在 Finder 打开报告文件夹", "浏览 NAS 报告"),
            ("使用系统应用打开", "浏览器打开"),
            ("系统应用打开", "浏览器打开"),
            ("rsync 下载到本机", "下载到本机"),
        )
        for old, new in replacements:
            content = content.replace(old, new)
    environment_name = current_environment_name()
    environment = current_environment()
    environment_label = str(environment.get("label") or environment_name)
    machine_badge = f'<span class="machine" title="当前环境：{html.escape(environment_name, quote=True)}">当前机器 · {html.escape(environment_label)}</span>'
    sync_status = task_index_sync_status()
    sync_badge = task_index_sync_badge(sync_status)
    sync_alert = task_index_sync_alert(sync_status)
    active_title = "任务检视" if title in {"整理中心", "任务检视"} else "资料浏览" if title == "资料浏览" else "视图" if title == "项目视图" else "项目" if title.endswith("任务视图") or title.endswith("项目介绍") or title.endswith("文案") else "归档中心" if title in {"资料归档", "发布归档", "归档中心"} else "设置" if title in {"执行工具", "执行器", "执行环境", "Agents", "Skills", "模型与执行工具", "设置"} else "任务台"
    work_categories = load_work_categories()
    category_groups = [
        (category, str(rule["title"]), [(slug, item) for slug, item in projects.items() if item.get("work_category") == category])
        for category, rule in work_categories.items()
    ]
    other_projects = [(slug, item) for slug, item in projects.items() if item.get("work_category") not in work_categories]
    if other_projects:
        category_groups.append(("other", "其他项目", other_projects))
    favorites = project_favorites()
    workspace_html = shell_page.workspace_nav({
        "favorites": [_sidebar_project_row(slug, projects[slug], active_project, favorites) for slug in favorites],
        "favorites_empty": "右键项目或点星标收藏",
        "sections": [
            {"key": category, "label": label, "active": any(slug == active_project for slug, _ in members),
             "rows": [_sidebar_project_row(slug, item, active_project, favorites) for slug, item in members],
             "empty_html": f'<a href="/projects#{quote(category)}">尚未登记项目</a>'}
            for category, label, members in category_groups
        ],
    })
    bridge_picker = ('<div class="bridge-picker"><label for="ember-bridge-picker">执行目标</label>'
                     '<select id="ember-bridge-picker"><option value="">仅复制提示词</option></select></div>') if ember_env("EMBER_CENTRAL_MODE") == "1" else ""
    primary = [("任务台", "/", "任务台"), ("项目视图", "/projects", "视图"), ("归档中心", "/archive", "归档中心"),
               ("任务检视", "/review", "任务检视"), ("资料浏览", "/library", "资料浏览"), ("设置", "/settings", "设置")]
    sidebar = shell_page.sidebar({
        "brand": {"href": "/", "label": "余烬 · Ember AI 工作台首页", "name": "余烬 · Ember", "subtitle": "AI 工作台"},
        "nav_id": "gstudioSidebarNav", "nav_prefix_html": nav_prefix,
        "primary": [{"label": label, "href": href, "active": active_title == key} for label, href, key in primary],
        "workspace_html": workspace_html, "bottom_html": bridge_picker,
        "runtime_label": "当前机器与索引状态", "runtime_html": machine_badge + sync_badge,
    })
    sidebar_after = (
        f'<script id="sidebarNavigationState">{SIDEBAR_STATE_JS}</script>'
        '<form id="sidebarFavoriteForm" class="action-form" method="post" action="/actions/project-favorite" hidden>'
        f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}">'
        '<input type="hidden" name="project"><input type="hidden" name="favorite"><input type="hidden" name="return_to">'
        '<button type="submit">保存收藏</button></form>'
        '<div class="sidebar-project-menu" id="sidebarProjectMenu" role="menu" aria-label="项目收藏操作" hidden><button type="button" role="menuitem">收藏置顶</button></div>'
    )
    js = r"""(function(){
  const COOLDOWN_MS = 30000;
  const currentUrl = new URL(location.href);
  function stampTaskReturn(element){
    if(!element || location.pathname.startsWith('/tasks/')) return;
    const rawTarget = element.dataset?.href || element.href;
    if(!rawTarget) return;
    const target = new URL(rawTarget, location.origin);
    if(target.origin !== location.origin || !target.pathname.startsWith('/tasks/') || target.searchParams.has('return_to')) return;
    target.searchParams.set('return_to', location.pathname + location.search + location.hash);
    const stamped = target.pathname + target.search + target.hash;
    if(element.dataset?.href !== undefined) element.dataset.href = stamped;
    else element.href = stamped;
  }
  function taskReturnElement(target){return target.closest?.('a[href^="/tasks/"],[data-href^="/tasks/"]')}
  document.addEventListener('pointerdown', event=>stampTaskReturn(taskReturnElement(event.target)), true);
  document.addEventListener('click', event=>stampTaskReturn(taskReturnElement(event.target)), true);
  let hasTransientMessage = false;
  ['notice', 'error'].forEach(name=>{
    if(currentUrl.searchParams.has(name)){
      currentUrl.searchParams.delete(name);
      hasTransientMessage = true;
    }
  });
  if(hasTransientMessage){
    const query = currentUrl.searchParams.toString();
    history.replaceState(null, '', currentUrl.pathname + (query ? '?' + query : '') + currentUrl.hash);
  }
  const {toast:showToast, copyPrompt} = window.EmberUI;
  function actionKey(form, submitter){
    const parts = Array.from(form.querySelectorAll('input[type="hidden"]'))
      .filter(i=>i.name!=='csrf')
      .sort((a,b)=>a.name.localeCompare(b.name))
      .map(i=>i.name+'='+i.value);
    if(submitter && submitter.name) parts.push(submitter.name+'='+submitter.value);
    return (submitter?.hasAttribute('formaction') ? submitter.formAction : form.action) + '?' + parts.join('&');
  }
  function cooling(key){
    const ts = sessionStorage.getItem('ember-cooldown-' + key);
    return ts && (Date.now() - parseInt(ts,10)) < COOLDOWN_MS;
  }
  document.querySelectorAll('.action-form').forEach(form=>{
    form.addEventListener('submit', async e=>{
      e.preventDefault();
      const key = actionKey(form, e.submitter);
      const actionUrl = e.submitter?.hasAttribute('formaction') ? e.submitter.formAction : form.action;
      const actionPath = new URL(actionUrl).pathname;
      const isHomeLaunch = location.pathname === '/' && (
        actionPath === '/actions/route-task' ||
        actionPath === '/actions/new-task' ||
        actionPath === '/actions/continue-task'
      );
      const bridgePicker = document.getElementById('ember-bridge-picker');
      const executorAction = e.submitter?.name === 'executor' || Boolean(form.querySelector('input[name="executor"]'));
      if(executorAction && bridgePicker?.dataset.targetOffline === '1'){
        showToast(`${bridgePicker.dataset.targetLabel || '上次选择的执行电脑'}当前离线，请选择在线电脑或“仅复制提示词”`, 'error', 5000);
        return;
      }
      if (!isHomeLaunch && cooling(key)){
        showToast('近期已经点击过，请稍后再试', 'info', 3000);
        return;
      }
      const btn = e.submitter || form.querySelector('button[type="submit"]');
      const original = btn.textContent;
      btn.disabled = true;
      const iconTrigger=btn.matches('[data-execution-confirm-trigger],.ember-action-trigger');
      if(iconTrigger)btn.setAttribute('aria-busy','true');else btn.textContent = '处理中…';
      try{
        const payload = new URLSearchParams(new FormData(form));
        if(bridgePicker && bridgePicker.value) payload.set('machine_id', bridgePicker.value);
        if(e.submitter && e.submitter.name) payload.set(e.submitter.name, e.submitter.value);
        const res = await fetch(actionUrl, {
          method: 'POST',
          headers: {'Accept': 'application/json'},
          body: payload
        });
        const data = await res.json();
        if(data.ok){
          if(data.clipboard_text){
            const copied = await copyPrompt(data.clipboard_text);
            if(copied){
              showToast(data.notice || '提示词已复制，请到已接入 余烬 · Ember 的 AI 工具中粘贴发送。', 'info', 5000);
            }else{
              window.prompt('自动复制失败，请手动复制完整提示词：', data.clipboard_text);
              showToast('请复制提示词，并到已接入 余烬 · Ember 的 AI 工具中粘贴发送。', 'error', 5000);
            }
            sessionStorage.setItem('ember-cooldown-' + key, String(Date.now()));
            return;
          }
          if(data.redirect){
            const destination = new URL(data.redirect, location.origin);
            if(data.notice) destination.searchParams.set('notice', data.notice);
            location.href = destination.pathname + destination.search + destination.hash;
            return;
          }
          if(form.dataset.reloadOnSuccess === '1'){
            location.reload();
            return;
          }
          if(isHomeLaunch){
            location.href = '/?notice=' + encodeURIComponent(data.notice || '已启动');
            return;
          }
          showToast(data.notice || '已完成', 'info', 3000);
          sessionStorage.setItem('ember-cooldown-' + key, String(Date.now()));
        } else {
          showToast(data.error || '操作失败', 'error', 5000);
        }
      }catch(err){
        showToast('网络或服务器错误，请刷新后重试', 'error', 5000);
      }finally{
        btn.disabled = false;
        if(iconTrigger)btn.removeAttribute('aria-busy');else btn.textContent = original;
        window.EmberExecutionTarget?.syncButtons();
      }
    });
  });
  const bridgePicker = document.getElementById('ember-bridge-picker');
  if(bridgePicker){
    const storageKey = 'ember-execution-target-v1';
    function readTarget(){
      try{
        const value = JSON.parse(localStorage.getItem(storageKey) || 'null');
        return value && typeof value.id === 'string' ? value : {id:'',label:'仅复制提示词'};
      }catch(error){
        return {id:'',label:'仅复制提示词'};
      }
    }
    function writeTarget(target){
      try{ localStorage.setItem(storageKey, JSON.stringify(target)); }catch(error){}
    }
    function selectedTarget(){
      const option = bridgePicker.selectedOptions[0];
      return {
        id: bridgePicker.value,
        label: option?.dataset.machineLabel || (bridgePicker.value ? option?.textContent || bridgePicker.value : '仅复制提示词'),
        finder: option?.dataset.finder === '1'
      };
    }
    function syncButtons(){
      const target = selectedTarget();
      const offline = bridgePicker.dataset.targetOffline === '1';
      document.querySelectorAll('.executor-btn').forEach(button=>{
        if(button.matches('[data-execution-confirm-trigger]'))return;
        const form = button.closest('form');
        const executor = button.value || form?.querySelector('input[name="executor"]')?.value || (button.classList.contains('opencode') ? 'opencode' : 'codex');
        const executorLabel = executor === 'opencode' ? 'OpenCode' : 'Codex';
        button.textContent = `打开 ${executorLabel}`;
        if(!target.id){
          button.title = `复制完整提示词，由你粘贴到 ${executorLabel}`;
        }else if(offline){
          button.title = `${target.label} 当前离线；请选择在线电脑或仅复制提示词`;
        }else{
          button.title = `把提示词派发到 ${target.label} 并打开 ${executorLabel}`;
        }
      });
      document.querySelectorAll('[data-bridge-action="nas"]').forEach(form=>{
        const button = form.querySelector('button');
        let machine = form.querySelector('input[name="machine_id"]');
        if(!machine){
          machine = document.createElement('input');
          machine.type = 'hidden';
          machine.name = 'machine_id';
          form.appendChild(machine);
        }
        machine.value = target.id;
        button.disabled = !target.id || offline || !target.finder;
        button.title = !target.id
          ? '请先在执行目标中选择要打开 NAS 的电脑'
          : offline
            ? `${target.label} 当前离线，无法打开 NAS 挂载盘`
            : !target.finder
              ? `${target.label} 的执行桥需要更新后才能打开 NAS`
              : `在 ${target.label} 的 Finder 中显示 NAS 挂载盘文件`;
      });
    }
    function applyTarget(target, bridges){
      const match = bridges.find(item=>String(item.machine_id || '') === target.id);
      bridgePicker.dataset.targetOffline = target.id && !match ? '1' : '0';
      bridgePicker.dataset.targetLabel = match ? String(match.label || match.machine_id) : String(target.label || target.id || '');
      if(target.id && !match){
        const option = new Option(`${bridgePicker.dataset.targetLabel}（离线）`, target.id);
        option.dataset.machineLabel = bridgePicker.dataset.targetLabel;
        option.dataset.offline = '1';
        bridgePicker.add(option);
      }
      bridgePicker.value = target.id;
      syncButtons();
    }
    window.EmberExecutionTarget = {syncButtons};
    const rememberedTarget = readTarget();
    fetch('/api/central/bridges', {headers:{'Accept':'application/json'}}).then(response=>response.json()).then(data=>{
      const bridges = Array.isArray(data.bridges) ? data.bridges : [];
      bridgePicker.innerHTML = '';
      bridgePicker.add(new Option('仅复制提示词', ''));
      bridges.forEach(item=>{
        const label = String(item.label || item.machine_id);
        const option = new Option(`在 ${label} 执行`, item.machine_id);
        option.dataset.machineLabel = label;
        option.dataset.finder = Array.isArray(item.executors) && item.executors.includes('finder') ? '1' : '0';
        bridgePicker.add(option);
      });
      applyTarget(rememberedTarget, bridges);
    }).catch(()=>{
      bridgePicker.innerHTML = '';
      bridgePicker.add(new Option('仅复制提示词', ''));
      applyTarget(rememberedTarget, []);
    });
    bridgePicker.addEventListener('change', ()=>{
      bridgePicker.dataset.targetOffline = bridgePicker.selectedOptions[0]?.dataset.offline === '1' ? '1' : '0';
      const target = selectedTarget();
      bridgePicker.dataset.targetLabel = target.label;
      writeTarget(target);
      syncButtons();
    });
    syncButtons();
  }
  document.querySelectorAll('.notice.flash').forEach(el=>{
    const type = el.classList.contains('error') ? 'error' : 'info';
    showToast(el.textContent || (type === 'error' ? '操作失败' : '操作完成'), type, type === 'error' ? 6000 : 3200);
    el.remove();
  });
})();"""
    if page_kind == "task-detail":
        page_class = " task-detail-page paper-management-page"
    elif page_kind == "project-workspace":
        page_class = " project-workspace-page paper-management-page"
    elif page_kind == "system-workspace":
        page_class = " system-workspace-page paper-management-page"
    elif title == "任务台":
        page_class = " home-page"
    elif title in {"整理中心", "任务检视"}:
        page_class = " organization-page paper-management-page"
    elif title == "归档中心":
        page_class = " archive-page paper-management-page"
    elif title == "项目视图":
        page_class = " project-view-page paper-management-page"
    elif title == "资料浏览":
        page_class = " library-page paper-management-page"
    elif title == "设置":
        page_class = " settings-page paper-management-page"
    else:
        page_class = ""
    environment = execution_environment()
    return shell_page.document({
        "title": "余烬 · Ember AI 工作台" if title == "任务台" else f"{title} · 余烬 · Ember AI 工作台", "icon": {"href": BRAND_FAVICON},
        "stylesheets": [(f"/assets/workbench.css?v={CSS_VERSION}", ())],
        "body_class": "paper-management-shell" if "paper-management-page" in page_class else "",
        "sidebar_html": sidebar, "sidebar_after_html": sidebar_after,
        "main": {"class": f"shell app-main{page_class}"}, "content_html": sync_alert + content,
        "after_main_html": shell_page.execution_dialog({"default_executor": environment["executor"], "configure_href": "/settings#execution"}),
        "scripts": [{"src": f"/assets/ember-ui.js?v={EMBER_UI_VERSION}"}, {"html": f"<script>{js}</script>"},
                    {"src": f"/assets/sidebar.js?v={SIDEBAR_VERSION}"}, {"src": f"/assets/project-navigation.js?v={PROJECT_NAVIGATION_VERSION}"},
                    {"src": f"/assets/execution-confirm.js?v={EXECUTION_CONFIRM_VERSION}"}],
    })


def render_status_page(title: str, heading: str, detail: str, token: str) -> str:
    from .pages.common import render_status_page as _present
    return _present(title, heading, detail, token)


ARCHIVE_ATTENTION_STATES = {"source_changed", "conflict", "failed_retryable", "receipt_pending"}


def home_attention_items() -> list[tuple[str, str]]:
    """Collect cheap needs-attention signals that are otherwise page-local."""
    items: list[tuple[str, str]] = []
    try:
        today = weekly_task_review.review_day(datetime.date.today())
        weekly = weekly_task_review.load_weekly_view(today)
        canonical = weekly_organization_task(
            organization_report_records(resolve_reports=False), str(weekly.get("week") or "")
        )
        if canonical:
            if str(canonical.get("status") or "") != "completed":
                labels = {
                    "awaiting_feedback": "本周整理建议待确认",
                    "confirmed_actions_pending_execution": "本周整理已确认，待执行",
                    "executing": "本周整理执行中",
                    "execution_needs_attention": "本周整理执行有失败项",
                    "ready_to_finalize": "本周整理待系统收口",
                }
                items.append(("/review", labels.get(str(canonical.get("current_stage") or ""), "本周整理进行中")))
        else:
            weekly_status = weekly.get("status") if isinstance(weekly.get("status"), dict) else {}
            if str(weekly_status.get("state") or "") == "pending_confirmation":
                items.append(("/review", "本周整理建议待确认"))
    except Exception:
        items.append(("/review", "周整理状态暂时无法读取"))
    payload = _archive_queue_payload_safe()
    if payload.get("_load_error"):
        items.append(("/archive", "归档队列状态暂时无法读取"))
    else:
        exception_count = sum(
            1 for item in payload.get("items", [])
            if str(item.get("state") or "") in ARCHIVE_ATTENTION_STATES
        )
        if exception_count:
            items.append(("/archive", f"归档中心有 {exception_count} 项异常待处理"))
    return items


def task_group_tag(record: dict[str, object]) -> str:
    """Render the shared user-facing task-line marker."""
    return '<span class="task-group-tag">任务主线</span>' if record.get("task_kind") == "task_group" else ""


def _form(
    action: str,
    token: str,
    fields: dict[str, str],
    label: str,
    css: str = "button",
    *,
    reload_on_success: bool = False,
) -> str:
    inputs = [f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}">']
    inputs.extend(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v, quote=True)}">' for k, v in fields.items())
    reload_attr = ' data-reload-on-success="1"' if reload_on_success else ""
    return f'<form class="action-form" method="post" action="{action}" data-action="{html.escape(action, quote=True)}"{reload_attr}>{"".join(inputs)}<button class="{css}" type="submit">{html.escape(label)}</button></form>'


def execution_prompt_preview(action: str, form: dict[str, str], parsed_form: dict[str, list[str]]) -> dict[str, str]:
    """Build a side-effect-free preview using the same canonical prompt builders."""
    executor = form.get("executor", "codex") or "codex"
    selections = parsed_form.get("selection", [])
    if action == "/actions/create-task-from-deliveries":
        return {"title": "从交付物建立新任务", "scope": f"已选 {len(selections)} 个交付文件", "prompt": create_task_from_deliveries_prompt(selections)}
    if action == "/actions/create-task-from-inputs":
        return {"title": "用输入资料开始处理", "scope": f"已选 {len(selections)} 条输入资料", "prompt": create_task_from_inputs_prompt(selections)}
    if action == "/actions/revise-library-files":
        return {"title": "交付文件二次处理", "scope": f"已选 {len(selections)} 个交付文件", "prompt": library_multi_revision_prompt(selections)}
    if action == "/actions/continue-task":
        task_id = form.get("task_id", "")
        record = record_map().get(task_id)
        source = task_source(task_id)
        if not record or not source:
            raise ValueError("没有找到对应任务卡。")
        prompt = continuation_prompt(record, source, selections, form.get("create_new_task", "") == "1")
        title = str(record.get("task_name") or record.get("title") or task_id)
        return {"title": f"继续 · {title}", "scope": f"任务 {task_id} · 所选文件 {len(selections)} 个", "prompt": prompt}
    if action == "/actions/continue-project":
        project = form.get("project", "")
        source = allowed_source("project", project)
        if not source:
            raise ValueError("没有找到对应项目看板。")
        return {"title": f"继续项目 · {project}", "scope": project, "prompt": project_continuation_prompt(project, source), "fixed_executor": "codex"}
    if action == "/actions/new-task":
        task_type = form.get("task_type", "")
        project = form.get("project", "")
        related = parsed_form.get("related_task_id", [])
        if task_type not in NEW_TASK_LABEL:
            raise ValueError("不支持的新建任务类型。")
        source = allowed_source("project", project) if project else None
        prompt = new_task_prompt(task_type, project, source, form.get("delivery_mode", "gate"), related)
        return {"title": NEW_TASK_LABEL[task_type], "scope": project or "由任务门禁判断项目", "prompt": prompt}
    if action == "/actions/workspace-inbox-task":
        task = form.get("inbox_action", "")
        prompt = workspace_inbox_task_prompt(task, parsed_form.get("source_path", []), parsed_form.get("archive_path", []))
        labels = {"organize_workspace":"整理工作台", "archive_selected":"归档选中内容", "organize_archive":"整理当前归档", "organize_baidu":"整理百度历史归档", "check_indexes":"检查归档备份", "publish_archive":"发布归档"}
        count = len(parsed_form.get("source_path", [])) + len(parsed_form.get("archive_path", []))
        return {"title": labels.get(task, "资料归档"), "scope": f"已选 {count} 项" if count else "整个约定范围", "prompt": prompt}
    if action == "/actions/archive-item":
        prompt = archive_item_prompt(form.get("project_name", ""), form.get("remote_path", ""), form.get("item_name", ""))
        return {"title": f"归档 · {form.get('item_name') or '项目'}", "scope": form.get("remote_path", ""), "prompt": prompt}
    if action == "/actions/create-task-group-from-selection":
        task_ids = parsed_form.get("selected_task_id", [])
        return {"title": "提炼任务主线", "scope": f"已选 {len(dict.fromkeys(task_ids))} 张任务卡", "prompt": selected_tasks_task_group_prompt(task_ids), "fixed_executor": "codex"}
    if action == "/actions/organize-selected-tasks":
        task_ids = parsed_form.get("selected_task_id", [])
        return {"title": "按任务整理", "scope": f"已选 {len(dict.fromkeys(task_ids))} 张任务卡", "prompt": selected_tasks_organization_prompt(executor, task_ids)}
    if action == "/actions/organization-start":
        mode, scope = form.get("mode", ""), form.get("scope", "")
        return {"title": ember_organization.MODE_LABELS.get(mode, "整理"), "scope": scope or "当前范围", "prompt": organization_prompt(executor, mode, scope)}
    if action == "/actions/weekly-confirm":
        project = form.get("project_name", "")
        prompt = weekly_confirmation_prompt(executor, new_round=form.get("new_round", "0") == "1", project_name=project)
        return {"title": f"每周整理 · {project}" if project else "每周整理", "scope": project or "本周全部项目", "prompt": prompt}
    if action == "/actions/organize-project-intro":
        project = form.get("project", "")
        return {"title": "整理项目介绍", "scope": project, "prompt": organize_project_intro_prompt(executor, project)}
    if action == "/actions/organize-project-intro-chat":
        project = form.get("project", "")
        return {"title": "讨论项目介绍", "scope": project, "prompt": organize_project_intro_chat_prompt(executor, project, form.get("user_input", ""))}
    if action == "/actions/maintain-project-intro":
        project = form.get("project", "")
        return {"title": "维护项目介绍", "scope": project, "prompt": maintain_project_intro_prompt(project, form.get("user_input", ""))}
    if action == "/actions/archive-maintenance-start":
        scope = form.get("scope", "inbox")
        return {"title": "整理收件箱", "scope": scope, "prompt": archive_maintenance_prompt(scope)}
    if action == "/actions/publish-archive":
        project, release_id = form.get("project", ""), form.get("release_id", "")
        record = ember_publish.find_record(project, release_id)
        if not record:
            raise ValueError("发布记录不存在。")
        return {"title": "发布资料归档", "scope": f"{project} · {release_id}", "prompt": publish_record_archive_prompt(record)}
    raise ValueError("这个动作尚未接入统一执行确认。")


def _executor_css(executor: str) -> str:
    return "executor-btn codex" if executor == "codex" else "executor-btn opencode"


def _execution_form(action: str, token: str, fields: dict[str, str], label: str, *, fixed_executor: str = "", css: str = "") -> str:
    inputs = [f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}">']
    inputs.extend(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v, quote=True)}">' for k, v in fields.items())
    fixed = f' data-fixed-executor="{html.escape(fixed_executor, quote=True)}"' if fixed_executor else ""
    return (
        f'<form class="action-form {html.escape(css, quote=True)}" method="post" action="{action}" data-execution-confirm '
        f'data-execution-label="{html.escape(label, quote=True)}"{fixed}>{"".join(inputs)}'
        f'{execution_confirm_button(label)}</form>'
    )


EXECUTOR_LABEL = {"codex": "Codex", "opencode": "OpenCode", "kimi": "OpenCode"}
# Display names for the task-card `executor` record; launchable executors stay in EXECUTOR_LABEL.
TASK_EXECUTOR_LABEL = {
    "codex": "Codex", "opencode": "OpenCode", "claude-code": "Claude Code", "workbuddy": "WorkBuddy",
    "qianwen-office": "千问办公", "doubao-work": "豆包工作", "external": "外部", "manual": "人工",
}


def weekly_action_menu(token: str, *, completed: bool, return_to: str) -> str:
    label = "再次整理" if completed else "开始整理"
    form = _execution_form('/actions/weekly-confirm', token, {'new_round':'1' if completed else '0','return_to':return_to}, f'{label}并确认执行器')
    return f'<div class="weekly-actions inline"><span class="weekly-action-label">{html.escape(label)}</span>{form}</div>'


def new_task_entry_grid(token: str, project: str = "", return_to: str = "/") -> str:
    """Render the task-type entry cards with Codex/OpenCode choices."""
    cards = []
    for task_type, label in NEW_TASK_LABEL.items():
        fields = {"task_type": task_type, "return_to": return_to}
        if project:
            fields["project"] = project
        action = _execution_form("/actions/new-task", token, fields, f"建立{label}并确认执行器")
        short_desc = html.escape(NEW_TASK_SHORT_DESCRIPTION.get(task_type, ""))
        cards.append(
            f'<article class="task-entry">'
            f'<div class="task-entry-main"><h3>{html.escape(label)}</h3>'
            f'<div class="task-entry-desc">{short_desc}</div></div>'
            f'<div class="task-entry-actions">{action}</div>'
            f'</article>'
        )
    return f'<div class="task-entry-grid">{"".join(cards)}</div>'


def project_task_entry_grid(project: str, token: str, return_to: str) -> str:
    """Render the five task-type entry cards scoped to a specific project."""
    cards = []
    for task_type, label in NEW_TASK_LABEL.items():
        if task_type in ("task_group", "generic"):
            continue
        action = _execution_form(
            "/actions/new-task", token,
            {"task_type": task_type, "project": project, "return_to": return_to},
            f"在项目内建立{label}并确认执行器",
        )
        short_desc = html.escape(NEW_TASK_SHORT_DESCRIPTION.get(task_type, ""))
        cards.append(
            f'<article class="task-entry">'
            f'<div class="task-entry-main"><h3>{html.escape(label)}</h3>'
            f'<div class="task-entry-desc">{short_desc}</div></div>'
            f'<div class="task-entry-actions">{action}</div>'
            f'</article>'
        )
    return f'<div class="task-entry-grid">{"".join(cards)}</div>'


def project_task_launcher(project: str, token: str, return_to: str, *, system: bool = False) -> str:
    """Render a single hot entry point for starting work in a project or system."""
    action = _execution_form(
        "/actions/new-task", token,
        {"task_type": "generic", "project": project, "return_to": return_to},
        "开始系统任务并确认执行器" if system else "开始项目任务并确认执行器",
    )
    return f'<div class="project-task-launcher">{action}</div>'


def project_overview_cards(records: list[dict[str, object]]) -> str:
    projects = project_items()
    cards = []
    for slug in formal_project_slugs():
        if slug not in projects:
            continue
        item = projects[slug]
        matching = [record for record in records if record.get("project") == slug]
        active = sum(1 for record in matching if record.get("status") == "active")
        deliveries = sum(1 for record in matching if record.get("delivery_folder") or record.get("paths"))
        ledgers = sum(1 for record in matching if record.get("record_type") == "ledger_row")
        capabilities = set(map(str, item.get("capabilities") or []))
        archive_action = f'<a class="button" href="/archive?project={quote(slug)}">资料归档</a>' if "archive" in capabilities else ""
        result_label = "交付" if "ember_delivery" in capabilities else "外部结果"
        cards.append(f'<article class="panel project-card"><div class="new-task-head"><h3><a href="/projects/{quote(slug)}">{html.escape(str(item.get("title") or slug))}</a></h3>{archive_action}</div><div class="facts facts-3"><div class="fact"><small>进行中</small>{active}</div><div class="fact"><small>{result_label}</small>{deliveries}</div><div class="fact"><small>发布</small>{ledgers if "publishing" in capabilities else "—"}</div></div></article>')
    return ''.join(cards)


def project_center_tabs(active_project: str = "") -> str:
    projects = project_items()
    overview_class = ' class="current"' if not active_project else ""
    links = [f'<a{overview_class} href="/projects">项目总览</a>']
    for slug in project_display_order():
        item = projects.get(slug)
        if not item:
            continue
        current = ' class="current"' if slug == active_project else ""
        links.append(f'<a{current} href="/projects/{quote(slug)}">{html.escape(str(item.get("title") or slug))}</a>')
    return f'<nav class="project-center-tabs" aria-label="项目切换">{"".join(links)}</nav>'


STALE_DAYS = 21
STATUS_LABEL_PROJECT = {
    "normal": "正常推进",
    "attention": "需要关注",
    "stalled": "暂无推进",
}


def _project_task_records(project: str, records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [record for record in records if record.get("project") == project and record.get("record_type") == "task_card"]


def _parse_record_datetime(record: dict[str, object]) -> datetime.datetime | None:
    return parse_sort_datetime(str(record.get("updated_at") or ""))


def _project_status_and_reason(records: list[dict[str, object]], project: str) -> tuple[str, str]:
    """Return (status_key, reason_text) for a project overview card.

    Rules:
      - stalled: no active tasks.
      - attention: the whole project lacks recent activity or most active tasks are stale.
      - normal: otherwise.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    matching = _project_task_records(project, records)
    active = [record for record in matching if record.get("status") == "active"]
    if not active:
        return "stalled", "没有进行中任务"
    stale = [
        record for record in active
        if not (updated := _parse_record_datetime(record)) or (now - updated).days > STALE_DAYS
    ]
    if len(stale) == len(active):
        return "attention", f"所有进行中任务均超过 {STALE_DAYS} 天未更新"
    if len(stale) * 2 > len(active):
        return "attention", f"过半进行中任务超过 {STALE_DAYS} 天未更新"
    if len(active) >= 6:
        return "normal", f"有近期更新；当前进行中任务较多（{len(active)} 项）"
    return "normal", "有近期更新，没有明显停滞"


def _next_task_for_project(records: list[dict[str, object]], project: str) -> tuple[dict[str, object] | None, str]:
    """Pick the next task from existing cards and explain why.

    Priority:
      1. manually designated project focus task;
      2. active tasks with a draft delivery, most recently updated;
      3. most recently updated active task;
      4. stale active task that is not closed yet;
      5. none -> (None, "")
    """
    matching = _project_task_records(project, records)
    active = [record for record in matching if record.get("status") == "active"]
    if not active:
        return None, ""

    # 1. manually designated focus task
    focus_id = project_items().get(project, {}).get("focus_task_id")
    if focus_id:
        for record in active:
            if str(record.get("task_id") or "") == str(focus_id):
                return record, "Evan 手动指定为项目重点任务"

    # 2. draft deliveries waiting for confirmation
    drafts = [record for record in active if "交付/草稿/" in str(record.get("delivery_folder") or "")]
    if drafts:
        drafts.sort(key=lambda record: _parse_record_datetime(record) or datetime.datetime.min, reverse=True)
        return drafts[0], "该任务已有草稿交付，等待确认后即可完成"

    # 3. most recently updated active task
    active.sort(key=lambda record: _parse_record_datetime(record) or datetime.datetime.min, reverse=True)
    if active:
        latest = active[0]
        return latest, "该项目最近仍在推进此任务"

    return None, ""


def _organize_url_for_project(project: str) -> str:
    """Open task organization with only the selected project prefilled."""
    return "/weekly?" + urlencode({"project": project})


def _project_board_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Board rows of the projects view, in the shape ember_ui.pages.projects renders."""
    rows = []
    for record in records:
        task_id = str(record.get("task_id") or "")
        status = str(record.get("status") or "")
        rows.append({
            "task_id": task_id, "title": str(record.get("task_name") or record.get("title") or task_id),
            "href": f"/tasks/{quote(task_id)}", "task_line": record.get("task_kind") == "task_group",
            "return_column": "completed" if status == "completed" else ("active" if status == "active" else ""),
        })
    return rows


def _project_board_columns(important, active, completed) -> list[dict[str, object]]:
    return [
        {"key": "important", "label": "当前重要事项", "empty": "拖动任务到这里", "rows": _project_board_rows(important)},
        {"key": "active", "label": "进行中", "empty": "无进行中任务", "rows": _project_board_rows(active)},
        {"key": "completed", "label": "近 30 天完成", "empty": "近 30 天无完成", "rows": _project_board_rows(completed)},
    ]


def _legacy_render_home(token: str, notice: str='', error: str='') -> str:
    from .pages.home import _legacy_render_home as _present
    return _present(token, notice, error)


def task_overview_data(records: list[dict[str, object]]) -> dict[str, object]:
    from .pages.task import task_overview_data as _present
    return _present(records)


def task_overview_section(records: list[dict[str, object]], token: str) -> str:
    """Render the homepage's read-only, cross-project task browser."""
    return home_page.task_overview(task_overview_data(records))


def launcher_task_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Show active cards first, then all remaining cards by update time."""
    return sorted(
        (record for record in records if record.get("record_type") == "task_card"),
        key=lambda record: (
            1 if record.get("status") == "active" else 0,
            parse_sort_datetime(str(record.get("updated_at") or "")),
        ),
        reverse=True,
    )


HOME_ROUTER_SCRIPT = r'''<script>(()=>{const input=document.getElementById('homeCommandInput'),results=document.getElementById('homeTaskResults'),form=document.getElementById('homeCommandForm'),supplement=document.getElementById('homeSupplementText'),zone=document.getElementById('homeMaterialZone'),chipsBox=document.getElementById('homeMaterialChips'),selectedId=document.getElementById('homeSelectedTaskId'),chip=document.getElementById('homeContextChip'),chipLabel=document.getElementById('homeContextLabel'),chipLink=document.getElementById('homeContextLink'),chipClear=document.getElementById('homeContextClear'),hint=document.getElementById('homeIntentHint');if(!input||!form)return;const taskMeta=__TASK_META__;let selectedTask='',selectedTitle='',request=0,activeIndex=-1,resultItems=[];function routeMode(){return document.querySelector('[name=route_mode]:checked')?.value||'new'}function setRouteMode(value){document.querySelectorAll('[name=route_mode]').forEach(item=>item.checked=item.value===value)}function specialIntent(){const text=input.value.trim();if(/整理|任务主线|合并|拆分/.test(text))return{label:'看起来像任务整理',href:'/weekly'};if(/归档|入库/.test(text))return{label:'看起来像资料归档',href:'/archive'};return null}function syncHint(){const intent=specialIntent();if(intent){hint.innerHTML=`<span>${intent.label}</span><a href="${intent.href}">前往${intent.href==='/weekly'?'任务检视':'归档中心'}</a>`;hint.hidden=false}else{hint.hidden=true}return intent}function clearContext(){selectedTask='';selectedTitle='';selectedId.value='';chip.hidden=true;if(routeMode()!=='new')setRouteMode('new')}function formatSize(bytes){if(bytes>=1048576)return (bytes/1048576).toFixed(1)+' MB';return Math.max(1,Math.round(bytes/1024))+' KB'}function addChip({name,detail,onRemove,loading,error}){const chipEl=document.createElement('span');chipEl.className='home-material-chip'+(loading?' loading':'')+(error?' error':'');const strong=document.createElement('b');strong.textContent=name;const small=document.createElement('i');small.textContent=detail;chipEl.append(strong,small);if(onRemove){const remove=document.createElement('button');remove.type='button';remove.setAttribute('aria-label','移除材料');remove.textContent='✕';remove.addEventListener('click',onRemove);chipEl.append(remove)}chipsBox.append(chipEl);return chipEl}async function stageFile(file){const chipEl=addChip({name:file.name,detail:'上传中…',loading:true});try{const data=new FormData();data.append('csrf',form.querySelector('[name=csrf]').value);data.append('file',file,file.name);const response=await fetch('/api/router/stage-file',{method:'POST',headers:{Accept:'application/json'},body:data}),payload=await response.json();if(!response.ok||payload.error)throw new Error(payload.error||'上传失败');chipEl.classList.remove('loading');chipEl.querySelector('i').textContent=formatSize(Number(payload.size)||file.size);const hidden=document.createElement('input');hidden.type='hidden';hidden.name='staged_file_id';hidden.value=payload.staging_id;form.appendChild(hidden);const remove=document.createElement('button');remove.type='button';remove.setAttribute('aria-label','移除文件');remove.textContent='✕';remove.addEventListener('click',()=>{hidden.remove();chipEl.remove()});chipEl.append(remove)}catch(error){chipEl.remove();window.EmberUI?.toast(`${file.name}：${error.message||'无法暂存文件'}`,'error',4200)}}function stageFiles(files){[...files].forEach(file=>stageFile(file))}zone.addEventListener('dragover',event=>{event.preventDefault();zone.classList.add('dragover')});zone.addEventListener('dragleave',()=>zone.classList.remove('dragover'));zone.addEventListener('drop',event=>{event.preventDefault();zone.classList.remove('dragover');if(event.dataTransfer?.files?.length)stageFiles(event.dataTransfer.files)});supplement.addEventListener('paste',event=>{const files=event.clipboardData?.files;if(files?.length){event.preventDefault();stageFiles(files)}});function renderRows(items){activeIndex=-1;resultItems=items;results.replaceChildren(...items.map((item,index)=>{const meta=taskMeta[item.task_id]||{},row=document.createElement('button');row.type='button';row.className='home-result-row';row.dataset.index=String(index);row.innerHTML=`<span class="home-result-dot"></span><span class="home-result-main"><strong></strong><small></small></span><span class="home-result-side"></span>`;row.querySelector('strong').textContent=meta.title||item.task_id;row.querySelector('small').textContent=item.evidence||'';row.querySelector('.home-result-side').textContent=[meta.project,meta.status_label||meta.status,meta.updated].filter(Boolean).join(' · ');row.addEventListener('click',()=>selectTask(item.task_id));return row}))}function moveActive(delta){if(!resultItems.length)return;activeIndex=(activeIndex+delta+resultItems.length)%resultItems.length;results.querySelectorAll('.home-result-row').forEach((row,index)=>{const active=index===activeIndex;row.classList.toggle('active',active);if(active)row.scrollIntoView({block:'nearest'})})}async function search(){const query=input.value.trim();if(!query||syncHint()){results.hidden=true;return}hint.hidden=true;results.hidden=false;results.innerHTML='<div class="home-task-empty">正在搜索…</div>';const current=++request;try{const response=await fetch('/api/tasks/search?q='+encodeURIComponent(query),{headers:{Accept:'application/json'}});if(!response.ok)throw new Error();const data=await response.json();if(current!==request)return;const items=(data.items||[]).slice(0,8);if(!items.length){results.innerHTML='<div class="home-task-empty">没有匹配任务；可直接建立新任务。</div>';resultItems=[];return}renderRows(items)}catch(error){if(current===request)results.innerHTML='<div class="home-task-empty">搜索暂不可用；可前往任务检视继续查找。</div>'}}function selectTask(taskId){const meta=taskMeta[taskId]||{};selectedTask=taskId;selectedTitle=meta.title||taskId;selectedId.value=taskId;if(routeMode()==='new')setRouteMode('continue');chipLabel.textContent=`${routeMode()==='derive'?'基于':'继续'}：${selectedTitle}`;chipLink.href='/tasks/'+encodeURIComponent(taskId);chip.hidden=false;results.hidden=true}input.addEventListener('input',search);input.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();moveActive(1)}else if(event.key==='ArrowUp'){event.preventDefault();moveActive(-1)}else if(event.key==='Enter'&&!event.shiftKey){if(activeIndex>=0&&resultItems[activeIndex]){event.preventDefault();selectTask(resultItems[activeIndex].task_id)}}else if(event.key==='Escape'){results.hidden=true}});document.querySelectorAll('[name=route_mode]').forEach(radio=>radio.addEventListener('change',()=>{if(selectedTask)chipLabel.textContent=`${routeMode()==='derive'?'基于':'继续'}：${selectedTitle}`}));chipClear.addEventListener('click',clearContext);form.addEventListener('submit',event=>{const mode=routeMode();if(['continue','derive'].includes(mode)&&!selectedTask){event.preventDefault();window.EmberUI?.toast('请先搜索并选择要继续或作为来源的任务','error',3600);input.focus()}});input.focus();})();</script>'''


def home_task_metadata(records: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for record in records:
        task_id = str(record.get("task_id") or "")
        if not task_id:
            continue
        status = str(record.get("status") or "")
        values[task_id] = {
            "title": str(record.get("task_name") or record.get("title") or task_id),
            "project": task_scope_title(str(record.get("project") or ""), str(record.get("project_title") or "")),
            "status": status,
            "status_label": STATUS_LABEL.get(status, status),
            "updated": format_display_time(record.get("updated_at")) or "未记录",
        }
    return values


# A request that reads like task organization or archiving suggests the page for it instead.
HOME_INTENTS = (
    {"pattern": "整理|任务主线|合并|拆分", "label": "看起来像任务整理", "href": "/weekly", "target": "任务检视"},
    {"pattern": "归档|入库", "label": "看起来像资料归档", "href": "/archive", "target": "归档中心"},
)


def render_home(token: str, notice: str='', error: str='') -> str:
    from .pages.home import render_home as _present
    return _present(token, notice, error)


# Inlined so the task page renders its layout without a second stylesheet request.
TASK_DETAIL_STYLE = TASK_DETAIL_CSS
PROJECT_STYLE = STATIC_ASSETS["project.css"]
PROJECTS_STYLE = STATIC_ASSETS["projects.css"]
SYSTEM_STYLE = STATIC_ASSETS["system.css"]
SETTINGS_STYLE = STATIC_ASSETS["settings.css"]
EXECUTOR_SETTINGS_STYLE = STATIC_ASSETS["executor-settings.css"]


# The materials controller is shared (ui/ember_ui/static/task-detail.js); the workbench supplies
# its file actions: form posts, and in central mode NAS opening and locating inputs in place.
TASK_DETAIL_CONTROLLER_START = r'''<script src="/assets/task-detail.js?v=__TASK_DETAIL_VERSION__"></script><script data-task-detail-controller="single">(()=>{const workspace=document.getElementById('taskDeliveryWorkspace');if(!workspace||!window.EmberTaskDetail)return;const taskId=workspace.dataset.taskId,centralMode=workspace.dataset.centralMode==='1',csrf=workspace.dataset.csrf,returnTo=location.pathname,relatedDeliveries='''
TASK_DETAIL_CONTROLLER_END = r''';const esc=value=>String(value??'').replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));
function actionForm(data,mode,label,input=false){if(input&&centralMode&&mode==='reveal')return `<button class="button" type="button" data-input-locate-file="${esc(data.relative_path)}">定位所在资料</button>`;const actualMode=centralMode&&!input&&mode==='reveal'?'nas':mode,actualLabel=centralMode&&!input&&mode==='reveal'?'在 NAS 打开':label,bridgeAttr=actualMode==='nas'?' data-bridge-action="nas"':'';return `<form class="action-form" method="post" action="/actions/open-library-item"${bridgeAttr}><input type="hidden" name="csrf" value="${esc(csrf)}"><input type="hidden" name="return_to" value="${esc(returnTo)}"><input type="hidden" name="task_id" value="${esc(data.task_id||taskId)}"><input type="hidden" name="delivery" value="${esc(input?'input':data.delivery_key)}"><input type="hidden" name="path" value="${esc(data.relative_path)}"><input type="hidden" name="mode" value="${esc(actualMode)}"><button class="button" type="submit">${esc(actualLabel)}</button></form>`}
const controller=window.EmberTaskDetail.mount(workspace,{relatedDeliveries,actions:(data,input)=>actionForm(data,'reveal','Finder 中显示',input)+actionForm(data,'open','系统应用打开',input)+(input?'':actionForm(data,'download',data.large_file?'下载到本机（推荐）':'下载到本机')),afterPreview:()=>window.EmberExecutionTarget?.syncButtons()});
if(centralMode){document.querySelectorAll('[data-task-folder-action]').forEach(form=>form.addEventListener('submit',event=>{event.preventDefault();event.stopImmediatePropagation();const mode=form.dataset.taskFolderAction==='delivery'?'delivery':'input';controller.selectFileMode(mode);document.getElementById(mode==='delivery'?'taskDeliveryFiles':'taskInputPanel').scrollTo({top:0,behavior:'smooth'});window.EmberUI?.toast(mode==='delivery'?'已回到交付文件夹':'已回到输入资料目录','info',3000)}))}})();</script>'''


def _task_body(body: str, name: str) -> tuple[str, list[tuple[str, str]] | None]:
    """The task narrative as HTML, and its execution log entries (None when the card has no log)."""
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", body))
    if not matches:
        return _strip_first_heading_if_title(markdown_to_html(markdown_for_html(body)), name), None
    reading = [body[:matches[0].start()]]
    execution_log: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section = body[match.start():end]
        (execution_log if match.group(1).strip() == "执行日志" else reading).append(section)
    reading_html = _strip_first_heading_if_title(markdown_to_html(markdown_for_html("".join(reading))), name)
    if not execution_log:
        return reading_html, None
    return reading_html, task_detail.parse_log_section("\n".join(execution_log))


def _render_task_body(body: str, name: str) -> tuple[str, str]:
    from .pages.task import _render_task_body as _present
    return _present(body, name)


# Deterministic writers whose consecutive entries are folded into one log row.
TASK_LOG_MACHINE_PREFIXES = ("登记任务输入快照", "首页执行交接登记任务输入快照")


def external_results_markup(text: str) -> str:
    """Display only recorded bridge facts; references never become arbitrary file actions."""
    try:
        entries = system_bridge.receipts(text)
    except ValueError:
        return '<p class="meta">跨系统记录格式异常；请核对任务卡，未当作无结果。</p>'
    if not entries:
        return ""
    state_labels = {"completed": "已完成", "success": "已完成", "succeeded": "已完成", "failed": "失败", "running": "进行中", "pending": "等待中"}
    rows = []
    for entry in entries:
        state = str(entry["state"])
        recorded = format_display_time(entry.get("recorded_at")) or ""
        summary = (
            f'<b>{html.escape(entry["system"])}</b><span class="task-external-state {html.escape(state, quote=True)}">{html.escape(state_labels.get(state, state))}</span>'
            f'<code>{html.escape(entry["job_id"])}</code>' + (f'<time>{html.escape(recorded)}</time>' if recorded else "")
        )
        details = ""
        if entry["canonical_paths"]:
            details += '<h4>成果正本</h4><ul class="task-external-paths">' + "".join(f'<li><code>{html.escape(path)}</code></li>' for path in entry["canonical_paths"]) + '</ul>'
        if entry["validations"]:
            details += '<h4>验证</h4><ul>' + "".join(f'<li>{html.escape(check)}</li>' for check in entry["validations"]) + '</ul>'
        rows.append(f'<details class="task-external-result"><summary>{summary}</summary>{details}</details>')
    return '<section class="task-external-results" aria-label="跨系统结果"><h3>跨系统结果</h3>' + ''.join(rows) + '</section>'


def render_task(task_id: str, token: str, notice: str='', error: str='', *, back_path: str='/projects', back_label: str='项目视图') -> str | None:
    from .pages.task import render_task as _present
    return _present(task_id, token, notice, error, back_path=back_path, back_label=back_label)


def workspace_inbox_path(raw_path: str = "") -> Path | None:
    """Resolve an existing path inside the inbox or the mounted CHIPB drive."""
    inbox_root = workspace_inbox_root().expanduser().resolve()
    roots = [inbox_root]
    if drive_root := external_drive_root():
        roots.append(drive_root)
    candidate = Path(raw_path).expanduser().resolve() if raw_path else inbox_root
    return candidate if candidate.exists() and any(_within(candidate, root) for root in roots) else None


def external_drive_root() -> Path | None:
    """Return CHIPB only while macOS reports it as a mounted volume."""
    root = EXTERNAL_DRIVE_ROOT.expanduser()
    return root.resolve() if root.is_dir() and os.path.ismount(root) else None


def directory_entries(root: Path, limit: int | None = None, offset: int = 0) -> list[dict[str, object]]:
    """List one directory level in the compact archive-browser shape."""
    fallback_directory_names: set[str] = set()
    try:
        paths = sorted((path for path in root.iterdir() if not path.name.startswith(".")), key=lambda path: (not path.is_dir(), path.name.casefold()))
    except OSError as error:
        print(f"Ember workbench cannot read directory {root}: {error!r}", file=sys.stderr, flush=True)
        try:
            result = subprocess.run(["/bin/ls", "-1Ap", str(root)], check=True, capture_output=True, text=True, timeout=10)
            fallback_directory_names = {name[:-1] for name in result.stdout.splitlines() if name.endswith("/")}
            paths = [root / name.rstrip("/") for name in result.stdout.splitlines() if name and not name.startswith(".")]
        except (OSError, subprocess.SubprocessError) as fallback_error:
            print(f"Ember workbench fallback cannot read directory {root}: {fallback_error!r}", file=sys.stderr, flush=True)
            return finder_directory_entries(root, limit, offset)
    start = max(0, offset)
    paths = paths[start:start + limit] if limit is not None else paths[start:]
    entries: list[dict[str, object]] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            if fallback_directory_names:
                entries.append({"name": path.name, "path": str(path), "is_dir": path.name in fallback_directory_names, "updated_at": ""})
            continue
        entries.append({"name": path.name, "path": str(path.resolve()), "is_dir": path.is_dir(), "updated_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return entries


def finder_directory_entries(root: Path, limit: int | None = None, offset: int = 0) -> list[dict[str, object]]:
    """Use macOS Foundation to enumerate an allowlisted source when LaunchAgent access is denied."""
    drive_root = external_drive_root()
    inbox_root = workspace_inbox_root().expanduser().resolve()
    resolved_root = root.expanduser().resolve()
    if not ((drive_root and _within(resolved_root, drive_root)) or _within(resolved_root, inbox_root)):
        return []
    start = max(0, offset)
    end = start + max(0, limit) if limit is not None else None
    slice_expression = f".slice({start},{end})" if end is not None else (f".slice({start})" if start else "")
    root_json = json.dumps(str(resolved_root), ensure_ascii=False)
    script = (
        'ObjC.import("Foundation");'
        'const fm=$.NSFileManager.defaultManager;'
        f'const root={root_json};'
        'const raw=fm.contentsOfDirectoryAtPathError(root,null);'
        'if(!raw)throw new Error("directory read failed");'
        f'const names=ObjC.unwrap(raw).map(ObjC.unwrap).filter(x=>x&&!x.startsWith(".")){slice_expression};'
        'JSON.stringify(names.map(name=>{const flag=Ref();'
        'fm.fileExistsAtPathIsDirectory(root+"/"+name,flag);'
        'return {name,cls:Boolean(flag[0])?"folder":"file"}}))'
    )
    try:
        result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script], check=True, capture_output=True, text=True, timeout=20)
        items = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f"Ember workbench Foundation fallback cannot read directory {root}: {error!r}", file=sys.stderr, flush=True)
        return []
    return [{"name": str(item.get("name") or ""), "path": str(root / str(item.get("name") or "")), "is_dir": item.get("cls") == "folder", "updated_at": ""} for item in items if item.get("name") and not str(item.get("name")).startswith(".")]


def refresh_workspace_inbox_entries() -> list[dict[str, object]]:
    """Refresh the bounded inbox snapshot, including fixed-folder item counts."""
    root = workspace_inbox_root().expanduser().resolve()
    if not root.is_dir():
        return []
    preview_limit = 50
    fixed_order = {name: index for index, name in enumerate(WORKSPACE_INBOX_FOLDERS)}
    root_children = directory_entries(root)
    if not root_children:
        cached = load_workspace_inbox_cache(root)
        if cached:
            print(f"Ember workbench refresh kept the last valid inbox snapshot for {root}.", file=sys.stderr, flush=True)
            return cached
    root_children.sort(key=lambda item: (
        str(item.get("name") or "") not in fixed_order,
        fixed_order.get(str(item.get("name") or ""), 999),
        str(item.get("name") or "").casefold(),
    ))
    truncated = len(root_children) > preview_limit
    entries: list[dict[str, object]] = []
    for item in root_children[:preview_limit]:
        entry = dict(item)
        name = str(entry.get("name") or "")
        entry["fixed"] = name in WORKSPACE_INBOX_FOLDERS
        entry["children"] = []
        if not entry["fixed"] and entry.get("is_dir"):
            continue
        if entry["fixed"] and entry.get("is_dir"):
            entry["child_count"] = len(directory_entries(Path(str(entry.get("path") or root / name))))
        entries.append(entry)
    if truncated:
        entries.append({"name": f"仅显示前 {preview_limit} 项；请整理到固定状态文件夹或在 Finder 中查看全部", "path": "", "is_dir": False, "fixed": False, "updated_at": "", "notice": True, "children": []})
    save_workspace_inbox_cache(root, entries)
    return entries


def workspace_inbox_entries() -> list[dict[str, object]]:
    """List a bounded root preview without eagerly traversing SMB folders."""
    root = workspace_inbox_root().expanduser().resolve()
    if not root.is_dir():
        return load_workspace_inbox_cache(root)
    preview_limit = 50
    entries: list[dict[str, object]] = []
    fixed_order = {name: index for index, name in enumerate(WORKSPACE_INBOX_FOLDERS)}
    try:
        root_children = sorted(
            (item for item in os.scandir(root) if not item.name.startswith(".")),
            key=lambda item: (item.name not in fixed_order, fixed_order.get(item.name, 999), item.name.casefold()),
        )
    except OSError:
        return load_workspace_inbox_cache(root)
    truncated = len(root_children) > preview_limit
    cached_counts = {
        str(entry.get("name") or ""): entry.get("child_count")
        for entry in load_workspace_inbox_cache(root)
        if entry.get("fixed") and isinstance(entry.get("child_count"), int)
    }
    for item in root_children[:preview_limit]:
        first = Path(item.path)
        try:
            first_stat = item.stat()
        except OSError:
            continue
        entry = {"name": item.name, "path": str(first), "is_dir": item.is_dir(), "fixed": item.name in WORKSPACE_INBOX_FOLDERS, "updated_at": datetime.datetime.fromtimestamp(first_stat.st_mtime).strftime("%Y-%m-%d %H:%M"), "children": []}
        if not entry["fixed"] and entry["is_dir"]:
            continue
        if item.name in cached_counts:
            entry["child_count"] = cached_counts[item.name]
        entries.append(entry)
    if truncated:
        entries.append({"name": f"仅显示前 {preview_limit} 项；请整理到固定状态文件夹或在 Finder 中查看全部", "path": "", "is_dir": False, "fixed": False, "updated_at": "", "notice": True, "children": []})
    if entries:
        save_workspace_inbox_cache(root, entries)
    elif cached := load_workspace_inbox_cache(root):
        return cached
    else:
        return refresh_workspace_inbox_entries()
    return entries


def load_workspace_inbox_cache(root: Path) -> list[dict[str, object]]:
    """Return the last foreground snapshot when a LaunchAgent cannot read SMB."""
    try:
        payload = json.loads(WORKSPACE_INBOX_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if payload.get("root") != str(root):
        return []
    entries = payload.get("entries")
    return entries if isinstance(entries, list) else []


def save_workspace_inbox_cache(root: Path, entries: list[dict[str, object]]) -> None:
    """Persist a small read-only snapshot for the loopback workbench service."""
    try:
        WORKSPACE_INBOX_CACHE.parent.mkdir(parents=True, exist_ok=True)
        temporary = WORKSPACE_INBOX_CACHE.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "root": str(root),
            "entries": entries,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(WORKSPACE_INBOX_CACHE)
    except OSError:
        pass


def workspace_inbox_directory_payload(raw_path: str, offset: int = 0) -> dict[str, object] | None:
    """Return one allowlisted inbox directory level for lazy tree expansion."""
    directory = workspace_inbox_path(raw_path)
    if not directory or not directory.is_dir():
        return None
    root = workspace_inbox_root().expanduser().resolve()
    if directory == root:
        if offset:
            return {"path": str(directory), "children": [], "truncated": False, "preview_limit": 50, "offset": offset, "next_offset": None, "has_more": False}
        children = workspace_inbox_entries()
        truncated = bool(children and children[-1].get("notice"))
        return {"path": str(directory), "children": children, "truncated": truncated, "preview_limit": 50, "offset": 0, "next_offset": None, "has_more": False, "cached": not os.access(directory, os.R_OK)}
    preview_limit = 50
    safe_offset = max(0, offset)
    preview = directory_entries(directory, preview_limit + 1, safe_offset)
    truncated = len(preview) > preview_limit
    children = preview[:preview_limit]
    if truncated:
        children.append({
            "name": "继续下拉加载…",
            "path": "",
            "is_dir": False,
            "updated_at": "",
            "notice": True,
            "load_more": True,
            "directory": str(directory),
            "offset": safe_offset + preview_limit,
        })
    return {
        "path": str(directory),
        "children": children,
        "truncated": truncated,
        "preview_limit": preview_limit,
        "offset": safe_offset,
        "next_offset": safe_offset + preview_limit if truncated else None,
        "has_more": truncated,
    }


def _workspace_inbox_prompt_text(action: str, selected_line: str) -> str:
    root = workspace_inbox_root().expanduser().resolve()
    tasks = {
        "organize_workspace": "只读扫描工作台，生成逐项整理建议。",
        "archive_selected": "核对所选资料的归档类型、项目、目标和操作方式，确认后执行归档。",
        "organize_archive": "只读检查所选 NAS 正本资料，生成 NAS 与百度副本的协调整理建议。",
        "organize_baidu": "只读检查百度独有历史归档，生成迁移、保留或清理建议。",
        "check_indexes": "只读核验最近 7 天 NAS 正本与百度备份副本。",
    }
    workflows = {
        "organize_workspace": (
            "使用 `project-intake` 处理资料，不要使用只整理任务卡的 `ember-organization` 代替。"
            "建议阶段 `mutated_files=0`。"
        ),
        "archive_selected": (
            "必须使用 `project-intake`；选中文件夹表示递归选择全部子文件夹与文件，不得只处理当前可见层级。"
            "先用路径、名称和时间比对，冲突时再算 checksum；已发布内容使用 `ledger_only`，"
            "按实际发布分配月度序号并更新项目年度发布记录。"
        ),
        "organize_archive": (
            "NAS 项目归档区是正本，百度是单向备份副本；只处理当前选择，完成后核对两端同路径结果。"
        ),
        "organize_baidu": (
            "只处理 NAS 正本不存在的历史内容；使用 AList + rclone 只读列目录。"
        ),
        "check_indexes": (
            "核对飞牛任务“项目归档区备份100项目”，运行备份审计并记录异常；全程只读，不自动修复。"
        ),
    }
    if action not in tasks:
        raise ValueError("不支持的工作台操作。")
    read_only = action in {"organize_workspace", "organize_archive", "organize_baidu", "check_indexes"}
    context = [
        "- 当前页面：归档中心",
        "- 运行入口：当前 余烬 · Ember runtime 与 `project-intake`",
        "- 路径必须由 `workspace_paths.py` 解析，不猜另一台机器的路径",
    ]
    if action == "check_indexes":
        context.extend([
            "- 归档正本：`/vol1/@team/项目归档区`",
            "- 百度副本：`alist:baidu/100项目`",
            "- 核验命令：`python3 scripts/ember_archive_backup_audit.py audit`",
        ])
    return render_catalog_prompt(
        "workspace-action",
        task=tasks[action],
        context="\n".join(context),
        input="\n".join([
            f"- 当前选择：{selected_line}",
            f"- 当前机器工作台：`{root}`",
            f"- 历史归档记录：`{ARCHIVE_OPERATION_LOG}`",
        ]),
        authorization=(
            "当前阶段只读，必须保持实际文件变更为 0；移动、归档、重命名、合并、覆盖或删除均需 Evan 逐项确认。"
            if read_only else
            "可进行只读比对和 checksum 核验。项目、分类、完整目标路径与操作方式获得 Evan 确认后才可写入；覆盖、删除或扩大范围需另行确认。"
        ) + workflows[action],
        success="范围与真源没有越界；建议包含来源、目标、理由和冲突风险；如有执行，已通过门禁、目标验证与共享回执记录。",
    )


def workspace_inbox_task_prompt(action: str, source_paths: str | list[str] = "", archive_paths: str | list[str] = "") -> str:
    raw_paths = [source_paths] if isinstance(source_paths, str) else source_paths
    selected = [path for raw in raw_paths if raw and (path := workspace_inbox_path(raw))]
    raw_archive_paths = [archive_paths] if isinstance(archive_paths, str) else archive_paths
    selected_archive = [path for raw in raw_archive_paths if raw and (path := archive_remote_path(raw))]
    if action == "archive_selected" and not selected:
        raise ValueError("请先在左侧选择一个或多个文件、文件夹。")
    if action == "organize_archive" and not selected_archive:
        raise ValueError("请先在右侧选择一个或多个文件、文件夹。")
    if action == "archive_selected":
        selected_line = "\n" + "\n".join(f"  {index}. {path}" for index, path in enumerate(selected, 1))
    elif action == "organize_workspace":
        selected_line = "整个工作台（忽略左侧单项选择）"
    elif action == "organize_archive":
        selected_line = "\n" + "\n".join(f"  {index}. {path}" for index, path in enumerate(selected_archive, 1))
    elif action == "organize_baidu":
        selected_line = "alist:baidu/100项目 中 NAS 正本不存在的历史内容"
    elif action == "check_indexes":
        selected_line = "最近 7 天归档包及飞牛备份状态"
    else:
        selected_line = "整个工作台或归档区（忽略偶然的单项选择）"
    return _workspace_inbox_prompt_text(action, selected_line)


def _render_archive_legacy_v1(token: str, notice: str='', error: str='', *, view: str='', publish_records: list[dict[str, object]] | None=None) -> str:
    from .pages.archive import _render_archive_legacy_v1 as _present
    return _present(token, notice, error, view=view, publish_records=publish_records)


def archive_capable_projects() -> dict[str, dict[str, object]]:
    return {slug: item for slug, item in project_items().items() if "archive" in set(item.get("capabilities") or [])}


def archive_delivery_tasks() -> list[dict[str, object]]:
    allowed = archive_capable_projects()
    result: list[dict[str, object]] = []
    for record in library_task_records():
        project = str(record.get("project") or "")
        delivery = record.get("library_delivery") if isinstance(record.get("library_delivery"), dict) else {}
        key = str(delivery.get("key") or "")
        if project not in allowed or key not in LIBRARY_DELIVERY_KINDS:
            continue
        result.append({
            "task_id": str(record.get("task_id") or ""),
            "title": str(record.get("task_name") or record.get("title") or record.get("task_id") or ""),
            "project": project,
            "project_title": str(allowed[project].get("title") or project),
            "delivery_state": key,
            "delivery_label": LIBRARY_DELIVERY_KINDS[key],
            "updated_at": format_display_time(record.get("updated_at")),
        })
    return sorted(result, key=lambda item: (str(item["project_title"]), str(item["updated_at"])), reverse=True)


def archive_local_source_path(source_kind: str, relative_path: str = "") -> Path | None:
    roots = {"inbox": archive_inbox_root(), "workspace": workspace_inbox_root(), "downloads": downloads_root()}
    root = roots.get(source_kind)
    if not root:
        return None
    relative = Path(relative_path or ".")
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (root.expanduser().resolve() / relative).resolve()
    if not candidate.exists() or not _within(candidate, root.expanduser().resolve()):
        return None
    if source_kind in {"inbox", "workspace"}:
        try:
            first = candidate.relative_to(root.expanduser().resolve()).parts[0]
        except (ValueError, IndexError):
            first = ""
        if (source_kind == "workspace" and first in {"可删除", "历史文档"}):
            return None
    return candidate


def archive_source_directory_payload(
    source_kind: str,
    relative_path: str = "",
    state: str = "unclassified",
    *,
    ledger_payload: dict[str, object] | None = None,
    offset: int = 0,
    limit: int = 50,
    query: str = "",
    snapshot_id: str = "",
) -> dict[str, object] | None:
    if source_kind == "inbox":
        if not relative_path and ledger_payload is None:
            snapshot = archive_inbox.load_snapshot()
            return archive_inbox.snapshot_page(
                snapshot,
                state,
                offset=offset,
                limit=limit,
                query=query,
                expected_snapshot_id=snapshot_id,
            )
        try:
            rows = archive_inbox.entries(
                archive_inbox_root(),
                state,
                relative_path,
                limit=max(1, min(200, int(limit))),
                ledger_payload=ledger_payload,
            )
        except archive_inbox.ArchiveInboxError:
            return None
        return {
            "source_kind": "inbox",
            "machine": current_environment_name(),
            "machine_label": current_environment().get("label"),
            "state": state,
            "current_path": relative_path,
            "entries": rows,
            "truncated": len(rows) >= max(1, min(200, int(limit))),
        }
    path = archive_local_source_path(source_kind, relative_path)
    if not path or not path.is_dir():
        return None
    roots = {"inbox": archive_inbox_root(), "workspace": workspace_inbox_root(), "downloads": downloads_root()}
    root = roots[source_kind].expanduser().resolve()
    entries: list[dict[str, object]] = []
    try:
        children = sorted((child for child in path.iterdir() if not child.name.startswith(".")), key=lambda child: (not child.is_dir(), child.name.casefold()))
    except OSError:
        return None
    for child in children[:200]:
        if source_kind == "workspace" and path == root and child.name in {"可删除", "历史文档"}:
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append({"name": child.name, "relative_path": child.relative_to(root).as_posix(), "is_dir": child.is_dir(), "size": int(stat.st_size), "updated_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return {"source_kind": source_kind, "machine": current_environment_name(), "machine_label": current_environment().get("label"), "current_path": "" if path == root else path.relative_to(root).as_posix(), "entries": entries, "truncated": len(children) > 200}


def archive_resolve_queue_item(item: dict[str, object]) -> Path | None:
    locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
    source = str(item.get("source_kind") or "")
    if source == "delivery":
        return canonical_library_delivery_path(str(locator.get("task_id") or item.get("task_id") or ""), str(locator.get("delivery_state") or item.get("delivery_state") or ""), str(locator.get("relative_path") or ""))
    if source in {"inbox", "workspace", "downloads"}:
        resolved = archive_local_source_path(source, str(locator.get("relative_path") or ""))
        if resolved or source not in {"inbox", "workspace"}:
            return resolved
        # Workspace material may be moved out of a legacy management path
        # while it is waiting in the metadata-only queue. Repair only the
        # unambiguous root-level case with the same name and fingerprint.
        name = str(item.get("name") or "").strip()
        candidate = archive_local_source_path(source, name) if name else None
        if candidate and archive_queue.lightweight_fingerprint(candidate) == item.get("fingerprint"):
            root = archive_inbox_root() if source == "inbox" else workspace_inbox_root()
            item["locator"] = {**locator, "relative_path": candidate.relative_to(root.expanduser().resolve()).as_posix()}
            item["error"] = ""
            return candidate
    return None


def archive_queue_add(expected_revision: int, selections: list[str]) -> dict[str, object]:
    items: list[dict[str, object]] = []
    allowed_projects = archive_capable_projects()
    for raw in selections:
        try:
            selection = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("归档选择格式无效。") from exc
        if not isinstance(selection, dict):
            raise ValueError("归档选择格式无效。")
        source = str(selection.get("source_kind") or "")
        relative = str(selection.get("relative_path") or "")
        if source in {"inbox", "workspace", "downloads"}:
            path = archive_local_source_path(source, relative)
            if not path:
                raise ValueError("所选来源不存在或不允许访问。")
            if source == "inbox":
                try:
                    inbox_state = archive_inbox.effective_state(path, archive_inbox_root(), archive_inbox.load())
                except archive_inbox.ArchiveInboxError as exc:
                    raise ValueError(str(exc)) from exc
                if inbox_state != "pending_archive":
                    raise ValueError("NAS Inbox 只有标记为“待归档”的内容可以加入归档队列。")
            roots = {"inbox": archive_inbox_root(), "workspace": workspace_inbox_root(), "downloads": downloads_root()}
            root = roots[source]
            item = archive_queue.path_item(source, root, path)
            if source == "inbox":
                item.update(archive_routing_suggestion(path, relative))
                item["cleanup_mode"] = "mark_deletable"
            items.append(item)
        elif source == "delivery":
            task_id = str(selection.get("task_id") or "")
            state = str(selection.get("delivery_state") or "")
            record = record_map().get(task_id) or {}
            project = str(record.get("project") or "")
            if project not in allowed_projects:
                raise ValueError("该任务不属于具有 archive 能力的项目。")
            path = canonical_library_delivery_path(task_id, state, relative)
            if not path:
                raise ValueError("任务交付定位无效；禁止路径穿越或缓存伪路径。")
            items.append(archive_queue.delivery_item(path, task_id=task_id, project=project, delivery_state=state, relative_path=relative))
        else:
            raise ValueError("不支持的归档来源。")
    result = archive_queue.add_items(expected_revision, items)
    attempted_ids = {str(item.get("item_id") or "") for item in items}
    retained_ids = {str(item.get("item_id") or "") for item in result.get("items", []) or []}
    added_ids = attempted_ids & retained_ids
    covered_names = [str(item.get("name") or "") for item in items if str(item.get("item_id") or "") not in added_ids]
    return {
        **result,
        "operation": {
            "attempted": len(items),
            "added": len(added_ids),
            "covered": len(covered_names),
            "covered_names": covered_names,
        },
    }


def archive_routing_suggestion(path: Path, relative_path: str = "") -> dict[str, object]:
    """Suggest only uniquely evidenced archive routing; leave ambiguity blank."""
    evidence = f"{relative_path} {path.name}".casefold()
    project_matches: list[tuple[str, str]] = []
    for slug, project in archive_capable_projects().items():
        aliases = [str(value).strip() for value in project.get("aliases") or []]
        matched = next((alias for alias in aliases if len(alias) >= 3 and alias.casefold() in evidence), "")
        if matched:
            project_matches.append((slug, matched))
    project = project_matches[0][0] if len(project_matches) == 1 else ""
    reasons: list[str] = []
    if project:
        reasons.append(f"项目别名“{project_matches[0][1]}”唯一命中")
    elif len(project_matches) > 1:
        reasons.append("命中多个项目，等待确认")
    else:
        reasons.append("未找到唯一项目证据")

    type_rules = (
        ("publish", ("发布归档", "已发布", "小红书发布", "抖音发布", "视频号发布")),
        ("activity", ("活动素材", "工作坊素材", "活动照片", "活动视频")),
        ("data_asset", ("数据资产", "数据统计", "运营数据")),
        ("theme_product", ("主题产品",)),
        ("professional_knowledge", ("专业知识", "课程知识")),
        ("external_cooperation", ("外部合作", "合作方交付")),
        ("project_material", ("项目资料",)),
    )
    type_matches = [(kind, keyword) for kind, keywords in type_rules for keyword in keywords if keyword.casefold() in evidence]
    unique_types = {kind for kind, _ in type_matches}
    archive_type = next(iter(unique_types)) if len(unique_types) == 1 else ""
    if archive_type:
        reasons.append(f"归档类型关键词“{type_matches[0][1]}”唯一命中")
    elif len(unique_types) > 1:
        reasons.append("命中多个归档类型，等待确认")
    else:
        reasons.append("归档类型等待确认")
    return {
        "project": project,
        "archive_type": archive_type,
        "metadata": {"routing_suggestion": "；".join(reasons)},
    }


def archive_inbox_open_path(state: str = "unclassified") -> Path:
    root = archive_inbox_root().expanduser().resolve()
    return root


def archive_inbox_transition(selections: list[str], source_state: str, target_state: str) -> dict[str, object]:
    if source_state not in archive_inbox.STATES or target_state not in archive_inbox.STATES:
        raise ValueError("标签参数缺失，请刷新归档页后重试。")
    relative_paths: list[str] = []
    inbox_root = archive_inbox_root().expanduser().resolve()
    for raw in selections:
        try:
            selection = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("收件箱选择格式无效。") from exc
        if not isinstance(selection, dict) or selection.get("source_kind") != "inbox":
            raise ValueError("状态调整只适用于 NAS 下载收件箱。")
        relative = Path(str(selection.get("relative_path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("收件箱选择路径无效。")
        candidate = (inbox_root / relative).resolve()
        try:
            candidate.relative_to(inbox_root)
        except ValueError as exc:
            raise ValueError("所选内容不属于 NAS Inbox。") from exc
        relative_paths.append(relative.as_posix())

    def build_queue_item(relative_path: str) -> dict[str, object]:
        path = (inbox_root / relative_path).resolve()
        item = archive_queue.path_item("inbox", inbox_root, path, machine="shared")
        item.update(archive_routing_suggestion(path, relative_path))
        item["cleanup_mode"] = "mark_deletable"
        return item

    result = archive_queue.sync_inbox_transition(
        source_state,
        target_state,
        relative_paths,
        lambda: archive_inbox.transition(
            source_state,
            target_state,
            relative_paths,
            root=inbox_root,
        ),
        build_queue_item if target_state == "pending_archive" else None,
    )
    archive_inbox.invalidate_snapshot(reason=f"label:{source_state}->{target_state}")
    return result


def archive_inbox_delete(selections: list[str]) -> dict[str, object]:
    relative_paths: list[str] = []
    inbox_root = archive_inbox_root().expanduser().resolve()
    for raw in selections:
        try:
            selection = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("收件箱选择格式无效。") from exc
        if not isinstance(selection, dict) or selection.get("source_kind") != "inbox":
            raise ValueError("永久删除只适用于 NAS 下载收件箱。")
        relative = Path(str(selection.get("relative_path") or ""))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("收件箱选择路径无效。")
        candidate = (inbox_root / relative).resolve()
        try:
            candidate.relative_to(inbox_root)
        except ValueError as exc:
            raise ValueError("所选内容不属于 NAS Inbox。") from exc
        relative_paths.append(relative.as_posix())
    result = archive_inbox.delete_deletable(relative_paths, root=inbox_root)
    archive_inbox.invalidate_snapshot(reason="delete:deletable")
    return result


def archive_queue_update(expected_revision: int, item_ids: list[str], form: dict[str, str]) -> dict[str, object]:
    metadata_keys = ("archive_month", "subproject", "publish_month", "topic", "copy_text", "platform", "account", "published_at", "link", "activity_month", "activity_name", "target_subdir", "material_name")
    metadata = {key: form.get(key, "").strip() for key in metadata_keys if key in form}
    archive_month = str(metadata.get("archive_month") or "").strip()
    archive_type = str(form.get("archive_type") or "").strip()
    if archive_month and archive_type == "publish":
        metadata["publish_month"] = archive_month
    elif archive_month and archive_type == "activity":
        metadata["activity_month"] = archive_month
    if not metadata.get("publish_month") and re.match(r"^\d{4}-\d{2}", str(metadata.get("published_at") or "")):
        metadata["publish_month"] = str(metadata["published_at"])[:7]
    changes: dict[str, object] = {"metadata": metadata}
    if form.get("project") and form["project"] not in archive_capable_projects():
        raise ValueError("只能选择具有 archive 能力的项目。")
    for key in ("project", "archive_type", "cleanup_mode"):
        if key in form:
            changes[key] = form[key]
    return archive_queue.update_items(expected_revision, item_ids, changes)


def archive_queue_recheck_sources(expected_revision: int, item_ids: list[str]) -> dict[str, object]:
    if not item_ids:
        raise ValueError("请先选择需要重新定位的来源。")
    return archive_queue.recheck_sources(
        expected_revision,
        item_ids,
        archive_resolve_queue_item,
    )


def archive_queue_remove(expected_revision: int, item_ids: list[str]) -> dict[str, object]:
    selected = set(item_ids)
    payload = archive_queue.load()
    current_revision = int(payload.get("revision") or 0)
    if current_revision != expected_revision:
        raise archive_queue.RevisionConflict(
            f"归档队列已由另一台机器更新（当前 revision {current_revision}），请刷新后重试。"
        )
    inbox_items = [
        item for item in payload.get("items", [])
        if item.get("item_id") in selected and item.get("source_kind") == "inbox"
    ]
    if inbox_items:
        selections = [
            json.dumps({
                "source_kind": "inbox",
                "relative_path": str((item.get("locator") or {}).get("relative_path") or ""),
            }, ensure_ascii=False)
            for item in inbox_items
        ]
        archive_inbox_transition(selections, "pending_archive", "unclassified")
    current = archive_queue.load()
    remaining_ids = {
        str(item.get("item_id") or "")
        for item in current.get("items", [])
        if item.get("item_id") in selected
    }
    if remaining_ids:
        return archive_queue.remove_items(
            int(current.get("revision") or 0),
            sorted(remaining_ids),
        )
    return current


def archive_queue_confirm(expected_revision: int, item_ids: list[str], form: dict[str, str]) -> dict[str, object]:
    if not item_ids:
        raise ValueError("请先选择至少一个待归档项目。")
    updated = archive_queue_update(expected_revision, item_ids, form)
    return archive_queue.confirm_batch(
        int(updated.get("revision") or 0),
        item_ids,
        archive_resolve_queue_item,
        target_builder=archive_package_target,
    )


def archive_batch_return_to_queue(expected_revision: int, batch_id: str) -> dict[str, object]:
    return archive_queue.return_batch_to_queue(expected_revision, batch_id)


def archive_batch_reconfirm_recovery(batch_id: str) -> dict[str, object]:
    payload = archive_queue.load()
    return archive_queue.reconfirm_recovery_batch(
        int(payload.get("revision") or 0),
        batch_id,
        archive_resolve_queue_item,
    )


def archive_package_target(item: dict[str, object]) -> str:
    base = project_archive_path(str(item.get("project") or ""))
    if not base:
        return ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if str(item.get("project") or "") == "small-project-pool":
        base = f"{base}/{str(metadata.get('subproject') or '').strip()}"
    kind = str(item.get("archive_type") or "")
    if kind == "publish":
        publish_month = str(metadata.get("archive_month") or metadata.get("publish_month") or metadata.get("published_at") or "")[:7].replace("-", "")
        topic = str(metadata.get("topic") or "").strip()
        source_name = str(item.get("name") or "").strip()
        if source_name and not item.get("is_dir"):
            source_name = Path(source_name).stem or source_name
        label = topic or source_name or "发布内容"
        label = label.replace("/", "-").replace("\\", "-").strip(" .") or "发布内容"
        suffix = f"{publish_month}_<执行时分配NN>_{label}"
        return f"{base}/发布归档/{suffix}/"
    if kind == "activity":
        month = str(metadata.get("archive_month") or metadata.get("activity_month") or "").replace("-", "")
        name = str(metadata.get("activity_name") or Path(str(item.get("name") or "活动素材")).stem or "活动素材").strip()
        return f"{base}/活动素材/{month}-{name}/"
    labels = {"project_material": "项目资料", "data_asset": "数据资产", "theme_product": "主题产品", "professional_knowledge": "专业知识", "external_cooperation": "外部合作"}
    label = labels.get(kind, "")
    name = str(metadata.get("target_subdir") or metadata.get("material_name") or Path(str(item.get("name") or "归档内容")).stem or "归档内容").strip()
    return f"{base}/{label}/{name}/" if label and name else ""


def archive_batch_prompt(batch_id: str) -> str:
    payload = archive_queue.load()
    batch = next((item for item in payload.get("batches", []) if item.get("batch_id") == batch_id), None)
    if not batch:
        raise ValueError("确认批次不存在，请重新确认。")
    batch_status = str(batch.get("status") or "confirmed")
    recovery_states = {"conflict", "failed_retryable", "receipt_pending"}
    stale_confirmation = int(payload.get("revision") or 0) != int(batch.get("confirmed_revision") or -1)
    if stale_confirmation:
        if batch_status == "confirmed":
            raise ValueError("队列 revision 已变化；请先将原批次返回队列重新确认，不得直接启动执行器。")
        raise ValueError("队列 revision 已变化；请先重新确认当前异常批次，不得直接启动执行器。")
    if batch_status not in recovery_states and not stale_confirmation:
        for package in batch.get("packages", []):
            for item in package.get("items", []):
                missing = archive_queue.required_details(item)
                if missing:
                    raise ValueError(f"{item.get('name')} 仍缺少：{'、'.join(missing)}，请返回队列重新确认。")
                path = archive_resolve_queue_item(item)
                if not path or archive_queue.lightweight_fingerprint(path) != item.get("fingerprint"):
                    raise ValueError(f"{item.get('name')} 的来源已变化，请重新确认。")
    manifest = archive_queue.execution_prompt(batch)
    if batch_status in recovery_states:
        labels = {"conflict": "冲突处理", "failed_retryable": "失败重试", "receipt_pending": "回执补写"}
        return render_catalog_prompt(
            "archive-batch-recovery",
            batch_id=batch_id,
            recovery_label=labels[batch_status],
            manifest=manifest,
        )
    return render_catalog_prompt(
        "archive-batch",
        batch_id=batch_id,
        manifest=manifest,
    )


def archive_maintenance_prompt(scope: str) -> str:
    settings = {
        "inbox": ("NAS 下载收件箱", archive_inbox_root()),
        "workspace": ("共享工作台", workspace_inbox_root()),
        "downloads": (f"当前机器下载（{current_environment().get('label') or current_environment_name()}）", downloads_root()),
    }
    if scope not in settings:
        raise ValueError("不支持的整理维护范围。")
    label, root = settings[scope]
    return render_catalog_prompt(
        "archive-maintenance",
        scope_label=label,
        scope_path=root,
    )


def _archive_source_rows(source_kind: str, state: str = "unclassified", payload: dict[str, object] | None = None) -> str:
    payload = payload or archive_source_directory_payload(source_kind, state=state) or {"entries": []}
    rows: list[str] = []
    for item in payload.get("entries", []):
        token = json.dumps({"source_kind": source_kind, "relative_path": item.get("relative_path")}, ensure_ascii=False, separators=(",", ":"))
        item_id = "archive-source-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        name = str(item.get("name") or "未命名")
        duplicate = '<em class="archive-duplicate-badge">重复同步</em>' if item.get("duplicate") else ""
        meta = "文件夹 · 递归保留结构" if item.get("is_dir") else format_bytes(int(item.get("size") or 0))
        if item.get("duplicate"):
            meta += f" · 已在{item.get('duplicate_state') or '其他状态'}记录"
        child_id = item_id + "-children"
        rows.append(
            f'<div class="archive-source-node" data-item-kind="{"folder" if item.get("is_dir") else "file"}">'
            f'<button class="archive-expand{" invisible" if not item.get("is_dir") else ""}" type="button" '
            f'data-source-kind="{html.escape(source_kind, quote=True)}" data-source-state="{html.escape(state, quote=True)}" '
            f'data-relative-path="{html.escape(str(item.get("state_relative_path") or item.get("relative_path") or ""), quote=True)}" '
            f'aria-label="展开：{html.escape(name, quote=True)}" aria-expanded="false" aria-controls="{child_id}">›</button>'
            f'<input id="{item_id}" type="checkbox" name="selection" value="{html.escape(token, quote=True)}">'
            f'<label for="{item_id}"><strong id="{item_id}-name">{html.escape(name)}{duplicate}</strong><small id="{item_id}-meta">{html.escape(meta)}</small></label>'
            f'<div id="{child_id}" class="archive-source-children" role="group" aria-labelledby="{item_id}-name" hidden></div></div>'
        )
    return "".join(rows)


def _archive_delivery_rows(items: list[dict[str, object]]) -> str:
    rows: list[str] = []
    for item in items:
        token = json.dumps(
            {
                "source_kind": "delivery",
                "task_id": item.get("task_id"),
                "delivery_state": item.get("delivery_state"),
                "relative_path": "",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        item_id = "archive-delivery-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        child_id = item_id + "-children"
        title = str(item.get("title") or item.get("task_id") or "未命名任务")
        meta = " · ".join(
            value for value in (
                str(item.get("project_title") or item.get("project") or ""),
                str(item.get("delivery_label") or ""),
                str(item.get("task_id") or ""),
                str(item.get("updated_at") or ""),
            ) if value
        )
        rows.append(
            f'<article class="archive-delivery-task archive-source-node">'
            f'<button class="archive-expand" type="button" data-source-kind="delivery" '
            f'data-delivery-task="{html.escape(str(item.get("task_id") or ""), quote=True)}" '
            f'data-delivery-state="{html.escape(str(item.get("delivery_state") or ""), quote=True)}" data-relative-path="" '
            f'aria-label="展开：{html.escape(title, quote=True)}" aria-expanded="false" aria-controls="{child_id}">›</button>'
            f'<input id="{item_id}" type="checkbox" name="selection" value="{html.escape(token, quote=True)}">'
            f'<label for="{item_id}"><strong id="{item_id}-name">{html.escape(title)}</strong><small id="{item_id}-meta">{html.escape(meta)}</small></label>'
            f'<div id="{child_id}" class="archive-source-children archive-delivery-children" role="group" aria-labelledby="{item_id}-name" hidden></div></article>'
        )
    return "".join(rows)


def _archive_queue_non_actionable_package_ids(payload: dict[str, object]) -> set[str]:
    """Package ids that belong outside the actionable archive queue.

    Confirmed, running, and completed packages are represented by the
    confirmation/execution section and archive history. Only packages that
    need human intervention (conflict, retry, receipt repair, source change)
    may return to the queue.
    """
    hidden: set[str] = set()
    for batch in payload.get("batches", []) or []:
        if str(batch.get("status") or "confirmed") == "returned_to_queue":
            continue
        for package in batch.get("packages", []) or []:
            if str(package.get("status") or "confirmed") in {"confirmed", "archiving", "archived"}:
                hidden.add(str(package.get("package_id") or ""))
    hidden.discard("")
    return hidden


def _archive_queue_table(
    payload: dict[str, object],
    token: str,
    *,
    group: str = "all",
    return_to: str = "/archive?scene=inbox&queue=pending",
) -> str:
    rows: list[str] = []
    source_labels = {"inbox": "NAS 下载收件箱", "workspace": "旧共享工作台", "downloads": "旧本机下载", "delivery": "任务交付"}
    state_labels = {"pending_classification": "待分类", "needs_details": "待补信息", "ready": "待确认", "archiving": "归档中", "archived": "已归档", "source_changed": "来源已变化", "conflict": "冲突待处理", "failed_retryable": "失败待重试", "receipt_pending": "回执待补"}
    current = current_environment_name()
    hidden_packages = _archive_queue_non_actionable_package_ids(payload)
    exception_states = {"source_changed", "conflict", "failed_retryable", "receipt_pending"}
    visible_items = [
        item for item in payload.get("items", [])
        if str(item.get("package_id") or "") not in hidden_packages
        and str(item.get("state") or "") not in {"archiving", "archived"}
        and (
            (group == "exception" and not item.get("package_id") and str(item.get("state") or "") in exception_states)
            or (group == "pending" and str(item.get("state") or "") not in exception_states)
            or group == "all"
        )
    ]
    if not visible_items:
        empty_text = "暂无需要处理的异常项目。" if group == "exception" else "当前阶段没有待补信息项目。"
        return f'<div class="archive-queue-empty"><strong>{empty_text}</strong><small>从左侧选择来源，相关操作会在需要时出现。</small></div>'
    for row_index, item in enumerate(visible_items):
        unavailable = item.get("source_kind") == "downloads" and item.get("source_machine") != current
        missing = archive_queue.required_details(item)
        recovered = False
        if item.get("state") == "source_changed" and item.get("source_kind") in {"inbox", "workspace"}:
            candidate = archive_resolve_queue_item(item)
            recovered = bool(candidate and archive_queue.lightweight_fingerprint(candidate) == item.get("fingerprint"))
        display_state = "ready" if recovered else str(item.get("state") or "")
        display_label = "已重新定位" if recovered else state_labels.get(display_state, display_state)
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        routing_reason = str(metadata.get("routing_suggestion") or "")
        project_label = task_scope_title(str(item.get("project") or "")) if item.get("project") else "待设置"
        type_label = {"publish": "发布归档", "activity": "活动素材", "project_material": "项目资料", "data_asset": "数据资产", "theme_product": "主题产品", "professional_knowledge": "专业知识", "external_cooperation": "外部合作"}.get(str(item.get("archive_type") or ""), "待设置")
        missing_text = "、".join(missing)
        checkbox_id = f"archive-queue-{group}-{row_index}-{str(item.get('item_id') or '')[:8]}"
        rows.append(
            f'<label class="archive-basket-item" data-archive-queue-row>'
            f'<input id="{html.escape(checkbox_id, quote=True)}" type="checkbox" name="item_id" value="{html.escape(str(item.get("item_id") or ""), quote=True)}" aria-label="选择 {html.escape(str(item.get("name") or ""), quote=True)}">'
            f'<span class="archive-basket-copy"><strong data-archive-source-name>{html.escape(str(item.get("name") or ""))}</strong>'
            f'<small>{source_labels.get(str(item.get("source_kind")), str(item.get("source_kind")))} · {html.escape(str(item.get("source_machine") or ""))}{" · 仅来源机器可执行" if unavailable else ""}</small>'
            f'<small>{html.escape(routing_reason or str(item.get("task_id") or ""))}</small></span>'
            f'<span class="archive-basket-meta"><span>{html.escape(project_label)}</span><span>{html.escape(type_label)}</span>'
            f'<span class="badge {html.escape(display_state, quote=True)}">{html.escape(display_label)}</span>'
            f'{f"<small>{html.escape(missing_text)}</small>" if missing_text else ""}</span></label>'
        )
    revision = int(payload.get("revision") or 0)
    projects = archive_capable_projects()
    def common_value(key: str) -> str:
        values = {
            str(item.get(key) or "").strip()
            for item in visible_items
        }
        return values.pop() if len(values) == 1 else ""

    selected_project = common_value("project")
    selected_type = common_value("archive_type")
    archive_month_values = {
        str((item.get("metadata") or {}).get("archive_month") or (item.get("metadata") or {}).get("publish_month") or (item.get("metadata") or {}).get("activity_month") or "").strip()
        for item in visible_items
    }
    selected_month = archive_month_values.pop() if len(archive_month_values) == 1 else ""
    project_options = '<option value="">选择项目</option>' + ''.join(
        f'<option value="{html.escape(slug, quote=True)}"{" selected" if slug == selected_project else ""}>{html.escape(str(item.get("title") or slug))}</option>'
        for slug, item in projects.items()
    )
    type_options = '<option value="">选择归档类型</option>' + ''.join(
        f'<option value="{value}"{" selected" if value == selected_type else ""}>{label}</option>'
        for value, label in (("publish","发布归档"),("activity","活动素材"),("project_material","项目资料"),("data_asset","数据资产"),("theme_product","主题产品"),("professional_knowledge","专业知识"),("external_cooperation","外部合作"))
    )
    hidden = f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="revision" value="{revision}"><input type="hidden" name="return_to" value="{html.escape(return_to, quote=True)}">'
    empty_text = "暂无需要处理的异常项目。" if group == "exception" else "归档篮暂无待补信息项目；从左侧选择内容加入待归档。"
    suffix = "Exception" if group == "exception" else "Pending"
    return f'''<form method="post" data-archive-queue-form data-archive-form-group="{html.escape(group, quote=True)}">{hidden}<div class="archive-queue-fields"><label><span>所属项目</span><select name="project" data-archive-project>{project_options}</select></label><label><span>月份</span><input type="month" name="archive_month" value="{html.escape(selected_month, quote=True)}" required></label><label><span>归档类型</span><select name="archive_type" data-archive-type>{type_options}</select></label></div><div class="archive-basket-list">{"".join(rows) or f'<div class="inbox-empty">{empty_text}</div>'}</div><div class="archive-queue-actions"><label class="archive-select-all"><input type="checkbox" data-archive-select-all aria-label="全选{suffix}"><span data-archive-selection>未选择归档项目</span></label><div><button class="button ghost" formaction="/actions/archive-queue-remove" type="submit" disabled>移出队列</button><button class="button" formaction="/actions/archive-queue-update" type="submit" disabled>保存</button><button class="button primary" formaction="/actions/archive-queue-confirm" type="submit" disabled>检查归档包</button></div></div></form>'''


def _archive_source_exception_cards(payload: dict[str, object], token: str) -> str:
    source_labels = {
        "inbox": "NAS 下载收件箱",
        "workspace": "旧共享工作台",
        "downloads": "旧本机下载",
        "delivery": "任务交付",
    }
    error_labels = {
        "source missing": "原位置已找不到该来源",
        "fingerprint changed": "同名来源的内容或时间戳已经变化",
    }
    type_labels = {
        "publish": "发布归档",
        "activity": "活动素材",
        "project_material": "项目资料",
        "data_asset": "数据资产",
        "theme_product": "主题产品",
        "professional_knowledge": "专业知识",
        "external_cooperation": "外部合作",
    }
    revision = int(payload.get("revision") or 0)
    cards: list[str] = []
    for item in payload.get("items", []) or []:
        if item.get("package_id") or str(item.get("state") or "") != "source_changed":
            continue
        item_id = str(item.get("item_id") or "")
        locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
        relative_path = str(locator.get("relative_path") or item.get("name") or "")
        project = task_scope_title(str(item.get("project") or "")) if item.get("project") else "项目待设置"
        archive_type = type_labels.get(str(item.get("archive_type") or ""), "归档类型待设置")
        error = error_labels.get(str(item.get("error") or ""), "来源需要重新核对")
        common = f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="revision" value="{revision}"><input type="hidden" name="return_to" value="/archive?view=exception#archiveBasket"><input type="hidden" name="item_id" value="{html.escape(item_id, quote=True)}">'
        cards.append(
            f'''<article class="archive-source-exception"><div class="archive-source-exception-copy"><span class="archive-batch-state source_changed">来源已变化</span><strong>{html.escape(str(item.get("name") or "未命名"))}</strong><small>{html.escape(error)}</small><p>{html.escape(source_labels.get(str(item.get("source_kind") or ""), str(item.get("source_kind") or "")))} · {html.escape(relative_path)}</p><div><span>{html.escape(project)}</span><span>{html.escape(archive_type)}</span></div></div><div class="archive-source-exception-actions"><form method="post" action="/actions/archive-queue-recheck-source" data-archive-action-form>{common}<button class="button primary" type="submit" data-busy-label="正在核对…">重新定位来源</button></form><form method="post" action="/actions/archive-queue-remove" data-archive-action-form>{common}<button class="button ghost" type="submit" data-busy-label="正在移出…">移出队列</button></form></div></article>'''
        )
    return '<div class="archive-source-exception-list">' + "".join(cards) + "</div>" if cards else ""


def _archive_index_directory_paths(payload: dict[str, object]) -> set[str]:
    paths: set[str] = set()
    stack = [project for project in payload.get("projects", []) if isinstance(project, dict)]
    while stack:
        item = stack.pop()
        if item.get("type") == "directory" or "children" in item:
            remote_path = str(item.get("remote_path") or "").rstrip("/")
            if remote_path:
                paths.add(remote_path)
        stack.extend(child for child in item.get("children", []) or [] if isinstance(child, dict))
    return paths


def _archive_target_display_path(uri: str) -> str:
    if uri.startswith("bypy:/"):
        return "alist:baidu/" + uri.removeprefix("bypy:/").lstrip("/")
    return uri.rstrip("/")


def _archive_remote_matches(package: dict[str, object], remote_paths: set[str]) -> list[str]:
    target = str(package.get("final_target_uri") or package.get("target_uri") or "").rstrip("/")
    display = _archive_target_display_path(target)
    if not display:
        return []
    pattern = re.escape(display)
    pattern = pattern.replace(re.escape("<执行时分配NN>"), r"\d{2}")
    pattern = pattern.replace(re.escape("<执行时分配YYYYMM_NN>"), r"\d{6}_\d{2}")
    matcher = re.compile("^" + pattern + "$")
    return sorted((path for path in remote_paths if matcher.match(path)), reverse=True)


def _archive_batch_item_ids(batch: dict[str, object]) -> list[str]:
    return [
        str(item.get("item_id") or "")
        for package in batch.get("packages", []) or []
        for item in package.get("items", []) or []
        if item.get("item_id")
    ]


def _archive_batch_is_superseded(payload: dict[str, object], batch: dict[str, object]) -> bool:
    """Hide stale batch snapshots whose authoritative queue items are complete."""
    item_ids = _archive_batch_item_ids(batch)
    if not item_ids:
        return False
    current = {
        str(item.get("item_id") or ""): str(item.get("state") or "")
        for item in payload.get("items", []) or []
        if item.get("item_id")
    }
    states = [current.get(item_id, "") for item_id in item_ids]
    return bool(states) and all(state == "archived" for state in states)


def _archive_batch_group(payload: dict[str, object], batch: dict[str, object]) -> str:
    status = str(batch.get("status") or "confirmed")
    if status in {"returned_to_queue", "archived"} or _archive_batch_is_superseded(payload, batch):
        return "hidden"
    if status in {"conflict", "failed_retryable", "receipt_pending"}:
        return "exception"
    if status == "archiving":
        return "ready"
    if status != "confirmed":
        return "hidden"
    stale = int(batch.get("confirmed_revision") or -1) != int(payload.get("revision") or 0)
    missing = any(
        archive_queue.required_details(item)
        for package in batch.get("packages", []) or []
        for item in package.get("items", []) or []
    )
    return "exception" if stale or missing else "ready"


def _archive_batches_in_group(payload: dict[str, object], group: str) -> list[dict[str, object]]:
    return [
        batch
        for batch in payload.get("batches", []) or []
        if _archive_batch_group(payload, batch) == group
    ]


def _archive_batch_item_count(batches: list[dict[str, object]]) -> int:
    item_ids: set[str] = set()
    anonymous = 0
    for batch in batches:
        for package in batch.get("packages", []) or []:
            for item in package.get("items", []) or []:
                item_id = str(item.get("item_id") or "")
                if item_id:
                    item_ids.add(item_id)
                else:
                    anonymous += 1
    return len(item_ids) + anonymous


def _archive_batch_card(payload: dict[str, object], token: str, archive_payload: dict[str, object] | None = None) -> str:
    batches = list(payload.get("batches", []))
    if not batches:
        return '<div class="inbox-empty">尚无锁定批次。</div>'
    revision = int(payload.get("revision") or 0)
    batch = batches[-1]
    if str(batch.get("status") or "confirmed") == "returned_to_queue" or _archive_batch_is_superseded(payload, batch):
        return ""
    packages = list(batch.get("packages", []))
    batch_status = str(batch.get("status") or "confirmed")
    recovery_states = {"conflict", "failed_retryable", "receipt_pending"}
    batch_id = str(batch.get("batch_id") or "")
    drawer_actions = ""
    drawer_title = "检查并归档"
    drawer_hint = "确认来源、完整目标和来源处理方式后，再完成第二次确认。"
    remote_paths = _archive_index_directory_paths(archive_payload or archive_index.load_index())
    missing = sorted({detail for package in packages for item in package.get("items", []) for detail in archive_queue.required_details(item)})
    stale_confirmation = batch_status == "confirmed" and int(batch.get("confirmed_revision") or -1) != revision
    executable = batch_status == "confirmed" and int(batch.get("confirmed_revision") or -1) == revision and not missing

    def executor_form(action_label: str, return_view: str, *, recovery: bool = False) -> str:
        recovery_class = " archive-recovery-action" if recovery else ""
        environment = execution_environment()
        executor = html.escape(str(environment["executor"]), quote=True)
        label = html.escape(str(environment["executor_label"] if environment["executor_ready"] else "未配置执行软件"))
        disabled = "" if environment["executor_ready"] else " disabled"
        return f'''<form class="archive-executor-form" method="post" action="/actions/archive-batch-execute" data-archive-action-form><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="/archive?view={html.escape(return_view, quote=True)}#archiveBasket"><input type="hidden" name="batch_id" value="{html.escape(batch_id, quote=True)}"><input type="hidden" name="executor" value="{executor}"><div class="execution-confirm-runner archive-runner"><span class="execution-confirm-runner-name">{label}</span>{"" if environment["executor_ready"] else '<a class="button ghost execution-confirm-configure" href="/settings#execution">去配置</a>'}</div><button class="button primary archive-confirm-action{recovery_class}" type="submit" data-busy-label="正在启动…"{disabled}>{html.escape(action_label)}</button></form>'''

    if batch_status == "archived":
        actions = '<span class="archive-batch-state complete">已完成</span>'
        notice = '<div class="archive-batch-ready">远端校验和归档回执均已完成。</div>'
    elif stale_confirmation:
        actions = f'''<div class="archive-batch-head-actions"><span class="archive-batch-state stale">待重新确认</span><form method="post" action="/actions/archive-batch-return" data-archive-action-form><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="revision" value="{revision}"><input type="hidden" name="return_to" value="/archive?view=pending#archiveBasket"><input type="hidden" name="batch_id" value="{html.escape(batch_id, quote=True)}"><button class="button primary" type="submit" data-busy-label="正在恢复…">返回重新确认</button></form></div>'''
        notice = '<div class="notice">队列版本已更新；原确认失效。填写内容仍保留，返回后重新检查归档包。</div>'
    elif batch_status in recovery_states:
        recovery_ui = {
            "conflict": ("冲突待处理", "处理冲突", "处理目标冲突", "提交时重新核对队列版本与来源指纹，再比较原批次中的冲突。", "重新核对并处理"),
            "failed_retryable": ("失败待重试", "重试失败步骤", "重试失败步骤", "提交时重新核对队列版本与来源指纹；保留已完成阶段，只重试允许恢复的步骤。", "重新核对并重试"),
            "receipt_pending": ("回执待补", "补写回执", "补写归档回执", "提交时重新核对队列版本与来源指纹；只补齐缺失回执，不重复复制。", "重新核对并补写"),
        }
        recovery_label, action_label, drawer_title, drawer_hint, submit_label = recovery_ui[batch_status]
        actions = f'<div class="archive-batch-head-actions"><span class="archive-batch-state {html.escape(batch_status, quote=True)}">{html.escape(recovery_label)}</span><button class="button primary archive-recovery-action" type="button" data-archive-drawer-open="{html.escape(batch_id, quote=True)}">{html.escape(action_label)}</button></div>'
        drawer_actions = f'<div class="archive-drawer-actions">{executor_form(submit_label, "exception", recovery=True)}</div>'
        notice = f'<div class="notice">{html.escape(drawer_hint)}</div>'
    elif batch_status == "archiving":
        actions = '<span class="archive-batch-state archiving">归档中</span>'
        notice = '<div class="notice">归档任务正在执行，请等待结果写回。</div>'
    elif executable:
        actions = f'<div class="archive-batch-head-actions"><span class="archive-batch-state ready">待执行</span><button class="button primary" type="button" data-archive-drawer-open="{html.escape(batch_id, quote=True)}">检查并归档</button></div>'
        return_form = f'''<form method="post" action="/actions/archive-batch-return" data-archive-action-form><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="revision" value="{revision}"><input type="hidden" name="return_to" value="/archive?view=pending#archiveBasket"><input type="hidden" name="batch_id" value="{html.escape(batch_id, quote=True)}"><button class="button ghost" type="submit" data-busy-label="正在返回…">返回修改</button></form>'''
        drawer_actions = f'<div class="archive-drawer-actions">{return_form}{executor_form("确认并开始归档", "ready")}</div>'
        notice = '<div class="archive-batch-ready">确认仍然有效；检查来源和目标后完成第二次确认。</div>'
    else:
        actions = f'<div class="archive-batch-head-actions"><span class="archive-batch-state stale">信息待重核</span><form method="post" action="/actions/archive-batch-return" data-archive-action-form><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="revision" value="{revision}"><input type="hidden" name="return_to" value="/archive?view=pending#archiveBasket"><input type="hidden" name="batch_id" value="{html.escape(str(batch.get("batch_id") or ""), quote=True)}"><button class="button" type="submit" data-busy-label="正在恢复…">返回补充信息</button></form></div>'
        reason = f'还需补充：{"、".join(missing)}。' if missing else '队列内容已变化，需要重新确认。'
        notice = f'<div class="notice">{html.escape(reason)}</div>'
    type_labels = {"publish": "发布归档", "activity": "活动素材", "project_material": "项目资料", "data_asset": "数据资产", "theme_product": "主题产品", "professional_knowledge": "专业知识", "external_cooperation": "外部合作"}
    summaries: list[str] = []
    technical: list[str] = []
    for package in packages:
        items = list(package.get("items", []))
        first = items[0] if items else {}
        package_missing = {detail for item in items for detail in archive_queue.required_details(item)}
        metadata = first.get("metadata") if isinstance(first.get("metadata"), dict) else {}
        project = task_scope_title(str(package.get("project") or ""))
        archive_type = type_labels.get(str(package.get("archive_type") or ""), str(package.get("archive_type") or ""))
        source_count = len(items)
        file_count = sum(int(item.get("file_count") or 0) for item in items)
        publish_month = str(metadata.get("publish_month") or "")
        activity_month = str(metadata.get("activity_month") or "")
        topic = str(metadata.get("topic") or first.get("name") or "未命名").strip()
        activity_name = str(metadata.get("activity_name") or first.get("name") or "未命名").strip()
        target = str(package.get("target_uri") or "")
        final_target = str(package.get("final_target_uri") or "")
        package_status = str(package.get("status") or batch_status)
        remote_matches = _archive_remote_matches(package, remote_paths)
        package_type = str(package.get("archive_type") or "")
        if package_type == "publish" and any("发布月份" in value for value in package_missing):
            target_name = "补充发布月份后生成"
        elif package_type == "activity" and package_missing:
            target_name = "补充活动信息后生成"
        else:
            target_name = target.rstrip("/").rsplit("/", 1)[-1] if target else "待重新确认"
        if final_target:
            target_name = final_target.rstrip("/").rsplit("/", 1)[-1]
        if package_type == "publish":
            detail_badges = (
                f'<span>发布月份 {html.escape(publish_month)}</span>'
                if publish_month else '<span class="missing">缺少发布月份</span>'
            ) + f'<span>归档名称 {html.escape(topic)}</span>'
        elif package_type == "activity":
            detail_badges = (
                f'<span>活动月份 {html.escape(activity_month)}</span>'
                if activity_month else '<span class="missing">缺少活动月份</span>'
            ) + f'<span>活动名称 {html.escape(activity_name)}</span>'
        else:
            archive_name = str(metadata.get("target_subdir") or metadata.get("material_name") or first.get("name") or "未命名").strip()
            detail_badges = f'<span>归档名称 {html.escape(archive_name)}</span>'
        if package_status == "archived":
            status_badge = '<span class="complete">已完成</span>'
        elif package_status == "receipt_pending":
            status_badge = '<span class="pending">网盘已验证 · 回执待补</span>'
        elif remote_matches:
            status_badge = '<span class="pending">目录已出现 · 待校验</span>'
        elif package_status == "conflict":
            status_badge = '<span class="missing">冲突待处理</span>'
        elif package_status == "archiving":
            status_badge = '<span class="pending">归档中</span>'
        else:
            status_badge = ""
        summaries.append(f'<article class="archive-package-summary"><div class="archive-package-title"><strong>{html.escape(archive_type)} · {html.escape(project)}</strong><small>{source_count} 个来源 · {file_count} 个文件 · {format_bytes(int(package.get("size") or 0))}</small></div><div class="archive-package-chips">{detail_badges}{status_badge}</div><div class="archive-package-target"><small>目标文件夹</small><strong>{html.escape(target_name)}</strong></div></article>')
        technical.append(f'<div><dt>{html.escape(str(package.get("package_id") or ""))}</dt><dd>{html.escape(final_target or target)}</dd></div>')
    details = f'<details class="archive-batch-technical"><summary>查看技术详情</summary><dl><div><dt>批次</dt><dd>{html.escape(str(batch.get("batch_id") or ""))}</dd></div><div><dt>确认版本</dt><dd>revision {int(batch.get("confirmed_revision") or 0)}</dd></div>{"".join(technical)}</dl></details>'
    confirmed_at = str(batch.get("confirmed_at") or "").replace("T", " ")[:16]
    drawer = ""
    if drawer_actions:
        drawer_packages: list[str] = []
        for package in packages:
            items = list(package.get("items", []))
            names = "、".join(str(item.get("name") or "未命名") for item in items)
            target = str(package.get("final_target_uri") or package.get("target_uri") or "待生成")
            target_name = target.rstrip("/").rsplit("/", 1)[-1] if target != "待生成" else target
            source_policy = "复制并保留" if all(item.get("source_kind") == "delivery" for item in items) else "归档成功后标记可删除"
            drawer_packages.append(
                f'<article><strong>{html.escape(names)}</strong><dl><div><dt>来源处理</dt><dd>{html.escape(source_policy)}</dd></div><div><dt>目标文件夹</dt><dd>{html.escape(target_name)}</dd></div></dl><details><summary>查看完整路径</summary><code>{html.escape(target)}</code></details></article>'
            )
        title_id = f"archive-drawer-title-{batch_id}"
        drawer = f'<div class="archive-drawer-backdrop" data-archive-drawer="{html.escape(batch_id, quote=True)}" data-archive-batch-drawer hidden><aside class="archive-confirm-drawer" role="dialog" aria-modal="true" aria-labelledby="{html.escape(title_id, quote=True)}"><header><div><strong id="{html.escape(title_id, quote=True)}">{html.escape(drawer_title)}</strong><small>{html.escape(drawer_hint)}</small></div><button class="archive-drawer-close" type="button" data-archive-drawer-close aria-label="关闭">×</button></header><div class="archive-drawer-body">{"".join(drawer_packages)}</div>{drawer_actions}</aside></div>'
    return f'<article class="archive-batch-card"><header><div><strong>归档批次 · {len(packages)} 个归档包</strong><small>{html.escape(confirmed_at)}</small></div>{actions}</header>{"".join(summaries)}{notice}<footer>{details}</footer></article>{drawer}'


def _archive_batches(
    payload: dict[str, object],
    token: str,
    archive_payload: dict[str, object] | None = None,
    *,
    group: str = "all",
) -> str:
    if group in {"ready", "exception"}:
        batches = _archive_batches_in_group(payload, group)
    elif group == "active":
        batches = [
            batch for batch in payload.get("batches", []) or []
            if _archive_batch_group(payload, batch) in {"ready", "exception"}
        ]
    elif group == "all":
        batches = [
            batch for batch in payload.get("batches", []) or []
            if str(batch.get("status") or "confirmed") != "returned_to_queue"
            and not _archive_batch_is_superseded(payload, batch)
        ]
    else:
        batches = []
    if not batches:
        empty = "暂无待执行批次。" if group == "ready" else "暂无需要处理的异常批次。"
        return f'<div class="inbox-empty">{empty}</div>'
    remote = archive_payload or archive_index.load_index()
    return "".join(
        _archive_batch_card({**payload, "batches": [batch]}, token, remote)
        for batch in reversed(batches)
    )


def _archive_remote_browser(token: str, payload: dict[str, object] | None = None) -> str:
    payload = payload if payload is not None else archive_index.load_index()
    projects = payload.get("projects", []) if isinstance(payload, dict) else []
    executor_buttons = execution_confirm_button("核对所选目录并开始整理", disabled=True)

    def node(item: dict[str, object], depth: int = 0) -> str:
        remote_path = str(item.get("remote_path") or "")
        is_dir = item.get("type") == "directory"
        children = item.get("children") or []
        meta = f"目录 · {len(children)} 项" if is_dir and children else "目录" if is_dir else "文件"
        node_id = "archive-remote-" + hashlib.sha256(remote_path.encode("utf-8")).hexdigest()[:12]
        return (
            f'<div class="inbox-tree-node archive-map-node" data-archive-search="{html.escape(str(item.get("name") or "").lower(), quote=True)}">'
            f'<div class="inbox-item" style="--inbox-depth:{depth}">'
            f'<button class="inbox-expand{"" if is_dir else " invisible"}" type="button" data-archive-map-expand="{html.escape(remote_path, quote=True)}" data-loaded="0" aria-expanded="false" aria-controls="{node_id}-children" aria-label="展开：{html.escape(str(item.get("name") or ""), quote=True)}">›</button>'
            f'<input id="{node_id}" type="checkbox" name="archiveSelection" value="{html.escape(remote_path, quote=True)}" data-kind="{"文件夹" if is_dir else "文件"}">'
            f'<label class="inbox-file-copy" for="{node_id}"><strong>{html.escape(str(item.get("name") or ""))}</strong><small>{html.escape(meta)}</small></label></div>'
            f'<div id="{node_id}-children" class="inbox-children" role="group" hidden data-archive-children></div></div>'
        )

    tabs: list[str] = []
    panes: list[str] = []
    for index, project in enumerate(projects):
        key = str(project.get("gstudio_project") or index)
        title = str(project.get("name") or key).replace("【项目】", "").removesuffix("Nas")
        path = str(project.get("remote_path") or "")
        tabs.append(
            f'<button class="inbox-tab{" active" if index == 0 else ""}" type="button" role="tab" aria-selected="{str(index == 0).lower()}" tabindex="{0 if index == 0 else -1}" data-archive-project-tab="{html.escape(key, quote=True)}" data-archive-project-path="{html.escape(path, quote=True)}"><span>{html.escape(title)}</span><small>{len(project.get("children") or [])}</small></button>'
        )
        contents = ''.join(node(child) for child in project.get("children") or []) or '<div class="inbox-empty">当前项目暂无目录。</div>'
        panes.append(f'<div class="inbox-pane{" active" if index == 0 else ""}" role="tabpanel" data-archive-project-pane="{html.escape(key, quote=True)}">{contents}</div>')
    hidden = (
        f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}">'
        '<input type="hidden" name="return_to" value="/archive">'
        '<input type="hidden" name="inbox_action" value="organize_archive">'
        '<span id="archiveRemoteFields" hidden></span>'
    )
    first_project = str(projects[0].get("gstudio_project") or "") if projects else ""
    refresh = f'''<form method="post" action="/actions/refresh-archive" class="archive-refresh-form"><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="/archive"><input type="hidden" id="archiveRefreshProject" name="project" value="{html.escape(first_project, quote=True)}"><button class="button ghost" type="submit">刷新目录</button></form>'''
    legacy_hidden = f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="/archive"><input type="hidden" name="inbox_action" value="organize_baidu">'
    legacy_buttons = execution_confirm_button("核对百度历史归档整理提示词并开始")
    maintenance = f'''<form method="post" action="/actions/workspace-inbox-task" class="archive-context-action archive-head-ai-action" data-execution-confirm data-execution-label="整理百度历史归档">{legacy_hidden}{legacy_buttons}</form>'''
    backup = archive_backup_audit.load_status()
    backup_status = str(backup.get("status") or "not_audited")
    backup_label = {"ok": "备份核验正常", "exception": "备份存在异常", "error": "备份状态异常", "not_audited": "备份待首次核验"}.get(backup_status, "备份状态未知")
    checked_at = str(backup.get("checked_at") or backup.get("last_confirmed_fnos_run_at") or "")
    backup_meta = f'<span class="badge archive-backup-status archive-heading-status {"complete" if backup_status == "ok" else "waiting"}" title="飞牛每日 00:00 单向备份；最近状态 {html.escape(checked_at)}">{html.escape(backup_label)}</span>'
    return f'''<section class="panel archive-browser-card archive-baidu-browser" id="archiveRemote"><header class="archive-browser-head"><div class="archive-panel-heading"><div class="archive-panel-titleline"><h2>归档库</h2>{backup_meta}</div><small>NAS 正本 · 飞牛每日备份到百度</small></div><div class="archive-head-actions">{refresh}{maintenance}</div></header><div class="archive-directory-browser-body"><div class="inbox-tabs archive-project-tabs" role="tablist" aria-label="归档项目">{''.join(tabs)}</div><div class="archive-map-scroll">{''.join(panes) if panes else '<div class="inbox-empty">NAS 归档索引尚未生成。</div>'}</div></div><section class="archive-source-maintenance archive-selection-operation" data-archive-selection-operation hidden><span><strong>整理已选目录</strong><small id="archiveSelectionLabel" aria-live="polite">已选 0 项</small></span><div class="archive-selection-actions"><button class="button ghost" id="clearArchiveSelection" type="button" disabled>清除选择</button><form method="post" action="/actions/workspace-inbox-task" id="archiveMapActionForm" class="archive-context-action" data-execution-confirm data-execution-label="整理已选归档目录">{hidden}<div class="archive-executor-actions">{executor_buttons}</div></form></div></section></section>'''


def _render_archive_legacy_v2(token: str, notice: str='', error: str='', *, view: str='', publish_records: list[dict[str, object]] | None=None) -> str:
    from .pages.archive import _render_archive_legacy_v2 as _present
    return _present(token, notice, error, view=view, publish_records=publish_records)


ARCHIVE_PAGE_SIZE = 30
ARCHIVE_ASSET_VERSION = "20260821-07"
ARCHIVE_SCENE_VALUES = {"inbox", "directory", "history"}
ARCHIVE_SOURCE_VALUES = {"inbox"}
ARCHIVE_LABEL_VALUES = {"unclassified", "processing", "pending_archive", "deletable"}
ARCHIVE_QUEUE_VALUES = {"pending", "ready", "exception"}
ARCHIVE_LABEL_NAMES = {
    "unclassified": "未分类",
    "processing": "处理中",
    "pending_archive": "待归档",
    "deletable": "可删除",
}



def normalize_archive_view_state(
    *,
    view: str = "",
    scene: str = "",
    source: str = "",
    label: str = "",
    queue_view: str = "",
    query: str = "",
    page: int | str = 1,
) -> dict[str, object]:
    """Normalize old archive links and allowlisted URL state."""
    legacy = str(view or "").strip()
    selected_scene = str(scene or "").strip()
    if selected_scene not in ARCHIVE_SCENE_VALUES:
        selected_scene = legacy if legacy in {"directory", "history"} else "inbox"
    selected_source = str(source or "").strip()
    if selected_source not in ARCHIVE_SOURCE_VALUES:
        selected_source = "inbox"
    selected_label = str(label or "").strip()
    if selected_label not in ARCHIVE_LABEL_VALUES:
        selected_label = "unclassified"
    selected_queue = str(queue_view or "").strip()
    if selected_queue not in ARCHIVE_QUEUE_VALUES:
        selected_queue = legacy if legacy in ARCHIVE_QUEUE_VALUES else "pending"
    try:
        selected_page = max(1, int(page))
    except (TypeError, ValueError):
        selected_page = 1
    return {
        "scene": selected_scene,
        "source": selected_source,
        "label": selected_label,
        "queue": selected_queue,
        "q": str(query or "").strip()[:160],
        "page": selected_page,
    }


def archive_view_url(state: dict[str, object], **updates: object) -> str:
    selected = {**state, **updates}
    scene = str(selected.get("scene") or "inbox")
    params: list[tuple[str, str]] = [("scene", scene)]
    if scene == "inbox":
        source = str(selected.get("source") or "inbox")
        params.extend((("source", source), ("queue", str(selected.get("queue") or "pending"))))
        if source == "inbox":
            params.append(("label", str(selected.get("label") or "unclassified")))
        query = str(selected.get("q") or "")
        if query:
            params.append(("q", query))
        page = max(1, int(selected.get("page") or 1))
        if page > 1:
            params.append(("page", str(page)))
    elif scene == "history":
        query = str(selected.get("q") or "")
        if query:
            params.append(("q", query))
        page = max(1, int(selected.get("page") or 1))
        if page > 1:
            params.append(("page", str(page)))
    if scene != "inbox" and str(selected.get("queue") or "pending") != "pending":
        params.append(("queue", str(selected.get("queue") or "pending")))
    return "/archive?" + urlencode(params)


def _archive_queue_payload_safe() -> dict[str, object]:
    load_errors = (archive_queue.ArchiveQueueError, OSError, json.JSONDecodeError)
    try:
        return archive_queue.load()
    except load_errors as first_error:
        print(
            f"Ember workbench archive queue read failed; retrying once: {first_error!r}",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(0.2)
        try:
            return archive_queue.load()
        except load_errors as final_error:
            print(
                f"Ember workbench archive queue retry failed: {final_error!r}",
                file=sys.stderr,
                flush=True,
            )
            return {
                "schema_version": 1,
                "revision": 0,
                "updated_at": "",
                "items": [],
                "batches": [],
                "_load_error": f"归档队列无法读取：{final_error}",
            }


def _archive_pagination(
    state: dict[str, object],
    *,
    total: int,
    page: int,
    page_size: int = ARCHIVE_PAGE_SIZE,
    kind: str = "source",
) -> str:
    pages = max(1, (max(total, 0) + page_size - 1) // page_size)
    page = min(max(page, 1), pages)
    start = 0 if total == 0 else (page - 1) * page_size + 1
    end = min(total, page * page_size)
    link_attr = "data-archive-source-page" if kind == "source" else ""
    previous = (
        f'<a class="button ghost" {link_attr} href="{html.escape(archive_view_url(state, page=page - 1), quote=True)}">上一页</a>'
        if page > 1 else '<span></span>'
    )
    following = (
        f'<a class="button ghost" {link_attr} href="{html.escape(archive_view_url(state, page=page + 1), quote=True)}">下一页</a>'
        if page < pages else '<span></span>'
    )
    return (
        f'<nav class="archive-pagination" aria-label="分页">{previous}'
        f'<span aria-live="polite">{start}–{end} / {total} · 第 {page}/{pages} 页</span>{following}</nav>'
    )


def _archive_source_health(payload: dict[str, object], total: int) -> tuple[str, str]:
    state = str(payload.get("snapshot_state") or payload.get("status") or "fresh")
    generated_at = str(payload.get("generated_at") or "")
    error = str(payload.get("last_error") or payload.get("error") or "")
    usable = bool(payload.get("usable", state not in {"missing", "error"}))
    if error:
        detail = f"刷新失败：{error}" + (f"；仍显示 {generated_at} 快照" if usable and generated_at else "")
        return "error", f'<span class="archive-source-health archive-heading-status error" role="alert" title="{html.escape(detail, quote=True)}">刷新失败 · 保留上次结果 <button class="link-button" type="submit" form="archiveSnapshotRefresh">重试</button></span>'
    if state in {"missing", "refreshing"} and not usable:
        return "loading", '<span class="archive-source-health archive-heading-status loading" role="status">正在读取…</span>'
    if state in {"stale", "dirty", "invalidated"}:
        return "stale", f'<span class="archive-source-health archive-heading-status stale" role="status" title="当前显示 {html.escape(generated_at or "上次成功", quote=True)} 快照">后台更新中 · {total} 项</span>'
    shown_at = generated_at[11:16] if len(generated_at) >= 16 else "刚刚"
    return ("empty" if total == 0 else "ready"), f'<span class="archive-source-health archive-heading-status ready" role="status" title="本机快照更新于 {html.escape(generated_at or "刚刚", quote=True)}">更新 {html.escape(shown_at)} · {total} 项</span>'


def _archive_source_actions(
    state: dict[str, object],
    *,
    queue_error: str = "",
) -> str:
    source = str(state.get("source") or "inbox")
    label = str(state.get("label") or "unclassified")
    disabled = " disabled" if queue_error else ""
    if source == "delivery":
        return f'''<dialog class="archive-source-action-dialog" id="archiveSourceActions" data-disabled="{str(bool(queue_error)).lower()}" aria-labelledby="archiveSourceActionTitle"><header><div><strong id="archiveSourceActionTitle">处理所选交付</strong><small id="archiveSourceDialogSelection" aria-live="polite">已选 0 项</small></div><button class="archive-drawer-close" type="button" data-archive-source-actions-close aria-label="关闭处理框">×</button></header><div class="archive-source-action-body"><span class="archive-current-state">复制并保留</span><p>任务交付始终从正本复制，原交付不移动、不改名、不删除。</p>{f'<div class="notice error" role="alert">{html.escape(queue_error)}</div>' if queue_error else ''}</div><footer><button class="button primary" form="archiveSourceForm" formaction="/actions/archive-queue-add" type="submit"{disabled}>加入归档任务</button></footer></dialog>'''
    buttons = {
        "unclassified": (
            ("processing", "处理中", "button"),
            ("pending_archive", "待归档", "button"),
            ("deletable", "可删除", "button"),
        ),
        "processing": (
            ("pending_archive", "待归档", "button"),
            ("deletable", "可删除", "button"),
            ("unclassified", "清除标签", "button ghost"),
        ),
        "pending_archive": (
            ("processing", "改为处理中", "button"),
            ("unclassified", "取消待归档", "button ghost"),
        ),
        "deletable": (
            ("processing", "恢复处理中", "button"),
            ("unclassified", "清除标签", "button ghost"),
        ),
    }
    actions = "".join(
        f'<button class="{css}" form="archiveSourceForm" formaction="/actions/archive-inbox-transition" name="target_state" value="{target}" type="submit" disabled>{text}</button>'
        for target, text, css in buttons.get(label, ())
    )
    if label == "deletable":
        actions = '<button class="button danger" form="archiveSourceForm" formaction="/actions/archive-inbox-delete" type="submit" disabled>永久删除…</button>' + actions
    explanations = {
        "unclassified": "临时收件；标签变化只写共享台账，不移动来源。",
        "processing": "仍被当前工作使用，不进入归档候选。",
        "pending_archive": "已进入归档任务；取消待归档会同步移出尚未确认的队列项目。",
        "deletable": "仍需逐项选择并确认；只删除 NAS Inbox 当前副本。",
    }
    return f'''<dialog class="archive-source-action-dialog" id="archiveSourceActions" data-disabled="{str(bool(queue_error)).lower()}" aria-labelledby="archiveSourceActionTitle"><header><div><strong id="archiveSourceActionTitle">处理所选文件</strong><small id="archiveSourceDialogSelection" aria-live="polite">已选 0 项</small></div><button class="archive-drawer-close" type="button" data-archive-source-actions-close aria-label="关闭处理框">×</button></header><div class="archive-source-action-body"><span class="archive-current-state">当前：{html.escape(ARCHIVE_LABEL_NAMES.get(label, label))}</span><p>{html.escape(explanations.get(label, ''))}</p>{f'<div class="notice error" role="alert">{html.escape(queue_error)}</div>' if queue_error else ''}</div><footer><div class="archive-source-state-actions">{actions}</div></footer></dialog>'''


def archive_source_view_payload(
    token: str,
    state: dict[str, object],
    *,
    queue_payload: dict[str, object] | None = None,
    inbox_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    state = {**state, "source": "inbox"}
    queue_payload = queue_payload or _archive_queue_payload_safe()
    revision = int(queue_payload.get("revision") or 0)
    source = "inbox"
    page = max(1, int(state.get("page") or 1))
    query = ""
    total = 0
    counts: dict[str, int] = {name: 0 for name in ARCHIVE_LABEL_VALUES}
    status = "ready"
    status_html = ""
    if source == "delivery":
        try:
            all_items = archive_delivery_tasks()
            if query:
                folded = query.casefold()
                all_items = [item for item in all_items if folded in " ".join(str(value) for value in item.values()).casefold()]
            total = len(all_items)
            pages = max(1, (total + ARCHIVE_PAGE_SIZE - 1) // ARCHIVE_PAGE_SIZE)
            page = min(page, pages)
            start = (page - 1) * ARCHIVE_PAGE_SIZE
            rows = _archive_delivery_rows(all_items[start:start + ARCHIVE_PAGE_SIZE])
            status = "empty" if not rows else "ready"
            status_html = f'<span class="archive-source-health ready" role="status" title="任务交付只读索引；来源始终复制并保留">索引 · {total} 项</span>'
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            rows = ""
            status = "error"
            status_html = f'<span class="archive-source-health error" role="alert" title="{html.escape(str(exc), quote=True)}">任务索引读取失败</span>'
    else:
        snapshot = inbox_snapshot if inbox_snapshot is not None else archive_inbox.load_snapshot()
        selected_label = str(state.get("label") or "unclassified")
        entries_by_state = snapshot.get("entries_by_state") if isinstance(snapshot.get("entries_by_state"), dict) else {}
        all_entries = [item for item in entries_by_state.get(selected_label, []) or [] if isinstance(item, dict)]
        total = len(all_entries)
        page = 1
        counts = {key: int(value or 0) for key, value in (snapshot.get("counts") or {}).items() if key in ARCHIVE_LABEL_VALUES}
        page_payload = {**snapshot, "entries": all_entries, "total": total, "offset": 0, "limit": total, "has_more": False}
        rows = _archive_source_rows("inbox", str(state.get("label") or "unclassified"), page_payload)
        status, status_html = _archive_source_health(page_payload, total)

    current_state = {**state, "q": "", "page": page}
    canonical = archive_view_url(current_state)
    label_tabs = ""
    if source == "inbox":
        selected_label = str(state.get("label") or "unclassified")
        label_tabs = '<nav class="archive-label-tabs" role="tablist" aria-label="Inbox 标签">' + "".join(
            f'<a role="tab" aria-selected="{str(selected_label == value).lower()}" tabindex="{0 if selected_label == value else -1}" class="{"active" if selected_label == value else ""}" data-archive-label-link href="{html.escape(archive_view_url(state, label=value, q="", page=1), quote=True)}"><span>{name}</span><small>{counts.get(value, 0)}</small></a>'
            for value, name in ARCHIVE_LABEL_NAMES.items()
        ) + '</nav>'
    empty_text = "暂无匹配内容。" if query else "当前列表为空。"
    if status == "loading":
        empty_text = "正在读取来源，不会把未加载状态当作空目录。"
    elif status == "error":
        empty_text = "来源暂不可用；修复后可在原位重试。"
    list_html = rows or f'<div class="archive-empty-state" data-state="{html.escape(status, quote=True)}">{html.escape(empty_text)}</div>'
    source_hidden = (
        f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}">'
        f'<input type="hidden" name="revision" value="{revision}">'
        f'<input type="hidden" name="return_to" value="{html.escape(canonical, quote=True)}">'
        f'<input type="hidden" name="source_state" value="{html.escape(str(state.get("label") or "unclassified"), quote=True)}">'
    )
    refresh_form = ""
    finder_form = ""
    if source == "inbox":
        refresh_form = f'<form id="archiveSnapshotRefresh" method="post" action="/actions/refresh-archive-inbox-snapshot" data-archive-async-form><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="{html.escape(canonical, quote=True)}"><button class="button ghost" type="submit" formaction="/actions/refresh-archive-inbox-snapshot">刷新列表</button></form>'
        finder_form = f'<form method="post" action="/actions/open-archive-inbox"><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="{html.escape(canonical, quote=True)}"><input type="hidden" name="state" value="{html.escape(str(state.get("label") or "unclassified"), quote=True)}"><button class="button ghost" type="submit">Finder 打开</button></form>'
    maintenance = ""
    if source == "inbox":
        buttons = execution_confirm_button("核对收件箱整理提示词并开始")
        maintenance = f'<form method="post" action="/actions/archive-maintenance-start" class="archive-context-action archive-head-ai-action" data-execution-confirm data-execution-label="整理收件箱"><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="{html.escape(canonical, quote=True)}"><input type="hidden" name="scope" value="inbox">{buttons}</form>'
    page_count = total
    action_label = "处理所选文件"
    selection_toolbar = f'''<div class="archive-source-selection-toolbar"><label><input type="checkbox" data-archive-source-select-all{' disabled' if page_count == 0 else ''}>全选当前分类 <small>{page_count} 项</small></label><div class="archive-source-selection-context"><small id="archiveSourceSelection" aria-live="polite">选择后可处理</small><button class="button ghost" id="archiveSourceActionTrigger" type="button" data-archive-source-actions-open hidden disabled>{action_label}</button></div></div>'''
    source_actions = _archive_source_actions(state, queue_error=str(queue_payload.get("_load_error") or ""))
    panel = f'''<section class="panel archive-browser-card archive-source-browser" id="archiveSourceArea" data-archive-source-status="{html.escape(status, quote=True)}" data-archive-auto-refresh="{str(status in {'loading', 'stale', 'error'}).lower()}"><header class="archive-browser-head"><div class="archive-panel-heading"><div class="archive-panel-titleline"><h2>收件箱</h2>{status_html}</div><small>NAS Inbox</small></div><div class="archive-head-actions">{refresh_form}{finder_form}{maintenance}</div></header><div class="archive-inbox-browser-body">{label_tabs}<form method="post" action="/actions/archive-inbox-transition" id="archiveSourceForm" data-source-kind="inbox">{source_hidden}{selection_toolbar}{source_actions}<div class="archive-source-list" role="tabpanel" aria-busy="{str(status == 'loading').lower()}">{list_html}</div></form></div></section>'''
    return {
        "ok": status != "error",
        "status": status,
        "html": panel,
        "actions_html": source_actions,
        "total": total,
        "page": page,
        "pages": 1,
        "revision": revision,
        "counts": counts,
        "canonical_url": canonical,
    }


def archive_queue_view_payload(
    token: str,
    state: dict[str, object],
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = payload or _archive_queue_payload_safe()
    queue_error = str(payload.get("_load_error") or "")
    exception_states = {"source_changed", "conflict", "failed_retryable", "receipt_pending"}
    pending_items = [
        item for item in payload.get("items", []) or []
        if not item.get("package_id") and str(item.get("state") or "") not in exception_states | {"archiving", "archived"}
    ]
    loose_exceptions = [
        item for item in payload.get("items", []) or []
        if not item.get("package_id") and str(item.get("state") or "") in exception_states
    ]
    ready_batches = _archive_batches_in_group(payload, "ready")
    exception_batches = _archive_batches_in_group(payload, "exception")
    counts = {
        "pending": len(pending_items),
        "ready": _archive_batch_item_count(ready_batches),
        "exception": len(loose_exceptions) + _archive_batch_item_count(exception_batches),
    }
    total_count = sum(counts.values())
    has_queue_work = bool(pending_items or ready_batches or loose_exceptions or exception_batches)
    selected = str(state.get("queue") or "pending")
    if selected not in ARCHIVE_QUEUE_VALUES:
        selected = "pending"
    canonical = archive_view_url(state, queue=selected)
    if queue_error:
        body = f'<div class="archive-empty-state error" role="alert">{html.escape(queue_error)}。列表未被当作空队列；修复后请重试。</div>'
        status = "error"
    elif not has_queue_work:
        body = '<div class="archive-queue-empty"><strong>现在没有归档任务</strong><small>选择左侧文件并标为待归档后，目标信息和确认步骤会在这里出现。</small></div>'
        status = "empty"
    elif selected == "pending":
        body = _archive_queue_table(payload, token, group="pending", return_to=canonical + "#archiveBasket")
        status = "empty" if not pending_items else "ready"
    else:
        remote = archive_index.load_index()
        if selected == "ready":
            body = f'<div class="archive-batch-list">{_archive_batches(payload, token, remote, group="ready")}</div>'
            status = "empty" if not counts["ready"] else "ready"
        else:
            editor = _archive_source_exception_cards(payload, token) if loose_exceptions else ""
            body = f'{editor}<div class="archive-batch-list">{_archive_batches(payload, token, remote, group="exception")}</div>'
            status = "empty" if not counts["exception"] else "ready"
    help_text = {
        "pending": "选择本次要处理的项目，再补充目标信息；默认不会全选。",
        "ready": "只显示确认仍有效、可以逐包检查并执行的批次。",
        "exception": "按原因重新核对来源、处理冲突、重试失败步骤或补写回执。",
    }[selected]
    tabs = "".join(
        f'<a role="tab" aria-selected="{str(selected == value).lower()}" tabindex="{0 if selected == value else -1}" class="{"active" if selected == value else ""}" data-archive-queue-link href="{html.escape(archive_view_url(state, queue=value), quote=True)}">{name}<small>{counts[value]}</small></a>'
        for value, name in (("pending", "待补信息"), ("ready", "待执行"), ("exception", "异常处理"))
    )
    navigation = "" if not has_queue_work and not queue_error else f'<nav class="archive-basket-tabs" role="tablist" aria-label="归档任务状态">{tabs}</nav><p class="archive-basket-help">{html.escape(help_text)}</p>'
    panel = f'''<section class="archive-task-operation" id="archiveQueueArea" data-archive-queue-status="{status}"><div class="archive-task-summary"><small>补全目标 → 检查归档包 → 确认执行 → 查看回执</small><span>{total_count} 项</span></div>{navigation}<div class="archive-basket-pane active" role="tabpanel">{body}</div></section>'''
    return {
        "ok": not queue_error,
        "status": status,
        "html": panel,
        "view": selected,
        "revision": int(payload.get("revision") or 0),
        "counts": counts,
        "canonical_url": canonical,
    }


def archive_history_view_payload(
    state: dict[str, object],
    *,
    queue_payload: dict[str, object] | None = None,
    publish_records: list[dict[str, object]] | None = None,
    embedded: bool = False,
) -> dict[str, object]:
    queue_payload = queue_payload or _archive_queue_payload_safe()
    rows: list[dict[str, str]] = []
    project_titles = {slug: str(item.get("title") or slug) for slug, item in project_items().items()}
    type_labels = {
        "publish": "发布归档",
        "activity": "活动素材",
        "project_material": "项目资料",
        "data_asset": "数据资产",
        "theme_product": "主题产品",
        "professional_knowledge": "专业知识",
        "external_cooperation": "外部合作",
    }
    for batch in queue_payload.get("batches", []) or []:
        batch_id = str(batch.get("batch_id") or "")
        for package in batch.get("packages", []) or []:
            if str(package.get("status") or "") != "archived" and not package.get("receipt_ref"):
                continue
            sources = "、".join(str(item.get("name") or "") for item in package.get("items", []) or [] if item.get("name"))
            rows.append({
                "sort": str(package.get("updated_at") or batch.get("updated_at") or batch.get("confirmed_at") or ""),
                "id": str(package.get("package_id") or batch_id),
                "project": project_titles.get(str(package.get("project") or ""), str(package.get("project") or "")),
                "type": type_labels.get(str(package.get("archive_type") or ""), str(package.get("archive_type") or "")),
                "source": sources,
                "target": str(package.get("final_target_uri") or package.get("target_uri") or ""),
                "verification": str(package.get("verification") or ""),
                "receipt": str(package.get("receipt_ref") or ""),
                "state": "物理归档完成",
            })
    records = publish_records if publish_records is not None else ember_publish.list_records()
    for item in records:
        status = str(item.get("status") or "")
        if status not in {"archived", "rejected"}:
            continue
        rows.append({
            "sort": str(item.get("updated_at") or item.get("published_at") or ""),
            "id": str(item.get("release_id") or ""),
            "project": project_titles.get(str(item.get("project") or ""), str(item.get("project") or "")),
            "type": "发布台账兼容",
            "source": str(item.get("topic") or ""),
            "target": str(item.get("material_path") or ""),
            "verification": "",
            "receipt": "",
            "state": ember_publish.STATUS_LABELS.get(status, status),
        })
    rows.sort(key=lambda item: item["sort"], reverse=True)
    query = str(state.get("q") or "")
    if query:
        folded = query.casefold()
        rows = [item for item in rows if folded in " ".join(item.values()).casefold()]
    total = len(rows)
    page = max(1, int(state.get("page") or 1))
    pages = max(1, (total + ARCHIVE_PAGE_SIZE - 1) // ARCHIVE_PAGE_SIZE)
    page = min(page, pages)
    page_rows = rows if embedded else rows[(page - 1) * ARCHIVE_PAGE_SIZE:page * ARCHIVE_PAGE_SIZE]
    record_parts: list[str] = []
    for item in page_rows:
        target_path = item["target"] or "目标未记录"
        record_parts.append(
            f'<div class="archive-history-row">'
            f'<time datetime="{html.escape(item["sort"], quote=True)}">{html.escape(item["sort"][:10] or "—")}</time>'
            f'<span class="archive-history-identity" title="{html.escape(item["project"] or "—", quote=True)} · {html.escape(item["type"] or "—", quote=True)}">{html.escape(item["project"] or "—")} · {html.escape(item["type"] or "—")}</span>'
            f'<span class="archive-history-route" title="{html.escape(target_path, quote=True)}">{html.escape(target_path)}</span>'
            f'<span class="badge complete">{html.escape(item["state"])}</span></div>'
        )
    record_rows = "".join(record_parts)
    if not record_rows:
        record_rows = '<div class="archive-empty-state">暂无匹配的归档记录。</div>'
    selected_state = {**state, "page": page}
    search_hidden = '<input type="hidden" name="scene" value="history">'
    pagination = "" if embedded else _archive_pagination(selected_state, total=total, page=page, kind="history")
    search_form = f'''<form class="archive-history-search" method="get" action="/archive">{search_hidden}<input id="archiveHistorySearch" type="search" name="q" value="{html.escape(query, quote=True)}" placeholder="项目、归档目录或路径…" aria-label="搜索归档记录"><button class="button" type="submit">搜索</button></form>'''
    panel = f'''<section class="panel archive-history{' embedded' if embedded else ''}" id="archiveHistory"><header class="archive-browser-head"><div><h2>归档记录</h2><small>直接查看 NAS 正本目录，并可按项目、文件夹或路径搜索。</small></div><div class="archive-history-head-actions"><span class="archive-history-count">{total} 条</span>{search_form}</div></header>{f'<div class="notice error" role="alert">{html.escape(str(queue_payload.get("_load_error")))}；发布兼容记录仍可查看。</div>' if queue_payload.get("_load_error") else ''}<div class="archive-history-list"><div class="archive-history-row header" aria-hidden="true"><span>日期</span><span>项目 / 类型</span><span>归档目录</span><span>状态</span></div>{record_rows}</div>{pagination}</section>'''
    return {"ok": True, "status": "empty" if total == 0 else "ready", "html": panel, "total": total, "page": page, "pages": pages, "canonical_url": archive_view_url(selected_state)}


def render_archive(token: str, notice: str='', error: str='', *, view: str='', scene: str='', source: str='', label: str='', queue_view: str='', query: str='', page: int | str=1, publish_records: list[dict[str, object]] | None=None, inbox_snapshot: dict[str, object] | None=None) -> str:
    from .pages.archive import render_archive as _present
    return _present(token, notice, error, view=view, scene=scene, source=source, label=label, queue_view=queue_view, query=query, page=page, publish_records=publish_records, inbox_snapshot=inbox_snapshot)


def format_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _organization_form(token: str, mode: str, options: list[tuple[str, str]] | None = None) -> str:
    hidden = (
        f'<input type="hidden" name="csrf" value="{html.escape(token, quote=True)}">'
        f'<input type="hidden" name="mode" value="{html.escape(mode, quote=True)}">'
        '<input type="hidden" name="return_to" value="/weekly">'
    )
    select = ""
    if options:
        select = '<select name="scope" aria-label="选择整理范围">' + "".join(
            f'<option value="{html.escape(value, quote=True)}">{html.escape(label)}</option>' for value, label in options
        ) + '</select>'
    action = execution_confirm_button('开始整理并确认执行器')
    return f'<form class="action-form organization-scope" method="post" action="/actions/organization-start" data-execution-confirm data-execution-label="开始整理">{hidden}{select}<div class="organization-actions">{action}</div></form>'


def task_search_summary(record: dict[str, object]) -> str:
    """Return the small metadata corpus safe to embed in an initial page."""
    task_id = str(record.get("task_id") or "")
    fields = [
        str(record.get("task_name") or record.get("title") or ""),
        str(record.get("description") or "")[:180],
        task_id,
        str(record.get("project") or ""),
        str(record.get("project_title") or ""),
        str(record.get("work_type") or ""),
        TYPE_LABEL.get(str(record.get("work_type") or ""), ""),
        str(record.get("status") or ""),
        STATUS_LABEL.get(str(record.get("status") or ""), ""),
    ]
    return re.sub(r"\s+", " ", " ".join(fields)).strip()[:500]


def organization_task_search_document(record: dict[str, object]) -> str:
    """Build full text on demand; never embed it in an initial page."""
    task_id = str(record.get("task_id") or "")
    fields = [task_search_summary(record)]
    source = task_source(task_id)
    if source:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
            _, body = tasks.frontmatter(text)
            fields.append(body)
        except OSError:
            pass
    document = re.sub(r"\s+", " ", " ".join(fields)).strip()
    return document[:16000]


def _task_search_document_match(
    query: str,
    document: str,
    *,
    lowered_document: str = "",
    compact_document: str = "",
) -> tuple[int, str]:
    """Score one prepared task document and return its evidence excerpt."""
    normalized_query = re.sub(r"\s+", " ", query.casefold()).strip()
    compact_query = re.sub(r"[\W_]+", "", normalized_query)
    terms = [term for term in re.split(r"[\s,，。；;、/]+", normalized_query) if len(term) > 1]
    if compact_query and compact_query not in terms:
        terms.append(compact_query)
    lowered = lowered_document or document.casefold()
    compact = compact_document or re.sub(r"[\W_]+", "", lowered)
    direct_at = lowered.find(normalized_query)
    compact_at = compact.find(compact_query) if compact_query else -1
    matched_terms = [term for term in terms if term in lowered or re.sub(r"[\W_]+", "", term) in compact]
    if direct_at < 0 and compact_at < 0 and not matched_terms:
        return 0, ""
    score = (
        1000 + len(compact_query)
        if direct_at >= 0 or compact_at >= 0
        else sum(max(1, len(term)) for term in matched_terms)
    )
    evidence_at = direct_at
    evidence_token = normalized_query
    if evidence_at < 0 and matched_terms:
        evidence_token = matched_terms[0]
        evidence_at = lowered.find(evidence_token)
    if evidence_at < 0:
        return score, "相关字符组合命中，请打开任务卡核对"
    start = max(0, evidence_at - 38)
    end = min(len(document), evidence_at + len(evidence_token) + 58)
    evidence = f"{'…' if start else ''}{document[start:end]}{'…' if end < len(document) else ''}"
    return score, evidence


def task_search_payload(
    query: str, *, project: str = "", work_type: str = "", status: str = ""
) -> dict[str, object]:
    """Search cached task-card text only after the user supplies a query."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:160]
    if not query:
        return {"query": "", "items": []}

    results: list[dict[str, object]] = []
    for record in launcher_task_records(collect_records()):
        if record.get("record_type") != "task_card":
            continue
        if project and str(record.get("project") or "") != project:
            continue
        if work_type and str(record.get("work_type") or "") != work_type:
            continue
        if status and str(record.get("status") or "") != status:
            continue
        document = organization_task_search_document(record)
        score, evidence = _task_search_document_match(query, document)
        if not score:
            continue
        results.append({
            "task_id": str(record.get("task_id") or ""),
            "score": score,
            "evidence": evidence,
        })
    results.sort(key=lambda item: (-int(item["score"]), str(item["task_id"])))
    return {"query": query, "items": results[:230]}


def _home_search_match(query: str, title: str, fields: list[tuple[str, int]]) -> tuple[int, str]:
    """Score one homepage search candidate without preferring an object type."""
    normalized_query = re.sub(r"\s+", " ", query.casefold()).strip()
    compact_query = re.sub(r"[\W_]+", "", normalized_query)
    normalized_title = re.sub(r"\s+", " ", title.casefold()).strip()
    compact_title = re.sub(r"[\W_]+", "", normalized_title)
    if normalized_title == normalized_query or (compact_query and compact_title == compact_query):
        return 5000 + len(compact_query), title
    if normalized_title.startswith(normalized_query) or (compact_query and compact_title.startswith(compact_query)):
        return 4600 + len(compact_query), title
    if normalized_query in normalized_title or (compact_query and compact_query in compact_title):
        return 4200 + len(compact_query), title
    for value, weight in fields:
        normalized = re.sub(r"\s+", " ", str(value or "").casefold()).strip()
        compact = re.sub(r"[\W_]+", "", normalized)
        if normalized_query in normalized or (compact_query and compact_query in compact):
            return weight + len(compact_query), str(value or title)
    terms = [term for term in re.split(r"[\s,，。；;、/]+", normalized_query) if len(term) > 1]
    document = " ".join([normalized_title, *(str(value or "").casefold() for value, _ in fields)])
    compact_document = re.sub(r"[\W_]+", "", document)
    if terms and all(term in document or re.sub(r"[\W_]+", "", term) in compact_document for term in terms):
        return 1400 + sum(len(term) for term in terms), title
    return 0, ""


def _home_task_search_result(
    query: str, record: dict[str, object], *, match_score: int, evidence: str
) -> dict[str, object]:
    task_id = str(record.get("task_id") or "")
    title = str(record.get("task_name") or record.get("title") or task_id)
    title_score, _ = _home_search_match(query, title, [])
    updated = str(record.get("updated_at") or "")
    parsed_updated = parse_sort_datetime(updated)
    return {
        "kind": "task", "kind_label": "任务", "title": title, "task_id": task_id,
        "project": task_scope_title(str(record.get("project") or ""), str(record.get("project_title") or "")),
        "status": STATUS_LABEL.get(str(record.get("status") or ""), str(record.get("status") or "")),
        "updated": format_display_time(updated) or "未记录", "evidence": evidence,
        "score": title_score or 1600 + match_score,
        "sort_epoch": int(parsed_updated.timestamp()) if parsed_updated else 0,
    }


def _home_material_search_result(query: str, material: dict[str, object]) -> dict[str, object] | None:
    title = str(material.get("name") or "资料")
    score, matched_value = _home_search_match(query, title, [
        (str(material.get("relative_path") or ""), 3500),
        (str(material.get("purpose") or ""), 3300),
        (str(material.get("task_title") or ""), 3000),
        (str(material.get("project_title") or ""), 2800),
        (str(material.get("source_locator") or ""), 2400),
    ])
    if not score:
        return None
    kind = str(material.get("kind") or "")
    selection = material.get("selection") if isinstance(material.get("selection"), dict) else {}
    updated = str(material.get("sort_time") or "")
    parsed_updated = parse_sort_datetime(updated)
    preview_url = ""
    if material.get("previewable"):
        delivery = "input" if kind == "input" else str(material.get("subtype") or "")
        preview_url = "/api/library/file-preview?" + urlencode({
            "task_id": str(material.get("task_id") or ""),
            "delivery": delivery,
            "path": str(material.get("relative_path") or ""),
        })
    location = str(material.get("location") or "")
    evidence = " · ".join(value for value in (str(material.get("subtype_label") or ""), location) if value)
    if matched_value and matched_value not in {title, location} and len(matched_value) <= 120:
        evidence = f"{evidence} · {matched_value}" if evidence else matched_value
    return {
        "kind": kind, "kind_label": "交付" if kind == "delivery" else "输入", "title": title,
        "task_id": str(material.get("task_id") or ""), "related_task": str(material.get("task_title") or ""),
        "project": str(material.get("project_title") or ""), "subtype": str(material.get("subtype_label") or ""),
        "updated": str(material.get("updated_at") or "未记录"), "evidence": evidence,
        "purpose": str(material.get("purpose") or ""), "source_locator": str(material.get("source_locator") or ""),
        "preview_url": preview_url, "previewable": bool(material.get("previewable")), "selection": selection,
        "score": score, "sort_epoch": int(parsed_updated.timestamp()) if parsed_updated else 0,
    }


def home_search_payload(query: str) -> dict[str, object]:
    """Return one relevance-ranked homepage list of tasks and registered materials."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:160]
    if not query:
        return {"query": "", "items": []}
    records = {
        str(record.get("task_id") or ""): record
        for record in launcher_task_records(collect_records())
        if record.get("record_type") == "task_card" and record.get("task_id")
    }
    results: list[dict[str, object]] = []
    for match in task_search_payload(query).get("items", []):
        task_id = str(match.get("task_id") or "")
        record = records.get(task_id, {})
        results.append(_home_task_search_result(
            query, record,
            match_score=int(match.get("score") or 0),
            evidence=str(match.get("evidence") or ""),
        ))
    for material in library_material_records():
        result = _home_material_search_result(query, material)
        if result:
            results.append(result)
    results.sort(key=lambda item: (-int(item.get("score") or 0), -int(item.get("sort_epoch") or 0), str(item.get("title") or "").casefold()))
    for item in results:
        item.pop("sort_epoch", None)
    return {"query": query, "items": results[:80]}


def home_search_index_source_revision() -> str:
    """Identify the local task index generation without touching the NAS."""
    try:
        stat = tasks.TASK_INDEX_JSON.stat()
    except OSError:
        return "missing"
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def build_home_search_index() -> dict[str, object]:
    """Build the combined task/material corpus from local workbench caches."""
    task_candidates: list[dict[str, object]] = []
    for record in launcher_task_records(collect_records()):
        if record.get("record_type") != "task_card" or not record.get("task_id"):
            continue
        search_document = organization_task_search_document(record)
        search_lowered = search_document.casefold()
        task_candidates.append({
            "task_id": str(record.get("task_id") or ""),
            "task_name": str(record.get("task_name") or ""),
            "title": str(record.get("title") or ""),
            "project": str(record.get("project") or ""),
            "project_title": str(record.get("project_title") or ""),
            "status": str(record.get("status") or ""),
            "updated_at": str(record.get("updated_at") or ""),
            "search_document": search_document,
            "search_lowered": search_lowered,
            "search_compact": re.sub(r"[\W_]+", "", search_lowered),
        })
    material_fields = (
        "kind", "name", "relative_path", "task_id", "task_title", "project", "project_title",
        "subtype", "subtype_label", "location", "purpose", "source_locator",
        "updated_at", "sort_time", "previewable", "selection",
    )
    materials = [
        {field: material.get(field) for field in material_fields if field in material}
        for material in library_material_records()
    ]
    return {
        "schema_version": HOME_SEARCH_INDEX_SCHEMA,
        "source_revision": home_search_index_source_revision(),
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "tasks": task_candidates,
        "materials": materials,
    }


def _valid_home_search_index(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and int(payload.get("schema_version") or 0) == HOME_SEARCH_INDEX_SCHEMA
        and isinstance(payload.get("tasks"), list)
        and isinstance(payload.get("materials"), list)
    )


def _read_home_search_index() -> dict[str, object] | None:
    try:
        payload = json.loads(HOME_SEARCH_INDEX_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if _valid_home_search_index(payload) else None


def refresh_home_search_index(*, force: bool = False) -> dict[str, object]:
    """Atomically replace the local snapshot; failures leave the last success intact."""
    global _HOME_SEARCH_INDEX_CACHE
    with HOME_SEARCH_INDEX_BUILD_LOCK:
        revision = home_search_index_source_revision()
        if not force:
            current = _read_home_search_index()
            if current and str(current.get("source_revision") or "") == revision:
                with HOME_SEARCH_INDEX_LOCK:
                    _HOME_SEARCH_INDEX_CACHE = current
                return current
        payload: dict[str, object] | None = None
        for _ in range(2):
            started_revision = home_search_index_source_revision()
            candidate = build_home_search_index()
            finished_revision = home_search_index_source_revision()
            if started_revision == finished_revision:
                payload = candidate
                payload["source_revision"] = finished_revision
                break
        if payload is None:
            raise RuntimeError("task index changed repeatedly while building homepage search index")
        tasks.atomic_write(HOME_SEARCH_INDEX_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        with HOME_SEARCH_INDEX_LOCK:
            _HOME_SEARCH_INDEX_CACHE = payload
        return payload


def _home_search_refresh_worker() -> None:
    global _HOME_SEARCH_INDEX_REFRESHING
    try:
        refresh_home_search_index(force=True)
    except Exception as exc:
        print(f"Homepage search index refresh failed; preserving last success: {exc}", file=sys.stderr)
    finally:
        with HOME_SEARCH_INDEX_LOCK:
            _HOME_SEARCH_INDEX_REFRESHING = False


def _schedule_home_search_refresh() -> None:
    global _HOME_SEARCH_INDEX_REFRESHING
    with HOME_SEARCH_INDEX_LOCK:
        if _HOME_SEARCH_INDEX_REFRESHING:
            return
        _HOME_SEARCH_INDEX_REFRESHING = True
    threading.Thread(
        target=_home_search_refresh_worker,
        name="ember-home-search-index",
        daemon=True,
    ).start()


def load_home_search_index() -> dict[str, object]:
    """Return a current snapshot, serving the last success during background refresh."""
    global _HOME_SEARCH_INDEX_CACHE
    revision = home_search_index_source_revision()
    with HOME_SEARCH_INDEX_LOCK:
        cached = _HOME_SEARCH_INDEX_CACHE
    if cached and str(cached.get("source_revision") or "") == revision:
        return cached
    disk = _read_home_search_index()
    if disk and str(disk.get("source_revision") or "") == revision:
        with HOME_SEARCH_INDEX_LOCK:
            _HOME_SEARCH_INDEX_CACHE = disk
        return disk
    stale = cached or disk
    if stale:
        _schedule_home_search_refresh()
        return stale
    return refresh_home_search_index(force=True)


def prime_home_search_index() -> dict[str, object] | None:
    """Load the last snapshot immediately and refresh stale data in the background."""
    global _HOME_SEARCH_INDEX_CACHE
    revision = home_search_index_source_revision()
    with HOME_SEARCH_INDEX_LOCK:
        cached = _HOME_SEARCH_INDEX_CACHE
    if cached and str(cached.get("source_revision") or "") == revision:
        return cached
    disk = _read_home_search_index()
    if disk:
        with HOME_SEARCH_INDEX_LOCK:
            _HOME_SEARCH_INDEX_CACHE = disk
        if str(disk.get("source_revision") or "") == revision:
            return disk
    _schedule_home_search_refresh()
    return disk


def search_home_search_index(query: str, payload: dict[str, object]) -> dict[str, object]:
    """Search one prepared in-memory corpus without file or NAS reads."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:160]
    if not query:
        return {"query": "", "items": []}
    task_matches: list[tuple[int, str, dict[str, object], str]] = []
    for candidate in payload.get("tasks", []):
        if not isinstance(candidate, dict):
            continue
        score, evidence = _task_search_document_match(
            query,
            str(candidate.get("search_document") or ""),
            lowered_document=str(candidate.get("search_lowered") or ""),
            compact_document=str(candidate.get("search_compact") or ""),
        )
        if score:
            task_matches.append((score, str(candidate.get("task_id") or ""), candidate, evidence))
    task_matches.sort(key=lambda item: (-item[0], item[1]))
    results = [
        _home_task_search_result(query, candidate, match_score=score, evidence=evidence)
        for score, _, candidate, evidence in task_matches[:230]
    ]
    for material in payload.get("materials", []):
        if not isinstance(material, dict):
            continue
        result = _home_material_search_result(query, material)
        if result:
            results.append(result)
    results.sort(key=lambda item: (
        -int(item.get("score") or 0),
        -int(item.get("sort_epoch") or 0),
        str(item.get("title") or "").casefold(),
    ))
    for item in results:
        item.pop("sort_epoch", None)
    return {"query": query, "items": results[:80]}


def cached_home_search_payload(query: str) -> dict[str, object]:
    """Serve homepage search from the local combined search snapshot."""
    return search_home_search_index(query, load_home_search_index())


def unified_search_payload(query: str, *, include_external: bool = True) -> dict[str, object]:
    """One read-only retrieval entry over existing indexes, with explicit source health."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:160]
    if not query:
        return {"query": "", "items": [], "providers": [], "read_only": True}
    try:
        local = cached_home_search_payload(query)
        status = home_search_index_status()
        state = str(status.get("state") or "missing")
        provider = {"provider": "gstudio", "state": "available" if state in {"ready", "stale", "refreshing"} and status.get("built_at") else "unavailable", "freshness": "current" if state == "ready" else "stale", "generated_at": status.get("built_at", ""), "message": "" if state == "ready" else "本地索引更新中或不可用；不是零匹配"}
        local_items = list(local.get("items") or [])
    except (OSError, ValueError, RuntimeError):
        local_items = []
        provider = {"provider": "gstudio", "state": "unavailable", "freshness": "unknown", "message": "本地检索失败；不是零匹配"}
    if not include_external:
        return {"query": query, "items": local_items[:80], "providers": [provider], "read_only": True}
    external = system_bridge.external_search(query)
    external_items = list(external["items"])
    for item in external_items:
        item.update({"kind_label": "对标" if item["provider"] == "muse" else "知识", "evidence": item.get("description", ""), "source_locator": item["canonical"], "subtype": item["source_label"], "project": "", "updated": "", "purpose": "通过所属系统按 ID 读取正本；本次仅检索元数据"})
        item["selection"] = dict(item["selection"], query=query)
    # Keep at least one match per available source visible in the compact seven-row popup.
    leading = [next((item for item in external_items if item["provider"] == name), None) for name in ("muse", "ebrain")]
    leading = [item for item in leading if item]
    ordered = local_items[:3] + leading + local_items[3:] + [item for item in external_items if item not in leading]
    return {"query": query, "items": system_bridge.deduplicate(ordered)[:80], "providers": [provider] + external["providers"], "read_only": True}


def cached_library_material_records() -> list[dict[str, object]]:
    """Serve the material browser from the prepared local search snapshot."""
    payload = load_home_search_index()
    return [dict(item) for item in payload.get("materials", []) if isinstance(item, dict)]


def home_search_index_status() -> dict[str, object]:
    """Return lightweight readiness evidence for the prepared search snapshot."""
    with HOME_SEARCH_INDEX_LOCK:
        cached = _HOME_SEARCH_INDEX_CACHE
        refreshing = _HOME_SEARCH_INDEX_REFRESHING
    payload = cached or _read_home_search_index()
    if not payload:
        return {"state": "refreshing" if refreshing else "missing", "refreshing": refreshing}
    current_revision = home_search_index_source_revision()
    source_revision = str(payload.get("source_revision") or "")
    state = "ready" if source_revision == current_revision else "refreshing" if refreshing else "stale"
    return {
        "state": state,
        "refreshing": refreshing,
        "built_at": str(payload.get("built_at") or ""),
        "task_count": len(payload.get("tasks", [])),
        "material_count": len(payload.get("materials", [])),
    }


def _render_library_legacy(token: str, notice: str='', error: str='') -> str:
    from .pages.library import _render_library_legacy as _present
    return _present(token, notice, error)


def _render_library_package_legacy(token: str, notice: str='', error: str='') -> str:
    from .pages.library import _render_library_package_legacy as _present
    return _present(token, notice, error)


def _library_input_item_id(item: dict[str, object], index: int) -> str:
    return str(item.get("id") or f"input-{index + 1}")


def library_material_records() -> list[dict[str, object]]:
    """Build a file-first index while retaining task provenance as metadata."""
    materials: list[dict[str, object]] = []
    for record in library_task_records():
        task_id = str(record.get("task_id") or "")
        task_title = str(record.get("task_name") or record.get("title") or task_id)
        project = str(record.get("project") or "independent")
        project_title = task_scope_title(project, str(record.get("project_title") or ""))
        status = str(record.get("status") or "")
        delivery = record.get("library_delivery") if isinstance(record.get("library_delivery"), dict) else {}
        delivery_key = str(delivery.get("key") or "")
        if delivery_key:
            metadata = _library_delivery_metadata_entries(delivery)
            if metadata is not None:
                payload = _library_flat_metadata_payload(task_id, delivery_key, metadata)
            elif ember_env("EMBER_CENTRAL_MODE") == "1":
                payload = library_flat_files_payload(task_id, delivery_key)
            else:
                payload = None
            for entry in (payload or {}).get("entries", []):
                if not isinstance(entry, dict):
                    continue
                relative_path = str(entry.get("relative_path") or "")
                updated_at = str(entry.get("updated_at") or format_display_time(record.get("updated_at")) or "未记录")
                materials.append({
                    "kind": "delivery", "task_id": task_id, "task_title": task_title,
                    "task_status": status, "project": project, "project_title": project_title,
                    "name": str(entry.get("name") or Path(relative_path).name),
                    "relative_path": relative_path, "suffix": str(entry.get("suffix") or ""),
                    "size": int(entry.get("size") or 0), "updated_at": updated_at,
                    "sort_time": str(entry.get("updated_at") or record.get("updated_at") or ""),
                    "subtype": delivery_key,
                    "subtype_label": "草稿交付" if delivery_key == "draft" else "正式交付",
                    "location": str(Path(relative_path).parent).replace(".", "交付目录", 1),
                    "previewable": True,
                    "selection": {"task_id": task_id, "delivery": delivery_key, "path": relative_path},
                })
        source = task_source(task_id)
        if not source:
            continue
        try:
            parsed = parse_inputs(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            parsed = {"items": []}
        items = parsed.get("items") if isinstance(parsed, dict) else []
        for index, item in enumerate(items if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            item_id = _library_input_item_id(item, index)
            storage = str(item.get("storage") or "reference")
            relative_path = ""
            previewable = False
            if storage == "snapshot":
                recorded_path = str(item.get("path") or "")
                prefix = f"任务资料/{task_id}/"
                relative_path = recorded_path.split(prefix, 1)[-1] if prefix in recorded_path else Path(recorded_path).name
                # Keep the index metadata-only; the preview endpoint resolves
                # and validates the canonical snapshot when it is selected.
                previewable = bool(relative_path)
            name = str(item.get("name") or item.get("source_locator") or "输入资料")
            storage_label = "快照" if storage == "snapshot" else "归档引用" if storage == "archive" else "外部引用"
            materials.append({
                "kind": "input", "task_id": task_id, "task_title": task_title,
                "task_status": status, "project": project, "project_title": project_title,
                "name": name, "relative_path": relative_path,
                "suffix": Path(relative_path or name).suffix.lower(), "size": int(item.get("size") or 0),
                "updated_at": format_display_time(item.get("added_at")) or format_display_time(record.get("updated_at")) or "未记录",
                "sort_time": str(item.get("added_at") or record.get("updated_at") or ""),
                "subtype": storage, "subtype_label": storage_label,
                "location": str(item.get("purpose") or item.get("source_locator") or "未记录用途"),
                "source_locator": str(item.get("source_locator") or ""),
                "purpose": str(item.get("purpose") or ""), "previewable": previewable,
                "selection": {"task_id": task_id, "input_id": item_id},
            })
    materials.sort(key=lambda item: (str(item.get("sort_time") or ""), str(item.get("name") or "").casefold()), reverse=True)
    return materials


def _validated_library_inputs(selections: list[str]) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw in selections:
        try:
            selected = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise ValueError("输入资料选择数据无效。") from None
        task_id = str(selected.get("task_id") or "")
        input_id = str(selected.get("input_id") or "")
        key = (task_id, input_id)
        if key in seen:
            continue
        seen.add(key)
        record = record_map().get(task_id)
        source = task_source(task_id)
        if not record or not source:
            raise ValueError("选择中包含失效的关联任务。")
        try:
            items = parse_inputs(source.read_text(encoding="utf-8")).get("items") or []
        except (OSError, ValueError):
            raise ValueError("关联任务的输入资料登记暂时无法读取。") from None
        matched = None
        for index, item in enumerate(items if isinstance(items, list) else []):
            if isinstance(item, dict) and _library_input_item_id(item, index) == input_id:
                matched = item
                break
        if not matched:
            raise ValueError("选择中包含失效或伪造的输入资料。")
        storage = str(matched.get("storage") or "reference")
        canonical = None
        if storage == "snapshot":
            recorded_path = str(matched.get("path") or "")
            prefix = f"任务资料/{task_id}/"
            relative_path = recorded_path.split(prefix, 1)[-1] if prefix in recorded_path else Path(recorded_path).name
            canonical = task_input_path(task_id, relative_path)
            if not canonical or not canonical.is_file():
                raise ValueError("选择中的输入快照已不可用。")
        sources.append({"task_id": task_id, "input_id": input_id, "item": matched, "record": record, "task_card": source, "canonical": canonical})
    if not sources:
        raise ValueError("请至少选择一条输入资料。")
    return sources


def home_material_context(selections: list[str]) -> list[str]:
    """Validate homepage material selections and describe their canonical sources."""
    deliveries: list[str] = []
    inputs_selected: list[str] = []
    external_selected: list[str] = []
    for raw in selections:
        try:
            selected = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raise ValueError("首页资料选择数据无效。") from None
        if not isinstance(selected, dict):
            raise ValueError("首页资料选择数据无效。")
        if selected.get("provider"):
            external_selected.append(system_bridge.selected_reference(selected, str(selected.get("query") or "")))
        elif selected.get("input_id"):
            inputs_selected.append(json.dumps(selected, ensure_ascii=False))
        elif selected.get("delivery") and selected.get("path"):
            deliveries.append(json.dumps(selected, ensure_ascii=False))
        else:
            raise ValueError("首页资料选择缺少有效来源。")
    lines: list[str] = []
    if external_selected:
        lines.append("- 所选外部资料（只读引用；经所属系统既有接口读取，不复制正本）：")
        lines.extend("  - " + reference for reference in external_selected)
    if deliveries:
        lines.append("- 所选交付文件（只读来源）：")
        lines.extend(f"  {line}" for line in _library_sources_context(_validated_library_sources(deliveries)).splitlines())
    if inputs_selected:
        lines.append("- 所选输入资料（只读来源）：")
        for source in _validated_library_inputs(inputs_selected):
            item = source["item"]
            locator = str(source.get("canonical") or item.get("source_locator") or item.get("path") or "未记录")
            lines.append(
                f"  - {item.get('name') or locator}｜{item.get('storage') or 'reference'}｜关联任务：{source['task_id']}｜locator：{locator}"
            )
    return lines


def create_task_from_inputs_prompt(selections: list[str]) -> str:
    """Build a guarded handoff from registered task inputs without changing them."""
    sources = _validated_library_inputs(selections)
    rows: list[str] = []
    projects: dict[str, str] = {}
    for source in sources:
        record = source["record"]
        item = source["item"]
        project = str(record.get("project") or "independent")
        projects[project] = task_scope_title(project, str(record.get("project_title") or ""))
        locator = str(source.get("canonical") or item.get("source_locator") or item.get("path") or "未记录")
        rows.append(
            f"- {item.get('name') or locator}｜{item.get('storage') or 'reference'}｜关联任务：{source['task_id']}｜locator：{locator}"
        )
    if len(projects) == 1:
        project, title = next(iter(projects.items()))
        routing = f"全部资料来自同一项目：{title}（{project}）；收到目标后再判断继续原任务或建立后续任务。"
    else:
        routing = "资料跨越多个项目；收到目标后必须先询问目标项目，确认前不得建卡。"
    return render_catalog_prompt(
        "library-create-input",
        routing=routing,
        selected_count=len(sources),
        sources="\n".join(rows),
    )


def library_material_forms(token: str, return_to: str) -> list[dict[str, object]]:
    hidden = [("csrf", token), ("return_to", return_to)]
    return [
        {"kind": "delivery", "action": "/actions/create-task-from-deliveries", "hidden": hidden, "label": "用所选交付文件开始处理", "confirm_label": "核对所选交付文件并开始处理"},
        {"kind": "input", "action": "/actions/create-task-from-inputs", "hidden": hidden, "label": "用所选输入资料开始处理", "confirm_label": "核对所选输入资料并开始处理"},
    ]


def render_library(token: str, notice: str='', error: str='') -> str:
    from .pages.library import render_library as _present
    return _present(token, notice, error)


def _mistaken_single_task_layout_draft(token: str, notice: str = "", error: str = "") -> str:
    """Inactive draft retained temporarily so the earlier library renderer remains authoritative."""
    records = library_task_records()
    projects = project_items()
    payload: list[dict[str, object]] = []
    choices: list[str] = []
    for record in records:
        task_id = str(record.get("task_id") or "")
        title = str(record.get("task_name") or record.get("title") or task_id)
        project = str(record.get("project") or "")
        project_title = task_scope_title(project, str(record.get("project_title") or ""))
        status = str(record.get("status") or "")
        work_type = str(record.get("work_type") or "")
        delivery = record.get("library_delivery") if isinstance(record.get("library_delivery"), dict) else {}
        delivery_key = str(delivery.get("key") or "")
        delivery_count = 0
        if delivery.get("path"):
            try:
                root = Path(str(delivery["path"]))
                delivery_count = sum(1 for path in root.rglob("*") if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts))
            except OSError:
                pass
        search_text = organization_task_search_document(record)
        item = {
            "task_id": task_id, "title": title, "project": project,
            "project_title": project_title, "status": status,
            "work_type": work_type, "delivery_key": delivery_key,
            "delivery_name": str(delivery.get("name") or ""),
            "delivery_count": delivery_count,
            "search": base64.b64encode(search_text.lower().encode("utf-8")).decode("ascii"),
        }
        payload.append(item)
        choices.append(
            f'<button class="library-task-choice" type="button" data-library-task-choice '
            f'data-project="{html.escape(project, quote=True)}" data-type="{html.escape(work_type, quote=True)}" '
            f'data-status="{html.escape(status, quote=True)}" data-delivery="{"yes" if delivery_key else "no"}" '
            f'data-search="{item["search"]}" data-task-id="{html.escape(task_id, quote=True)}">'
            f'<span class="library-task-choice-main"><span class="library-task-title">{html.escape(title)}</span>'
            f'<span class="library-task-meta">{html.escape(project_title)} · {delivery_count} 个交付物</span></span>'
            f'<span class="badge {html.escape(status, quote=True)}">{html.escape(STATUS_LABEL.get(status, status))}</span></button>'
        )

    def multi_filter(identifier: str, label: str, values: list[tuple[str, str]]) -> str:
        items = "".join(f'<label><input type="checkbox" value="{html.escape(value, quote=True)}">{html.escape(text)}</label>' for value, text in values)
        return f'<details class="library-multi-filter" data-library-filter="{identifier}" data-label="{html.escape(label, quote=True)}"><summary>{html.escape(label)}</summary><div class="library-multi-filter-menu">{items}</div></details>'

    project_values = sorted({(str(item["project"]), str(item["project_title"])) for item in payload if item["project"]}, key=lambda value: value[1])
    type_values = sorted({(str(item["work_type"]), TYPE_LABEL.get(str(item["work_type"]), str(item["work_type"]))) for item in payload if item["work_type"]}, key=lambda value: value[1])
    status_values = sorted({(str(item["status"]), STATUS_LABEL.get(str(item["status"]), str(item["status"]))) for item in payload if item["status"]}, key=lambda value: value[1])
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    csrf_json = json.dumps(token)
    message = flash_message(notice, error)
    content = message + rf'''
    <style>
    .library-layout{{grid-template-columns:320px minmax(0,1fr)}}
    .library-task-choice{{grid-template-columns:minmax(0,1fr) auto;width:100%;text-align:left}}
    .library-task-choice.selected{{border-color:var(--line);box-shadow:inset 3px 0 0 var(--ink)}}
    .library-workspace{{display:grid;grid-template-rows:minmax(112px,1fr) 7px minmax(0,6fr);min-width:0;min-height:0;overflow:hidden}}
    .library-file-shelf{{display:flex;min-height:0;flex-direction:column;overflow:hidden}}
    .library-file-toolbar{{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:6px 10px;border-bottom:1px solid var(--line-soft)}}
    .library-file-toolbar-copy{{min-width:0}}.library-file-toolbar-copy strong{{display:block;font-size:12px}}.library-file-toolbar-copy span{{color:var(--muted);font-size:9px}}
    .library-ai-actions{{display:flex;flex:0 0 auto}}.library-ai-actions form{{margin:0}}.library-ai-actions .executor-btn{{width:auto;min-width:86px}}
    .library-groups{{display:block;min-height:0;flex:1;overflow:auto;padding:7px}}
    .library-group{{border:0}}.library-group-body{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:4px;padding:0}}
    .library-node.file-selectable{{border:1px solid var(--line-soft);border-radius:6px;background:var(--surface)}}
    .library-preview-column{{display:flex;min-height:0;flex-direction:column;overflow:hidden}}
    .library-preview-column .library-preview-body{{flex:1}}
    .library-preview-divider{{background:var(--line);cursor:row-resize}}
    @media(max-width:850px){{.library-layout{{grid-template-columns:1fr;height:auto}}.library-workspace{{height:760px;grid-template-rows:180px 7px minmax(0,1fr)}}}}
    </style>
    <div class="library-layout">
      <section class="panel library-column library-filter-column">
        <div class="library-column-head"><h1>任务</h1><span class="meta" id="libraryTaskCount"></span></div>
        <div class="library-filter-stack"><div class="search-wrap"><span class="search-icon">⌕</span><input id="libraryTaskSearch" type="search" placeholder="搜索任务卡内容"></div><div class="library-filter-row">{multi_filter("project", "全部项目", project_values)}{multi_filter("type", "全部类型", type_values)}</div><div class="library-filter-row">{multi_filter("status", "全部状态", status_values)}{multi_filter("delivery", "交付物", [("yes", "有交付物"), ("no", "无交付物")])}</div></div>
        <div class="library-task-list" id="libraryTaskList">{''.join(choices) if choices else '<div class="library-empty">暂无任务卡</div>'}</div>
      </section>
      <section class="panel library-workspace" id="libraryWorkspace">
        <section class="library-file-shelf"><div class="library-column-head"><h2 id="libraryFolderTitle">交付文件夹</h2><span class="meta" id="libraryFileCount"></span></div><div class="library-file-toolbar"><div class="library-file-toolbar-copy"><strong>继续处理</strong><span id="libraryFileSelectionMeta">未选择任务</span></div><div class="library-ai-actions"><form method="post" action="/actions/revise-library-files" data-library-revise-form data-execution-confirm data-execution-label="交付文件二次处理"><input type="hidden" name="csrf" value="{html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="/library"><input type="hidden" name="task_id" value="">{execution_confirm_button("核对所选文件并继续处理", disabled=True)}</form></div></div><div class="library-groups" id="libraryGroups"><div class="library-empty">请从左侧选择任务。</div></div></section>
        <div class="library-preview-divider" id="libraryPreviewDivider" role="separator" aria-label="调整交付文件夹高度" aria-orientation="horizontal" tabindex="0"></div>
        <section class="library-preview-column"><div class="library-preview-pane-head"><strong id="libraryFilePreviewTitle">交付文件预览</strong><div class="library-preview-pane-actions"><a class="button ghost" id="libraryTaskDetail" href="/">查看任务卡</a></div></div><div class="library-preview-body" id="libraryFilePreview"><div class="library-preview-placeholder">选择交付文件后在这里预览。</div></div></section>
      </section>
    </div>
    <script id="libraryData" type="application/json">{data_json}</script><script>(()=>{{
      const tasks=JSON.parse(document.getElementById('libraryData').textContent),taskMap=new Map(tasks.map(item=>[item.task_id,item])),csrf={csrf_json};
      const choices=[...document.querySelectorAll('[data-library-task-choice]')],search=document.getElementById('libraryTaskSearch'),filters=[...document.querySelectorAll('[data-library-filter]')],groups=document.getElementById('libraryGroups'),folderTitle=document.getElementById('libraryFolderTitle'),fileCount=document.getElementById('libraryFileCount'),fileTitle=document.getElementById('libraryFilePreviewTitle'),fileBody=document.getElementById('libraryFilePreview'),fileSelectionMeta=document.getElementById('libraryFileSelectionMeta'),taskDetail=document.getElementById('libraryTaskDetail'),forms=[...document.querySelectorAll('[data-library-revise-form]')],workspace=document.getElementById('libraryWorkspace'),divider=document.getElementById('libraryPreviewDivider');
      let activeTaskId='';
      const esc=value=>String(value??'').replace(/[&<>\"]/g,char=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[char]));
      const decode=value=>new TextDecoder().decode(Uint8Array.from(atob(value||''),character=>character.charCodeAt(0)));
      const normalizeSearch=value=>String(value??'').normalize('NFKC').toLowerCase().replace(/[\u200B-\u200D\uFEFF]/g,'').replace(/[‐‑‒–—―﹘﹣－]/g,'-').trim();
      const compactSearch=value=>normalizeSearch(value).replace(/[\s\-_.·,，。:：;；/\\|()[\]{{}}《》【】'"“”‘’]+/g,'');
      function fuzzyContains(document,term){{if(document.includes(term))return true;const haystack=compactSearch(document),needle=compactSearch(term);if(!needle)return true;if(haystack.includes(needle))return true;if(needle.length<2)return false;let first=-1,position=-1;for(const character of needle){{position=haystack.indexOf(character,position+1);if(position<0)return false;if(first<0)first=position}}return position-first+1<=Math.max(needle.length*4,needle.length+10)}}
      const icon=entry=>entry.suffix==='.md'?'M':['.png','.jpg','.jpeg','.webp','.gif'].includes(entry.suffix)?'◇':['.mp4','.mov','.m4v','.webm'].includes(entry.suffix)?'▶':entry.suffix==='.pdf'?'P':'·';
      const filterValues=filter=>[...filter.querySelectorAll('input:checked')].map(input=>input.value);
      function updateFilterLabel(filter){{const values=filterValues(filter),label=filter.dataset.label;filter.querySelector('summary').textContent=values.length?`${{label.replace('全部','')}} · ${{values.length}}项`:label}}
      function filterTasks(){{const terms=normalizeSearch(search.value).split(/\s+/).filter(Boolean);let count=0;choices.forEach(choice=>{{const document=normalizeSearch(decode(choice.dataset.search)),filterMatch=filters.every(filter=>{{const values=filterValues(filter);return !values.length||values.includes(choice.dataset[filter.dataset.libraryFilter])}}),match=terms.every(term=>fuzzyContains(document,term))&&filterMatch;choice.style.display=match?'':'none';if(match)count++}});document.getElementById('libraryTaskCount').textContent=`${{count}} 项`}}
      function updateContinuation(){{const checked=[...document.querySelectorAll('[data-library-file-check]:checked')],values=checked.map(input=>input.value);fileSelectionMeta.textContent=activeTaskId?(values.length?`已选 ${{values.length}} 个交付文件，将优先修改并同步任务卡`:'未选交付文件，将从任务卡继续'): '未选择任务';forms.forEach(form=>{{form.querySelectorAll('input[name="selection"]').forEach(input=>input.remove());form.querySelector('input[name="task_id"]').value=activeTaskId;values.forEach(value=>{{const input=document.createElement('input');input.type='hidden';input.name='selection';input.value=value;form.appendChild(input)}});form.querySelector('button').disabled=!activeTaskId}})}}
      async function selectTask(taskId){{activeTaskId=taskId;const item=taskMap.get(taskId);choices.forEach(choice=>choice.classList.toggle('selected',choice.dataset.taskId===taskId));folderTitle.textContent=`交付文件夹 · ${{item.title}}`;taskDetail.href=`/tasks/${{encodeURIComponent(taskId)}}`;fileTitle.textContent='交付文件预览';fileBody.innerHTML='<div class="library-preview-placeholder">选择上方交付文件后在这里预览。</div>';groups.innerHTML='<div class="library-empty">正在读取交付文件…</div>';if(!item.delivery_key){{groups.innerHTML='<div class="library-empty">当前任务没有交付文件。</div>';fileCount.textContent='0 个文件';updateContinuation();return}}try{{const response=await fetch(`/api/library/directory?task_id=${{encodeURIComponent(taskId)}}&delivery=${{encodeURIComponent(item.delivery_key)}}&flat=1`);if(!response.ok)throw new Error();const data=await response.json();fileCount.textContent=`${{data.entries.length}} 个文件`;groups.innerHTML=data.entries.length?`<section class="library-group"><div class="library-group-body">${{data.entries.map(entry=>`<div class="library-node file-selectable"><input type="checkbox" data-library-file-check value="${{esc(JSON.stringify({{task_id:taskId,delivery:item.delivery_key,path:entry.relative_path}}))}}"><span class="library-node-icon">${{icon(entry)}}</span><button class="library-node-name" type="button" data-library-file-preview="${{esc(entry.relative_path)}}" title="${{esc(entry.relative_path)}}">${{esc(entry.name)}}</button></div>`).join('')}}</div></section>`:'<div class="library-empty">交付文件夹为空。</div>';groups.querySelectorAll('[data-library-file-check]').forEach(input=>input.addEventListener('change',updateContinuation));groups.querySelectorAll('[data-library-file-preview]').forEach(button=>button.addEventListener('click',()=>previewFile(taskId,item.delivery_key,button.dataset.libraryFilePreview)));updateContinuation()}}catch(error){{groups.innerHTML='<div class="library-empty">暂时无法读取交付文件夹。</div>';updateContinuation()}}}}
      function actionForm(data,mode,label){{return `<form method="post" action="/actions/open-library-item"><input type="hidden" name="csrf" value="${{esc(csrf)}}"><input type="hidden" name="return_to" value="/library"><input type="hidden" name="task_id" value="${{esc(data.task_id)}}"><input type="hidden" name="delivery" value="${{esc(data.delivery_key)}}"><input type="hidden" name="path" value="${{esc(data.relative_path)}}"><input type="hidden" name="mode" value="${{esc(mode)}}"><button class="button" type="submit">${{esc(label)}}</button></form>`}}
      async function submitFileAction(form){{const button=form.querySelector('button'),original=button.textContent;button.disabled=true;button.textContent='正在打开…';try{{const response=await fetch(form.action,{{method:'POST',headers:{{Accept:'application/json'}},body:new URLSearchParams(new FormData(form))}}),data=await response.json();if(data.redirect){{location.href=data.redirect;return}}button.textContent=data.error||data.notice||'操作完成'}}catch(error){{button.textContent='打开失败'}}finally{{setTimeout(()=>{{button.disabled=false;button.textContent=original}},1500)}}}}
      async function previewFile(taskId,delivery,path){{fileBody.innerHTML='<div class="library-preview-placeholder">正在加载交付文件…</div>';try{{const response=await fetch(`/api/library/file-preview?task_id=${{encodeURIComponent(taskId)}}&delivery=${{encodeURIComponent(delivery)}}&path=${{encodeURIComponent(path)}}`);if(!response.ok)throw new Error();const data=await response.json();fileTitle.textContent=data.name;let body='';if(data.kind==='markdown'||data.kind==='text')body=`<article class="article md">${{data.body_html||'<p>文件过大或暂时无法读取。</p>'}}</article>`;else if(data.kind==='image')body=`<div class="library-preview-media"><img src="${{esc(data.raw_url)}}" alt="${{esc(data.name)}}"></div>`;else if(data.kind==='video')body=`<div class="library-preview-media"><video src="${{esc(data.raw_url)}}" controls preload="metadata"></video></div>`;else if(data.kind==='audio')body=`<div class="library-preview-media"><audio src="${{esc(data.raw_url)}}" controls preload="metadata"></audio></div>`;else if(data.kind==='pdf')body=`<div class="library-preview-media"><iframe src="${{esc(data.raw_url)}}" title="${{esc(data.name)}}"></iframe></div>`;else body=`<div class="library-file-info"><h3>${{esc(data.name)}}</h3><div class="library-file-meta"><span>类型</span><span>${{esc(data.mime)}}</span><span>大小</span><span>${{Math.max(1,Math.round(data.size/1024)).toLocaleString()}} KB</span><span>更新时间</span><span>${{esc(data.updated_at)}}</span><span>路径</span><span>${{esc(data.relative_path)}}</span></div></div>`;fileBody.innerHTML=body+`<div class="library-file-info"><div class="library-file-actions">${{actionForm(data,'reveal','在 Finder 中显示')}}${{actionForm(data,'open','使用系统应用打开')}}</div></div>`;fileBody.querySelectorAll('form[action="/actions/open-library-item"]').forEach(form=>form.addEventListener('submit',event=>{{event.preventDefault();submitFileAction(form)}}))}}catch(error){{fileBody.innerHTML='<div class="library-preview-placeholder">暂时无法预览该文件。</div>'}}}}
      function setSplit(clientY){{const rect=workspace.getBoundingClientRect(),dividerHeight=7,min=112,max=Math.min(rect.height*.5,rect.height-220),top=Math.max(min,Math.min(max,clientY-rect.top));workspace.style.gridTemplateRows=`${{top}}px ${{dividerHeight}}px minmax(0,1fr)`}}
      divider.addEventListener('pointerdown',event=>{{divider.setPointerCapture(event.pointerId);document.body.classList.add('library-resizing')}});divider.addEventListener('pointermove',event=>{{if(divider.hasPointerCapture(event.pointerId))setSplit(event.clientY)}});divider.addEventListener('pointerup',event=>{{if(divider.hasPointerCapture(event.pointerId))divider.releasePointerCapture(event.pointerId);document.body.classList.remove('library-resizing')}});
      choices.forEach(choice=>choice.addEventListener('click',()=>selectTask(choice.dataset.taskId)));search.addEventListener('input',filterTasks);filters.forEach(filter=>{{updateFilterLabel(filter);filter.querySelectorAll('input').forEach(input=>input.addEventListener('change',()=>{{updateFilterLabel(filter);filterTasks()}}))}});filterTasks();updateContinuation();
    }})();</script>'''
    return _layout("资料浏览", content, token)


def render_weekly(token: str, notice: str='', error: str='', *, mode: str='', review_view: str='', panel: str='') -> str:
    from .pages.common import render_weekly as _present
    return _present(token, notice, error, mode=mode, review_view=review_view, panel=panel)


def render_executors(token: str, section: str='executors', notice: str='', error: str='') -> str:
    from .pages.common import render_executors as _present
    return _present(token, section, notice, error)


def _render_skills_settings(token: str, notice: str='', error: str='') -> str:
    from .pages.setting import _render_skills_settings as _present
    return _present(token, notice, error)


def render_skills(token: str, notice: str='', error: str='') -> str:
    from .pages.skill import render_skills as _present
    return _present(token, notice, error)


def render_agents(token: str, notice: str='', error: str='') -> str:
    from .pages.agent import render_agents as _present
    return _present(token, notice, error)


def render_settings(token: str, notice: str='', error: str='') -> str:
    from .pages.setting import render_settings as _present
    return _present(token, notice, error)


def render_projects(token: str) -> str:
    from .pages.project import render_projects as _present
    return _present(token)


project_entry_locator_kind = project_page.locator_kind
_project_entry_parts = project_page.entry_parts


def project_described_entries(intro: dict[str, object] | None) -> set[str]:
    return {
        row[2] for part in _project_entry_parts(str((intro or {}).get("entries") or ""))
        if isinstance(part, list) for row in part if project_entry_locator_kind(row[2])
    }


def _registered_project_entry_values(project: str) -> dict[str, str]:
    item = project_items().get(project) or {}
    entries = item.get("entries") if isinstance(item.get("entries"), dict) else {}
    environment = current_environment_name()
    result: dict[str, str] = {}
    for key, entry in entries.items():
        if isinstance(entry, dict):
            environments = entry.get("environments") if isinstance(entry.get("environments"), dict) else {}
            value = str(entry.get("value") or environments.get(environment) or "")
        else:
            value = str(entry or "")
        if value:
            result[str(key)] = value
    return result


def render_project_entries(markdown: str, project: str, token: str='', return_to: str='') -> str:
    from .pages.project import render_project_entries as _present
    return _present(markdown, project, token, return_to)


def project_entry_parts_data(markdown: str, project: str, token: str='', return_to: str='') -> list[dict[str, object]]:
    from .pages.project import project_entry_parts_data as _present
    return _present(markdown, project, token, return_to)


def project_asset_cards(project: str, token: str, return_to: str, *, include_actions: bool = True, described_entries: set[str] | None = None) -> str:
    """Render one non-duplicated location row for a project or system."""
    return project_page.location_strip(project_location_strip(project, include_actions=include_actions, described_entries=described_entries))


def project_location_strip(project: str, *, include_actions: bool = True, described_entries: set[str] | None = None) -> dict[str, list] | None:
    item = project_items().get(project)
    if not item:
        return None
    capabilities = set(map(str, item.get("capabilities") or []))
    archive_remote = project_archive_path(project) if "archive" in capabilities else ""
    items: list[dict[str, object]] = [{"label": "说明正本", "value": "余烬 · Ember", "strong": True}]
    actions: list[dict[str, str]] = []
    if archive_remote and archive_remote not in (described_entries or set()):
        items.append({"label": "项目归档", "value": archive_remote, "wide": True})
    entries = item.get("entries") if isinstance(item.get("entries"), dict) else {}
    registered = _registered_project_entry_values(project)
    entry_labels = {"workbench": "工作台", "runtime": "运行系统", "active_wiki": "知识库", "raw": "原始资料", "archive": "项目归档", "writing_workspace": "写作工程", "continuation_task": "既有设定任务"}
    for label in entries:
        if registered.get(str(label)) in (described_entries or set()):
            continue
        target = project_entry_target(project, str(label))
        value = target[1] if target else "当前机器不可用"
        human_label = entry_labels.get(str(label), str(label).replace("_", " ").title())
        if target and target[0] == "url":
            if include_actions:
                actions.append({"href": str(value), "label": f"打开{human_label}"})
        else:
            items.append({"label": human_label, "value": str(value), "wide": True})
    return {"items": items, "actions": actions}


def project_workbench_action(project: str) -> str:
    """Return the registered system workbench as a primary header action."""
    target = project_entry_target(project, "workbench")
    if not target or target[0] != "url":
        return ""
    return f'<a class="button ghost" href="{html.escape(str(target[1]), quote=True)}">打开工作台</a>'


def project_maintenance_records(project: str) -> str:
    """Render the project intro organization history as a maintenance log table."""
    history = load_project_intro_history(project)
    if not history:
        return '<section class="panel maintenance-records"><div class="section-head"><div><div class="eyebrow">MAINTENANCE LOG</div><h2>整理维护记录</h2></div></div><div class="subtitle">暂无整理维护记录。</div></section>'
    rows = []
    for entry in history:
        rnd = entry.get("round", 0)
        ts = html.escape(str(entry.get("timestamp") or "未知时间"))
        source_tasks = [str(t) for t in entry.get("source_tasks", []) or []]
        src = html.escape(f"{len(source_tasks)} 项" if len(source_tasks) > 4 else ", ".join(source_tasks) or "-")
        summary = html.escape(str(entry.get("summary") or ""))
        rows.append(f'<tr><td>R{int(rnd):02d}</td><td>{ts}</td><td>{src}</td><td>{summary}</td></tr>')
    table = f'<div class="table-wrap"><table class="task-table"><thead><tr><th>轮次</th><th>时间</th><th>来源任务</th><th>摘要</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    return f'<section class="panel maintenance-records"><div class="section-head"><div><div class="eyebrow">MAINTENANCE LOG</div><h2>整理维护记录</h2></div><span class="meta">{len(history)} 条</span></div>{table}</section>'


def project_work_entry(project: str, token: str, return_to: str) -> str:
    """Render a single AI maintenance entry with OpenCode and Codex buttons."""
    form = _execution_form('/actions/maintain-project-intro', token, {'project': project, 'return_to': return_to}, '维护项目介绍并确认执行器')
    return f'<div class="project-work-entry compact">{form}</div>'


def _context_section_html(value: object, body: str) -> str:
    from .pages.common import _context_section_html as _present
    return _present(value, body)


def context_overview_details(intro: dict[str, object] | None, *, system: bool = False, project: str = "", token: str = "") -> str:
    """Render the shared project card's overview and meaningful timeline."""
    return project_page.overview(context_overview_data(intro, system=system, project=project, token=token))


def context_overview_data(intro: dict[str, object] | None, *, system: bool=False, project: str='', token: str='') -> dict[str, object]:
    from .pages.common import context_overview_data as _present
    return _present(intro, system=system, project=project, token=token)


def project_intro_card(project: str, token: str, records: list[dict[str, object]] | None = None) -> str:
    """Render the project identity, current focus and AI entry as one header."""
    return project_page.hero(project_hero_data(project, token, records))


def project_hero_data(project: str, token: str, records: list[dict[str, object]] | None=None) -> dict[str, object]:
    from .pages.project import project_hero_data as _present
    return _present(project, token, records)


def _legacy_render_project_tasks(project: str, token: str) -> str | None:
    from .pages.task import _legacy_render_project_tasks as _present
    return _present(project, token)


def _project_task_group(
    title: str,
    records: list[dict[str, object]],
    token: str,
    project: str,
    group_key: str,
    *,
    group: bool = False,
) -> str:
    """Render one grouped task list for the project workspace left pane."""
    empty_label = "暂无任务主线。" if group else "暂无任务。"
    if not records:
        return (
            f'<div class="project-task-group" data-task-group="{html.escape(group_key, quote=True)}">'
            f'<div class="project-task-group-head"><h3>{html.escape(title)}</h3><span>0</span></div>'
            f'<div class="project-task-empty">{html.escape(empty_label)}</div></div>'
        )
    items = []
    important_ids = set(project_priorities().get(project, []))
    for record in records:
        task_id = str(record.get("task_id") or "")
        name = str(record.get("task_name") or record.get("title") or task_id)
        group_tag = task_group_tag(record)
        delivery = resolve_delivery_folder(record)
        artifact_label = (
            "主线索引" if record.get("task_kind") == "task_group"
            else ("有交付文件" if delivery else "无独立交付文件")
        )
        delivery_label_class = "delivery-label has-delivery" if delivery else "delivery-label"
        important = task_id in important_ids
        search_parts = [
            str(record.get("task_name") or ""),
            str(record.get("description") or ""),
            str(record.get("subproject") or ""),
            task_id,
        ]
        search_value = " ".join(search_parts).casefold()
        items.append(
            f'<article class="project-task-row" data-task-search="{html.escape(search_value, quote=True)}" '
            f'data-task-id="{html.escape(task_id, quote=True)}" data-task-group-ref="{html.escape(group_key, quote=True)}" '
            f'data-has-delivery="{"1" if delivery else "0"}">'
            f'<div class="project-task-row-main"><a href="/tasks/{quote(task_id)}">{html.escape(name)}{group_tag}</a>'
            f'<div class="subtitle">{html.escape(str(record.get("description") or ""))}</div></div>'
            f'<div class="project-task-row-meta"><span class="badge {html.escape(str(record.get("status") or ""), quote=True)}">'
            f'{html.escape(STATUS_LABEL.get(str(record.get("status") or ""), str(record.get("status") or "")))}</span>'
            f'<span class="{html.escape(delivery_label_class, quote=True)}">{html.escape(artifact_label)}</span></div></article>'
        )
    return (
        f'<div class="project-task-group" data-task-group="{html.escape(group_key, quote=True)}">'
        f'<div class="project-task-group-head"><h3>{html.escape(title)}</h3><span>{len(records)}</span></div>'
        f'{"".join(items)}</div>'
    )


def _project_task_rows(
    records: list[dict[str, object]],
    token: str,
    project: str,
    *,
    show_artifacts: bool = True,
) -> str:
    """Render a flat, filterable task list for the project workspace left pane."""
    return project_page.task_rows(project_task_row_data(records, project), show_artifacts=show_artifacts)


def project_task_row_data(records: list[dict[str, object]], project: str) -> list[dict[str, object]]:
    from .pages.task import project_task_row_data as _present
    return _present(records, project)


def _record_delivery_key(record: dict[str, object]) -> str:
    """Infer draft/final delivery key from task-card metadata only.

    Avoids filesystem access so the project delivery index renders quickly
    over the NAS SMB mount; the actual directory contents are lazy-loaded on expand.
    """
    declared = str(record.get("delivery_folder") or "")
    if "正式交付" in declared or str(record.get("delivery_state") or "") == "final":
        return "final"
    if "草稿" in declared:
        return "draft"
    for value in record.get("paths", []) or []:
        path = str(value)
        if "正式交付" in path:
            return "final"
        if "草稿" in path:
            return "draft"
    return ""


def project_delivery_items(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Build a metadata-only project delivery index without reading file bodies."""
    items: list[dict[str, object]] = []
    for record in records:
        task_id = str(record.get("task_id") or "")
        delivery_key = _record_delivery_key(record)
        if not delivery_key:
            continue
        # File counts are loaded lazily when the user expands a task directory.
        search_parts = [
            str(record.get("task_name") or record.get("title") or task_id),
            task_id,
        ]
        items.append({
            "task_id": task_id,
            "title": str(record.get("task_name") or record.get("title") or task_id),
            "status": str(record.get("status") or ""),
            "updated_at": str(record.get("updated_at") or ""),
            "delivery_key": delivery_key,
            "file_count": None,
            "folder_count": None,
            "search": " ".join(search_parts).casefold(),
        })
    items.sort(
        key=lambda item: parse_sort_datetime(str(item.get("updated_at") or "")),
        reverse=True,
    )
    return items


def project_delivery_browser(
    project: str,
    records: list[dict[str, object]],
    token: str,
    return_to: str,
) -> tuple[str, dict[str, int | bool]]:
    """Render a fixed-height, lazy project delivery explorer."""
    items = project_delivery_items(records)
    draft_count = sum(item["delivery_key"] == "draft" for item in items)
    final_count = sum(item["delivery_key"] == "final" for item in items)
    indexed = all(item["file_count"] is not None for item in items)
    file_count = sum(int(item["file_count"] or 0) for item in items)
    folder_count = sum(int(item["folder_count"] or 0) for item in items)

    def task_rows(key: str) -> str:
        rows = []
        for item in items:
            if item["delivery_key"] != key:
                continue
            task_id = html.escape(str(item["task_id"]), quote=True)
            title = html.escape(str(item["title"]))
            search = html.escape(str(item["search"]), quote=True)
            file_total = item["file_count"]
            folder_total = item["folder_count"]
            counts = (
                f'{int(file_total or 0)} 个文件 · {int(folder_total or 0)} 个文件夹'
                if file_total is not None else "展开后读取"
            )
            rows.append(
                f'<section class="project-delivery-task" data-project-delivery-task '
                f'data-delivery="{key}" data-task-id="{task_id}" data-search="{search}">'
                f'<div class="project-delivery-task-head">'
                f'<button type="button" class="project-delivery-task-toggle" aria-expanded="false">'
                f'<span class="project-delivery-caret">›</span><span class="project-delivery-folder-icon">📁</span>'
                f'<span class="project-delivery-task-copy"><strong>{title}</strong><small>{html.escape(counts)}</small></span>'
                f'</button><a href="/tasks/{quote(str(item["task_id"]))}">任务详情</a></div>'
                f'<div class="project-delivery-task-children"></div></section>'
            )
        return "".join(rows) or '<div class="project-delivery-empty">暂无交付目录。</div>'

    count_label = f"{file_count} 个文件" if indexed else f"{len(items)} 个任务目录"
    content = f'''<section class="panel project-delivery-browser" id="projectDeliveryBrowser">
      <div class="project-delivery-browser-head"><div class="project-delivery-title"><h2>项目交付</h2></div><input id="projectDeliverySearch" class="project-delivery-search" type="search" placeholder="搜索任务或文件…" aria-label="搜索项目交付"></div>
      <div class="project-delivery-toolbar"><div class="chips" aria-label="筛选交付状态"><button type="button" class="chip active" data-delivery-filter="all">全部</button><button type="button" class="chip" data-delivery-filter="draft">草稿 {draft_count}</button><button type="button" class="chip" data-delivery-filter="final">正式 {final_count}</button></div></div>
      <div class="project-delivery-layout"><div class="project-delivery-tree" id="projectDeliveryTree">
        <section class="project-delivery-state" data-delivery-state="draft"><div class="project-delivery-state-head"><strong>草稿交付</strong><span>{draft_count}</span></div>{task_rows("draft")}</section>
        <section class="project-delivery-state" data-delivery-state="final"><div class="project-delivery-state-head"><strong>正式交付</strong><span>{final_count}</span></div>{task_rows("final")}</section>
        <div class="project-delivery-empty" id="projectDeliveryNoResults" hidden>没有匹配的交付文件。</div>
      </div><section class="project-delivery-preview"><div class="project-delivery-preview-head"><strong id="projectDeliveryPreviewTitle">交付文件预览</strong><div id="projectDeliveryPreviewActions"></div></div><div class="project-delivery-preview-body" id="projectDeliveryPreview"><div class="library-preview-placeholder">从左侧展开任务目录并选择文件。</div></div></section></div>
    </section>'''
    script = r'''<script>(()=>{const params=new URLSearchParams(location.search),browser=document.getElementById('projectDeliveryBrowser');if(!browser)return;const tree=document.getElementById('projectDeliveryTree'),search=document.getElementById('projectDeliverySearch'),preview=document.getElementById('projectDeliveryPreview'),previewTitle=document.getElementById('projectDeliveryPreviewTitle'),previewActions=document.getElementById('projectDeliveryPreviewActions'),empty=document.getElementById('projectDeliveryNoResults'),csrf=__CSRF__,returnTo=__RETURN_TO__;let state=['draft','final'].includes(params.get('delivery_state'))?params.get('delivery_state'):'all';search.value=params.get('delivery_q')||'';const esc=value=>String(value??'').replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));const icon=entry=>entry.suffix==='.md'?'M':['.png','.jpg','.jpeg','.webp','.gif'].includes(entry.suffix)?'◇':['.mp4','.mov','.m4v','.webm'].includes(entry.suffix)?'▶':entry.suffix==='.pdf'?'P':'·';function actionForm(data,mode,label){return `<form method="post" action="/actions/open-library-item"><input type="hidden" name="csrf" value="${esc(csrf)}"><input type="hidden" name="return_to" value="${esc(returnTo)}"><input type="hidden" name="task_id" value="${esc(data.task_id)}"><input type="hidden" name="delivery" value="${esc(data.delivery_key)}"><input type="hidden" name="path" value="${esc(data.relative_path)}"><input type="hidden" name="mode" value="${esc(mode)}"><button class="button" type="submit">${esc(label)}</button></form>`}function fileRow(entry,depth){return `<button type="button" class="project-delivery-file" style="padding-left:${12+depth*15}px" data-project-delivery-file="${esc(entry.relative_path)}"><span>${icon(entry)}</span><span>${esc(entry.name)}</span></button>`}function folderRow(entry,depth){return `<div class="project-delivery-subfolder"><button type="button" class="project-delivery-folder" style="padding-left:${12+depth*15}px" data-project-delivery-folder="${esc(entry.relative_path)}" aria-expanded="false"><span class="project-delivery-caret">›</span><span>📁</span><span>${esc(entry.name)}</span></button><div class="project-delivery-folder-children"></div></div>`}function entryHtml(entries,depth){return entries.length?entries.map(entry=>entry.is_dir?folderRow(entry,depth):fileRow(entry,depth)).join(''):'<div class="project-delivery-tree-message">文件夹为空。</div>'}async function fetchDirectory(taskId,delivery,path=''){const response=await fetch(`/api/library/directory?task_id=${encodeURIComponent(taskId)}&delivery=${encodeURIComponent(delivery)}&path=${encodeURIComponent(path)}`);if(!response.ok)throw new Error();return response.json()}async function toggleTask(button){const task=button.closest('[data-project-delivery-task]'),children=task.querySelector('.project-delivery-task-children'),opening=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(opening));task.classList.toggle('expanded',opening);if(!opening||children.dataset.loaded)return;children.innerHTML='<div class="project-delivery-tree-message">正在读取…</div>';try{const data=await fetchDirectory(task.dataset.taskId,task.dataset.delivery);children.innerHTML=entryHtml(data.entries,0);children.dataset.loaded='1';bindEntries(children,task)}catch(error){children.innerHTML='<div class="project-delivery-tree-message">暂时无法读取目录。</div>'}}async function toggleFolder(button,task){const holder=button.closest('.project-delivery-subfolder'),children=holder.querySelector(':scope > .project-delivery-folder-children'),opening=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(opening));holder.classList.toggle('expanded',opening);if(!opening||children.dataset.loaded)return;children.innerHTML='<div class="project-delivery-tree-message">正在读取…</div>';try{const data=await fetchDirectory(task.dataset.taskId,task.dataset.delivery,button.dataset.projectDeliveryFolder),depth=button.dataset.projectDeliveryFolder.split('/').length;children.innerHTML=entryHtml(data.entries,depth);children.dataset.loaded='1';bindEntries(children,task)}catch(error){children.innerHTML='<div class="project-delivery-tree-message">暂时无法读取目录。</div>'}}async function previewFile(task,path,node){tree.querySelectorAll('.active-file').forEach(item=>item.classList.remove('active-file'));node.classList.add('active-file');preview.innerHTML='<div class="library-preview-placeholder">正在加载文件…</div>';try{const response=await fetch(`/api/library/file-preview?task_id=${encodeURIComponent(task.dataset.taskId)}&delivery=${encodeURIComponent(task.dataset.delivery)}&path=${encodeURIComponent(path)}`);if(!response.ok)throw new Error();const data=await response.json();previewTitle.textContent=data.name;let body='';if(data.kind==='markdown'||data.kind==='text')body=`<article class="article md">${data.body_html||'<p>文件过大或暂时无法读取。</p>'}</article>`;else if(data.kind==='image')body=`<div class="library-preview-media"><img src="${esc(data.raw_url)}" alt="${esc(data.name)}"></div>`;else if(data.kind==='video')body=`<div class="library-preview-media"><video src="${esc(data.raw_url)}" controls preload="metadata"></video></div>`;else if(data.kind==='audio')body=`<div class="library-preview-media"><audio src="${esc(data.raw_url)}" controls preload="metadata"></audio></div>`;else if(data.kind==='pdf')body=`<div class="library-preview-media"><iframe src="${esc(data.raw_url)}" title="${esc(data.name)}"></iframe></div>`;else body=`<div class="library-file-info"><h3>${esc(data.name)}</h3><div class="library-file-meta"><span>类型</span><span>${esc(data.mime)}</span><span>大小</span><span>${Math.max(1,Math.round(data.size/1024)).toLocaleString()} KB</span><span>更新时间</span><span>${esc(data.updated_at)}</span><span>路径</span><span>${esc(data.relative_path)}</span></div></div>`;preview.innerHTML=body;previewActions.innerHTML=actionForm(data,'reveal','Finder 中显示')+actionForm(data,'open','系统应用打开')}catch(error){preview.innerHTML='<div class="library-preview-placeholder">暂时无法预览该文件。</div>'}}function bindEntries(scope,task){scope.querySelectorAll('[data-project-delivery-folder]').forEach(button=>button.addEventListener('click',()=>toggleFolder(button,task)));scope.querySelectorAll('[data-project-delivery-file]').forEach(button=>button.addEventListener('click',()=>previewFile(task,button.dataset.projectDeliveryFile,button)))}function syncUrl(){const next=new URLSearchParams(location.search);search.value.trim()?next.set('delivery_q',search.value.trim()):next.delete('delivery_q');state==='all'?next.delete('delivery_state'):next.set('delivery_state',state);history.replaceState(null,'',location.pathname+(next.size?'?'+next:''))}function filter(){const query=search.value.trim().toLowerCase();let visible=0;tree.querySelectorAll('[data-project-delivery-task]').forEach(task=>{const show=(state==='all'||task.dataset.delivery===state)&&(!query||task.dataset.search.includes(query));task.hidden=!show;if(show)visible++});tree.querySelectorAll('[data-delivery-state]').forEach(group=>{group.hidden=!group.querySelector('[data-project-delivery-task]:not([hidden])')});empty.hidden=visible>0;browser.querySelectorAll('[data-delivery-filter]').forEach(item=>item.classList.toggle('active',item.dataset.deliveryFilter===state));syncUrl()}tree.querySelectorAll('.project-delivery-task-toggle').forEach(button=>button.addEventListener('click',()=>toggleTask(button)));browser.querySelectorAll('[data-delivery-filter]').forEach(button=>button.addEventListener('click',()=>{state=button.dataset.deliveryFilter;filter()}));search.addEventListener('input',filter);filter()})();</script>'''
    script = script.replace("__CSRF__", json.dumps(token)).replace("__RETURN_TO__", json.dumps(return_to))
    styles = '''<style>.project-delivery-browser{overflow:hidden;display:flex;flex-direction:column;height:100%}.project-delivery-browser-head{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 12px;border-bottom:1px solid var(--line);background:var(--surface)}.project-delivery-browser-head h2{margin:0;font-size:14px;font-weight:700}.project-delivery-browser-head .meta{display:none}.project-delivery-search{width:200px;padding:6px 10px;border:1px solid var(--line);border-radius:7px;background:var(--surface);font-size:12px}.project-delivery-search:focus{outline:none;border-color:var(--muted)}.project-delivery-toolbar{flex:0 0 auto;display:flex;flex-wrap:wrap;gap:5px;padding:7px 10px;border-bottom:1px solid var(--line-soft);background:var(--surface)}.project-delivery-toolbar .chip{padding:3px 8px;font-size:11px;font-weight:600;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--secondary);cursor:pointer;transition:all .08s ease}.project-delivery-toolbar .chip:hover{border-color:var(--muted);background:var(--line-soft)}.project-delivery-toolbar .chip.active{border-color:var(--ink);background:var(--ink);color:#fff}.project-delivery-layout{flex:1 1 auto;display:grid;grid-template-columns:minmax(290px,.38fr) minmax(430px,.62fr);min-height:0}.project-delivery-tree,.project-delivery-preview-body{min-height:0;overflow:auto}.project-delivery-tree{padding:7px;background:var(--line-soft);border-right:1px solid var(--line)}.project-delivery-state{margin-bottom:8px;overflow:hidden;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.project-delivery-state-head{display:flex;justify-content:space-between;padding:8px 10px;border-bottom:1px solid var(--line-soft);font-size:10px}.project-delivery-task{border-bottom:1px solid var(--line-soft)}.project-delivery-task:last-child{border-bottom:0}.project-delivery-task-head{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:5px;padding-right:7px}.project-delivery-task-head>a{font-size:9px;white-space:nowrap}.project-delivery-task-toggle{display:grid;grid-template-columns:12px 20px minmax(0,1fr);align-items:center;gap:5px;min-width:0;padding:7px;border:0;background:transparent;color:var(--ink);text-align:left;cursor:pointer}.project-delivery-task-toggle:hover,.project-delivery-file:hover,.project-delivery-folder:hover{background:var(--line-soft)}.project-delivery-task-copy{display:grid;min-width:0}.project-delivery-task-copy strong,.project-delivery-task-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.project-delivery-task-copy strong{font-size:11px}.project-delivery-task-copy small{margin-top:2px;color:var(--muted);font-size:9px}.project-delivery-caret{display:inline-block;color:var(--muted);transition:transform .12s}.project-delivery-task.expanded>.project-delivery-task-head .project-delivery-caret,.project-delivery-subfolder.expanded>.project-delivery-folder .project-delivery-caret{transform:rotate(90deg)}.project-delivery-task-children,.project-delivery-folder-children{display:none}.project-delivery-task.expanded>.project-delivery-task-children,.project-delivery-subfolder.expanded>.project-delivery-folder-children{display:block}.project-delivery-task-children{padding:2px 0 5px;background:var(--line-soft)}.project-delivery-file,.project-delivery-folder{display:grid;grid-template-columns:18px minmax(0,1fr);align-items:center;gap:5px;width:100%;min-height:29px;border:0;background:transparent;color:var(--ink);font-size:10px;text-align:left;cursor:pointer}.project-delivery-folder{grid-template-columns:12px 18px minmax(0,1fr)}.project-delivery-file span:last-child,.project-delivery-folder span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.project-delivery-file.active-file{background:#e7edff;color:#1e3a8a}.project-delivery-tree-message,.project-delivery-empty{padding:10px;color:var(--muted);font-size:10px}.project-delivery-preview{display:flex;min-width:0;min-height:0;flex-direction:column}.project-delivery-preview-head{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:42px;padding:8px 11px;border-bottom:1px solid var(--line-soft)}.project-delivery-preview-head>strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.project-delivery-preview-head>div{display:flex;gap:5px}.project-delivery-preview-head form{margin:0}.project-delivery-preview-head .button{padding:3px 7px;font-size:9px}.project-delivery-preview-body{flex:1}.project-delivery-preview-body>.article{border:0;border-radius:0}.project-page-tabs{display:flex;gap:4px;margin:10px 0;padding:4px;border:1px solid var(--line);border-radius:9px;background:var(--line-soft)}.project-page-tab{padding:7px 12px;border:0;border-radius:6px;background:transparent;color:var(--muted);font-size:11px;font-weight:750;cursor:pointer}.project-page-tab.active{background:var(--surface);color:var(--ink);box-shadow:0 1px 3px rgba(15,23,42,.08)}.project-view-panel[hidden]{display:none!important}.project-delivery-summary{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;margin-top:12px;padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}.project-delivery-summary h2{margin:0 0 3px;font-size:14px}.project-delivery-summary p{margin:0;color:var(--muted);font-size:10px}@media(max-width:800px){.project-delivery-browser-head,.project-delivery-filters{align-items:stretch;flex-direction:column}.project-delivery-filters input{width:100%}.project-delivery-layout{grid-template-columns:1fr;height:auto}.project-delivery-tree{height:360px;border-right:0;border-bottom:1px solid var(--line)}.project-delivery-preview{height:500px}.project-delivery-summary{grid-template-columns:1fr}}</style>'''
    return content + styles + script, {
        "task_count": len(items), "draft_count": draft_count, "final_count": final_count,
        "file_count": file_count, "folder_count": folder_count, "indexed": indexed,
    }


def project_material_browser(
    project: str,
    token: str,
    return_to: str,
) -> tuple[str, int, int]:
    """Embed the shared file-first delivery/input browser for one project."""
    # Like the library page, use the prepared snapshot; rebuilding here probes
    # every task's delivery paths over SMB before the project can be displayed.
    materials = [item for item in cached_library_material_records() if str(item.get("project") or "") == project]
    delivery_count = sum(1 for item in materials if item.get("kind") == "delivery")
    input_count = sum(1 for item in materials if item.get("kind") == "input")
    page = {
        "materials": materials, "project": (project, task_scope_title(project)), "forms": library_material_forms(token, return_to),
        "browser": {"csrf": token, "return_to": return_to, "controller": "EmberProjectMaterialSwitch", "sync_url": False},
    }
    return library_page.pane(page) + f'<script src="/assets/library.js?v={LIBRARY_VERSION}"></script>', delivery_count, input_count


def _render_system_workspace(project: str, item: dict[str, object], records: list[dict[str, object]], token: str) -> str:
    from .pages.common import _render_system_workspace as _present
    return _present(project, item, records, token)


def render_project_tasks(project: str, token: str) -> str | None:
    from .pages.task import render_project_tasks as _present
    return _present(project, token)


def render_project(project: str, token: str, notice: str='', error: str='') -> str | None:
    from .pages.project import render_project as _present
    return _present(project, token, notice, error)


CITATION_RE = re.compile(r"\[\^(GB|T)(\d+)\]")


def _citation_key(kind: str, num: str) -> str:
    return f"{kind}{num}"


def extract_citations(markdown: str) -> dict[str, dict[str, str]]:
    """Extract citation labels [^GB1] / [^T1] and build a lookup table.

    Returns a dict keyed by citation id (e.g. 'GB1', 'T1') with keys:
    - kind: 'GB' or 'T'
    - num:  citation number
    - ref:  the source reference text found in the citation table, if any
    """
    result: dict[str, dict[str, str]] = {}
    for match in CITATION_RE.finditer(markdown):
        kind, num = match.group(1), match.group(2)
        key = _citation_key(kind, num)
        if key not in result:
            result[key] = {"kind": kind, "num": num, "ref": ""}
    # Try to populate ref text from the source table at the bottom of the doc.
    # Look for rows like: | [^GB1] | `yoga-platform.md` |
    table_pattern = re.compile(r"\|\s*\[\^(GB|T)(\d+)\]\s*\|\s*(.*?)\s*\|\s*$", re.MULTILINE)
    for match in table_pattern.finditer(markdown):
        kind, num, ref = match.group(1), match.group(2), match.group(3).strip()
        key = _citation_key(kind, num)
        if key in result:
            result[key]["ref"] = ref
    return result


def _citation_badge(key: str, citation: dict[str, str]) -> str:
    label = f"{citation['kind']}{citation['num']}"
    ref = html.escape(citation.get("ref") or "", quote=True)
    kind_label = "EBrain" if citation["kind"] == "GB" else "任务"
    return f'<sup class="citation" data-ref="{ref}" title="{kind_label} 来源：{ref}">{label}</sup>'


def render_project_intro_markdown(markdown: str, project: str, *, token: str='') -> str:
    from .pages.project import render_project_intro_markdown as _present
    return _present(markdown, project, token=token)


def render_copy_board_markdown(markdown: str) -> str:
    from .pages.common import render_copy_board_markdown as _present
    return _present(markdown)
