#!/usr/bin/env python3
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import fcntl
import html
import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = _deployment_root()
from .path_config import project_archive_roots
from .time_format import now_iso_string, parse_sort_datetime
from .workspace_paths import equivalent_path_strings, shared_task_root
from .task_dashboard import render_task_dashboard
from . import gstudio_publish

SHARED_TASK_ROOT = shared_task_root()
LOCAL_TASK_ROOT = ROOT / "tasks"
TASK_INDEX_ROOT = ROOT / "task-cards"
TASK_INDEX_JSON = TASK_INDEX_ROOT / "index.json"
TASK_DASHBOARD = TASK_INDEX_ROOT / "dashboard.md"
SHARED_TASK_DASHBOARD = SHARED_TASK_ROOT / "任务总览.md"
HTML_TASK_DASHBOARD = SHARED_TASK_ROOT.parent / "管理中心" / "整理记录" / "任务看板" / "index.html"
SOURCE_CACHE_ROOT = TASK_INDEX_ROOT / "source-cache"
SHARED_PROJECT_INDEX_ROOT = SHARED_TASK_ROOT / "项目索引"
SHARED_WORKSPACE_ROOT = SHARED_TASK_ROOT.parent
PROJECTS_CONFIG = ROOT / "config" / "projects.json"
DELIVERY_CACHE_ROOT = SOURCE_CACHE_ROOT / "deliveries"
EXECUTOR_ALIASES = {
    "codex": "codex",
    "opencode": "opencode",
    "kimi": "opencode",
    "kimi code cli": "opencode",
    "external-mcp": "external",
}
NON_MODEL_VALUES = {"single", "single_agent", "direct", "default", "legacy-unspecified"}


def compact_model_family(value: str) -> str:
    """Return a short model family label without inferring from the executor."""
    raw = value.strip().strip("\"'")
    normalized = re.sub(r"[\s_-]+", "", raw).lower()
    non_models = {re.sub(r"[\s_-]+", "", item).lower() for item in NON_MODEL_VALUES}
    executors = {re.sub(r"[\s_-]+", "", item).lower() for item in EXECUTOR_ALIASES}
    if not normalized or normalized in non_models or normalized in executors:
        return ""
    if "deepseek" in normalized:
        return "DeepSeek"
    if "kimi" in normalized or normalized in {"k3", "k2", "kimi3"}:
        return "Kimi"
    if "gpt" in normalized:
        return "GPT"
    return raw


def _history_model(value: str) -> str:
    """Read the model cell from the one legacy pipe-delimited history shape."""
    parts = [part.strip() for part in value.split("|")]
    return parts[2] if len(parts) >= 3 else value.strip()


def _is_subsequence(query: str, text: str) -> bool:
    """Return True if every character of query appears in text in order."""
    query = query.lower()
    text = text.lower()
    index = 0
    for char in query:
        index = text.find(char, index)
        if index == -1:
            return False
        index += 1
    return True


