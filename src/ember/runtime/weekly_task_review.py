#!/usr/bin/env python3
"""Generate a proposal-only weekly review for GStudio task cards.

This command may refresh derived indexes and write a review Markdown file. It
never edits, closes, or moves canonical task cards.
"""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

ROOT = _deployment_root()
from . import gstudio_task as tasks
from . import gstudio_archive_index as archive_index
from . import gstudio_archive_backup_audit as archive_backup_audit
from .workspace_paths import equivalent_path_strings

REVIEW_ROOT = tasks.SHARED_TASK_ROOT / "每周整理"
LOCAL_CACHE_PATH = ROOT / "outputs" / "reports" / "weekly-review-current.json"


def formal_project_slugs() -> list[str]:
    return list(tasks.project_registry()[0])


def previous_complete_week(day: dt.date) -> tuple[dt.date, dt.date]:
    """Return Monday..Sunday for the complete natural week before *day*."""
    current_monday = day - dt.timedelta(days=day.weekday())
    end = current_monday - dt.timedelta(days=1)
    return end - dt.timedelta(days=6), end


def review_day(day: dt.date) -> dt.date:
    """Use the previous complete week's Monday as the review identity."""
    return previous_complete_week(day)[0]


def review_window(day: dt.date) -> tuple[dt.date, dt.date]:
    """Return the Monday..Sunday window containing a review identity day."""
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def record_in_window(record: dict[str, object], start: dt.date, end: dt.date) -> bool:
    activity = record_activity_date(record)
    return bool(activity and start <= activity <= end)


def record_activity_date(record: dict[str, object]) -> dt.date | None:
    """Return the effective weekly activity date for a task.

    New cards initialize updated_at to created_at, so the same rule covers a
    task's first week without a creation-only special case. Historical cards
    fall back explicitly rather than disappearing from weekly organization.
    """
    for value in (
        record.get("updated_at"),
        record.get("created_at"),
        record.get("task_id"),
    ):
        if parsed := parse_date(value):
            return parsed
    return None


def record_created_in_window(record: dict[str, object], start: dt.date, end: dt.date) -> bool:
    """Keep project-overview creation counters tied to creation semantics."""
    created = parse_date(record.get("created_at")) or parse_date(record.get("task_id"))
    return bool(created and start <= created <= end)


def parse_date(value: object, fallback: str = "") -> dt.date | None:
    text = str(value or fallback)
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", text)
    if not match:
        return None
    try:
        return dt.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def row(record: dict[str, object], reason: str) -> str:
    return (
        f"| [{record.get('title')}](<{record.get('canonical_path')}>) | "
        f"{record.get('project_title')} | {record.get('status')} | {reason} |"
    )


def table(records: list[tuple[dict[str, object], str]]) -> list[str]:
    if not records:
        return ["_无_", ""]
    lines = ["| 任务 | 项目 | 状态 | 整理建议 |", "|---|---|---|---|"]
    lines.extend(row(record, reason) for record, reason in records)
    lines.append("")
    return lines


def duplicate_delivery_folders(records: list[dict[str, object]]) -> list[tuple[dict[str, object], str]]:
    """Find scoped tasks that physically exist in both delivery states.

    The weekly report only proposes a repair. It must not move either folder or
    rewrite the task card without Evan's item-level confirmation.
    """
    conflicts: list[tuple[dict[str, object], str]] = []
    for record in records:
        task_id = str(record.get("task_id") or "").strip()
        if not task_id:
            continue
        draft = tasks.SHARED_WORKSPACE_ROOT / "交付" / "草稿" / task_id
        formal = tasks.SHARED_WORKSPACE_ROOT / "交付" / "正式交付" / task_id
        if draft.is_dir() and formal.is_dir():
            conflicts.append((record, "草稿与正式交付存在同名任务目录：逐项确认保留状态、文件归属和目录修复"))
    return conflicts


