#!/usr/bin/env python3
"""Build a read-only GStudio daily handoff packet from local indexed evidence."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = _deployment_root()
from .workspace_paths import shared_workspace_root
from .gstudio_task import current_project_titles

INDEX_PATH = ROOT / "task-cards" / "index.json"
INDEX_STATUS_PATH = ROOT / "task-cards" / "task-index-sync-status.json"
SKILL_PATH = ROOT / "skills" / "gstudio-daily-report" / "SKILL.md"
STYLE_PATH = ROOT / "skills" / "gstudio-daily-report" / "references" / "report-style.md"
CONTRACT_PATH = ROOT / "skills" / "gstudio-daily-report" / "references" / "handoff-contract.md"
TIMEZONE_NAME = "Asia/Shanghai"
TZ = ZoneInfo(TIMEZONE_NAME)
SCHEMA_VERSION = 2
REPORT_KIND = "gstudio_daily_handoff"


class DailyReportError(RuntimeError):
    """Raised when canonical indexed evidence cannot produce a valid packet."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DailyReportError(f"required GStudio evidence is missing: {path.name}") from exc
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise DailyReportError(f"invalid GStudio evidence: {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise DailyReportError(f"invalid GStudio evidence shape: {path.name}")
    return value


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def report_window(report_date: str = "latest", *, now: datetime | None = None) -> tuple[date, datetime, datetime]:
    current = (now or datetime.now(TZ)).astimezone(TZ)
    if report_date in {"", "latest"}:
        selected = current.date() - timedelta(days=1)
    else:
        try:
            selected = date.fromisoformat(report_date)
        except ValueError as exc:
            raise DailyReportError("report_date must be latest or YYYY-MM-DD") from exc
        if selected >= current.date():
            raise DailyReportError("report_date must be a complete calendar day before today")
    start = datetime.combine(selected, time.min, tzinfo=TZ)
    return selected, start, start + timedelta(days=1)


def reporting_schedule(report_date: str = "latest", *, now: datetime | None = None) -> dict[str, Any]:
    """Tell a reporting consumer whether normal daily prose should be shown.

    Explicit historical daily requests always remain available.  For the ordinary
    ``latest`` call on Monday, the complete weekly report is the primary report and
    this packet is retained only as an exception/health fallback.
    """
    current = (now or datetime.now(TZ)).astimezone(TZ)
    monday_weekly = report_date in {"", "latest"} and current.weekday() == 0
    return {
        "local_day": current.date().isoformat(),
        "weekday": current.strftime("%A").casefold(),
        "preferred_report_kind": "gstudio_weekly_handoff" if monday_weekly else REPORT_KIND,
        "suppress_daily_prose": monday_weekly,
        "daily_packet_role": "exceptions_and_health_fallback" if monday_weekly else "primary",
        "weekly_call": (
            {
                "tool": "gstudio_get_weekly_organization", "report_week": "latest",
                "source": "Mac mini frozen R01 or latest feedback revision",
            }
            if monday_weekly else None
        ),
    }


def _in_window(value: Any, start: datetime, end: datetime) -> bool:
    parsed = _parse_datetime(value)
    return bool(parsed and start <= parsed < end)


def _task_item(record: dict[str, Any]) -> dict[str, Any]:
    delivery_class = ""
    folder = str(record.get("delivery_folder") or "")
    state = str(record.get("delivery_state") or "").casefold()
    if "交付/草稿/" in folder or state in {"draft", "draft_delivered", "reviewing"}:
        delivery_class = "draft"
    elif "交付/正式交付/" in folder or state in {"final", "final_delivered", "formal"}:
        delivery_class = "final"
    return {
        "task_id": str(record.get("task_id") or ""),
        "title": str(record.get("task_name") or record.get("title") or record.get("task_id") or ""),
        "project": str(record.get("project") or "independent"),
        "project_title": str(record.get("project_title") or record.get("project") or "独立任务"),
        "status": str(record.get("status") or record.get("state") or ""),
        "work_type": str(record.get("work_type") or ""),
        "artifact_mode": str(record.get("artifact_mode") or ""),
        "delivery_class": delivery_class,
        "external_system": str(record.get("external_system") or ""),
        "external_job_id": str(record.get("external_job_id") or ""),
        "external_state": str(record.get("external_state") or ""),
        "updated_at": str(record.get("updated_at") or ""),
    }


def _git(*args: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", *args], cwd=ROOT, text=True, capture_output=True,
        timeout=15, check=False,
    )
    if result.returncode:
        return ""
    return result.stdout.strip()


def _runtime_activity(start: datetime, end: datetime) -> dict[str, Any]:
    separator = "\x1f"
    raw = _git(
        "log", f"--since={start.isoformat()}", f"--until={end.isoformat()}",
        f"--format=%h{separator}%s",
    )
    commits = []
    for line in raw.splitlines():
        if separator not in line:
            continue
        short_commit, subject = line.split(separator, 1)
        commits.append({"short_commit": short_commit, "subject": subject})
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    remote_head = _git("rev-parse", "origin/main")
    return {
        "commit_count": len(commits),
        "commits": commits,
        "branch": branch,
        "clean": not bool(_git("status", "--porcelain")),
        "head": head[:12],
        "origin_main": remote_head[:12],
        "origin_aligned": bool(head and remote_head and head == remote_head),
    }


def _source_hash() -> str:
    digest = hashlib.sha256()
    for path in (SKILL_PATH, STYLE_PATH, CONTRACT_PATH):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_packet(report_date: str = "latest", *, now: datetime | None = None) -> dict[str, Any]:
    selected, start, end = report_window(report_date, now=now)
    index = _read_json(INDEX_PATH)
    records = index.get("records")
    if not isinstance(records, list):
        raise DailyReportError("invalid GStudio task index: records must be a list")
    records = current_project_titles(records)
    task_records = [item for item in records if isinstance(item, dict) and item.get("record_type") == "task_card"]
    release_records = [item for item in records if isinstance(item, dict) and item.get("record_type") == "release_record"]
    touched_raw = [item for item in task_records if _in_window(item.get("updated_at") or item.get("created_at"), start, end)]
    created_raw = [item for item in task_records if _in_window(item.get("created_at"), start, end)]
    touched = [_task_item(item) for item in touched_raw]
    created_ids = {str(item.get("task_id") or "") for item in created_raw}
    active = [item for item in touched if item["status"] == "active" or str(item["status"]).startswith("waiting")]
    completed = [item for item in touched if item["status"] == "completed" or str(item["status"]) == "archived"]
    draft = [item for item in touched if item["delivery_class"] == "draft"]
    final = [item for item in touched if item["delivery_class"] == "final"]
    external_results = [item for item in touched if item["external_system"] and item["external_state"]]
    publishing = [
        {
            "release_id": str(item.get("release_id") or ""),
            "title": str(item.get("task_name") or item.get("title") or ""),
            "project": str(item.get("project") or ""),
            "project_title": str(item.get("project_title") or item.get("project") or ""),
            "status": str(item.get("status") or ""),
        }
        for item in release_records
        if _in_window(item.get("updated_at") or item.get("created_at"), start, end)
    ]
    archive_tasks = [
        item for item in touched
        if item["artifact_mode"] == "archive" or item["work_type"] == "archive"
    ]
    system_tasks = [
        item for item in touched
        if item["project"] == "gstudio" and item["work_type"] == "system"
    ]
    explicit_attention = [item for item in touched if item["status"] in {"waiting_user", "blocked"}]
    failed_external = [
        item for item in external_results
        if any(token in item["external_state"].casefold() for token in ("fail", "error", "blocked", "conflict"))
    ]
    runtime = _runtime_activity(start, end)
    try:
        index_status = _read_json(INDEX_STATUS_PATH)
    except DailyReportError as exc:
        index_status = {"state": "missing", "cache_consistent": False, "error": str(exc)}
    shared_available = (shared_workspace_root() / "tasks").is_dir()
    index_ok = index_status.get("state") == "ok" and index_status.get("cache_consistent") is True
    git_ok = runtime["clean"] and runtime["origin_aligned"] and runtime["branch"] == "main"
    health_issues: list[dict[str, str]] = []
    if not shared_available:
        health_issues.append({"kind": "shared_workspace", "status": "unavailable"})
    if not index_ok:
        health_issues.append({"kind": "task_index", "status": str(index_status.get("state") or "unhealthy")})
    if not git_ok:
        health_issues.append({"kind": "runtime_git", "status": "not_clean_or_aligned"})
    healthy = not health_issues
    generated = (now or datetime.now(TZ)).astimezone(TZ)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_kind": REPORT_KIND,
        "generated_at": generated.isoformat(timespec="seconds"),
        "report_date": selected.isoformat(),
        "report_timezone": TIMEZONE_NAME,
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "source_of_truth": {
            "owner": "gstudio",
            "skill": "skills/gstudio-daily-report/SKILL.md",
            "style": "skills/gstudio-daily-report/references/report-style.md",
            "contract": "skills/gstudio-daily-report/references/handoff-contract.md",
            "policy_version": "gstudio-reporting-v2",
            "content_sha256": _source_hash(),
            "task_index_generated_at": str(index.get("generated_at") or ""),
        },
        "task_activity": {
            "touched": len(touched),
            "created": len(created_raw),
            "created_task_ids": sorted(created_ids),
            "active_touched": len(active),
            "completed_state_touched": len(completed),
            "items": touched,
        },
        "delivery_activity": {
            "draft": len(draft),
            "final": len(final),
            "external_results": len(external_results),
            "draft_items": draft,
            "final_items": final,
            "external_items": external_results,
        },
        "publishing_archive_activity": {
            "publishing_records": len(publishing),
            "archive_tasks": len(archive_tasks),
            "publishing_items": publishing,
            "archive_items": archive_tasks,
        },
        "runtime_activity": {
            "system_tasks": len(system_tasks),
            "system_task_items": system_tasks,
            **runtime,
        },
        "attention": {
            "count": len(explicit_attention) + len(failed_external) + len(health_issues),
            "manual_task_states": explicit_attention,
            "external_failures": failed_external,
            "health_issues": health_issues,
        },
        "health": {
            "healthy": healthy,
            "shared_workspace_available": shared_available,
            "task_index": {
                "state": str(index_status.get("state") or "unknown"),
                "cache_consistent": bool(index_status.get("cache_consistent")),
                "last_check_at": str(index_status.get("last_check_at") or ""),
                "source_task_count": index_status.get("source_task_count"),
                "record_count": index_status.get("record_count"),
            },
            "runtime_git": {
                "branch": runtime["branch"],
                "clean": runtime["clean"],
                "origin_aligned": runtime["origin_aligned"],
            },
        },
        "consumer_contract": {
            "reporting_agent": "caller",
            "read_only": True,
            "may": ["render", "cache_rendered_report", "transmit_rendered_report"],
            "may_not": [
                "modify_task_cards", "change_task_status", "modify_delivery",
                "modify_archive", "refresh_indexes", "change_git", "edit_report_source",
            ],
        },
    }


def get_daily_report(report_date: str = "latest", *, include_style: bool = True, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(TZ)
    result: dict[str, Any] = {
        "packet": build_packet(report_date, now=current),
        "reporting_schedule": reporting_schedule(report_date, now=current),
    }
    if include_style:
        result["style_markdown"] = STYLE_PATH.read_text(encoding="utf-8")
        result["handoff_contract_markdown"] = CONTRACT_PATH.read_text(encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read GStudio daily handoff evidence")
    parser.add_argument("--date", default="latest", help="latest or YYYY-MM-DD")
    parser.add_argument("--include-style", action="store_true")
    args = parser.parse_args()
    try:
        payload = get_daily_report(args.date, include_style=args.include_style)
    except DailyReportError as exc:
        print(json.dumps({"error": "report_unavailable", "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