TITLE_OVERRIDES_CONFIG = ROOT / "config" / "task-title-overrides.json"
PROJECT_ARCHIVE_ROOTS = project_archive_roots()
LEDGER_ROW_RE = re.compile(
    r"^\|\s*(20\d{6})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*`?([^|`]+?)`?\s*\|\s*`?([^|`]+?)`?\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def atomic_write(path: Path, text: str) -> None:
    """Replace a generated local file only after the complete payload exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def task_roots() -> list[tuple[str, Path]]:
    return [("icloud", SHARED_TASK_ROOT), ("local", LOCAL_TASK_ROOT)]


def find_task(task_id: str) -> tuple[str, str, Path] | None:
    for label, root in task_roots():
        for state in ("active", "completed"):
            path = root / state / f"{task_id}.md"
            if path.exists():
                return label, state, path
    return None


def frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    return text[4:end], text[end + 5 :]


def prepend_execution_log_entry(text: str, entry: str) -> str:
    """Insert one audit entry directly below the final execution-log heading."""
    value = entry.strip()
    if not value.startswith("-"):
        value = f"- {value}"
    match = re.search(r"^## 执行日志\s*$", text, re.MULTILINE)
    if not match:
        return text.rstrip() + f"\n\n## 执行日志\n\n{value}\n"
    tail = text[match.end():].lstrip("\n")
    revised = text[:match.end()] + f"\n\n{value}\n"
    if tail:
        revised += tail
    return revised


def first_h1(body: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return match.group(1).strip() if match else ""


def first_section_paragraph(body: str) -> str:
    match = re.search(
        r"^##\s+(?:任务目标|当前目标|本轮产出)\s*$\n+(.*?)(?=^##\s+|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    for paragraph in re.split(r"\n\s*\n", match.group(1).strip()):
        value = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
        value = re.sub(r"^[>*-]\s*", "", value).strip()
        if value and not value.startswith("```"):
            return value
    return ""


def short_task_name(title: str, limit: int = 20) -> str:
    value = re.sub(r"^(?:任务卡|自媒体内容任务卡)[：:｜|]\s*", "", title.strip())
    if len(value) <= limit:
        return value
    for separator in ("｜", "：", ":", "，", "。"):
        first = value.split(separator, 1)[0].strip()
        if 4 <= len(first) <= limit:
            return first
    return value[:limit].rstrip()


def cell(value: object, limit: int = 90) -> str:
    text = " ".join(str(value or "").split()).replace("|", "／")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def load_projects() -> dict[str, object]:
    return json.loads(read(PROJECTS_CONFIG))


def load_title_overrides() -> dict[str, str]:
    if not TITLE_OVERRIDES_CONFIG.exists():
        return {}
    data = json.loads(read(TITLE_OVERRIDES_CONFIG))
    return {str(key): str(value) for key, value in data.items()}


def project_registry(
    *, include_legacy_aliases: bool = False
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    by_slug: dict[str, dict[str, object]] = {}
    by_alias: dict[str, dict[str, object]] = {}
    for item in load_projects().get("projects", []):
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", ""))
        by_slug[slug] = item
        aliases = [slug, *item.get("aliases", [])]
        if include_legacy_aliases:
            aliases.extend(item.get("legacy_aliases", []))
        for alias in aliases:
            by_alias[str(alias).strip().lower()] = item
    return by_slug, by_alias


def normalize_project(
    raw: str, *, include_legacy_aliases: bool = False
) -> tuple[str, str, str]:
    _, by_alias = project_registry(include_legacy_aliases=include_legacy_aliases)
    key = raw.strip().lower()
    item = by_alias.get(key)
    if item:
        return str(item["slug"]), str(item["title"]), ""
    scope = load_projects().get("independent_scope", {})
    return (
        str(scope.get("slug") or "independent"),
        str(scope.get("title") or "独立任务"),
        raw.strip() or "无项目归属",
    )


def infer_work_type(fm: str, project: str) -> str:
    current = top_value(fm, "work_type")
    task_id = top_value(fm, "task_id").lower()
    title = top_value(fm, "title").lower()
    identity = f"{task_id} {title}"
    if any(key in identity for key in ("weekly-review", "每周整理", "整理报告")) or "gstudio-weekly" in task_id:
        return "organize"
    if any(key in identity for key in ("archive", "归档")):
        return "archive"
    if current in {"text", "image", "video", "audio", "data", "system", "organize", "archive", "mixed"}:
        return current
    task_types = set(list_value(fm, "task_type"))
    stage = top_value(fm, "current_stage").lower()
    content_format = top_value(fm, "content_format").lower()
    if project == "gstudio":
        return "system"
    if task_types & {"voiceover_tts"} or "tts" in stage:
        return "audio"
    if task_types & {"image_visual_summary"} or content_format == "image":
        return "image"
    if task_types & {"publish_copy", "script_generation", "topic_planning", "project_plan", "shooting_brief", "edit_brief"}:
        return "text"
    if task_types & {"data_review", "social_data_collection"} or content_format in {"data_only", "research"}:
        return "data"
    if task_types & {"transcript_extraction", "subtitle_generation", "reference_analysis", "video_content_analysis", "content_download"} or content_format == "video":
        return "video"
    if content_format == "mixed":
        return "mixed"
    return "text"


def normalize_status(fm: str, state: str) -> str:
    """Resolve canonical status from frontmatter and physical folder.

    The physical folder (state) is the authoritative source of truth:
    - completed/ -> completed
    - active/    -> use explicit frontmatter status if valid, else active

    current_stage is intentionally NOT used to infer status, to avoid confusion
    when a workflow stage (e.g. reviewing, production) is recorded on a task
    that has already been moved to the completed folder.
    """
    if state == "completed":
        return "completed"
    current = top_value(fm, "status")
    if current in {"active", "waiting_user", "blocked", "completed"}:
        return current
    return "active"


def top_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else ""


def nested_block(text: str, parent: str) -> tuple[int, int, str] | None:
    match = re.search(
        rf"^{re.escape(parent)}:\s*$\n((?:  .*(?:\n|$))*)",
        text,
        re.MULTILINE,
    )
    if not match:
        return None
    return match.start(1), match.end(1), match.group(1)


def nested_value(text: str, parent: str, child: str) -> str:
    block = nested_block(text, parent)
    if not block:
        return ""
    match = re.search(rf"^  {re.escape(child)}:\s*(.+?)\s*$", block[2], re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else ""


def nested_list_value(text: str, parent: str, child: str) -> list[str]:
    block = nested_block(text, parent)
    if not block:
        return []
    match = re.search(
        rf"^  {re.escape(child)}:\s*$\n((?:    - .*(?:\n|$))*)",
        block[2],
        re.MULTILINE,
    )
    if not match:
        return []
    values: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:].strip().strip("\"'"))
    return values


def extract_output_paths(text: str) -> list[str]:
    paths = re.findall(r"/(?:Users|Volumes)/[^\"`\n\s，。；：、）\)\]\}]+", text)
    cleaned: list[str] = []
    for path in paths:
        value = path.rstrip(",.;:]，。；：、）)")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def task_files() -> list[tuple[str, str, Path]]:
    seen: dict[str, tuple[str, str, Path]] = {}
    for root_label, root in task_roots():
        if not root.exists():
            continue
        for state in ("active", "completed"):
            for path in sorted((root / state).glob("*.md")):
                # iCloud Documents is canonical and task_roots() scans it first.
                seen.setdefault(path.name, (root_label, state, path))
    return list(seen.values())


def list_value(text: str, key: str) -> list[str]:
    match = re.search(rf"^{re.escape(key)}:\s*$\n((?:  - .*(?:\n|$))*)", text, re.MULTILINE)
    if not match:
        raw = top_value(text, key)
        return [raw] if raw else []
    values: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:].strip().strip("\"'"))
    return values


def task_record(root: str, state: str, path: Path, *, source_text: str | None = None) -> dict[str, object]:
    text = read(path) if source_text is None else source_text
    fm, body = frontmatter(text)
    task_id = top_value(fm, "task_id") or path.stem
    raw_project = top_value(fm, "project")
    project, project_title, inferred_subproject = normalize_project(
        raw_project, include_legacy_aliases=True
    )
    # Historical unknown values remain readable with their former small-pool
    # presentation. New cards are validated against the registry and may not
    # enter this compatibility branch.
    if project == "independent" and raw_project and task_id[:8] < "20260720":
        project, project_title = "small-project-pool", "小项目池"
    title = top_value(fm, "title") or first_h1(body) or top_value(fm, "primary_goal") or task_id
    if title.startswith("自媒体内容任务卡｜") and top_value(fm, "primary_goal"):
        title = top_value(fm, "primary_goal")
    h1 = first_h1(body)
    name_source = title
    if h1 and not h1.startswith("自媒体内容任务卡｜") and 4 <= len(h1) <= 30 and len(h1) < len(title):
        name_source = h1
    description = top_value(fm, "description") or top_value(fm, "primary_goal") or first_section_paragraph(body) or title
    updated_at = top_value(fm, "updated_at") or nested_value(fm, "workflow_lock", "last_read_at")
    delivery_folder = nested_value(fm, "delivery", "folder")
    raw_model = top_value(fm, "execution_model") or top_value(fm, "primary_model")
    executor = top_value(fm, "executor")
    normalized = raw_model.strip().strip('"').lower()
    if not executor and normalized in EXECUTOR_ALIASES:
        executor = EXECUTOR_ALIASES[normalized]
        raw_model = ""
    elif normalized in NON_MODEL_VALUES:
        raw_model = ""
    execution_models: list[str] = []
    for item in list_value(fm, "model_history"):
        candidate = _history_model(item)
        if compact_model_family(candidate) and candidate.casefold() not in {
            value.casefold() for value in execution_models
        }:
            execution_models.append(candidate)
    for candidate in [*list_value(fm, "execution_models"), raw_model]:
        if compact_model_family(candidate) and candidate.casefold() not in {
            value.casefold() for value in execution_models
        }:
            execution_models.append(candidate)
    model_families: list[str] = []
    for item in execution_models:
        family = compact_model_family(item)
        if family and family not in model_families:
            model_families.append(family)
    return {
        "record_type": "task_card",
        "task_card_type": top_value(fm, "type") or "media_content_task",
        "task_id": task_id,
        "project": project,
        "project_title": project_title,
        "source_project": raw_project,
        "subproject": top_value(fm, "subproject") or inferred_subproject,
        "title": title,
        "task_name": load_title_overrides().get(task_id) or short_task_name(name_source),
        "description": description,
        "status": normalize_status(fm, state),
        "execution_mode": top_value(fm, "execution_mode") or "custom",
        "system_boundary": top_value(fm, "system_boundary") or "gstudio",
        "writeback_status": top_value(fm, "writeback_status") or "",
        "delivery_state": top_value(fm, "delivery_state") or "",
        "assigned_agent": top_value(fm, "assigned_agent"),
        "role_lane": top_value(fm, "role_lane"),
        "root": root,
        "state": state,
        "canonical_path": str(path),
        "ledger_path": "",
        "seq": "",
        "account": top_value(fm, "account"),
        "platform": top_value(fm, "platform"),
        "work_type": infer_work_type(fm, project),
        "task_kind": top_value(fm, "task_kind"),
        "artifact_mode": top_value(fm, "artifact_mode") or ("delivery" if delivery_folder else ""),
        "external_system": nested_value(fm, "external", "system"),
        "external_correlation_id": nested_value(fm, "external", "correlation_id"),
        "external_job_id": nested_value(fm, "external", "job_id"),
        "external_state": nested_value(fm, "external", "state"),
        "output_owner": nested_value(fm, "outputs", "owner"),
        "canonical_paths": nested_list_value(fm, "outputs", "canonical_paths"),
        "external_validations": nested_list_value(fm, "outputs", "validations"),
        # related_task_ids is the single-source task-group relation. Keep the
        # legacy field readable until existing cards have been migrated.
        "related_task_ids": list_value(fm, "related_task_ids") or list_value(fm, "member_task_ids"),
        "executor": executor,
        # primary_model remains a read-only compatibility alias. Executor-like
        # and routing-mode values are intentionally not presented as models.
        "execution_model": raw_model,
        "execution_models": execution_models,
        "model_families": model_families,
        "skills_used": list_value(fm, "skills_used"),
        "content_format": top_value(fm, "content_format"),
        "task_type": list_value(fm, "task_type"),
        "paths": extract_output_paths(fm),
        "updated_at": updated_at,
        "created_at": top_value(fm, "created_at"),
        "delivery_folder": delivery_folder,
        "next_action": "; ".join(list_value(nested_block(fm, "workflow_lock")[2], "next_allowed_actions")) if nested_block(fm, "workflow_lock") else "",
    }


def ledger_files() -> list[tuple[str, Path]]:
    ledgers: list[tuple[str, Path]] = []
    for project, root in PROJECT_ARCHIVE_ROOTS.items():
        base = root / "发布归档"
        if not base.exists():
            continue
        for pattern in ("20[0-9][0-9][0-1][0-9]_发布记录表.md", "20[0-9][0-9]/*月/*发布记录表.md"):
            for path in sorted(base.glob(pattern)):
                ledgers.append((project, path))
    return ledgers


def parse_ledger_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for project, path in ledger_files():
        in_records = False
        for line in read(path).splitlines():
            if line.strip() == "## 发布记录":
                in_records = True
                continue
            if in_records and line.startswith("## "):
                break
            if not in_records:
                continue
            match = LEDGER_ROW_RE.match(line)
            if not match:
                continue
            seq, status, publish_date, account, platform, content_format, title, copy_path, archive_path, publish_link, metrics, notes = [
                part.strip() for part in match.groups()
            ]
            if seq == "---":
                continue
            state = "completed" if status in {"已归档", "已复盘"} else "active"
            task_id = f"ledger-{project}-{seq}"
            normalized_project, project_title, inferred_subproject = normalize_project(project)
            records.append({
                "record_type": "ledger_row",
                "task_id": task_id,
                "project": normalized_project,
                "project_title": project_title,
                "source_project": project,
                "subproject": inferred_subproject,
                "title": title,
                "task_name": short_task_name(title),
                "description": notes or title,
                "status": status,
                "execution_mode": "ledger_only",
                "system_boundary": "gstudio",
                "writeback_status": "not_required",
                "delivery_state": "archived" if status in {"已归档", "已复盘"} else "none",
                "assigned_agent": "production-operator",
                "role_lane": "archive",
                "root": "ledger",
                "state": state,
                "canonical_path": "",
                "ledger_path": str(path),
                "seq": seq,
                "publish_date": publish_date,
                "account": account,
                "platform": platform,
                "content_format": content_format,
                "task_type": ["publish_archive"],
                "paths": [p for p in [copy_path, archive_path] if p and p not in {"待补", "待归档"}],
                "publish_link": publish_link,
                "metrics": metrics,
                "notes": notes,
                "updated_at": "",
                "next_action": notes if status not in {"已归档", "已复盘"} else "",
            })
    return records


def parse_publish_records() -> list[dict[str, object]]:
    """Expose shared publish-workbench records as task-like index records."""
    records: list[dict[str, object]] = []
    for item in gstudio_publish.list_records():
        project = str(item.get("project") or "")
        normalized_project, project_title, inferred_subproject = normalize_project(project)
        release_id = str(item.get("release_id") or "")
        status = str(item.get("status") or "ready")
        completed = status in {"archived", "rejected"}
        material = str(item.get("material_path") or "")
        archive_uri = str(item.get("archive_uri") or "")
        records.append({
            "record_type": "release_record",
            "task_id": f"release-{project}-{release_id}",
            "release_id": release_id,
            "project": normalized_project,
            "project_title": project_title,
            "source_project": project,
            "subproject": inferred_subproject,
            "title": str(item.get("topic") or release_id),
            "task_name": short_task_name(str(item.get("topic") or release_id)),
            "description": f"{item.get('platform') or '未记录平台'} · {item.get('account') or '未记录账号'}",
            "status": status,
            "execution_mode": "ledger_only",
            "system_boundary": "gstudio",
            "writeback_status": "not_required",
            "delivery_state": "archived" if status == "archived" else "none",
            "root": "publish_workbench",
            "state": "completed" if completed else "active",
            "canonical_path": "",
            "ledger_path": str(item.get("ledger_path") or ""),
            "seq": release_id,
            "publish_date": str(item.get("published_at") or ""),
            "account": str(item.get("account") or ""),
            "platform": str(item.get("platform") or ""),
            "content_format": "",
            "work_type": "archive",
            "task_type": ["publish_archive"],
            "paths": [path for path in (material, archive_uri) if path],
            "publish_link": "",
            "metrics": "",
            "notes": "",
            "updated_at": str(item.get("updated_at") or ""),
            "created_at": str(item.get("created_at") or ""),
            "next_action": "" if completed else gstudio_publish.STATUS_LABELS.get(status, status),
        })
    return records


def current_project_titles(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Resolve display names from the registry without rewriting cached evidence."""
    projects, _ = project_registry()
    return [
        {**record, "project_title": projects[str(record.get("project"))]["title"]}
        if isinstance(record, dict) and str(record.get("project")) in projects else record
        for record in records
    ]


def load_index() -> list[dict[str, object]]:
    if not TASK_INDEX_JSON.exists():
        return []
    data = json.loads(read(TASK_INDEX_JSON))
    if isinstance(data, dict):
        records = data.get("records", [])
        return current_project_titles(records) if isinstance(records, list) else []
    return current_project_titles(data) if isinstance(data, list) else []


def write_record_mirror(record: dict[str, object]) -> None:
    state = str(record.get("state") or "active")
    target = TASK_INDEX_ROOT / state / f"{record['task_id']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"record_type: {record.get('record_type', '')}",
        f"task_id: {record.get('task_id', '')}",
        f"project: {record.get('project', '')}",
        f"status: {record.get('status', '')}",
        f"execution_mode: {record.get('execution_mode', '')}",
        f"delivery_state: {record.get('delivery_state', '')}",
        f"writeback_status: {record.get('writeback_status', '')}",
        f"canonical_path: {record.get('canonical_path', '')}",
        f"ledger_path: {record.get('ledger_path', '')}",
        "---",
        "",
        f"# {record.get('title') or record.get('task_id')}",
        "",
        f"- task_id: `{record.get('task_id')}`",
        f"- type: `{record.get('record_type')}`",
        f"- status: `{record.get('status')}`",
        f"- project: `{record.get('project')}`",
        f"- work_type: `{record.get('work_type')}`",
    ]
    if record.get("seq"):
        lines.append(f"- ledger seq: `{record.get('seq')}`")
    if record.get("canonical_path"):
        lines.append(f"- canonical task: `{record.get('canonical_path')}`")
    if record.get("ledger_path"):
        lines.append(f"- ledger: `{record.get('ledger_path')}`")
    paths = record.get("paths") or []
    if isinstance(paths, list) and paths:
        lines += ["", "## Paths", ""]
        lines += [f"- `{path}`" for path in paths]
    write(target, "\n".join(lines) + "\n")


