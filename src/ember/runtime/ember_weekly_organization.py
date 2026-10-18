#!/usr/bin/env python3
"""Create, freeze, read, and revise one governed weekly organization round."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root
from ..process import module_command

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

ROOT = _deployment_root()
from . import ember_task as tasks
from . import ember_agent
from . import ember_weekly_report as weekly
from . import weekly_task_review

TZ = ZoneInfo("Asia/Shanghai")
REVIEW_ROOT = tasks.SHARED_TASK_ROOT / "每周整理"
LOCK_PATH = REVIEW_ROOT / ".weekly-organization.lock"
EXECUTION_STATE_NAME = "03_任务整理执行状态.json"
COMPLETION_REPORT_NAME = "03_任务整理完成报告.md"
AUTOMATIC_ACTIONS = {"promote_delivery", "complete_task"}


class WeeklyOrganizationError(RuntimeError):
    pass


def _now(value: datetime | None = None) -> datetime:
    return (value or datetime.now(TZ)).astimezone(TZ)


def _timestamp(value: datetime | None = None) -> str:
    return _now(value).strftime("%Y-%m-%d %H:%M:%S+08:00")


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def shared_lock() -> Iterator[None]:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def identity(report_week: str = "latest", *, now: datetime | None = None) -> dict[str, str]:
    week_id, start_date, end_date, _, end = weekly.report_window(report_week, now=_now(now))
    task_id = f"{end.date():%Y%m%d}-gstudio-weekly-organization"
    return {
        "report_week": week_id, "week_start": start_date.isoformat(),
        "week_end": end_date.isoformat(), "week_end_exclusive": end.date().isoformat(),
        "task_id": task_id,
        "title": f"{week_id.split('-W')[-1]}周每周任务整理", "revision_id": f"{week_id}-R01",
    }


def _paths(task_id: str) -> tuple[Path, Path, Path]:
    return (
        tasks.SHARED_TASK_ROOT / "active" / f"{task_id}.md",
        tasks.SHARED_TASK_ROOT / "completed" / f"{task_id}.md",
        tasks.SHARED_WORKSPACE_ROOT / "交付" / "草稿" / task_id,
    )


def _matching_weekly_task(info: dict[str, str]) -> tuple[Path, Path] | None:
    """Resolve one existing weekly round even when it uses a legacy task ID."""
    matches: list[tuple[int, Path, Path]] = []
    for state, rank in (("completed", 0), ("active", 1)):
        root = tasks.SHARED_TASK_ROOT / state
        if not root.is_dir():
            continue
        for path in root.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, _ = tasks.frontmatter(text)
            if tasks.top_value(fm, "work_type") != "organize":
                continue
            if tasks.top_value(fm, "merged_into"):
                continue
            mode = tasks.nested_value(fm, "organization", "mode") or tasks.nested_value(
                fm, "inputs", "organization_mode"
            )
            kind = tasks.top_value(fm, "task_kind")
            if mode != "weekly" and kind != "weekly_organization":
                continue
            report_week = tasks.nested_value(fm, "organization", "report_week")
            scope = tasks.nested_value(fm, "inputs", "organization_scope")
            same_week = report_week == info["report_week"] or info["report_week"] in text
            same_window = info["week_start"] in scope and info["week_end_exclusive"] in scope
            if not same_week and not same_window:
                continue
            task_id = tasks.top_value(fm, "task_id") or path.stem
            delivery = tasks.nested_value(fm, "delivery", "folder")
            if delivery:
                folder = tasks.SHARED_WORKSPACE_ROOT / delivery
            else:
                delivery_state = "正式交付" if state == "completed" else "草稿"
                folder = tasks.SHARED_WORKSPACE_ROOT / "交付" / delivery_state / task_id
            matches.append((rank, path, folder))
    if not matches:
        return None
    matches.sort(key=lambda value: (value[0], value[1].name))
    return matches[0][1], matches[0][2]


def _resolved_paths(info: dict[str, str]) -> tuple[Path, Path]:
    existing = _matching_weekly_task(info)
    if existing:
        return existing
    active, completed, folder = _paths(info["task_id"])
    if active.exists():
        return active, folder
    if completed.exists():
        return completed, tasks.SHARED_WORKSPACE_ROOT / "交付" / "正式交付" / info["task_id"]
    return active, folder


def _render_task(info: dict[str, str], now: datetime) -> str:
    stamp = _timestamp(now)
    return f'''---
type: gstudio_task
task_id: {info["task_id"]}
title: {info["title"]}
project: gstudio
work_type: organize
task_kind: weekly_organization
status: active
executor: external
created_at: "{stamp}"
updated_at: "{stamp}"
skills_used:
  - gstudio
  - ember-daily-report
  - ember-organization
artifact_mode: delivery
current_stage: awaiting_feedback
organization:
  mode: weekly
  report_week: {info["report_week"]}
  revision_id: {info["revision_id"]}
confirmations:
  promotions_confirmed: false
  completions_confirmed: false
  assignments_confirmed: false
---

# {info["title"]}

## 任务目标

冻结 {info["report_week"]} 的任务整理建议，记录 Evan 的逐项反馈，只执行明确确认项并形成回执。

## 任务描述

依据已冻结的周度报告组织确认与执行；报告编号和确认键只用于定位，不代表 Evan 已确认任何变更。

## 当前结果

- 整理范围：{info["week_start"]} 至 {info["week_end"]}，Asia/Shanghai。
- R01 生成阶段只读，不修改任何被审计任务。
- 报告编号与确认键不是确认，确认必须写入本任务。

## 确认记录

_尚未收到反馈。_

## 执行日志

- {stamp}：Mac mini 周一调度幂等创建本周整理任务，准备冻结 R01。
'''


def _gate(command: str, task_id: str, artifacts: list[Path] | None = None,
          *, run_id: str = "") -> None:
    args = module_command("ember.runtime.task_gate", command, "--task-id", task_id)
    if run_id:
        args.extend(["--run-id", run_id])
    for artifact in artifacts or []:
        args.extend(["--artifact", str(artifact)])
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode:
        raise WeeklyOrganizationError((result.stdout + result.stderr).strip())


def _revision_path(folder: Path, revision: int, suffix: str) -> Path:
    return folder / f"{revision:02d}_任务整理报告_R{revision:02d}.{suffix}"


def _snapshots(folder: Path) -> list[Path]:
    return sorted(folder.glob("*_任务整理报告_R*.json"))


def _load_latest(folder: Path) -> dict[str, Any]:
    files = _snapshots(folder)
    if not files:
        raise WeeklyOrganizationError("weekly organization snapshot is missing")
    try:
        value = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeeklyOrganizationError(f"invalid weekly snapshot: {exc}") from exc
    if not isinstance(value, dict):
        raise WeeklyOrganizationError("invalid weekly snapshot shape")
    return value


def _add_delivery(text: str, task_id: str, stamp: str, artifacts: list[Path]) -> str:
    if not re.search(r"^delivery:\s*$", text, re.MULTILINE):
        text = text.replace(
            "artifact_mode: delivery\n",
            f"artifact_mode: delivery\ndelivery:\n  state: draft\n  folder: 交付/草稿/{task_id}/\n", 1,
        )
        text = text.replace(
            "## 任务目标\n",
            f"## Quick Navigation\n\n- [打开交付文件夹](<{tasks.SHARED_WORKSPACE_ROOT / '交付/草稿' / task_id}/>)\n\n## 任务目标\n", 1,
        )
    text = re.sub(r'^updated_at:\s*.*$', f'updated_at: "{stamp}"', text, count=1, flags=re.MULTILINE)
    if "## 输出文件" not in text:
        output = "## 输出文件\n\n" + "\n".join(f"- `{path}`" for path in artifacts) + "\n\n"
        text = text.replace("## 确认记录\n", output + "## 确认记录\n", 1)
    return tasks.prepend_execution_log_entry(text, f"{stamp}：R01 已冻结到任务草稿交付目录。")


def generate(report_week: str = "latest", *, now: datetime | None = None) -> dict[str, Any]:
    current, info = _now(now), identity(report_week, now=now)
    with shared_lock():
        task, folder = _resolved_paths(info)
        if task.exists():
            actual_id = tasks.top_value(tasks.frontmatter(task.read_text(encoding="utf-8"))[0], "task_id") or task.stem
            if actual_id != info["task_id"] or task.parent.name == "completed":
                return {"created": False, "reused": True, **handoff(info["report_week"], include_style=False, now=current)}
        active, _, folder = _paths(info["task_id"])
        created = False
        if not active.exists():
            _atomic_text(active, _render_task(info, current))
            created = True
        _gate("preflight", info["task_id"])
        if _snapshots(folder):
            state = _load_latest(folder)
            revision = int(state.get("revision") or 1)
            artifacts = [folder / "00_当前任务整理报告.md", _revision_path(folder, revision, "md"), _revision_path(folder, revision, "json")]
            _atomic_text(active, _add_delivery(active.read_text(encoding="utf-8"), info["task_id"], _timestamp(current), artifacts))
            _gate("finalize", info["task_id"], artifacts)
            return {"created": created, "reused": True, **handoff(info["report_week"], include_style=False, now=current)}
        packet = weekly.build_packet(info["report_week"], now=current, include_details=True)
        state = {
            "schema_version": 1, "organization_task_id": info["task_id"],
            "report_week": info["report_week"], "revision": 1,
            "revision_id": info["revision_id"], "generated_at": current.isoformat(timespec="seconds"),
            "state": "awaiting_feedback", "decisions": {}, "packet": packet,
        }
        folder.mkdir(parents=True, exist_ok=True)
        markdown, metadata = _revision_path(folder, 1, "md"), _revision_path(folder, 1, "json")
        current_report = folder / "00_当前任务整理报告.md"
        _atomic_text(markdown, str(packet.get("report_markdown") or ""))
        _atomic_text(current_report, str(packet.get("report_markdown") or ""))
        _atomic_json(metadata, state)
        artifacts = [current_report, markdown, metadata]
        _atomic_text(active, _add_delivery(active.read_text(encoding="utf-8"), info["task_id"], _timestamp(current), artifacts))
        _gate("finalize", info["task_id"], artifacts)
        tasks.sync_index_records()
        return {"created": created, "reused": False, **handoff(info["report_week"], include_style=False, now=current)}


def _find(report_week: str, now: datetime | None = None) -> tuple[dict[str, str], Path, Path]:
    info = identity(report_week, now=now)
    task, folder = _resolved_paths(info)
    if not task.exists():
        raise WeeklyOrganizationError(f"weekly organization is not ready: {info['report_week']}")
    fm, _ = tasks.frontmatter(task.read_text(encoding="utf-8"))
    info = {**info, "task_id": tasks.top_value(fm, "task_id") or task.stem}
    return info, task, folder


def _legacy_handoff(info: dict[str, str], task: Path, folder: Path) -> dict[str, Any]:
    fm, _ = tasks.frontmatter(task.read_text(encoding="utf-8"))
    report_value = tasks.nested_value(fm, "outputs", "proposal")
    candidates = [Path(report_value)] if report_value else []
    candidates.extend((folder / "整理报告.md", folder / "00_当前任务整理报告.md"))
    report = next((path for path in candidates if path.is_file()), None)
    if report is None:
        raise WeeklyOrganizationError("existing weekly organization report is missing")
    status = tasks.top_value(fm, "status") or task.parent.name
    return {
        "organization_task": {
            "task_id": info["task_id"], "task_card": str(task),
            "report_week": info["report_week"], "revision": 1,
            "revision_id": f"{info['report_week']}-R01", "state": status,
            "report_path": str(report),
        },
        "packet": {
            "schema_version": 1, "report_kind": "weekly_organization_legacy",
            "report_week": info["report_week"], "report_timezone": "Asia/Shanghai",
            "window_start": info["week_start"], "window_end": info["week_end_exclusive"],
            "source_of_truth": "completed Ember weekly organization task",
        },
        "decisions": {},
        "report_markdown": report.read_text(encoding="utf-8"),
    }


def retire_duplicate(duplicate_task_id: str, surviving_task_id: str,
                     *, now: datetime | None = None) -> dict[str, Any]:
    """Retire one confirmed duplicate weekly round without promoting its draft."""
    if duplicate_task_id == surviving_task_id:
        raise WeeklyOrganizationError("duplicate and surviving task must differ")
    current = _now(now)
    duplicate_active, duplicate_completed, duplicate_folder = _paths(duplicate_task_id)
    _, surviving_completed, _ = _paths(surviving_task_id)
    surviving_folder = tasks.SHARED_WORKSPACE_ROOT / "交付" / "正式交付" / surviving_task_id
    if not duplicate_active.is_file() or duplicate_completed.exists():
        raise WeeklyOrganizationError("duplicate weekly task must be active only")
    if not surviving_completed.is_file():
        raise WeeklyOrganizationError("surviving weekly task must be completed")
    duplicate_text = duplicate_active.read_text(encoding="utf-8")
    surviving_text = surviving_completed.read_text(encoding="utf-8")
    duplicate_fm, _ = tasks.frontmatter(duplicate_text)
    surviving_fm, _ = tasks.frontmatter(surviving_text)
    for label, fm in (("duplicate", duplicate_fm), ("surviving", surviving_fm)):
        mode = tasks.nested_value(fm, "organization", "mode") or tasks.nested_value(
            fm, "inputs", "organization_mode"
        )
        if tasks.top_value(fm, "work_type") != "organize" or (
            mode != "weekly" and tasks.top_value(fm, "task_kind") != "weekly_organization"
        ):
            raise WeeklyOrganizationError(f"{label} task is not a weekly organization task")
    duplicate_week = tasks.nested_value(duplicate_fm, "organization", "report_week")
    if not duplicate_week:
        match = re.search(r"20\d{2}-W\d{2}", duplicate_text)
        duplicate_week = match.group(0) if match else ""
    if not duplicate_week:
        raise WeeklyOrganizationError("duplicate weekly task has no report week")
    info = identity(duplicate_week, now=current)
    surviving_scope = tasks.nested_value(surviving_fm, "inputs", "organization_scope")
    same_week = duplicate_week in surviving_text or (
        info["week_start"] in surviving_scope and info["week_end_exclusive"] in surviving_scope
    )
    if not same_week:
        raise WeeklyOrganizationError("weekly tasks do not cover the same report week")
    expected_folder = f"交付/草稿/{duplicate_task_id}/"
    if tasks.nested_value(duplicate_fm, "delivery", "folder") != expected_folder:
        raise WeeklyOrganizationError("duplicate task draft folder is not canonical")
    if not duplicate_folder.is_dir() or not surviving_folder.is_dir():
        raise WeeklyOrganizationError("weekly task delivery evidence is missing")
    stamp = _timestamp(current)
    revised = re.sub(r'^status:\s*.*$', 'status: completed', duplicate_text, count=1, flags=re.MULTILINE)
    revised = re.sub(r'^updated_at:\s*.*$', f'updated_at: "{stamp}"', revised, count=1, flags=re.MULTILINE)
    if re.search(r'^merged_into:', revised, re.MULTILINE):
        revised = re.sub(r'^merged_into:\s*.*$', f'merged_into: {surviving_task_id}', revised, count=1, flags=re.MULTILINE)
    else:
        revised = re.sub(r'(^task_id:\s*.*$)', rf'\1\nmerged_into: {surviving_task_id}', revised, count=1, flags=re.MULTILINE)
    if re.search(r'^current_stage:', revised, re.MULTILINE):
        revised = re.sub(r'^current_stage:\s*.*$', 'current_stage: retired_duplicate', revised, count=1, flags=re.MULTILINE)
    revised = tasks.prepend_execution_log_entry(
        revised,
        f"{stamp}：经 Evan 确认，本卡作为 {duplicate_week} 重复整理任务退役并回链 "
        f"`{surviving_task_id}`；草稿证据原位保留，未晋级、覆盖或删除。",
    )
    _atomic_text(duplicate_completed, revised)
    duplicate_active.unlink()
    tasks.sync_index_records()
    return {
        "retired_task_id": duplicate_task_id,
        "retired_task_card": str(duplicate_completed),
        "retained_draft_folder": str(duplicate_folder),
        "surviving_task_id": surviving_task_id,
        "surviving_task_card": str(surviving_completed),
        "surviving_delivery_folder": str(surviving_folder),
        "report_week": duplicate_week,
    }


def handoff(report_week: str = "latest", *, include_style: bool = True,
            now: datetime | None = None) -> dict[str, Any]:
    info, task, folder = _find(report_week, now)
    if not _snapshots(folder):
        result = _legacy_handoff(info, task, folder)
        if include_style:
            result["style_markdown"] = weekly.STYLE_PATH.read_text(encoding="utf-8")
            result["handoff_contract_markdown"] = weekly.CONTRACT_PATH.read_text(encoding="utf-8")
        return result
    state = _load_latest(folder)
    revision = int(state.get("revision") or 1)
    report = _revision_path(folder, revision, "md")
    packet = state.get("packet") if isinstance(state.get("packet"), dict) else {}
    runtime = packet.get("runtime_activity") if isinstance(packet.get("runtime_activity"), dict) else {}
    consumer_packet = {
        key: packet.get(key) for key in (
            "schema_version", "report_kind", "generated_at", "report_week",
            "report_timezone", "window_start", "window_end", "source_of_truth",
            "summary", "organization_proposal", "health", "consumer_contract",
        )
    }
    consumer_packet["runtime_summary"] = {
        "commit_count": runtime.get("commit_count"), "commits": runtime.get("commits", []),
        "branch": runtime.get("branch"), "clean": runtime.get("clean"),
        "origin_aligned": runtime.get("origin_aligned"),
    }
    result: dict[str, Any] = {
        "organization_task": {
            "task_id": info["task_id"], "task_card": str(task), "report_week": info["report_week"],
            "revision": revision, "revision_id": str(state.get("revision_id") or ""),
            "state": str(state.get("state") or ""), "report_path": str(report),
        },
        "packet": consumer_packet,
        "decisions": state.get("decisions") if isinstance(state.get("decisions"), dict) else {},
        "report_markdown": report.read_text(encoding="utf-8"),
    }
    try:
        execution = _execution_summary(state, _load_execution(folder, state))
        result["execution"] = execution
        if execution.get("state"):
            result["organization_task"]["state"] = execution["state"]
    except WeeklyOrganizationError:
        pass
    if include_style:
        result["style_markdown"] = weekly.STYLE_PATH.read_text(encoding="utf-8")
        result["handoff_contract_markdown"] = weekly.CONTRACT_PATH.read_text(encoding="utf-8")
    return result


def _feedback_report(packet: dict[str, Any], decisions: dict[str, Any], revision: int) -> str:
    labels = {"confirm": "确认执行", "reject": "不执行", "hold": "继续保留"}
    lines = [str(packet.get("report_markdown") or "").rstrip(), "", f"## Evan 反馈与确认｜R{revision:02d}", ""]
    for item in sorted(decisions.values(), key=lambda value: str(value.get("item_id") or "")):
        note = f"；备注：{item['note']}" if item.get("note") else ""
        lines.append(f"- **{item['item_id']}** `{item['confirmation_key']}`：{labels[item['decision']]}{note}")
    lines.extend(["", "> 只有“确认执行”项可进入受治理执行；其他项目不得修改。", ""])
    return "\n".join(lines)


def _update_task(text: str, decisions: dict[str, Any], stamp: str, artifacts: list[Path],
                 *, close_round: bool = False) -> str:
    confirmed = [value for value in decisions.values() if value["decision"] == "confirm"]
    promotion = any(value["action_code"] == "promote_delivery" for value in confirmed)
    completion = any(value["action_code"] == "complete_task" for value in confirmed)
    text = re.sub(r'^updated_at:\s*.*$', f'updated_at: "{stamp}"', text, count=1, flags=re.MULTILINE)
    stage = "confirmed_actions_pending_execution" if confirmed else (
        "round_closed_no_actions" if close_round else "awaiting_feedback"
    )
    text = re.sub(r'^current_stage:\s*.*$', f'current_stage: {stage}', text, count=1, flags=re.MULTILINE)
    text = re.sub(r'(^  promotions_confirmed:)\s*.*$', rf'\1 {str(promotion).lower()}', text, count=1, flags=re.MULTILINE)
    text = re.sub(r'(^  completions_confirmed:)\s*.*$', rf'\1 {str(completion).lower()}', text, count=1, flags=re.MULTILINE)
    rows = []
    for value in sorted(confirmed, key=lambda item: item["item_id"]):
        marker = {"promote_delivery": "confirmed-promotion", "complete_task": "confirmed-completion"}.get(value["action_code"], "confirmed-organization")
        rows.append(f"- {marker}: {value.get('task_id') or 'no-task-id'} | item: {value['item_id']} | key: {value['confirmation_key']}")
    body = "\n".join(rows) if rows else "_尚无确认执行项。_"
    for artifact in artifacts:
        line = f"- `{artifact}`"
        if line not in text:
            text = text.replace("## 确认记录\n", line + "\n\n## 确认记录\n", 1)
    text = re.sub(r"(^## 确认记录\s*$\n)(.*?)(?=^##\s+执行日志\s*$)", rf"\1\n{body}\n\n", text, count=1, flags=re.MULTILINE | re.DOTALL)
    return tasks.prepend_execution_log_entry(text, f"{stamp}：写入 Evan 反馈并生成新的确认版报告。")


def _set_nested_scalar(text: str, parent: str, key: str, value: str) -> str:
    pattern = rf"(^{re.escape(parent)}:\s*$\n(?:  .*\n)*?^  {re.escape(key)}:)\s*.*$"
    if re.search(pattern, text, re.MULTILINE):
        return re.sub(pattern, rf"\1 {value}", text, count=1, flags=re.MULTILINE)
    return text


def _merge_confirmation_details(raw: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    details = raw.get("details")
    if not isinstance(details, dict):
        raise WeeklyOrganizationError(f"merge confirmation requires structured details: {item.get('item_id')}")
    candidate_values = item.get("candidate_task_ids")
    candidates = [str(value) for value in candidate_values if str(value)] if isinstance(candidate_values, list) else []
    survivor = str(details.get("survivor_task_id") or "")
    source_values = details.get("source_task_ids")
    sources = [str(value) for value in source_values if str(value)] if isinstance(source_values, list) else []
    artifact_plan = details.get("artifact_plan")
    dispositions = details.get("source_lifecycle_dispositions")
    expected_sources = [value for value in candidates if value != survivor]
    if len(candidates) < 2 or survivor not in candidates or sorted(sources) != sorted(expected_sources):
        raise WeeklyOrganizationError(f"merge confirmation does not identify the exact candidates: {item.get('item_id')}")
    if artifact_plan != {"mode": "references"}:
        raise WeeklyOrganizationError(
            f"weekly merge supports only artifact_plan={{'mode':'references'}}; use the ordinary organization flow otherwise: {item.get('item_id')}"
        )
    if not isinstance(dispositions, dict) or set(dispositions) != set(sources) or any(
        str(value) not in {"retired_active", "retired_completed"}
        for value in dispositions.values()
    ):
        raise WeeklyOrganizationError(
            f"merge confirmation requires retired_active or retired_completed for every source: {item.get('item_id')}"
        )
    return {
        "survivor_task_id": survivor,
        "source_task_ids": sources,
        "artifact_plan": artifact_plan,
        "source_lifecycle_dispositions": {key: str(dispositions[key]).strip() for key in sources},
    }


def _receipt_matches_item(receipt: Any, item: dict[str, Any]) -> bool:
    expected_fingerprint = _confirmation_fingerprint(item)
    recorded_fingerprint = str(item.get("confirmation_fingerprint") or "")
    return isinstance(receipt, dict) and (not recorded_fingerprint or recorded_fingerprint == expected_fingerprint) and all(
        str(receipt.get(field) or "") == str(item.get(field) or "")
        for field in ("item_id", "confirmation_key", "task_id", "action_code")
    ) and str(receipt.get("confirmation_fingerprint") or "") == expected_fingerprint


def _confirmation_fingerprint(item: dict[str, Any]) -> str:
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


def record_feedback(task_id: str, revision_id: str, run_id: str, decisions: list[dict[str, Any]],
                    *, close_round: bool = False, now: datetime | None = None) -> dict[str, Any]:
    if not decisions and not close_round:
        raise WeeklyOrganizationError("feedback requires at least one decision or explicit close_round")
    current = _now(now)
    recorder_executor = _run_executor(_require_run(run_id, task_id))
    active, completed, folder = _paths(task_id)
    if completed.exists() or not active.exists():
        raise WeeklyOrganizationError("weekly organization task must be active")
    with shared_lock():
        state = _load_latest(folder)
        if str(state.get("revision_id") or "") != revision_id:
            raise WeeklyOrganizationError("revision_id is stale; read the latest report first")
        packet = state.get("packet") if isinstance(state.get("packet"), dict) else {}
        categories = packet.get("organization_proposal", {}).get("categories", [])
        frozen = {(str(i.get("item_id") or ""), str(i.get("confirmation_key") or "")): i for c in categories if isinstance(c, dict) for i in c.get("items", []) if isinstance(i, dict)}
        merged = dict(state.get("decisions") or {})
        execution_exists = _execution_path(folder).is_file()
        execution = _load_execution(folder, state) if execution_exists else None
        existing_receipts = execution.get("receipts", {}) if isinstance(execution, dict) else {}
        for raw in decisions:
            item_id, key = str(raw.get("item_id") or ""), str(raw.get("confirmation_key") or "")
            decision = str(raw.get("decision") or "").casefold()
            if (item_id, key) not in frozen or decision not in {"confirm", "reject", "hold"}:
                raise WeeklyOrganizationError(f"feedback does not match frozen item: {item_id}")
            item = frozen[(item_id, key)]
            if decision == "confirm" and not item.get("requires_item_confirmation"):
                raise WeeklyOrganizationError(f"display-only item cannot be confirmed: {item_id}")
            existing = existing_receipts.get(key) if isinstance(existing_receipts, dict) else None
            previous = merged.get(key) if isinstance(merged.get(key), dict) else item
            if _receipt_matches_item(existing, previous) and existing.get("state") == "succeeded" and decision != "confirm":
                raise WeeklyOrganizationError(f"cannot change a succeeded item's decision: {item_id}")
            details: dict[str, Any] = {}
            if decision == "confirm" and str(item.get("action_code") or "") == "merge":
                details = _merge_confirmation_details(raw, item)
            merged[key] = {
                "item_id": item_id, "confirmation_key": key, "decision": decision,
                "note": str(raw.get("note") or "").strip(), "task_id": str(item.get("task_id") or ""),
                "action_code": str(item.get("action_code") or "manual_organization"),
                "recorded_at": current.isoformat(timespec="seconds"),
                "feedback_source": "caller_reported_evan_feedback",
                "run_id": run_id, "executor": recorder_executor,
            }
            if details:
                merged[key]["details"] = details
                merged[key]["candidate_task_ids"] = [
                    str(value) for value in item.get("candidate_task_ids", []) if str(value)
                ]
            merged[key]["confirmation_fingerprint"] = _confirmation_fingerprint(merged[key])
        revision = int(state.get("revision") or 1) + 1
        next_id = f"{state['report_week']}-R{revision:02d}"
        markdown, metadata = _revision_path(folder, revision, "md"), _revision_path(folder, revision, "json")
        current_report = folder / "00_当前任务整理报告.md"
        report_text = _feedback_report(packet, merged, revision)
        confirmed = any(v["decision"] == "confirm" for v in merged.values())
        next_state = {**state, "revision": revision, "revision_id": next_id, "updated_at": current.isoformat(timespec="seconds"),
                      "state": "confirmed_actions_pending_execution" if confirmed else ("round_closed_no_actions" if close_round else "awaiting_feedback"), "decisions": merged}
        if close_round:
            next_state["close_round"] = {
                "decision": "close", "feedback_source": "caller_reported_evan_feedback",
                "run_id": run_id, "executor": recorder_executor,
                "recorded_at": current.isoformat(timespec="seconds"),
            }
        else:
            next_state.pop("close_round", None)
        _atomic_text(markdown, report_text)
        _atomic_text(current_report, report_text)
        _atomic_json(metadata, next_state)
        artifacts = [current_report, markdown, metadata]
        if execution is not None:
            migrated = {}
            for item in _confirmed(next_state):
                receipt = existing_receipts.get(str(item.get("confirmation_key") or ""))
                if _receipt_matches_item(receipt, item):
                    migrated[str(item["confirmation_key"])] = receipt
            execution.update({
                "organization_task_id": task_id, "report_week": str(state.get("report_week") or ""),
                "revision_id": next_id, "receipts": migrated,
                "updated_at": current.isoformat(timespec="seconds"),
            })
            migrated_status = _execution_summary(next_state, execution)
            execution["state"] = (
                "execution_needs_attention" if migrated_status["failed"] else
                "executing" if confirmed else
                "round_closed_no_actions" if close_round else "awaiting_feedback"
            )
            execution.pop("all_confirmed_succeeded", None)
            _atomic_json(_execution_path(folder), execution)
        revised_task = _update_task(
            active.read_text(encoding="utf-8"), merged, _timestamp(current), artifacts,
            close_round=close_round,
        )
        revised_task = _set_nested_scalar(revised_task, "organization", "revision_id", next_id)
        _atomic_text(active, revised_task)
        _gate("finalize", task_id, artifacts)
        tasks.sync_index_records()
        return handoff(str(state["report_week"]), include_style=False, now=current)


def _execution_path(folder: Path) -> Path:
    return folder / EXECUTION_STATE_NAME


def _completion_path(folder: Path) -> Path:
    return folder / COMPLETION_REPORT_NAME


def _confirmed(state: dict[str, Any]) -> list[dict[str, Any]]:
    values = state.get("decisions") if isinstance(state.get("decisions"), dict) else {}
    return sorted(
        (dict(value) for value in values.values() if isinstance(value, dict) and value.get("decision") == "confirm"),
        key=lambda value: str(value.get("item_id") or ""),
    )


def _load_execution(folder: Path, state: dict[str, Any]) -> dict[str, Any]:
    path = _execution_path(folder)
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WeeklyOrganizationError(f"invalid weekly execution state: {exc}") from exc
        if not isinstance(value, dict):
            raise WeeklyOrganizationError("invalid weekly execution state shape")
        if str(value.get("revision_id") or "") != str(state.get("revision_id") or ""):
            raise WeeklyOrganizationError("weekly execution state belongs to a stale revision")
        if str(value.get("organization_task_id") or "") != str(state.get("organization_task_id") or ""):
            raise WeeklyOrganizationError("weekly execution state belongs to another task")
        return value
    return {
        "schema_version": 1,
        "organization_task_id": str(state.get("organization_task_id") or ""),
        "report_week": str(state.get("report_week") or ""),
        "revision_id": str(state.get("revision_id") or ""),
        "state": "confirmed_actions_pending_execution",
        "updated_at": "",
        "receipts": {},
    }


def _require_run(run_id: str, task_id: str) -> dict[str, Any]:
    try:
        return ember_agent.require_run(run_id=run_id, mode="task_organization", task_id=task_id)
    except ember_agent.AgentError as exc:
        raise WeeklyOrganizationError(str(exc)) from exc


def _run_executor(run: dict[str, Any]) -> str:
    authorization = run.get("authorization") if isinstance(run.get("authorization"), dict) else {}
    executor = str(authorization.get("executor") or "")
    if not executor:
        raise WeeklyOrganizationError("authorized Agent run has no executor identity")
    return executor


def _target_record(task_id: str) -> tuple[str, str, Path, str] | None:
    found = tasks.find_task(task_id)
    if not found:
        return None
    root, state, path = found
    return root, state, path, path.read_text(encoding="utf-8", errors="replace")


def _automatic_outcome(item: dict[str, Any]) -> tuple[bool, str]:
    record = _target_record(str(item.get("task_id") or ""))
    if not record:
        return False, "target task is missing"
    _, state, _, text = record
    action = str(item.get("action_code") or "")
    if action == "promote_delivery":
        return (
            state == "completed"
            and tasks.top_value(tasks.frontmatter(text)[0], "status") == "completed"
            and tasks.nested_value(tasks.frontmatter(text)[0], "delivery", "state") == "final",
            "target is completed with formal delivery",
        )
    if action == "complete_task":
        return (
            state == "completed" and tasks.top_value(tasks.frontmatter(text)[0], "status") == "completed",
            "target task is completed",
        )
    return False, "action is not deterministic"


def _receipt(item: dict[str, Any], *, state: str, executor: str, run_id: str,
             summary: str, result_refs: list[str] | None = None,
             verification: dict[str, Any] | None = None,
             error: str = "", now: datetime | None = None) -> dict[str, Any]:
    value = {
        "item_id": str(item.get("item_id") or ""),
        "confirmation_key": str(item.get("confirmation_key") or ""),
        "task_id": str(item.get("task_id") or ""),
        "action_code": str(item.get("action_code") or ""),
        "confirmation_fingerprint": _confirmation_fingerprint(item),
        "state": state,
        "executor": executor,
        "run_id": run_id,
        "summary": re.sub(r"\s+", " ", summary).strip()[:300],
        "result_refs": list(dict.fromkeys(str(value) for value in (result_refs or []) if str(value).strip())),
        "recorded_at": _now(now).isoformat(timespec="seconds"),
    }
    if verification:
        value["verification"] = verification
    if error:
        value["error"] = re.sub(r"\s+", " ", error).strip()[:500]
    return value


def _execution_summary(state: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    confirmed = _confirmed(state)
    receipts = execution.get("receipts") if isinstance(execution.get("receipts"), dict) else {}
    rows = []
    for item in confirmed:
        receipt = receipts.get(str(item.get("confirmation_key") or ""))
        if not _receipt_matches_item(receipt, item):
            receipt = {
                "item_id": item.get("item_id"), "confirmation_key": item.get("confirmation_key"),
                "task_id": item.get("task_id"), "action_code": item.get("action_code"),
                "state": "pending" if item.get("action_code") in AUTOMATIC_ACTIONS else "pending_manual",
            }
        rows.append(receipt)
    succeeded = sum(1 for value in rows if value.get("state") == "succeeded")
    failed = sum(1 for value in rows if value.get("state") == "failed")
    pending_manual = sum(1 for value in rows if value.get("state") == "pending_manual")
    pending = len(rows) - succeeded - failed - pending_manual
    return {
        "organization_task_id": str(state.get("organization_task_id") or ""),
        "report_week": str(state.get("report_week") or ""),
        "revision_id": str(state.get("revision_id") or ""),
        "state": str(execution.get("state") or "confirmed_actions_pending_execution"),
        "confirmed": len(rows), "succeeded": succeeded, "failed": failed,
        "pending": pending, "pending_manual": pending_manual,
        "ready_to_finalize": bool(rows) and succeeded == len(rows) and not failed and not pending and not pending_manual
                             or not rows and isinstance(state.get("close_round"), dict)
                             and state["close_round"].get("decision") == "close",
        "close_round": isinstance(state.get("close_round"), dict)
                       and state["close_round"].get("decision") == "close",
        "items": rows,
    }


def execution_status(report_week: str = "latest", *, now: datetime | None = None) -> dict[str, Any]:
    _, task, folder = _find(report_week, now)
    snapshots = _snapshots(folder)
    if not snapshots:
        fm, _ = tasks.frontmatter(task.read_text(encoding="utf-8"))
        completed = tasks.top_value(fm, "status") == "completed"
        return {"organization_task_id": task.stem, "report_week": report_week,
                "state": "completed" if completed else "legacy", "confirmed": 0,
                "succeeded": 0, "failed": 0, "pending": 0, "pending_manual": 0,
                "ready_to_finalize": False, "items": []}
    state = _load_latest(folder)
    execution = _load_execution(folder, state)
    summary = _execution_summary(state, execution)
    fm, _ = tasks.frontmatter(task.read_text(encoding="utf-8"))
    if tasks.top_value(fm, "status") == "completed":
        summary["state"] = "completed"
    return summary


def execute_confirmed(task_id: str, revision_id: str, run_id: str,
                      *, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    executor = _run_executor(_require_run(run_id, task_id))
    active, completed, folder = _paths(task_id)
    if completed.exists() or not active.exists():
        raise WeeklyOrganizationError("weekly organization task must be active")
    _gate("preflight", task_id)
    with shared_lock():
        state = _load_latest(folder)
        if str(state.get("revision_id") or "") != revision_id:
            raise WeeklyOrganizationError("revision_id is stale; read the latest report first")
        execution = _load_execution(folder, state)
        receipts = execution.get("receipts") if isinstance(execution.get("receipts"), dict) else {}
        for item in _confirmed(state):
            key = str(item.get("confirmation_key") or "")
            if (
                _receipt_matches_item(receipts.get(key), item)
                and receipts[key].get("state") == "succeeded"
                and receipts[key].get("run_id") == run_id
                and receipts[key].get("executor") == executor
            ):
                continue
            action = str(item.get("action_code") or "")
            if action not in AUTOMATIC_ACTIONS:
                continue
            ok, summary = _automatic_outcome(item)
            error = ""
            if not ok:
                command = "promote-delivery" if action == "promote_delivery" else "complete-task"
                try:
                    args = module_command("ember.runtime.task_gate", command, "--task-id", str(item.get("task_id") or ""), "--organization-task-id", task_id)
                    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
                    if result.returncode:
                        error = (result.stdout + result.stderr).strip()
                    ok, summary = _automatic_outcome(item)
                except OSError as exc:
                    error = str(exc)
            receipts[key] = _receipt(
                item, state="succeeded" if ok else "failed", executor=executor, run_id=run_id,
                summary=summary, result_refs=[str(item.get("task_id") or "")],
                verification={"canonical_outcome": summary} if ok else None, error=error,
                now=current,
            )
        execution["receipts"] = receipts
        execution["updated_at"] = current.isoformat(timespec="seconds")
        summary = _execution_summary(state, execution)
        execution["state"] = "execution_needs_attention" if summary["failed"] else "executing"
        _atomic_json(_execution_path(folder), execution)
        task_text = active.read_text(encoding="utf-8")
        task_text = re.sub(r'^updated_at:\s*.*$', f'updated_at: "{_timestamp(current)}"', task_text, count=1, flags=re.MULTILINE)
        task_text = re.sub(r'^current_stage:\s*.*$', f'current_stage: {execution["state"]}', task_text, count=1, flags=re.MULTILINE)
        task_text = tasks.prepend_execution_log_entry(
            task_text,
            f"{_timestamp(current)}：通过受治理执行接口处理已确认项；成功 {summary['succeeded']}/{summary['confirmed']}，失败 {summary['failed']}，待 Agent 回执 {summary['pending_manual']}。",
        )
        _atomic_text(active, task_text)
        tasks.sync_index_records()
        return _execution_summary(state, execution)


def record_execution_receipt(task_id: str, revision_id: str, item_id: str,
                             confirmation_key: str, run_id: str, state_value: str,
                             summary: str, result_refs: list[str] | None = None,
                             verification: dict[str, Any] | None = None,
                             *, now: datetime | None = None) -> dict[str, Any]:
    if state_value not in {"succeeded", "failed"}:
        raise WeeklyOrganizationError("execution receipt state must be succeeded or failed")
    current = _now(now)
    executor = _run_executor(_require_run(run_id, task_id))
    active, completed, folder = _paths(task_id)
    if completed.exists() or not active.exists():
        raise WeeklyOrganizationError("weekly organization task must be active")
    with shared_lock():
        state = _load_latest(folder)
        if str(state.get("revision_id") or "") != revision_id:
            raise WeeklyOrganizationError("revision_id is stale; read the latest report first")
        item = next((value for value in _confirmed(state)
                     if value.get("item_id") == item_id and value.get("confirmation_key") == confirmation_key), None)
        if not item:
            raise WeeklyOrganizationError("execution receipt does not match a confirmed item")
        if str(item.get("action_code") or "") in AUTOMATIC_ACTIONS:
            raise WeeklyOrganizationError("deterministic actions must be receipted by execute_weekly_organization")
        execution = _load_execution(folder, state)
        receipts = execution.get("receipts") if isinstance(execution.get("receipts"), dict) else {}
        existing = receipts.get(confirmation_key)
        if (
            _receipt_matches_item(existing, item)
            and existing.get("state") == "succeeded"
            and existing.get("run_id") == run_id
            and existing.get("executor") == executor
        ):
            return _execution_summary(state, execution)
        refs = list(dict.fromkeys(str(value) for value in (result_refs or []) if str(value).strip()))
        checked_verification = verification if isinstance(verification, dict) else {}
        action = str(item.get("action_code") or "")
        if state_value == "succeeded" and action != "merge":
            raise WeeklyOrganizationError("successful semantic receipts are supported only for canonically validated merges")
        if state_value == "succeeded" and not refs:
            raise WeeklyOrganizationError("successful merge receipt requires result_refs")
        if state_value == "succeeded" and action == "merge":
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            survivor = str(details.get("survivor_task_id") or "")
            source_values = details.get("source_task_ids")
            sources = [str(value) for value in source_values if str(value)] if isinstance(source_values, list) else []
            disposition_values = details.get("source_lifecycle_dispositions")
            dispositions = disposition_values if isinstance(disposition_values, dict) else {}
            if not survivor or not sources:
                raise WeeklyOrganizationError("merge receipt is missing exact confirmed merge details")
            if not _target_record(survivor):
                raise WeeklyOrganizationError(f"merge survivor task is missing: {survivor}")
            canonical_sources: dict[str, Any] = {}
            for source in sources:
                record = _target_record(source)
                disposition = str(dispositions.get(source) or "")
                expected_state = {
                    "retired_active": "active", "retired_completed": "completed",
                }.get(disposition)
                if not record or tasks.top_value(tasks.frontmatter(record[3])[0], "merged_into") != survivor:
                    raise WeeklyOrganizationError(f"merge source does not link to the confirmed survivor: {source}")
                source_status = tasks.top_value(tasks.frontmatter(record[3])[0], "status")
                expected_path = tasks.SHARED_TASK_ROOT / str(expected_state) / f"{source}.md"
                if (
                    not expected_state or record[0] != "icloud" or record[2] != expected_path
                    or record[1] != expected_state or source_status != expected_state
                ):
                    raise WeeklyOrganizationError(
                        f"merge source lifecycle does not match {disposition}: {source}"
                    )
                canonical_sources[source] = {
                    "merged_into": survivor, "disposition": disposition,
                    "task_state": record[1], "status": source_status,
                    "task_card": str(record[2]),
                }
            checked_verification = {
                "survivor_task_id": survivor,
                "source_tasks": canonical_sources,
            }
        receipts[confirmation_key] = _receipt(
            item, state=state_value, executor=executor, run_id=run_id, summary=summary,
            result_refs=refs, verification=checked_verification, now=current,
        )
        execution["receipts"] = receipts
        execution["updated_at"] = current.isoformat(timespec="seconds")
        status = _execution_summary(state, execution)
        execution["state"] = "execution_needs_attention" if status["failed"] else "executing"
        _atomic_json(_execution_path(folder), execution)
        task_text = active.read_text(encoding="utf-8")
        task_text = re.sub(r'^updated_at:\s*.*$', f'updated_at: "{_timestamp(current)}"', task_text, count=1, flags=re.MULTILINE)
        task_text = re.sub(r'^current_stage:\s*.*$', f'current_stage: {execution["state"]}', task_text, count=1, flags=re.MULTILINE)
        task_text = tasks.prepend_execution_log_entry(
            task_text,
            f"{_timestamp(current)}：登记 {item_id} 执行回执：{state_value}（run_id `{run_id}`）。",
        )
        _atomic_text(active, task_text)
        tasks.sync_index_records()
        return _execution_summary(state, execution)


def _completion_report(state: dict[str, Any], status: dict[str, Any], executor: str,
                       current: datetime) -> str:
    lines = [
        f"# 余烬 · Ember 每周任务整理完成报告｜{state.get('report_week')}", "",
        "## 结论", "",
        f"- 本轮确认执行 {status['confirmed']} 项，成功 {status['succeeded']} 项，失败 0 项。",
        f"- 执行入口：{executor}", f"- 完成时间：{current.isoformat(timespec='seconds')}", "",
        "## 执行回执", "",
    ]
    if status["items"]:
        for item in status["items"]:
            lines.append(
                f"- **{item.get('item_id')}** `{item.get('confirmation_key')}`｜{item.get('action_code')}"
                f"｜{item.get('task_id')}｜成功｜{item.get('summary') or '已验证'}"
            )
    else:
        lines.append("- Evan 已明确关闭本轮，且未确认任何执行项。")
    held = [value for value in (state.get("decisions") or {}).values()
            if isinstance(value, dict) and value.get("decision") != "confirm"]
    lines.extend(["", "## 未执行项", ""])
    if held:
        for item in sorted(held, key=lambda value: str(value.get("item_id") or "")):
            lines.append(f"- **{item.get('item_id')}**：{item.get('decision')}，保持原状态。")
    else:
        lines.append("_无。_")
    lines.extend(["", "## 验证", "", "- 所有确认项均有结构化执行回执。", "- 任务索引已刷新。", ""])
    return "\n".join(lines)


def finalize_organization(task_id: str, revision_id: str, run_id: str,
                          *, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    executor = _run_executor(_require_run(run_id, task_id))
    active, completed, folder = _paths(task_id)
    if completed.exists():
        folder = tasks.SHARED_WORKSPACE_ROOT / "交付" / "正式交付" / task_id
        if not _snapshots(folder):
            fm, _ = tasks.frontmatter(completed.read_text(encoding="utf-8"))
            return {
                "organization_task_id": task_id,
                "report_week": tasks.nested_value(fm, "organization", "report_week"),
                "revision_id": revision_id,
                "state": "completed", "legacy": True,
                "confirmed": 0, "succeeded": 0, "failed": 0,
                "pending": 0, "pending_manual": 0,
                "ready_to_finalize": False, "items": [],
                "task_card": str(completed), "completion_report": "",
            }
        state = _load_latest(folder)
        if str(state.get("revision_id") or "") != revision_id:
            raise WeeklyOrganizationError("revision_id is stale; read the latest report first")
        return execution_status(str(state.get("report_week") or "latest"), now=current)
    if not active.exists():
        raise WeeklyOrganizationError("weekly organization task must be active")
    with shared_lock():
        state = _load_latest(folder)
        if str(state.get("revision_id") or "") != revision_id:
            raise WeeklyOrganizationError("revision_id is stale; read the latest report first")
        execution = _load_execution(folder, state)
        status = _execution_summary(state, execution)
        if not status["ready_to_finalize"]:
            raise WeeklyOrganizationError(
                f"weekly organization is not ready: succeeded={status['succeeded']}/{status['confirmed']}, "
                f"failed={status['failed']}, pending_manual={status['pending_manual']}"
            )
        _atomic_text(_completion_path(folder), _completion_report(state, status, executor, current))
        execution["state"] = "ready_to_finalize"
        execution["all_confirmed_succeeded"] = True
        execution["updated_at"] = current.isoformat(timespec="seconds")
        _atomic_json(_execution_path(folder), execution)
        task_text = active.read_text(encoding="utf-8")
        task_text = re.sub(r'^updated_at:\s*.*$', f'updated_at: "{_timestamp(current)}"', task_text, count=1, flags=re.MULTILINE)
        task_text = re.sub(r'^current_stage:\s*.*$', 'current_stage: ready_to_finalize', task_text, count=1, flags=re.MULTILINE)
        for path in (_execution_path(folder), _completion_path(folder)):
            line = f"- `{path}`"
            if line not in task_text:
                task_text = task_text.replace("## 确认记录\n", line + "\n\n## 确认记录\n", 1)
        task_text = tasks.prepend_execution_log_entry(
            task_text,
            f"{_timestamp(current)}：全部确认项已取得成功回执，生成正式完成报告，准备通过专用门禁收口。",
        )
        _atomic_text(active, task_text)
    _gate("finalize-weekly-organization", task_id, run_id=run_id)
    final_folder = tasks.SHARED_WORKSPACE_ROOT / "交付" / "正式交付" / task_id
    compatibility_error = ""
    try:
        start = str((state.get("packet") or {}).get("window_start") or "")[:10]
        review_day = datetime.fromisoformat(start).date()
        weekly_task_review.mark_complete(
            review_day, executor,
            "已通过 canonical 周整理任务回执完成收口。",
            final_folder / COMPLETION_REPORT_NAME,
        )
    except Exception as exc:
        compatibility_error = f"{type(exc).__name__}: {exc}"
    result = execution_status(str(state.get("report_week") or "latest"), now=current)
    result["task_card"] = str(tasks.SHARED_TASK_ROOT / "completed" / f"{task_id}.md")
    result["completion_report"] = str(final_folder / COMPLETION_REPORT_NAME)
    if compatibility_error:
        result["compatibility_cache_warning"] = compatibility_error
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "read"):
        child = sub.add_parser(name); child.add_argument("--week", default="latest")
    feedback = sub.add_parser("feedback")
    feedback.add_argument("--task-id", required=True); feedback.add_argument("--revision-id", required=True)
    feedback.add_argument("--run-id", required=True); feedback.add_argument("--decisions-json", required=True)
    feedback.add_argument("--close-round", action="store_true")
    retire = sub.add_parser("retire-duplicate")
    retire.add_argument("--duplicate-task-id", required=True)
    retire.add_argument("--surviving-task-id", required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("--task-id", required=True); execute.add_argument("--revision-id", required=True)
    execute.add_argument("--run-id", required=True)
    status = sub.add_parser("status"); status.add_argument("--week", default="latest")
    receipt = sub.add_parser("receipt")
    receipt.add_argument("--task-id", required=True); receipt.add_argument("--revision-id", required=True)
    receipt.add_argument("--item-id", required=True); receipt.add_argument("--confirmation-key", required=True)
    receipt.add_argument("--run-id", required=True); receipt.add_argument("--state", required=True)
    receipt.add_argument("--summary", required=True); receipt.add_argument("--result-ref", action="append", default=[])
    receipt.add_argument("--verification-json", default="{}")
    finish = sub.add_parser("finalize")
    finish.add_argument("--task-id", required=True); finish.add_argument("--revision-id", required=True)
    finish.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "generate": result = generate(args.week)
        elif args.command == "read": result = handoff(args.week)
        elif args.command == "feedback":
            value = json.loads(args.decisions_json)
            if not isinstance(value, list): raise WeeklyOrganizationError("decisions-json must be a list")
            result = record_feedback(args.task_id, args.revision_id, args.run_id, value, close_round=args.close_round)
        elif args.command == "retire-duplicate":
            result = retire_duplicate(args.duplicate_task_id, args.surviving_task_id)
        elif args.command == "execute":
            result = execute_confirmed(args.task_id, args.revision_id, args.run_id)
        elif args.command == "status": result = execution_status(args.week)
        elif args.command == "receipt":
            verification = json.loads(args.verification_json)
            if not isinstance(verification, dict): raise WeeklyOrganizationError("verification-json must be an object")
            result = record_execution_receipt(args.task_id, args.revision_id, args.item_id,
                args.confirmation_key, args.run_id, args.state, args.summary, args.result_ref,
                verification)
        else: result = finalize_organization(args.task_id, args.revision_id, args.run_id)
    except (WeeklyOrganizationError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": "weekly_organization_failed", "detail": str(exc)}, ensure_ascii=False, indent=2)); return 1
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
