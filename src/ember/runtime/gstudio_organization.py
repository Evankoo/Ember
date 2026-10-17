#!/usr/bin/env python3
"""Generate proposal-only GStudio organization reports and a derived index.

Weekly mode delegates its fixed date-window semantics to weekly_task_review.
Project, task-type, and task-status modes are read-only scans. No mode mutates
canonical task cards while generating a proposal.
"""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import datetime as dt
import json
import os
import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from . import gstudio_task as tasks
from . import weekly_task_review
from .workspace_paths import equivalent_path_strings

ROOT = _deployment_root()
ORGANIZATION_ROOT = tasks.SHARED_WORKSPACE_ROOT / "管理中心" / "整理记录"
INDEX_PATH = ORGANIZATION_ROOT / "整理总览.md"
HISTORY_PATH = ORGANIZATION_ROOT / "history.json"
MODES = ("weekly", "project", "task_type", "task_status")
MODE_LABELS = {
    "weekly": "按周整理",
    "project": "按项目整理",
    "task_type": "按任务类型整理",
    "task_status": "按任务状态整理",
}


def load_cards() -> list[dict[str, object]]:
    return [tasks.task_record(root, state, path) for root, state, path in tasks.task_files()]


def select_records(
    records: list[dict[str, object]], mode: str, scope: str = "", day: dt.date | None = None
) -> list[dict[str, object]]:
    if mode not in MODES:
        raise ValueError(f"不支持的整理模式：{mode}")
    scope = scope.strip()
    if mode == "weekly":
        review_identity = weekly_task_review.review_day(day or dt.date.today())
        start, end = weekly_task_review.review_window(review_identity)
        return [record for record in records if weekly_task_review.record_in_window(record, start, end)]
    if not scope:
        raise ValueError(f"{MODE_LABELS[mode]}必须提供 scope")
    if mode == "project":
        return [record for record in records if str(record.get("project") or "") == scope]
    if mode == "task_status":
        return [record for record in records if str(record.get("status") or "") == scope]
    return [
        record
        for record in records
        if str(record.get("work_type") or "") == scope
        or scope in [str(value) for value in (record.get("task_type") or [])]
    ]


def _date(value: object) -> dt.date | None:
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", str(value or ""))
    if not match:
        return None
    try:
        return dt.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def proposal_items(records: list[dict[str, object]]) -> dict[str, list[tuple[dict[str, object], str]]]:
    active = [record for record in records if record.get("status") == "active"]
    draft = [
        (record, "草稿交付已登记：确认内容后可晋级正式交付并完成收口")
        for record in active
        if "交付/草稿/" in str(record.get("delivery_folder") or "")
    ]
    formal = [
        (record, "任务仍在进行中但已指向正式交付：核对 finalize、状态和卡片位置")
        for record in active
        if "交付/正式交付/" in str(record.get("delivery_folder") or "")
    ]
    stale_cutoff = dt.date.today() - dt.timedelta(days=21)
    stale = [
        (record, "进行中任务超过 21 天未更新：确认继续、改写说明或完整收口")
        for record in active
        if (updated := _date(record.get("updated_at") or record.get("task_id"))) and updated < stale_cutoff
    ]
    exceptions = [
        (record, "人工例外状态：仅展示，未经 Evan 明确要求不修改")
        for record in records
        if record.get("status") in {"waiting_user", "blocked"}
    ]
    delivery_issues = [
        (record, "delivery.folder 未使用精确 task_id 文件夹")
        for record in records
        if (folder := str(record.get("delivery_folder") or "")) and str(record.get("task_id") or "") not in folder
    ]
    duplicates: list[tuple[dict[str, object], str]] = []
    comparable = [record for record in records if record.get("status") == "active"]
    for index, left in enumerate(comparable):
        for right in comparable[index + 1 :]:
            if left.get("project") != right.get("project"):
                continue
            left_title, right_title = str(left.get("title") or ""), str(right.get("title") or "")
            ratio = SequenceMatcher(None, left_title, right_title).ratio()
            if ratio >= 0.72:
                duplicates.append((right, f"与《{left_title}》相似度 {ratio:.0%}：确认合并、前后续或保持独立"))
    return {
        "draft_promotions": draft,
        "formal_closeout": formal,
        "stale_active": stale,
        "manual_exceptions": exceptions,
        "delivery_issues": delivery_issues,
        "merge_candidates": duplicates,
        "delivery_health": weekly_task_review.delivery_health_issues(records),
    }