def render_dashboard(records: list[dict[str, object]]) -> str:
    active = [r for r in records if r.get("state") == "active"]
    completed = [r for r in records if r.get("state") == "completed"]
    ledger = [r for r in records if r.get("record_type") == "ledger_row"]
    lines = [
        "# 余烬 · Ember 任务总览",
        "",
        f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- 全部记录：{len(records)}",
        f"- 活跃/待处理：{len(active)}",
        f"- 已完成：{len(completed)}",
        f"- 发布流水记录：{len(ledger)}",
        "",
        "## 按项目进入",
        "",
    ]
    by_slug, _ = project_registry()
    for slug, item in by_slug.items():
        project_records = [r for r in records if r.get("project") == slug]
        if not project_records and slug == "gstudio":
            continue
        index_path = SHARED_PROJECT_INDEX_ROOT / f"{slug}-任务索引.md"
        board = item.get("project_card") or item.get("copy_board")
        board_link = f" · [项目看板](<{SHARED_WORKSPACE_ROOT / str(board)}>)" if board else ""
        lines.append(f"- [{item['title']}](<{index_path}>)：{len(project_records)} 条{board_link}")
    independent_records = [r for r in records if r.get("project") == "independent"]
    if independent_records:
        lines.append(f"- 独立任务：{len(independent_records)} 条（不属于正式项目）")
    lines += ["", "## 当前需要关注", "", "| 任务名称 | 任务描述 | 项目 | 状态 | 类型 |", "|---|---|---|---|---|"]
    for record in active[:80]:
        name = cell(record.get("task_name"), 24)
        description = cell(record.get("description"))
        lines.append(f"| [{name}](<{record.get('canonical_path')}>) | {description} | {record.get('project_title')} | {record.get('status')} | {record.get('work_type')} |")
    return "\n".join(lines) + "\n"