def delivery_health_issues(records: list[dict[str, object]]) -> list[tuple[dict[str, object], str]]:
    """Read-only delivery and task-line health audit."""
    issues: list[tuple[dict[str, object], str]] = []
    by_id = {str(record.get("task_id") or ""): record for record in records}
    declared: set[Path] = set()
    for record in records:
        folder_value = str(record.get("delivery_folder") or "")
        if folder_value:
            folder = (tasks.SHARED_WORKSPACE_ROOT / folder_value).resolve()
            declared.add(folder)
            if not folder.is_dir():
                issues.append((record, "任务卡指向不存在的交付目录"))
            elif not any(path for path in folder.iterdir() if not path.name.startswith(".")):
                issues.append((record, "交付目录为空：逐项确认是否误建、遗留或异常完成"))
            if "交付/草稿/" in folder_value:
                task_id = str(record.get("task_id") or "").strip()
                card_path = Path(str(record.get("canonical_path") or ""))
                historical_relative = f"交付/正式交付/{task_id}"
                try:
                    card_text = card_path.read_text(encoding="utf-8")
                except OSError:
                    card_text = ""
                if task_id and historical_relative in card_text:
                    declared.add((tasks.SHARED_WORKSPACE_ROOT / historical_relative).resolve())
        if record.get("task_kind") == "task_group":
            if not folder_value:
                issues.append((record, "任务主线缺少交付目录"))
            else:
                folder = (tasks.SHARED_WORKSPACE_ROOT / folder_value).resolve()
                for name in ("00_任务组说明.md", "01_关联任务索引.md"):
                    if not (folder / name).is_file():
                        issues.append((record, f"任务主线缺少 {name}"))
            for member_id in record.get("member_task_ids") or []:
                if str(member_id) not in by_id:
                    issues.append((record, f"任务主线的相关任务不存在：{member_id}"))
    for state in ("草稿", "正式交付"):
        root = tasks.SHARED_WORKSPACE_ROOT / "交付" / state
        if not root.is_dir():
            continue
        for folder in root.iterdir():
            if folder.is_dir() and folder.resolve() not in declared:
                issues.append(({
                    "title": folder.name,
                    "project_title": "未登记",
                    "status": "orphan",
                    "canonical_path": str(folder),
                }, f"无任务卡声明的孤儿交付目录（{state}）"))
    return issues


def non_delivery_closeout_candidates(
    records: list[dict[str, object]],
) -> list[tuple[dict[str, object], str]]:
    """Expose active non-delivery work for item-level closeout review.

    This is deliberately proposal-only. Evidence changes the explanation, not
    the task state or whether Evan must confirm the closeout.
    """
    candidates: list[tuple[dict[str, object], str]] = []
    modes = {"none", "system", "archive", "external"}
    evidence_markers = (
        "finalize 通过",
        "finalize通过",
        "发布提交",
        "推送成功",
        "验证通过",
        "验收通过",
        "state=completed",
        "state=verified",
        "实现完成",
        "任务实现全部完成",
    )
    for record in records:
        mode = str(record.get("artifact_mode") or "").strip()
        if mode not in modes or record.get("delivery_folder"):
            continue

        external_state = str(record.get("external_state") or "").strip()
        if mode == "external" and external_state in {"completed", "verified"}:
            evidence = f"外部状态为 `{external_state}`"
        else:
            path = Path(str(record.get("canonical_path") or ""))
            try:
                text = path.read_text(encoding="utf-8") if path.is_file() else ""
            except OSError:
                text = ""
            marker = next((value for value in evidence_markers if value in text), "")
            evidence = f"任务卡记录“{marker}”" if marker else "任务卡未发现明确完成标记"

        candidates.append(
            (
                record,
                f"`artifact_mode: {mode}` 且仍为 active；{evidence}。逐项核验模式证据后确认收口或继续执行",
            )
        )
    return candidates