def _table(items: list[tuple[dict[str, object], str]]) -> list[str]:
    if not items:
        return ["_无_", ""]
    lines = ["| 任务 | 项目 | 状态 | 建议 |", "|---|---|---|---|"]
    for record, reason in items:
        lines.append(
            f"| [{record.get('title')}](<{record.get('canonical_path')}>) | "
            f"{record.get('project_title')} | {record.get('status')} | {reason} |"
        )
    return [*lines, ""]


def generate(mode: str, scope: str = "", *, records: list[dict[str, object]] | None = None, day: dt.date | None = None) -> tuple[str, int]:
    all_records = records if records is not None else load_cards()
    selected = select_records(all_records, mode, scope, day)
    items = proposal_items(selected)
    label = MODE_LABELS[mode]
    effective_scope = scope or weekly_task_review.week_id(weekly_task_review.review_day(day or dt.date.today()))
    lines = [
        f"# 余烬 · Ember {label}报告｜{effective_scope}",
        "",
        "> 本报告只生成建议，不会自动创建、关闭、移动、合并或改写任务卡。所有变更必须由 Evan 逐项确认。",
        "",
        "## 范围",
        "",
        f"- 模式：`{mode}`",
        f"- 范围：`{effective_scope}`",
        f"- 范围内任务卡：{len(selected)}",
        "- mutated_task_cards：0",
        "",
        "## 草稿晋级候选（逐项确认)", "", *_table(items["draft_promotions"]),
        "## 正式交付收口候选（逐项确认）", "", *_table(items["formal_closeout"]),
        "## 长期未更新的进行中任务", "", *_table(items["stale_active"]),
        "## 合并候选（仅建议）", "", *_table(items["merge_candidates"]),
        "## 人工例外状态", "", *_table(items["manual_exceptions"]),
        "## 交付路径异常", "", *_table(items["delivery_issues"]),
        "## 交付目录与任务组健康检查", "", *_table(items["delivery_health"]),
        "## 下一步", "",
        "1. Evan 逐项确认需要执行的建议。",
        "2. 只执行确认项，并把已执行、跳过和验证结果继续写入本报告。",
        "3. 生成整理执行回执，刷新任务索引与整理中心索引；没有整理报告不得完成本轮整理任务。",
        "",
    ]
    return "\n".join(lines), len(selected)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _atomic_json(path: Path, payload: object) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _task_frontmatter(record: dict[str, object]) -> str:
    path = Path(str(record.get("canonical_path") or ""))
    cached = ROOT / "task-cards" / "source-cache" / "tasks" / str(record.get("state") or record.get("status") or "active") / f"{record.get('task_id')}.md"
    # Local pages consume the incrementally refreshed task mirror. The NAS
    # card remains a fallback; central mode keeps its NAS-local card first.
    candidates = (path, cached) if os.environ.get("GSTUDIO_CENTRAL_MODE") == "1" else (cached, path)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return tasks.frontmatter(candidate.read_text(encoding="utf-8"))[0]
        except OSError:
            continue
    return ""


def organization_metadata(record: dict[str, object]) -> tuple[str, str]:
    fm = _task_frontmatter(record)
    mode = tasks.nested_value(fm, "organization", "mode") if fm else ""
    scope = tasks.nested_value(fm, "organization", "report_week") if fm else ""
    if not mode:
        mode = tasks.nested_value(fm, "inputs", "organization_mode") if fm else ""
    if not scope:
        scope = tasks.nested_value(fm, "inputs", "organization_scope") if fm else ""
    blob = f"{record.get('task_id')} {record.get('title')}".lower()
    if mode not in MODES:
        if "weekly" in blob or "每周" in blob:
            mode = "weekly"
        elif "project" in blob or "项目" in blob:
            mode = "project"
        elif "status" in blob or "状态" in blob:
            mode = "task_status"
        elif "type" in blob or "类型" in blob:
            mode = "task_type"
        else:
            mode = "weekly"
    return mode, scope


def _report_path(record: dict[str, object]) -> Path | None:
    """Return an existing legacy/current report, or the standard expected path."""
    candidates: list[tuple[int, Path]] = []
    for value in record.get("paths", []) or []:
        for translated in equivalent_path_strings(Path(str(value)).expanduser()):
            path = Path(translated).expanduser()
            if path.is_file() and path.suffix.lower() == ".md":
                name = path.name.lower()
                score = 90 if "completion-report" in name or "完成报告" in name else 80 if "整理报告" in name else 60 if "整理建议" in name else 0
                if score:
                    candidates.append((score, path.resolve()))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    delivery = str(record.get("delivery_folder") or "").strip()
    if delivery:
        return tasks.SHARED_WORKSPACE_ROOT / delivery / "整理报告.md"
    return None