WORK_TYPE_TITLES = {
    "text": "文字", "image": "图片", "video": "视频", "audio": "音频",
    "data": "数据", "system": "系统", "mixed": "混合",
}


def render_project_index(slug: str, item: dict[str, object], records: list[dict[str, object]]) -> str:
    lines = [f"# {item['title']}｜任务索引", "", f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    board = item.get("project_card") or item.get("copy_board")
    if board:
        lines += [f"- [打开项目看板](<{SHARED_WORKSPACE_ROOT / str(board)}>)", ""]
    for status, status_title in (("active", "进行中"), ("completed", "最近完成")):
        subset = [r for r in records if r.get("project") == slug and r.get("status") == status]
        if status == "completed":
            subset = sorted(subset, key=lambda r: str(r.get("updated_at") or r.get("task_id")), reverse=True)[:60]
        lines += [f"## {status_title}", ""]
        if not subset:
            lines += ["_无_", ""]
            continue
        for work_type, work_title in WORK_TYPE_TITLES.items():
            typed = [r for r in subset if r.get("work_type") == work_type]
            if not typed:
                continue
            lines += [f"### {work_title}", "", "| 任务名称 | 任务描述 | 更新时间 |", "|---|---|---|"]
            for record in typed:
                subproject = f"【{record.get('subproject')}】" if record.get("subproject") else ""
                name = cell(record.get("task_name"), 24)
                description = cell(record.get("description"))
                lines.append(f"| {subproject}[{name}](<{record.get('canonical_path')}>) | {description} | {record.get('updated_at', '')} |")
            lines.append("")
    return "\n".join(lines) + "\n"


def sync_index_records(
    *,
    publish_shared: bool = True,
    expected_task_count: int | None = None,
    sync_delivery_metadata: bool = True,
) -> list[dict[str, object]]:
    """Refresh the local workbench cache and optionally shared static indexes.

    Background cross-machine refreshes pass ``publish_shared=False`` so both
    Macs never compete to rewrite shared generated pages. Task gates keep the
    historical default and may publish those shared navigation files.
    """
    records = [task_record(root, state, path) for root, state, path in task_files()]
    publish_records = parse_publish_records()
    publish_keys = {(str(item.get("project") or ""), str(item.get("seq") or "")) for item in publish_records}
    records.extend(item for item in parse_ledger_records() if (str(item.get("project") or ""), str(item.get("seq") or "")) not in publish_keys)
    records.extend(publish_records)
    records.sort(key=lambda item: (str(item.get("state")), str(item.get("project")), str(item.get("task_id"))))
    task_count = sum(record.get("record_type") == "task_card" for record in records)
    if expected_task_count is not None and task_count != expected_task_count:
        raise RuntimeError(
            "任务索引源数量不一致，拒绝覆盖最近成功缓存："
            f"预期 {expected_task_count}，实际读取 {task_count}"
        )
    _write_index_records(records, publish_shared=publish_shared)
    for record in records:
        write_record_mirror(record)

    # Login LaunchAgents cannot reliably traverse iCloud Documents under macOS
    # privacy controls. Keep a generated, read-only local source cache for the
    # loopback workbench; canonical Markdown remains the only writable truth.
    for record in records:
        if record.get("record_type") != "task_card":
            continue
        source = Path(str(record.get("canonical_path") or ""))
        if source.exists():
            target = SOURCE_CACHE_ROOT / "tasks" / str(record.get("state") or "active") / f"{record['task_id']}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            write(target, read(source))
    for slug in project_registry()[0]:
        source = SHARED_WORKSPACE_ROOT / "项目" / slug / "项目看板.md"
        if source.exists():
            target = SOURCE_CACHE_ROOT / "projects" / slug / "项目看板.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            write(target, read(source))
    report_cache = SOURCE_CACHE_ROOT / "organization-reports"
    report_cache.mkdir(parents=True, exist_ok=True)
    for record in records:
        if record.get("record_type") != "task_card" or record.get("work_type") != "organize":
            continue
        report_candidates: list[tuple[int, Path]] = []
        delivery = str(record.get("delivery_folder") or "").strip()
        if delivery:
            report_candidates.append((100, SHARED_WORKSPACE_ROOT / delivery / "整理报告.md"))
        for value in record.get("paths", []) or []:
            for translated in equivalent_path_strings(Path(str(value)).expanduser()):
                candidate = Path(translated).expanduser()
                name = candidate.name.lower()
                score = 90 if "completion-report" in name or "完成报告" in name else 85 if "整理报告" in name else 65 if "整理建议" in name else 0
                if score:
                    report_candidates.append((score, candidate))
        readable = [(score, path) for score, path in report_candidates if path.is_file()]
        if readable:
            readable.sort(key=lambda item: item[0], reverse=True)
            write(report_cache / f"{record['task_id']}.md", read(readable[0][1]))
    if sync_delivery_metadata:
        sync_delivery_cache(records)
    return records


def _write_index_records(records: list[dict[str, object]], *, publish_shared: bool = False) -> None:
    """Atomically replace the local index from already parsed records."""
    records.sort(key=lambda item: (str(item.get("state")), str(item.get("project")), str(item.get("task_id"))))
    TASK_INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    (TASK_INDEX_ROOT / "active").mkdir(exist_ok=True)
    (TASK_INDEX_ROOT / "completed").mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "record_count": len(records),
        "records": records,
    }
    atomic_write(TASK_INDEX_JSON, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write(TASK_DASHBOARD, render_dashboard(records))
    if publish_shared:
        _publish_shared_index_views(records)


def _publish_shared_index_views(records: list[dict[str, object]]) -> None:
    """Publish compatibility navigation from local records without rereading cards."""
    by_slug, _ = project_registry()
    SHARED_PROJECT_INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    write(SHARED_TASK_DASHBOARD, render_dashboard(records))
    HTML_TASK_DASHBOARD.parent.mkdir(parents=True, exist_ok=True)
    project_boards = {
        slug: f"http://127.0.0.1:8765/projects/{slug}/copy"
        for slug, item in by_slug.items()
        if "copy_board" in set(map(str, item.get("capabilities") or []))
    }
    write(
        HTML_TASK_DASHBOARD,
        render_task_dashboard(records, project_order=list(by_slug), project_boards=project_boards),
    )
    for slug, item in by_slug.items():
        write(SHARED_PROJECT_INDEX_ROOT / f"{slug}-任务索引.md", render_project_index(slug, item, records))


def _task_path_context(path: Path) -> tuple[str, str]:
    resolved = path.resolve(strict=False)
    state = resolved.parent.name
    if state not in {"active", "completed"}:
        raise RuntimeError(f"任务卡不在 active/completed 目录：{path}")
    for label, root in task_roots():
        try:
            resolved.relative_to(root.resolve(strict=False))
            return label, state
        except ValueError:
            continue
    raise RuntimeError(f"任务卡不在已登记任务根目录：{path}")


class LocalIndexError(RuntimeError):
    """The local parsed index is missing or cannot support an incremental update."""


def _load_index_strict() -> list[dict[str, object]]:
    if not TASK_INDEX_JSON.is_file():
        raise LocalIndexError("本地任务索引缺失")
    try:
        payload = json.loads(read(TASK_INDEX_JSON))
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
        raise LocalIndexError(f"本地任务索引不可读：{exc}") from exc
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise LocalIndexError("本地任务索引不可读")
    return [item for item in records if isinstance(item, dict)]


def _sync_changed_source_cache(records: list[dict[str, object]], task_ids: set[str]) -> None:
    for task_id in task_ids:
        for state in ("active", "completed"):
            (SOURCE_CACHE_ROOT / "tasks" / state / f"{task_id}.md").unlink(missing_ok=True)
            (TASK_INDEX_ROOT / state / f"{task_id}.md").unlink(missing_ok=True)
    for record in records:
        if record.get("record_type") != "task_card" or str(record.get("task_id") or "") not in task_ids:
            continue
        write_record_mirror(record)
        source = Path(str(record.get("canonical_path") or ""))
        if source.is_file():
            target = SOURCE_CACHE_ROOT / "tasks" / str(record.get("state") or "active") / f"{record['task_id']}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            write(target, read(source))


def sync_changed_task_records(
    changed_paths: list[Path],
    *,
    removed_task_ids: set[str] | None = None,
    expected_task_count: int | None = None,
    publish_shared: bool = False,
    sync_delivery_metadata: bool = True,
) -> list[dict[str, object]]:
    """Update only changed canonical cards inside an existing healthy index."""
    current = _load_index_strict()
    removed = set(removed_task_ids or set())
    changed_records: list[dict[str, object]] = []
    for path in changed_paths:
        label, state = _task_path_context(path)
        changed_records.append(task_record(label, state, path))
    touched_ids = removed | {str(record.get("task_id") or "") for record in changed_records}
    records = [
        record for record in current
        if not (record.get("record_type") == "task_card" and str(record.get("task_id") or "") in touched_ids)
    ]
    records.extend(changed_records)
    task_count = sum(record.get("record_type") == "task_card" for record in records)
    if expected_task_count is not None and task_count != expected_task_count:
        raise RuntimeError(
            "任务索引源数量不一致，拒绝增量替换："
            f"预期 {expected_task_count}，实际 {task_count}"
        )
    _write_index_records(records, publish_shared=publish_shared)
    _sync_changed_source_cache(records, touched_ids)
    if sync_delivery_metadata:
        sync_delivery_cache_tasks(records, touched_ids)
    return records


def sync_delivery_cache(records: list[dict[str, object]]) -> dict[str, int]:
    """Serialize and rebuild the metadata-only delivery view.

    Foreground task gates and the background index daemon both call this
    function.  They must share a lock because the cache rebuild swaps the same
    staging and live directories; overlapping writers can otherwise remove a
    directory while the other writer is still traversing it.
    """
    lock_path = DELIVERY_CACHE_ROOT.parent / ".delivery-cache-sync.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _sync_delivery_cache_unlocked(records)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def sync_delivery_cache_tasks(records: list[dict[str, object]], task_ids: set[str]) -> dict[str, int]:
    """Refresh delivery metadata only for the changed task IDs."""
    lock_path = DELIVERY_CACHE_ROOT.parent / ".delivery-cache-sync.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        indexed = skipped = 0
        try:
            for task_id in task_ids:
                for key in ("draft", "final"):
                    target = DELIVERY_CACHE_ROOT / key / task_id
                    if target.exists():
                        shutil.rmtree(target)
            by_id = {
                str(record.get("task_id") or ""): record
                for record in records
                if record.get("record_type") == "task_card"
            }
            for task_id in task_ids:
                record = by_id.get(task_id)
                delivery = str((record or {}).get("delivery_folder") or "").strip()
                key = "final" if "正式交付" in delivery else "draft" if "草稿" in delivery else ""
                if not record or not delivery or not key:
                    continue
                source = (SHARED_WORKSPACE_ROOT / delivery).resolve()
                if not source.is_dir() or source.name != task_id:
                    continue
                target_root = DELIVERY_CACHE_ROOT / key / task_id
                target_root.mkdir(parents=True, exist_ok=True)
                entries: list[dict[str, object]] = []
                try:
                    paths = list(source.rglob("*"))
                except OSError:
                    skipped += 1
                    continue
                for path in paths:
                    relative = path.relative_to(source)
                    if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
                        skipped += 1
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        skipped += 1
                        continue
                    entries.append({
                        "name": path.name,
                        "relative_path": relative.as_posix(),
                        "is_dir": path.is_dir(),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "suffix": path.suffix.lower(),
                    })
                    indexed += 1
                write(target_root / ".gstudio-metadata.json", json.dumps({
                    "version": 1,
                    "task_id": task_id,
                    "delivery_key": key,
                    "entries": entries,
                }, ensure_ascii=False, indent=2) + "\n")
            return {"indexed": indexed, "copied": 0, "skipped": skipped}
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _sync_delivery_cache_unlocked(records: list[dict[str, object]]) -> dict[str, int]:
    """Build a metadata-only delivery view for the loopback LaunchAgent.

    The web service may not be allowed to traverse a mounted network volume.
    Keep names, hierarchy, sizes, and timestamps locally without copying file
    contents across SMB. Preview and open actions resolve the canonical shared
    source only when the user requests a specific file.
    """
    staging = SOURCE_CACHE_ROOT / "deliveries-next"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    indexed = skipped = 0
    for record in records:
        if record.get("record_type") != "task_card":
            continue
        task_id = str(record.get("task_id") or "")
        delivery = str(record.get("delivery_folder") or "").strip()
        if not task_id or not delivery:
            continue
        key = "final" if "正式交付" in delivery else "draft" if "草稿" in delivery else ""
        if not key:
            continue
        source = (SHARED_WORKSPACE_ROOT / delivery).resolve()
        if not source.is_dir() or source.name != task_id:
            continue
        target_root = staging / key / task_id
        target_root.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, object]] = []
        try:
            paths = list(source.rglob("*"))
        except OSError:
            skipped += 1
            continue
        for path in paths:
            relative = path.relative_to(source)
            if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
                skipped += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                skipped += 1
                continue
            entries.append({
                "name": path.name,
                "relative_path": relative.as_posix(),
                "is_dir": path.is_dir(),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "suffix": path.suffix.lower(),
            })
            indexed += 1
        write(target_root / ".gstudio-metadata.json", json.dumps({
            "version": 1,
            "task_id": task_id,
            "delivery_key": key,
            "entries": entries,
        }, ensure_ascii=False, indent=2) + "\n")
    if DELIVERY_CACHE_ROOT.exists():
        shutil.rmtree(DELIVERY_CACHE_ROOT)
    staging.rename(DELIVERY_CACHE_ROOT)
    return {"indexed": indexed, "copied": 0, "skipped": skipped}