def generate_project_overview(day: dt.date, records: list[dict[str, object]] | None = None) -> dict[str, object]:
    """Build the stable weekly narrative used by the project center.

    Numeric counters remain live in the web view. This snapshot intentionally
    changes only when the Monday weekly process writes a new overview.
    """
    records = records if records is not None else tasks.load_index()
    cards = [record for record in records if record.get("record_type") == "task_card"]
    registry, _ = tasks.project_registry()
    window_start, window_end = review_window(day)
    projects: list[dict[str, object]] = []
    for slug in formal_project_slugs():
        matching = [record for record in cards if record.get("project") == slug]
        created_this_week = [record for record in matching if record_created_in_window(record, window_start, window_end)]
        completed_this_week = [record for record in matching if record.get("status") == "completed" and record_created_in_window(record, window_start, window_end)]
        active = [record for record in matching if record.get("status") == "active"]
        draft = [record for record in active if "交付/草稿/" in str(record.get("delivery_folder") or "")]
        stale = [
            record for record in active
            if (updated := parse_date(record.get("updated_at"), str(record.get("task_id") or "")))
            and updated < window_start - dt.timedelta(days=21)
        ]
        latest = max((parse_date(record.get("updated_at"), str(record.get("task_id") or "")) for record in matching), default=None)
        title = str(registry.get(slug, {}).get("title") or slug)
        projects.append({
            "slug": slug,
            "title": title,
            "active": len(active),
            "created_this_week": len(created_this_week),
            "completed_this_week": len(completed_this_week),
            "draft_pending": len(draft),
            "stale_active": len(stale),
            "latest_update": latest.isoformat() if latest else "",
        })

    busiest = max(projects, key=lambda item: int(item["active"]), default=None)
    most_progress = max(projects, key=lambda item: int(item["completed_this_week"]), default=None)
    summary_parts = []
    if busiest and busiest["active"]:
        summary_parts.append(f"{busiest['title']}当前进行中任务最多（{busiest['active']}项），是本周的主要执行重心。")
    if most_progress and most_progress["completed_this_week"]:
        summary_parts.append(f"{most_progress['title']}在本周新建的任务中已完成 {most_progress['completed_this_week']} 项，进展最明显。")
    if not summary_parts:
        summary_parts.append("本周没有出现明显的跨项目任务变化，建议继续关注现有进行中任务。")

    attention = []
    for item in projects:
        if item["stale_active"]:
            attention.append(f"{item['title']}有 {item['stale_active']} 项较长时间未更新的进行中任务。")
        if item["draft_pending"]:
            attention.append(f"{item['title']}有 {item['draft_pending']} 项草稿交付待确认。")
    recommendations = attention[:2]
    if busiest and busiest["active"]:
        recommendations.append(f"优先梳理{busiest['title']}的进行中任务，确认本周真正需要推进的工作。")
    recommendations = recommendations[:3] or ["继续按当前优先级推进，下周再根据任务和交付变化重新评估。"]
    progress = [
        f"{item['title']}：本周新建 {item['created_this_week']} 项，其中已完成 {item['completed_this_week']} 项。"
        for item in projects if item["created_this_week"] or item["completed_this_week"]
    ]
    return {
        "week": week_id(day),
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "period_start": window_start.isoformat(),
        "period_end": window_end.isoformat(),
        "summary": "".join(summary_parts),
        "projects": projects,
        "attention": attention[:6],
        "progress": progress[:6],
        "recommendations": recommendations,
    }


