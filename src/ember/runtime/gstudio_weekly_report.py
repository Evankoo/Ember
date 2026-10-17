#!/usr/bin/env python3
"""Build a read-only GStudio weekly handoff and organization proposal packet."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = _deployment_root()
from . import gstudio_archive_index as archive_index
from . import gstudio_daily_report as daily
from . import weekly_task_review as review
from .workspace_paths import shared_workspace_root
from .gstudio_task import current_project_titles

INDEX_PATH = ROOT / "task-cards" / "index.json"
INDEX_STATUS_PATH = ROOT / "task-cards" / "task-index-sync-status.json"
SKILL_PATH = ROOT / "skills" / "gstudio-daily-report" / "SKILL.md"
STYLE_PATH = ROOT / "skills" / "gstudio-daily-report" / "references" / "weekly-report-style.md"
CONTRACT_PATH = ROOT / "skills" / "gstudio-daily-report" / "references" / "weekly-handoff-contract.md"
TZ = ZoneInfo("Asia/Shanghai")
TIMEZONE_NAME = "Asia/Shanghai"
SCHEMA_VERSION = 1
REPORT_KIND = "gstudio_weekly_handoff"


class WeeklyReportError(RuntimeError):
    """Raised when a complete weekly packet cannot be built."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WeeklyReportError(f"required GStudio evidence is missing: {path.name}") from exc
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise WeeklyReportError(f"invalid GStudio evidence: {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise WeeklyReportError(f"invalid GStudio evidence shape: {path.name}")
    return value


def report_window(report_week: str = "latest", *, now: datetime | None = None) -> tuple[str, date, date, datetime, datetime]:
    current = (now or datetime.now(TZ)).astimezone(TZ)
    current_monday = current.date() - timedelta(days=current.weekday())
    if report_week in {"", "latest"}:
        start = current_monday - timedelta(days=7)
    else:
        try:
            year_text, week_text = report_week.upper().split("-W", 1)
            start = date.fromisocalendar(int(year_text), int(week_text), 1)
        except (ValueError, TypeError) as exc:
            raise WeeklyReportError("report_week must be latest or YYYY-Www") from exc
        if start >= current_monday:
            raise WeeklyReportError("report_week must be a complete natural week before this week")
    end_date = start + timedelta(days=7)
    iso = start.isocalendar()
    week_id = f"{iso.year}-W{iso.week:02d}"
    start_at = datetime.combine(start, time.min, tzinfo=TZ)
    return week_id, start, end_date - timedelta(days=1), start_at, start_at + timedelta(days=7)


def _source_hash() -> str:
    digest = hashlib.sha256()
    for path in (SKILL_PATH, STYLE_PATH, CONTRACT_PATH):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _record_status(record: dict[str, Any]) -> str:
    return str(record.get("status") or record.get("state") or "")


def _public_task(record: dict[str, Any]) -> dict[str, Any]:
    return daily._task_item(record)


def _candidate_item(
    week_id: str, category: str, number: int, record: dict[str, Any], reason: str,
    action: str, *, requires_confirmation: bool,
) -> dict[str, Any]:
    task_id = str(record.get("task_id") or "")
    title = str(record.get("task_name") or record.get("title") or task_id or "未登记交付目录")
    candidate_task_ids = [
        str(value) for value in record.get("candidate_task_ids", []) if str(value)
    ]
    identity = f"{week_id}\0{category}\0{task_id}\0{title}\0{reason}\0{'|'.join(candidate_task_ids)}"
    folder = str(record.get("delivery_folder") or "")
    artifact_mode = str(record.get("artifact_mode") or "")
    action_code = "manual_organization"
    if category == "A":
        action_code = "promote_delivery"
    elif category == "B" and artifact_mode in {"none", "system", "archive", "external"} and not folder:
        action_code = "complete_task"
    elif category in {"C", "D"}:
        action_code = "repair"
    elif category == "E":
        action_code = "merge"
    result = {
        "item_id": f"{category}{number:02d}",
        "confirmation_key": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "task_id": task_id,
        "title": title,
        "project": str(record.get("project") or "independent"),
        "project_title": str(record.get("project_title") or record.get("project") or "独立任务"),
        "status": _record_status(record),
        "reason": reason,
        "suggested_action": action,
        "action_code": action_code,
        "requires_item_confirmation": requires_confirmation,
    }
    if candidate_task_ids:
        result["candidate_task_ids"] = candidate_task_ids
        result["required_confirmation_details"] = {
            "survivor_task_id": "one candidate task ID",
            "source_task_ids": "all other candidate task IDs",
            "artifact_plan": {"mode": "references"},
            "source_lifecycle_dispositions": "exactly retired_active or retired_completed per source task",
        }
    return result


def _category(
    week_id: str, code: str, title: str,
    rows: list[tuple[dict[str, Any], str, str]], *, requires_confirmation: bool,
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda value: (
        str(value[0].get("project") or ""),
        str(value[0].get("task_id") or ""),
        str(value[0].get("task_name") or value[0].get("title") or ""),
        value[1],
    ))
    items = [
        _candidate_item(week_id, code, index, record, reason, action,
                        requires_confirmation=requires_confirmation)
        for index, (record, reason, action) in enumerate(ordered, 1)
    ]
    return {
        "category": code,
        "title": title,
        "count": len(items),
        "requires_item_confirmation": requires_confirmation,
        "items": items,
    }


def _organization_categories(
    week_id: str, cards: list[dict[str, Any]], all_cards: list[dict[str, Any]],
    publish_repairs: list[tuple[dict[str, Any], str, str]],
) -> list[dict[str, Any]]:
    active = [record for record in cards if str(record.get("state") or _record_status(record)) == "active"]
    operational = [record for record in active if _record_status(record) == "active"]
    manual = [record for record in active if _record_status(record) in {"waiting_user", "blocked"}]

    promotions = [
        (record, "已登记草稿交付，尚未晋级正式交付", "确认内容后晋级正式交付并完成任务")
        for record in operational if "交付/草稿/" in str(record.get("delivery_folder") or "")
    ]
    closeouts = [
        (record, "已指向正式交付但任务仍在 active", "确认完成并移入 completed")
        for record in operational if "交付/正式交付/" in str(record.get("delivery_folder") or "")
    ]
    closeouts.extend(
        (record, "任务卡位于 active 范围但已标记完成", "核验正式交付后移入 completed")
        for record in active if _record_status(record) == "completed"
    )
    closeouts.extend(
        (record, reason, "核验对应模式证据后确认收口或继续执行")
        for record, reason in review.non_delivery_closeout_candidates(operational)
    )

    conflicts = [
        (record, reason, "逐项确认保留状态、文件归属和目录修复")
        for record, reason in review.duplicate_delivery_folders(cards)
    ]
    scoped_ids = {str(record.get("task_id") or "") for record in cards}
    repairs = [
        (record, reason, "核验后修复登记或目录结构")
        for record, reason in review.delivery_health_issues(all_cards)
        if str(record.get("task_id") or "") in scoped_ids
    ]
    repairs.extend(
        (record, "任务缺少 work_type", "补充或核对 work_type")
        for record in operational if not record.get("work_type")
    )
    repairs.extend(
        (record, f"原项目值 {record.get('source_project')} 已归一为 {record.get('project')}", "核对项目归属并按治理流程修正")
        for record in cards
        if record.get("source_project") and str(record.get("source_project")).casefold() != str(record.get("project")).casefold()
    )
    repairs.extend(publish_repairs)
    repairs.extend(
        (record, "delivery.folder 未使用精确 task_id 文件夹", "核对并修复交付登记")
        for record in operational
        if record.get("delivery_folder") and str(record.get("task_id") or "") not in str(record.get("delivery_folder") or "")
    )

    merges: list[tuple[dict[str, Any], str, str]] = []
    for index, left in enumerate(operational):
        for right in operational[index + 1:]:
            if left.get("project") != right.get("project"):
                continue
            left_title = str(left.get("task_name") or left.get("title") or "")
            right_title = str(right.get("task_name") or right.get("title") or "")
            ratio = SequenceMatcher(None, left_title, right_title).ratio()
            if ratio >= 0.72:
                candidate = dict(right)
                candidate["candidate_task_ids"] = [
                    str(left.get("task_id") or ""), str(right.get("task_id") or ""),
                ]
                merges.append((candidate, f"与《{left_title}》标题相似度 {ratio:.0%}", "确认合并、前后续或保持独立"))

    exceptions = [
        (record, f"人工状态为 {_record_status(record)}", "保留人工状态，不自动处理")
        for record in manual
    ]
    return [
        _category(week_id, "A", "草稿晋级正式交付", promotions, requires_confirmation=True),
        _category(week_id, "B", "任务完成与收口", closeouts, requires_confirmation=True),
        _category(week_id, "C", "登记与交付健康修复", repairs, requires_confirmation=True),
        _category(week_id, "D", "草稿与正式交付目录冲突", conflicts, requires_confirmation=True),
        _category(week_id, "E", "任务合并候选", merges, requires_confirmation=True),
        _category(week_id, "F", "人工例外状态", exceptions, requires_confirmation=False),
    ]


def _publish_repair_rows(
    records: list[dict[str, Any]], start_date: date, end_date: date,
) -> list[tuple[dict[str, Any], str, str]]:
    """Return bounded cached publish-archive gaps without exposing remote paths."""
    scan = archive_index.load_publish_scan()
    folders = scan.get("new_folders") if isinstance(scan.get("new_folders"), list) else []
    ledger_paths = {
        str(path) for record in records if record.get("record_type") == "ledger_row"
        for path in (record.get("paths") or [])
    }
    ledger_sequences = {
        str(record.get("seq") or "") for record in records
        if record.get("record_type") == "ledger_row" and record.get("seq")
    }
    rows: list[tuple[dict[str, Any], str, str]] = []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        folder_date = review.parse_date(folder.get("name"), str(folder.get("remote_path") or ""))
        if not folder_date or not start_date <= folder_date <= end_date:
            continue
        remote_path = str(folder.get("remote_path") or "")
        name = str(folder.get("name") or "")
        if remote_path in ledger_paths or any(name.startswith(sequence) for sequence in ledger_sequences):
            continue
        rows.append((
            {
                "task_id": "", "task_name": name, "title": name,
                "project": str(folder.get("project") or "independent"),
                "project_title": str(folder.get("project") or "未登记项目"),
                "status": "unmatched_publish_archive",
            },
            "本周缓存扫描发现发布归档文件夹尚无匹配发布记录",
            "确认是否补建发布记录",
        ))
    return rows


def _render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        f"# 余烬 · Ember 周报｜{packet['report_week']}", "",
        f"> 范围：{packet['window_start'][:10]} 至 {packet['window_end'][:10]}（右端不含）；本报告只读，任何晋级、收口、合并或修复都需逐项确认。",
        "", "## 一周总览", "",
        f"- 有效更新任务：{summary['tasks_touched']}",
        f"- 新建任务：{summary['tasks_created']}",
        f"- 草稿交付：{summary['draft_deliveries']}",
        f"- 正式交付：{summary['final_deliveries']}",
        f"- 发布记录：{summary['publishing_records']}",
        f"- 系统任务：{summary['system_tasks']}",
        f"- 待逐项确认：{summary['confirmation_items']}",
        "", "## 任务整理与确认", "",
    ]
    for category in packet["organization_proposal"]["categories"]:
        lines.extend([f"### {category['category']}｜{category['title']}（{category['count']}）", ""])
        if not category["items"]:
            lines.extend(["无。", ""])
            continue
        for item in category["items"]:
            label = "需逐项确认" if item["requires_item_confirmation"] else "只读保留"
            lines.append(
                f"- **{item['item_id']}** `{item['confirmation_key']}`｜{item['project_title']}｜"
                f"{item['title']}｜{item['status'] or '未标记'}｜{item['reason']}；建议：{item['suggested_action']}（{label}）"
            )
        lines.append("")
    health = packet["health"]
    lines.extend([
        "## 系统健康", "",
        f"- 共享工作区：{'可用' if health['shared_workspace_available'] else '不可用'}",
        f"- 任务索引：{health['task_index']['state']}",
        f"- Git：{'正常' if health['runtime_git']['clean'] and health['runtime_git']['origin_aligned'] else '需关注'}",
        "", "## 确认说明", "",
        "请按 `item_id + confirmation_key` 逐项确认；未明确确认的项目不得执行。",
    ])
    return "\n".join(lines) + "\n"