def index_record(task_id: str) -> dict[str, object] | None:
    for record in load_index():
        if record.get("task_id") == task_id:
            return record
    return None


def set_nested_value(text: str, parent: str, child: str, value: str) -> str:
    block = nested_block(text, parent)
    line = f"  {child}: \"{value}\"\n"
    if not block:
        return text.rstrip() + f"\n{parent}:\n{line}"
    start, end, body = block
    pattern = re.compile(rf"^  {re.escape(child)}:\s*.*$", re.MULTILINE)
    if pattern.search(body):
        new_body = pattern.sub(line.rstrip(), body)
    else:
        new_body = body.rstrip("\n") + "\n" + line
    return text[:start] + new_body + text[end:]


def command_locate(args: argparse.Namespace) -> int:
    found = find_task(args.task_id)
    if not found:
        print(json.dumps({"found": False, "task_id": args.task_id}, ensure_ascii=False))
        return 1
    root, state, path = found
    print(json.dumps({
        "found": True,
        "task_id": args.task_id,
        "root": root,
        "state": state,
        "path": str(path),
        "canonical": root == "icloud",
    }, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    found = find_task(args.task_id)
    if not found:
        record = index_record(args.task_id)
        if record:
            print(json.dumps({"found": True, "source": "task_index", **record}, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps({"found": False, "task_id": args.task_id}, ensure_ascii=False))
        return 1
    root, state, path = found
    text = read(path)
    fm, _ = frontmatter(text)
    status = {
        "found": True,
        "task_id": args.task_id,
        "root": root,
        "state": state,
        "path": str(path),
        "canonical": root == "icloud",
        "project": top_value(fm, "project"),
        "current_stage": top_value(fm, "current_stage"),
        "execution_mode": top_value(fm, "execution_mode"),
        "system_boundary": top_value(fm, "system_boundary"),
        "writeback_status": top_value(fm, "writeback_status"),
        "delivery_state": top_value(fm, "delivery_state"),
        "skills_used": list_value(fm, "skills_used"),
        "assigned_agent": top_value(fm, "assigned_agent"),
        "role_lane": top_value(fm, "role_lane"),
        "last_read_at": nested_value(fm, "workflow_lock", "last_read_at"),
        "last_action": nested_value(fm, "workflow_lock", "last_action"),
        "next_allowed_actions": [],
        "paths": extract_output_paths(fm),
    }
    block = nested_block(fm, "workflow_lock")
    if block:
        lines = block[2].splitlines()
        collecting = False
        for line in lines:
            if re.match(r"^  next_allowed_actions:\s*$", line):
                collecting = True
                continue
            if collecting and line.startswith("    - "):
                status["next_allowed_actions"].append(line.split("- ", 1)[1].strip().strip("\"'"))
            elif collecting and line.startswith("  ") and not line.startswith("    "):
                break
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def command_sync_index(args: argparse.Namespace) -> int:
    records = sync_index_records()
    ledger_count = sum(1 for record in records if record.get("record_type") == "ledger_row")
    task_count = sum(1 for record in records if record.get("record_type") == "task_card")
    print(json.dumps({
        "synced": True,
        "index": str(TASK_INDEX_JSON),
        "dashboard": str(TASK_DASHBOARD),
        "records": len(records),
        "task_cards": task_count,
        "ledger_rows": ledger_count,
    }, ensure_ascii=False, indent=2))
    return 0


def command_search(args: argparse.Namespace) -> int:
    records = load_index()
    if not records:
        records = sync_index_records()
    terms = [term.lower() for term in args.query.split() if term.strip()]
    matches: list[dict[str, object]] = []
    for record in records:
        blob = json.dumps(record, ensure_ascii=False).lower()
        if all(_is_subsequence(term, blob) for term in terms):
            matches.append(record)
    limit = max(1, min(args.limit, 100))
    output = matches[:limit]
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for record in output:
            print(f"{record.get('task_id')} [{record.get('record_type')}] {record.get('status')} {record.get('project')} - {record.get('title')}")
            if record.get("canonical_path"):
                print(f"  task: {record.get('canonical_path')}")
            if record.get("ledger_path"):
                print(f"  ledger: {record.get('ledger_path')}")
    return 0 if output else 1


def command_dashboard(args: argparse.Namespace) -> int:
    if not TASK_DASHBOARD.exists() or args.refresh:
        sync_index_records()
    print(str(TASK_DASHBOARD))
    if args.print:
        print(read(TASK_DASHBOARD))
    return 0


def html_page(title: str, body: str) -> bytes:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d8dee8;
      --surface: #f7f7f4;
      --accent: #256b5f;
      --warn: #9f5f13;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #fbfaf7;
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      border-bottom: 1px solid var(--line);
      background: rgba(251, 250, 247, .94);
      backdrop-filter: blur(10px);
    }}
    .bar {{
      display: flex;
      align-items: center;
      gap: 14px;
      max-width: 1280px;
      margin: 0 auto;
      padding: 12px 18px;
    }}
    h1 {{ margin: 0; font-size: 18px; letter-spacing: 0; }}
    nav {{ margin-left: auto; display: flex; gap: 10px; flex-wrap: wrap; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 18px; }}
    .tools {{ display: grid; grid-template-columns: 1fr 160px 160px; gap: 10px; margin-bottom: 14px; }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
      color: var(--ink);
      padding: 10px 12px;
      font: inherit;
    }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid var(--line); }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ background: var(--surface); font-size: 12px; color: var(--muted); font-weight: 650; }}
    tr:hover td {{ background: #f6faf8; }}
    .pill {{ display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 1px 8px; color: var(--muted); background: var(--surface); }}
    .warn {{ color: var(--warn); }}
    .path, code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; overflow-wrap: anywhere; }}
    .grid {{ display: grid; grid-template-columns: 220px 1fr; gap: 12px; }}
    .label {{ color: var(--muted); }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: white; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .empty {{ color: var(--muted); padding: 26px; text-align: center; border: 1px dashed var(--line); border-radius: 8px; background: white; }}
    @media (max-width: 760px) {{
      .bar {{ align-items: flex-start; flex-direction: column; }}
      nav {{ margin-left: 0; }}
      .tools {{ grid-template-columns: 1fr; }}
      table, thead, tbody, tr, th, td {{ display: block; }}
      thead {{ display: none; }}
      tr {{ border-bottom: 1px solid var(--line); }}
      td {{ border: 0; padding: 8px 10px; }}
      td::before {{ content: attr(data-label); display: block; color: var(--muted); font-size: 12px; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<header><div class="bar"><h1>{safe_title}</h1><nav><a href="/">任务</a><a href="/weekly">每周整理</a><a href="/api/records">JSON</a></nav></div></header>
<main>{body}</main>
</body>
</html>
""".encode("utf-8")


def task_link(record: dict[str, object]) -> str:
    task_id = quote(str(record.get("task_id") or ""))
    return f"/task/{task_id}"


def render_server_home(records: list[dict[str, object]], query: str = "", project: str = "", status: str = "") -> bytes:
    # Default sort: newest updated_at first
    records = sorted(records, key=lambda r: parse_sort_datetime(str(r.get("updated_at") or "")), reverse=True)
    filtered = records
    if query:
        terms = [term.lower() for term in query.split() if term.strip()]
        filtered = [r for r in filtered if all(_is_subsequence(term, json.dumps(r, ensure_ascii=False).lower()) for term in terms)]
    if project:
        filtered = [r for r in filtered if str(r.get("project") or "") == project]
    if status:
        filtered = [r for r in filtered if str(r.get("status") or "") == status]

    projects = sorted({str(r.get("project") or "") for r in records if r.get("project")})
    statuses = sorted({str(r.get("status") or "") for r in records if r.get("status")})

    def option(value: str, label: str, current: str) -> str:
        selected = " selected" if value == current else ""
        return f'<option value="{html.escape(value)}"{selected}>{html.escape(label)}</option>'

    rows = []
    for record in filtered[:300]:
        name = html.escape(str(record.get("task_name") or record.get("title") or record.get("task_id")))
        description = html.escape(str(record.get("description") or ""))
        rows.append(
            "<tr>"
            f'<td data-label="任务"><a href="{task_link(record)}">{name}</a><br><span class="path">{html.escape(str(record.get("task_id") or ""))}</span></td>'
            f'<td data-label="描述">{description}</td>'
            f'<td data-label="项目"><span class="pill">{html.escape(str(record.get("project_title") or record.get("project") or ""))}</span></td>'
            f'<td data-label="状态"><span class="pill">{html.escape(str(record.get("status") or ""))}</span></td>'
            f'<td data-label="类型">{html.escape(str(record.get("work_type") or ""))}</td>'
            "</tr>"
        )
    table = (
        '<table><thead><tr><th>任务</th><th>描述</th><th>项目</th><th>状态</th><th>类型</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
        if rows
        else '<div class="empty">没有匹配记录</div>'
    )
    body = f"""
<form class="tools" action="/" method="get">
  <input name="q" value="{html.escape(query)}" placeholder="搜索任务、路径、项目、描述">
  <select name="project">{option("", "全部项目", project)}{''.join(option(p, p, project) for p in projects)}</select>
  <select name="status">{option("", "全部状态", status)}{''.join(option(s, s, status) for s in statuses)}</select>
</form>
<p class="label">显示 {len(filtered)} / {len(records)} 条记录。修改任务卡或项目看板后先运行 <code>python3 scripts/gstudio_task.py sync-index</code>，或重启/刷新本服务。</p>
{table}
"""
    return html_page("余烬 · Ember 命令工作台", body)


def render_record_detail(task_id: str, records: list[dict[str, object]]) -> bytes:
    record = next((item for item in records if str(item.get("task_id")) == task_id), None)
    if not record:
        return html_page("任务未找到", f'<div class="empty">没有找到 <code>{html.escape(task_id)}</code></div>')
    pairs = []
    for key in (
        "task_id", "record_type", "title", "description", "project", "subproject",
        "status", "work_type", "execution_mode", "delivery_state", "updated_at",
        "skills_used", "canonical_path", "ledger_path", "delivery_folder", "next_action",
    ):
        value = record.get(key)
        if value:
            pairs.append(f'<div class="label">{html.escape(key)}</div><div>{html.escape(str(value))}</div>')
    paths = record.get("paths") if isinstance(record.get("paths"), list) else []
    path_block = ""
    if paths:
        path_block = "<h2>Paths</h2><pre>" + html.escape("\n".join(str(path) for path in paths)) + "</pre>"
    source_path = record.get("canonical_path") or record.get("ledger_path")
    source_block = ""
    if source_path and Path(str(source_path)).exists():
        source_block = "<h2>Source</h2><pre>" + html.escape(read(Path(str(source_path)))[:30000]) + "</pre>"
    body = f'<div class="grid">{"".join(pairs)}</div>{path_block}{source_block}'
    return html_page(str(record.get("task_name") or task_id), body)


def render_weekly_review() -> bytes:
    from . import weekly_task_review

    report = weekly_task_review.generate(datetime.now().date())
    return html_page("余烬 · Ember 每周整理", "<pre>" + html.escape(report) + "</pre>")


class GStudioTaskHttpHandler(http.server.BaseHTTPRequestHandler):
    server_version = "GStudioTaskHTTP/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"[gstudio_task serve] {self.address_string()} - {format % args}", file=sys.stderr)

    def send_bytes(self, payload: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def current_records(self) -> list[dict[str, object]]:
        if getattr(self.server, "refresh", False):
            return sync_index_records()
        records = load_index()
        return records if records else sync_index_records()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/healthz":
                self.send_bytes(b"ok\n", "text/plain; charset=utf-8")
                return
            if parsed.path == "/api/records":
                payload = json.dumps({"records": self.current_records()}, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_bytes(payload, "application/json; charset=utf-8")
                return
            if parsed.path == "/weekly":
                self.send_bytes(render_weekly_review())
                return
            if parsed.path.startswith("/task/"):
                task_id = unquote(parsed.path.split("/task/", 1)[1])
                self.send_bytes(render_record_detail(task_id, self.current_records()))
                return
            if parsed.path == "/":
                query = parse_qs(parsed.query)
                self.send_bytes(render_server_home(
                    self.current_records(),
                    query.get("q", [""])[0],
                    query.get("project", [""])[0],
                    query.get("status", [""])[0],
                ))
                return
            self.send_bytes(html_page("未找到", '<div class="empty">页面不存在</div>'), status=404)
        except Exception as exc:  # pragma: no cover - keeps the browser useful during local debugging.
            message = f"<pre>{html.escape(type(exc).__name__ + ': ' + str(exc))}</pre>"
            self.send_bytes(html_page("服务错误", message), status=500)


def command_serve(args: argparse.Namespace) -> int:
    if args.refresh:
        sync_index_records()
    server = http.server.ThreadingHTTPServer((args.host, args.port), GStudioTaskHttpHandler)
    server.refresh = args.live_refresh  # type: ignore[attr-defined]
    url = f"http://{args.host}:{args.port}/"
    print(json.dumps({"serving": True, "url": url, "live_refresh": args.live_refresh}, ensure_ascii=False, indent=2))
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", file=sys.stderr)
    finally:
        server.server_close()
    return 0


def command_touch_lock(args: argparse.Namespace) -> int:
    found = find_task(args.task_id)
    if not found:
        print(f"task card not found: {args.task_id}", file=sys.stderr)
        return 1
    root, _, path = found
    if root != "icloud" and not args.allow_local:
        print("refusing to update legacy local task without --allow-local", file=sys.stderr)
        return 1
    text = read(path)
    fm, body = frontmatter(text)
    if not fm:
        print(f"task frontmatter not found: {path}", file=sys.stderr)
        return 1
    now = args.at or now_iso_string()
    # Always keep updated_at in sync with last_read_at so task cards carry a
    # precise timestamp rather than a stale date-only value.
    fm = re.sub(
        r"^updated_at:\s*.*$",
        f"updated_at: {now}",
        fm,
        count=1,
        flags=re.M,
    )
    if "updated_at:" not in fm:
        fm = fm.rstrip() + f"\nupdated_at: {now}\n"
    fm = set_nested_value(fm, "workflow_lock", "require_task_card_read", "true")
    fm = set_nested_value(fm, "workflow_lock", "last_read_at", now)
    fm = set_nested_value(fm, "workflow_lock", "last_action", args.action)
    write(path, "---\n" + fm.rstrip() + "\n---" + body)
    print(json.dumps({"updated": True, "path": str(path), "updated_at": now, "last_read_at": now, "last_action": args.action}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and lightly update GStudio task cards")
    sub = parser.add_subparsers(dest="command", required=True)

    locate = sub.add_parser("locate")
    locate.add_argument("--task-id", required=True)
    locate.set_defaults(func=command_locate)

    status = sub.add_parser("status")
    status.add_argument("--task-id", required=True)
    status.set_defaults(func=command_status)

    touch = sub.add_parser("touch-lock")
    touch.add_argument("--task-id", required=True)
    touch.add_argument("--action", required=True)
    touch.add_argument("--at")
    touch.add_argument("--allow-local", action="store_true")
    touch.set_defaults(func=command_touch_lock)

    sync = sub.add_parser("sync-index")
    sync.set_defaults(func=command_sync_index)

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("-n", "--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=command_search)

    dashboard = sub.add_parser("dashboard")
    dashboard.add_argument("--refresh", action="store_true")
    dashboard.add_argument("--print", action="store_true")
    dashboard.set_defaults(func=command_dashboard)

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--refresh", action="store_true", help="refresh the task index before starting")
    serve.add_argument("--live-refresh", action="store_true", help="rebuild the task index on every request")
    serve.add_argument("--open", action="store_true", help="open the server URL in the default browser")
    serve.set_defaults(func=command_serve)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