def rebuild_index(records: list[dict[str, object]] | None = None) -> tuple[Path, Path, int]:
    cards = records if records is not None else load_cards()
    organized = [record for record in cards if record.get("work_type") == "organize"]
    organized.sort(key=lambda record: str(record.get("updated_at") or ""), reverse=True)
    history: list[dict[str, object]] = []
    rows = []
    for record in organized:
        mode, scope = organization_metadata(record)
        entry = {
            "task_id": record.get("task_id"),
            "title": record.get("title"),
            "mode": mode,
            "scope": scope,
            "project": record.get("project"),
            "status": record.get("status"),
            "updated_at": record.get("updated_at"),
            "task_card": record.get("canonical_path"),
            "delivery_folder": record.get("delivery_folder"),
            "report_path": str(_report_path(record) or ""),
        }
        history.append(entry)
        delivery = str(record.get("delivery_folder") or "")
        delivery_path = tasks.SHARED_WORKSPACE_ROOT / delivery if delivery else None
        delivery_link = f"[打开](<{delivery_path}>)" if delivery_path else "-"
        rows.append(
            f"| [{record.get('title')}](<{record.get('canonical_path')}>) | {MODE_LABELS.get(mode, mode)} | "
            f"{scope or '-'} | {record.get('status')} | {record.get('updated_at') or '-'} | {delivery_link} |"
        )
    generated = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    markdown = "\n".join([
        "# 余烬 · Ember 整理中心",
        "",
        "> 这是从普通整理任务卡生成的索引，不是整理报告正本。报告正本位于各任务的标准交付文件夹。",
        "",
        f"- 更新时间：{generated}",
        f"- 整理任务：{len(organized)}",
        "- 模式：按周 / 按项目 / 按任务类型 / 按任务状态",
        "",
        "| 整理任务 | 模式 | 范围 | 状态 | 最近更新 | 交付文件夹 |",
        "|---|---|---|---|---|---|",
        *(rows or ["| 暂无整理任务 | - | - | - | - | - |"]),
        "",
    ])
    _atomic_text(INDEX_PATH, markdown)
    _atomic_json(HISTORY_PATH, {"generated_at": generated, "count": len(history), "records": history})
    return INDEX_PATH, HISTORY_PATH, len(history)


def write_proposal(task_id: str, mode: str, scope: str = "", *, day: dt.date | None = None) -> tuple[Path, int]:
    found = tasks.find_task(task_id)
    if not found:
        raise FileNotFoundError(f"找不到普通整理任务卡：{task_id}")
    _, state, path = found
    if state != "active":
        raise ValueError("整理建议只能写入 active 普通任务卡的草稿交付目录")
    fm, _ = tasks.frontmatter(path.read_text(encoding="utf-8"))
    if tasks.top_value(fm, "work_type") != "organize":
        raise ValueError("整理任务卡必须使用 work_type: organize")
    delivery_folder = tasks.nested_value(fm, "delivery", "folder")
    if not delivery_folder.startswith("交付/草稿/") or task_id not in delivery_folder:
        raise ValueError("整理任务卡必须使用精确的标准草稿交付文件夹")
    report, count = generate(mode, scope, day=day)
    destination = tasks.SHARED_WORKSPACE_ROOT / delivery_folder / "整理报告.md"
    _atomic_text(destination, report)
    return destination, count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--scope", default="")
    parser.add_argument("--task-id")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--refresh-index", action="store_true")
    args = parser.parse_args()
    if args.refresh_index:
        index, history, count = rebuild_index()
        print(json.dumps({"index": str(index), "history": str(history), "records": count}, ensure_ascii=False))
        return 0
    if not args.mode:
        parser.error("--mode 或 --refresh-index 至少提供一个")
    day = dt.date.fromisoformat(args.date) if args.date else None
    if args.mode == "weekly":
        parser.error("weekly 模式请使用 scripts/weekly_task_review.py，以保留固定自然周语义")
    if args.write:
        if not args.task_id:
            parser.error("--write 必须提供 --task-id")
        path, count = write_proposal(args.task_id, args.mode, args.scope, day=day)
        index, history, history_count = rebuild_index()
        print(json.dumps({
            "written": str(path), "mode": args.mode, "scope": args.scope,
            "records": count, "mutated_task_cards": 0,
            "index": str(index), "history": str(history), "history_records": history_count,
        }, ensure_ascii=False))
        return 0
    report, _ = generate(args.mode, args.scope, day=day)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