def generate(today: dt.date, *, refresh_index: bool = True, all_history: bool = False) -> str:
    records = tasks.sync_index_records() if refresh_index else tasks.load_index()
    if refresh_index:
        try:
            previous_scan = archive_index.load_publish_scan()
            previous_paths = {str(item.get("remote_path") or "") for item in (previous_scan.get("folders") or []) if isinstance(item, dict)}
            refreshed_scan = archive_index.build_publish_scan()
            refreshed_scan["new_folders"] = [] if previous_scan.get("status") == "missing" else [item for item in (refreshed_scan.get("folders") or []) if isinstance(item, dict) and str(item.get("remote_path") or "") not in previous_paths]
            archive_index.save_publish_scan(refreshed_scan)
        except archive_index.ArchiveIndexError:
            pass
        try:
            archive_backup_audit.audit()
        except (archive_backup_audit.BackupAuditError, OSError, ValueError):
            # Weekly task review remains available when the backup transport is
            # temporarily unavailable; the previous audit status is preserved.
            pass
    publish_scan = archive_index.load_publish_scan()
    all_cards = [r for r in records if r.get("record_type") == "task_card"]
    window_start, window_end = review_window(today)
    cards = all_cards if all_history else [r for r in all_cards if record_in_window(r, window_start, window_end)]
    active = [r for r in cards if r.get("state") == "active"]
    operational = [r for r in active if r.get("status") == "active"]
    manual_exceptions = [r for r in active if r.get("status") in {"waiting_user", "blocked"}]
    terminal = [(r, "任务卡仍在 active 目录但已标记完成：确认正式交付后移入 completed") for r in active if r.get("status") == "completed"]
    draft_promotions = [
        (r, "草稿交付已登记：确认内容后晋级正式交付并完成任务")
        for r in operational
        if "交付/草稿/" in str(r.get("delivery_folder") or "")
    ]
    formal_mismatches = [
        (r, "已指向正式交付但任务仍在 active：确认完成并移入 completed")
        for r in operational
        if "交付/正式交付/" in str(r.get("delivery_folder") or "")
    ]
    non_delivery_closeouts = non_delivery_closeout_candidates(operational)
    duplicate_folders = duplicate_delivery_folders(cards)
    health_issues = delivery_health_issues(all_cards)

    similar: list[tuple[dict[str, object], str]] = []
    for index, left in enumerate(operational):
        left_title = str(left.get("title") or "")
        for right in operational[index + 1:]:
            if left.get("project") != right.get("project"):
                continue
            right_title = str(right.get("title") or "")
            ratio = SequenceMatcher(None, left_title, right_title).ratio()
            if ratio >= 0.72:
                similar.append((right, f"与《{left_title}》相似度 {ratio:.0%}：确认合并、前后续或保持独立"))

    aliases = [
        (r, f"原项目值 `{r.get('source_project')}` 已归一为 `{r.get('project')}`")
        for r in cards
        if r.get("source_project") and str(r.get("source_project")).lower() != str(r.get("project")).lower()
    ]
    missing_type = [(r, "补充或核对 work_type") for r in operational if not r.get("work_type")]

    delivery_issues: list[tuple[dict[str, object], str]] = []
    for record in operational:
        folder = str(record.get("delivery_folder") or "")
        if folder and str(record.get("task_id")) not in folder:
            delivery_issues.append((record, "delivery.folder 未使用精确 task_id 文件夹"))

    ledger_paths = {str(path) for record in records if record.get("record_type") == "ledger_row" for path in (record.get("paths") or [])}
    ledger_sequences = {str(record.get("seq") or "") for record in records if record.get("record_type") == "ledger_row" and record.get("seq")}
    publish_folders = publish_scan.get("new_folders") if isinstance(publish_scan.get("new_folders"), list) else []
    if not all_history:
        publish_folders = [
            folder for folder in publish_folders
            if isinstance(folder, dict)
            and (folder_date := parse_date(folder.get("name"), str(folder.get("remote_path") or "")))
            and window_start <= folder_date <= window_end
        ]
    unmatched_publish = [folder for folder in publish_folders if isinstance(folder, dict) and str(folder.get("remote_path") or "") not in ledger_paths and not any(str(folder.get("name") or "").startswith(seq) for seq in ledger_sequences)]
    publish_lines = [
        f"| {folder.get('project')} | {folder.get('name')} | `{folder.get('remote_path')}` | 待 Evan 确认是否补建发布记录 |"
        for folder in unmatched_publish
    ]
    if publish_lines:
        publish_lines = ["| 项目 | 归档文件夹 | 远程路径 | 建议 |", "|---|---|---|---|", *publish_lines, ""]
    else:
        publish_lines = ["_未发现待补发布记录，或本周远程扫描尚未成功。_", ""]

    iso = today.isocalendar()
    lines = [
        f"# 余烬 · Ember 每周任务整理建议｜{iso.year}-W{iso.week:02d}",
        "",
        f"> 整理范围：有效修改时间位于 {window_start.isoformat()} 00:00 至 {(window_end + dt.timedelta(days=1)).isoformat()} 00:00（左闭右开）；优先使用 `updated_at`，缺失时依次回退 `created_at` 与任务 ID 日期。本报告只提出建议，不会自动关闭、移动或改写任务卡。",
        *( ["> 范围模式：已按 Evan 的额外要求扩大到全部历史任务。"] if all_history else [] ),
        "",
        "## 总览",
        "",
        f"- 本周范围内任务卡：{len(cards)}",
        f"- 进行中任务：{len(operational)}",
        f"- 草稿待晋级：{len(draft_promotions)}",
        f"- 正式交付待收口：{len(formal_mismatches) + len(terminal)}",
        f"- 非交付任务待收口核验：{len(non_delivery_closeouts)}",
        f"- 草稿/正式同名目录冲突：{len(duplicate_folders)}",
        f"- 交付与任务主线健康异常：{len(health_issues)}",
        f"- 合并候选：{len(similar)}",
        f"- 发布归档待补记录：{len(unmatched_publish)}",
        "",
        "## 草稿晋级正式交付（逐项确认）", "", *table(draft_promotions),
        "## 正式交付与完成收口（逐项确认）", "", *table(formal_mismatches + terminal),
        "## 非交付任务完成收口（逐项确认）", "", *table(non_delivery_closeouts),
        "## 草稿与正式交付同名目录冲突（逐项确认）", "", *table(duplicate_folders),
        "## 交付目录与任务主线健康检查（只读）", "", *table(health_issues),
        "## 任务合并候选（仅建议）", "", *table(similar),
        "## 人工例外状态（只保留，不自动处理）", "", *table([(r, "人工状态；本轮不自动修改") for r in manual_exceptions]),
        "## 项目别名归一化检查", "", *table(aliases[:80]),
        "## 类型与交付异常", "", *table(missing_type + delivery_issues),
        "## 发布归档核对", "", *publish_lines,
        "## 本周建议动作", "",
        "1. Evan 逐项确认草稿晋级、交付与非交付任务完成收口及合并建议。",
        "2. 只执行确认项：移动交付目录、更新卡片或建立合并关联记录。",
        "3. 执行后刷新索引；项目知识与长期可复用内容仍由 EBrain 维护。",
        "",
    ]
    return "\n".join(lines)