def build_packet(report_week: str = "latest", *, now: datetime | None = None, include_details: bool = True) -> dict[str, Any]:
    week_id, start_date, end_date, start, end = report_window(report_week, now=now)
    index = _read_json(INDEX_PATH)
    records = index.get("records")
    if not isinstance(records, list):
        raise WeeklyReportError("invalid GStudio task index: records must be a list")
    records = current_project_titles(records)
    all_cards = [item for item in records if isinstance(item, dict) and item.get("record_type") == "task_card"]
    cards = [item for item in all_cards if review.record_in_window(item, start_date, end_date)]
    releases = [
        item for item in records if isinstance(item, dict) and item.get("record_type") == "release_record"
        and daily._in_window(item.get("updated_at") or item.get("created_at"), start, end)
    ]
    public = [_public_task(item) for item in cards]
    created = [item for item in cards if review.record_created_in_window(item, start_date, end_date)]
    draft = [item for item in public if item["delivery_class"] == "draft"]
    final = [item for item in public if item["delivery_class"] == "final"]
    system = [item for item in public if item["project"] == "gstudio" and item["work_type"] == "system"]
    runtime = daily._runtime_activity(start, end)
    try:
        index_status = _read_json(INDEX_STATUS_PATH)
    except WeeklyReportError as exc:
        index_status = {"state": "missing", "cache_consistent": False, "error": str(exc)}
    shared_available = (shared_workspace_root() / "tasks").is_dir()
    categories = _organization_categories(
        week_id, cards, all_cards, _publish_repair_rows(records, start_date, end_date)
    )
    confirmation_items = sum(category["count"] for category in categories if category["requires_item_confirmation"])
    generated = (now or datetime.now(TZ)).astimezone(TZ)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": REPORT_KIND,
        "generated_at": generated.isoformat(timespec="seconds"),
        "report_week": week_id,
        "report_timezone": TIMEZONE_NAME,
        "scheduled_generation_time": "Monday 03:00 Asia/Shanghai on Mac mini",
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "source_of_truth": {
            "owner": "gstudio", "skill": "skills/gstudio-daily-report/SKILL.md",
            "style": "skills/gstudio-daily-report/references/weekly-report-style.md",
            "contract": "skills/gstudio-daily-report/references/weekly-handoff-contract.md",
            "policy_version": "gstudio-reporting-v2", "content_sha256": _source_hash(),
            "task_index_generated_at": str(index.get("generated_at") or ""),
        },
        "summary": {
            "tasks_touched": len(cards), "tasks_created": len(created),
            "draft_deliveries": len(draft), "final_deliveries": len(final),
            "publishing_records": len(releases), "system_tasks": len(system),
            "confirmation_items": confirmation_items,
        },
        "task_activity": {"items": public if include_details else []},
        "delivery_activity": {
            "draft_items": draft if include_details else [],
            "final_items": final if include_details else [],
        },
        "publishing_archive_activity": {
            "publishing_items": [
                {"release_id": str(item.get("release_id") or ""), "title": str(item.get("title") or item.get("task_name") or ""),
                 "project": str(item.get("project") or ""), "project_title": str(item.get("project_title") or item.get("project") or ""),
                 "status": str(item.get("status") or "")}
                for item in releases
            ] if include_details else [],
            "archive_tasks": len([item for item in public if item["artifact_mode"] == "archive" or item["work_type"] == "archive"]),
        },
        "runtime_activity": {"system_task_items": system if include_details else [], **runtime},
        "organization_proposal": {
            "proposal_only": True, "item_level_confirmation_required": True,
            "categories": categories if include_details else [
                {key: value for key, value in category.items() if key != "items"} | {"items": []}
                for category in categories
            ],
        },
        "health": {
            "healthy": shared_available and index_status.get("state") == "ok" and index_status.get("cache_consistent") is True
                       and runtime["clean"] and runtime["origin_aligned"] and runtime["branch"] == "main",
            "shared_workspace_available": shared_available,
            "task_index": {"state": str(index_status.get("state") or "unknown"), "cache_consistent": bool(index_status.get("cache_consistent")),
                           "last_check_at": str(index_status.get("last_check_at") or "")},
            "runtime_git": {"branch": runtime["branch"], "clean": runtime["clean"], "origin_aligned": runtime["origin_aligned"]},
        },
        "consumer_contract": {
            "reporting_agent": "caller", "read_only": True,
            "may": ["render", "cache_rendered_report", "transmit_rendered_report"],
            "may_not": ["modify_task_cards", "change_task_status", "promote_delivery", "modify_archive", "refresh_indexes", "change_git"],
        },
    }
    if include_details:
        packet["report_markdown"] = _render_markdown(packet)
    return packet


def get_weekly_report(report_week: str = "latest", *, include_style: bool = True,
                      include_details: bool = True, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(TZ)
    result: dict[str, Any] = {"packet": build_packet(report_week, now=current, include_details=include_details)}
    if include_style:
        result["style_markdown"] = STYLE_PATH.read_text(encoding="utf-8")
        result["handoff_contract_markdown"] = CONTRACT_PATH.read_text(encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read GStudio weekly handoff evidence")
    parser.add_argument("--week", default="latest", help="latest or YYYY-Www")
    parser.add_argument("--include-style", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    try:
        payload = get_weekly_report(args.week, include_style=args.include_style, include_details=not args.summary_only)
    except WeeklyReportError as exc:
        print(json.dumps({"error": "report_unavailable", "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