def week_id(day: dt.date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def round_id(day: dt.date, round_number: int) -> str:
    return f"{week_id(day)}-R{round_number:02d}"


def cached_round(day: dt.date) -> int:
    try:
        value = json.loads(LOCAL_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    if isinstance(value, dict) and value.get("week") == week_id(day):
        try:
            return max(1, int(value.get("round") or 1))
        except (TypeError, ValueError):
            return 1
    return 1


def report_path(day: dt.date, round_number: int = 1) -> Path:
    return REVIEW_ROOT / f"{round_id(day, round_number)}.md"


def status_path(day: dt.date, round_number: int = 1) -> Path:
    return REVIEW_ROOT / f"{round_id(day, round_number)}.status.json"


def legacy_status_path(day: dt.date) -> Path:
    return REVIEW_ROOT / f"{week_id(day)}.status.json"


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def cache_weekly_view(day: dt.date, report: str, status: dict[str, object], round_number: int = 1, project_overview: dict[str, object] | None = None) -> Path:
    if project_overview is None:
        try:
            current = json.loads(LOCAL_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        if isinstance(current, dict) and current.get("week") == week_id(day) and isinstance(current.get("project_overview"), dict):
            project_overview = current["project_overview"]
    payload = {
        "week": week_id(day),
        "round": round_number,
        "round_id": round_id(day, round_number),
        "cached_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "report": report,
        "status": status,
        "project_overview": project_overview or {},
    }
    _atomic_json(LOCAL_CACHE_PATH, payload)
    return LOCAL_CACHE_PATH


def local_equivalent_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_file():
        return expanded.resolve()
    for value in equivalent_path_strings(expanded):
        candidate = Path(value)
        if candidate.is_file():
            return candidate.resolve()
    return expanded.resolve()


def load_weekly_view(day: dt.date) -> dict[str, object]:
    try:
        value = json.loads(LOCAL_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    if isinstance(value, dict) and value.get("week") == week_id(day):
        status = value.get("status") if isinstance(value.get("status"), dict) else {}
        return {"week": week_id(day), "round": int(value.get("round") or 1), "round_id": str(value.get("round_id") or round_id(day, 1)), "report": str(value.get("report") or ""), "status": status, "project_overview": value.get("project_overview") if isinstance(value.get("project_overview"), dict) else {}, "source": "local_cache"}
    shared_status = completion_status(day, 1)
    if shared_status.get("state") == "completed" and shared_status.get("report_path"):
        try:
            cache = sync_cache(day)
            value = json.loads(cache.read_text(encoding="utf-8"))
            status = value.get("status") if isinstance(value.get("status"), dict) else {}
            return {"week": week_id(day), "round": int(value.get("round") or 1), "round_id": str(value.get("round_id") or round_id(day, 1)), "report": str(value.get("report") or ""), "status": status, "source": "recovered_shared_completion"}
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    proposal = report_path(day, 1)
    if proposal.exists():
        report = proposal.read_text(encoding="utf-8")
        return {"week": week_id(day), "round": 1, "round_id": round_id(day, 1), "report": report, "status": {"week": week_id(day), "round": 1, "state": "pending_confirmation"}, "source": "shared_proposal"}
    start, end = review_window(day)
    report = f"# 余烬 · Ember 每周任务整理｜{week_id(day)}\n\n> 整理范围：{start.isoformat()} 00:00 至 {(end + dt.timedelta(days=1)).isoformat()} 00:00。\n\n本轮建议由 Mac mini 在周一 03:00 建立整理任务并冻结；报告调用方只读取得冻结版本。"
    return {"week": week_id(day), "round": 1, "round_id": round_id(day, 1), "report": report, "status": {"week": week_id(day), "round": 1, "state": "scheduled"}, "source": "scheduled_placeholder"}


def write_proposal(day: dt.date, *, new_round: bool = False) -> tuple[Path, Path]:
    round_number = cached_round(day) + 1 if new_round else 1
    report = generate(day)
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    canonical = report_path(day, round_number)
    canonical.write_text(report, encoding="utf-8")
    status = {"week": week_id(day), "round": round_number, "round_id": round_id(day, round_number), "state": "pending_confirmation", "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "phase": "proposal"}
    _atomic_json(status_path(day, round_number), status)
    cache = cache_weekly_view(day, report, status, round_number, generate_project_overview(day))
    return canonical, cache


def refresh_project_overview(day: dt.date) -> Path:
    """Refresh only the weekly project-center narrative, preserving review state."""
    view = load_weekly_view(day)
    status = view.get("status") if isinstance(view.get("status"), dict) else {}
    return cache_weekly_view(
        day,
        str(view.get("report") or ""),
        status,
        int(view.get("round") or 1),
        generate_project_overview(day),
    )


def completion_report_text(path: Path) -> str:
    resolved = local_equivalent_path(path)
    formal_root = (tasks.SHARED_WORKSPACE_ROOT / "交付" / "正式交付").resolve()
    try:
        resolved.relative_to(formal_root)
    except ValueError as exc:
        raise ValueError(f"完成汇总报告必须位于正式交付目录：{formal_root}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"完成汇总报告不存在：{resolved}")
    return resolved.read_text(encoding="utf-8")


def sync_cache(day: dt.date, report_override: Path | None = None) -> Path:
    round_number = cached_round(day)
    status = completion_status(day, round_number)
    if status.get("state") == "completed":
        source = report_override or (Path(str(status.get("report_path"))) if status.get("report_path") else None)
        if source is None:
            raise ValueError("本周已标记完成，但完成回执缺少正式完成汇总报告路径。")
        report = completion_report_text(source)
        if report_override is not None:
            status["report_path"] = str(local_equivalent_path(source))
        return cache_weekly_view(day, report, status, round_number)
    proposal = report_path(day, round_number)
    if proposal.exists():
        report = proposal.read_text(encoding="utf-8")
        pending = {"week": week_id(day), "round": round_number, "round_id": round_id(day, round_number), "state": "pending_confirmation", "phase": "proposal"}
        return cache_weekly_view(day, report, pending, round_number)
    _, cache = write_proposal(day)
    return cache


def completion_status(day: dt.date, round_number: int | None = None) -> dict[str, object]:
    round_number = round_number or cached_round(day)
    path = status_path(day, round_number)
    if not path.exists() and round_number == 1 and legacy_status_path(day).exists():
        path = legacy_status_path(day)
    if not path.exists():
        return {"week": week_id(day), "round": round_number, "round_id": round_id(day, round_number), "state": "pending_confirmation"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"week": week_id(day), "state": "pending_confirmation"}
    except (OSError, json.JSONDecodeError):
        return {"week": week_id(day), "state": "pending_confirmation"}


def mark_complete(day: dt.date, executor: str, summary: str, report_path_value: Path | None = None) -> Path:
    if report_path_value is None:
        raise ValueError("必须先生成正式完成汇总报告，并通过 --report 提供路径。")
    report = completion_report_text(report_path_value)
    round_number = cached_round(day)
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "week": week_id(day),
        "round": round_number,
        "round_id": round_id(day, round_number),
        "state": "completed",
        "completed_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "executor": executor,
        "summary": summary.strip() or "已按 Evan 确认完成本周任务整理。",
        "report_path": str(report_path_value.expanduser().resolve()),
    }
    path = status_path(day, round_number)
    _atomic_json(path, payload)
    cache_weekly_view(day, report, payload, round_number)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD，默认今天")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--new-round", action="store_true")
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--sync-cache", action="store_true")
    parser.add_argument("--refresh-project-overview", action="store_true")
    parser.add_argument("--executor", choices=["codex", "opencode", "hermes", "external"], default="codex")
    parser.add_argument("--summary", default="")
    parser.add_argument("--report", help="正式完成汇总报告 Markdown 绝对路径")
    parser.add_argument("--all-history", action="store_true", help="仅在 Evan 明确要求扩大范围时使用")
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.date) if args.date else review_day(dt.date.today())
    if args.complete:
        path = mark_complete(today, args.executor, args.summary, Path(args.report) if args.report else None)
        print(json.dumps({"completed": str(path), "week": week_id(today)}, ensure_ascii=False))
        return 0
    if args.sync_cache:
        path = sync_cache(today, Path(args.report) if args.report else None)
        print(json.dumps({"cache": str(path), "week": week_id(today)}, ensure_ascii=False))
        return 0
    if args.refresh_project_overview:
        path = refresh_project_overview(today)
        print(json.dumps({"project_overview_cache": str(path), "week": week_id(today)}, ensure_ascii=False))
        return 0
    if args.write:
        if args.all_history:
            report = generate(today, all_history=True)
            round_number = cached_round(today) + 1 if args.new_round else 1
            REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
            path = report_path(today, round_number)
            path.write_text(report, encoding="utf-8")
            status = {"week": week_id(today), "round": round_number, "round_id": round_id(today, round_number), "state": "pending_confirmation", "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "phase": "proposal", "scope": "all_history"}
            _atomic_json(status_path(today, round_number), status)
            cache = cache_weekly_view(today, report, status, round_number)
        else:
            path, cache = write_proposal(today, new_round=args.new_round)
        print(json.dumps({"written": str(path), "cache": str(cache), "mutated_task_cards": 0}, ensure_ascii=False))
    else:
        print(generate(today, all_history=args.all_history))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
