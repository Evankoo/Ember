#!/usr/bin/env python3
"""Restricted local stdio MCP surface for deterministic Ember task operations."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root
from ..process import module_command

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from argparse import Namespace
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = _deployment_root()
from . import ember_task
from .ember_project import load_work_categories
from . import ember_daily_report
from . import ember_weekly_report
from . import ember_weekly_organization
from . import task_intake
from . import ember_system_bridge as bridge
from .workspace_paths import shared_task_root


def now_beijing() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S+08:00")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _preflight(task_id: str) -> None:
    result = subprocess.run(
        module_command("ember.runtime.task_gate", "preflight", "--continuation", "--task-id", task_id),
        cwd=ROOT, text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr).strip())


@contextmanager
def _shared_bridge_lock(key: str):
    root = shared_task_root()
    if not root.parent.is_dir() or (str(root.parent).startswith("/Volumes/") and not os.path.ismount(root.parent)):
        raise RuntimeError("shared task root unavailable; no local write fallback")
    lock_dir = root.parent / ".gstudio-task-bridge"
    lock_dir.mkdir(exist_ok=True)
    with (lock_dir / f"{key}.lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield root


def _registered_scope(project: str) -> dict[str, Any]:
    payload = ember_task.load_projects()
    if project == "independent":
        item = payload.get("independent_scope")
    else:
        item = next((value for value in payload.get("projects", []) if value.get("slug") == project), None)
    if not isinstance(item, dict):
        raise ValueError(f"unregistered project slug: {project}")
    return item


def _project_category_context(scope: dict[str, Any]) -> dict[str, Any]:
    """Expose registered project context; never classify a task by title or tool."""
    category = scope.get("work_category")
    rule = load_work_categories().get(category, {})
    return {"project_work_category": category, "project_work_category_title": rule.get("title")}


def _continuation_task(task_id: str):
    """Follow only an already-confirmed merged_into relation; never mutate source evidence."""
    redirected = []
    for _ in range(16):
        bridge.validate_task_id(task_id)
        if task_id in redirected:
            raise ValueError("merged task continuation cycle")
        found = ember_task.find_task(task_id)
        if not found:
            raise ValueError(f"existing task not found: {task_id}")
        fm, _ = ember_task.frontmatter(found[2].read_text(encoding="utf-8"))
        successor = ember_task.top_value(fm, "merged_into")
        if not successor:
            return task_id, found, redirected
        redirected.append(task_id)
        task_id = successor
    raise ValueError("merged task continuation chain is too long")


def ember_task_route(
    *, has_input: bool = False, independent_deliverable: bool = False,
    multi_step: bool = False, needs_confirmation: bool = False,
    external_mutation: bool = False, system_change: bool = False,
    confirmed_simple_copy: bool = False, project: str = "independent",
    existing_task_id: str = "", capability: str = "",
) -> dict[str, Any]:
    """Apply the necessity gate and return an existing capability route; never execute it."""
    system_route = bridge.route(capability)
    if existing_task_id:
        existing_task_id, found, redirected = _continuation_task(existing_task_id)
        fm, _ = ember_task.frontmatter(found[2].read_text(encoding="utf-8"))
        result = {"mode": "continue_existing", "task_card_required": True, "task_id": existing_task_id, "project": ember_task.top_value(fm, "project")}
        result.update(_project_category_context(ember_task.project_registry()[0].get(str(result["project"]), {})))
        if system_route:
            result["system_route"] = system_route
        if redirected:
            result["redirected_from_task_ids"] = redirected
        return result
    scope = _registered_scope(project)
    retrieval_only = bool(system_route and system_route.get("read_only") and not any((independent_deliverable, multi_step, needs_confirmation, external_mutation, system_change, confirmed_simple_copy)))
    args = Namespace(
        has_input=has_input and not retrieval_only, independent_deliverable=independent_deliverable,
        multi_step=multi_step, needs_confirmation=needs_confirmation,
        external_mutation=external_mutation, system_change=system_change,
        confirmed_simple_copy=confirmed_simple_copy,
    )
    decision = task_intake.decide(args)
    if decision["task_card_required"]:
        policy = scope.get("artifact_policy") if isinstance(scope.get("artifact_policy"), dict) else {}
        decision["artifact_mode"] = str(policy.get("default_mode") or decision["artifact_mode"])
    decision["project"] = project
    decision.update(_project_category_context(scope))
    if system_route:
        decision["system_route"] = system_route
    return decision


def _external_value(fm: str, key: str) -> str:
    block = ember_task.nested_block(fm, "external")
    match = re.search(rf"^  {re.escape(key)}:[ \t]*(.*?)$", block[2], re.MULTILINE) if block else None
    if not match:
        return ""
    raw = match.group(1).strip()
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
            if isinstance(value, str):
                return value
        except ValueError:
            pass
    return raw.strip("\"'")


def _existing_by_correlation(external_system: str, correlation_id: str) -> str:
    for _, _, path in ember_task.task_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, _ = ember_task.frontmatter(text)
        if (
            _external_value(fm, "system") == external_system
            and _external_value(fm, "correlation_id") == correlation_id
        ):
            return ember_task.top_value(fm, "task_id") or path.stem
    return ""


def _clean_title(title: str) -> str:
    value = re.sub(r"\s+", " ", title).strip()
    if not value or len(value) > 20 or "…" in value or "..." in value:
        raise ValueError("title must be a complete name of 1–20 characters without ellipsis")
    return value


def _task_id(external_system: str, correlation_id: str) -> str:
    system = re.sub(r"[^a-z0-9]+", "-", external_system.casefold()).strip("-") or "external"
    digest = hashlib.sha256(f"{external_system}\0{correlation_id}".encode()).hexdigest()[:12]
    return f"{datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')}-{system}-{digest}"


def _render_task(
    task_id: str, title: str, objective: str, project: str,
    external_system: str, correlation_id: str, artifact_mode: str,
) -> str:
    timestamp = now_beijing()
    work_type = "system" if artifact_mode == "system" else "data"
    return f'''---
type: gstudio_task
task_id: {task_id}
title: {json.dumps(title, ensure_ascii=False)}
project: {project}
work_type: {work_type}
task_kind: external_job
status: active
executor: external
created_at: "{timestamp}"
updated_at: "{timestamp}"
skills_used:
  - gstudio
artifact_mode: {artifact_mode}
external:
  system: {json.dumps(external_system)}
  correlation_id: {json.dumps(correlation_id, ensure_ascii=False)}
  state: registered
---

# {title}

## 任务目标

{objective.strip()}

## 任务描述

由外部系统 `{external_system}` 通过稳定关联标识 `{correlation_id}` 发起；余烬 · Ember 负责执行记录，外部系统持有成果正本。

## 当前结果

成果正本由外部系统持有；余烬 · Ember 记录任务过程、关联标识、结果路径和验证。

## 执行日志

- {timestamp}：通过 余烬 · Ember MCP 幂等创建任务。
'''


def ember_task_ensure(
    *, external_system: str, correlation_id: str, title: str, objective: str,
    project: str = "independent", existing_task_id: str = "",
) -> dict[str, Any]:
    """Create or reuse one task by external_system + correlation_id."""
    if existing_task_id:
        existing_task_id, _, redirected = _continuation_task(existing_task_id)
        _preflight(existing_task_id)
        result = ember_task_get(existing_task_id)
        if redirected:
            result["redirected_from_task_ids"] = redirected
        return result
    if not re.fullmatch(r"[a-z0-9._-]{1,80}", external_system) or not correlation_id.strip() or len(correlation_id) > 200 or any(ord(c) < 32 for c in correlation_id):
        raise ValueError("valid external_system and bounded correlation_id are required")
    objective = bridge.summary(objective) or ""
    if not objective:
        raise ValueError("objective is required")
    scope = _registered_scope(project)
    correlation_id = correlation_id.strip()
    lock_key = "ensure-" + hashlib.sha256(f"{external_system}\0{correlation_id}".encode()).hexdigest()
    with _shared_bridge_lock(lock_key) as root:
        existing = _existing_by_correlation(external_system, correlation_id)
        if existing:
            existing, _, redirected = _continuation_task(existing)
            _preflight(existing)
            result = ember_task_get(existing)
            result["reused"] = True
            if redirected:
                result["redirected_from_task_ids"] = redirected
            return result
        policy = scope.get("artifact_policy") if isinstance(scope.get("artifact_policy"), dict) else {}
        artifact_mode = str(policy.get("default_mode") or "none")
        task_id = _task_id(external_system, correlation_id)
        path = root / "active" / f"{task_id}.md"
        if path.exists():
            raise RuntimeError(f"task id collision: {task_id}")
        _atomic_write(path, _render_task(
            task_id, _clean_title(title), objective, project,
            external_system, correlation_id, artifact_mode,
        ))
        # Preserve the new card on a failed preflight; never erase request evidence.
        _preflight(task_id)
        result = ember_task_get(task_id)
        result["reused"] = False
        return result


def ember_task_get(task_id: str) -> dict[str, Any]:
    """Return canonical task context for continuation, without reading delivery contents."""
    bridge.validate_task_id(task_id)
    found = ember_task.find_task(task_id)
    if not found:
        raise ValueError(f"task not found: {task_id}")
    record = ember_task.task_record(found[0], found[1], found[2])
    keys = (
        "task_id", "task_name", "description", "project", "project_title",
        "status", "work_type", "task_kind", "artifact_mode", "updated_at",
        "executor", "execution_model", "execution_models", "skills_used", "current_stage",
        "external_system", "external_correlation_id", "external_job_id",
        "external_state", "output_owner", "paths",
    )
    result = {key: record.get(key) for key in keys}
    result.update(_project_category_context(ember_task.project_registry()[0].get(str(record.get("project") or ""), {})))
    text = found[2].read_text(encoding="utf-8")
    result["context"] = bridge.task_context(text)
    fm, _ = ember_task.frontmatter(text)
    result["context"]["relations"] = {
        "related_task_ids": record.get("related_task_ids") or ember_task.list_value(fm, "related_task_ids") or ember_task.list_value(fm, "member_task_ids"),
        "merged_into": ember_task.top_value(fm, "merged_into"),
        "merged_from_task_ids": ember_task.list_value(fm, "merged_from_task_ids"),
        "split_from": ember_task.top_value(fm, "split_from"),
        "split_into_task_ids": ember_task.list_value(fm, "split_into_task_ids"),
    }
    for field, child in (("external_system", "system"), ("external_correlation_id", "correlation_id"), ("external_job_id", "job_id"), ("external_state", "state")):
        result[field] = _external_value(fm, child)
    return result


def ember_search(*, query: str) -> dict[str, Any]:
    """Search existing Ember/Muse/EBrain indexes read-only; never creates a task."""
    from .ember_workbench import unified_search_payload
    return unified_search_payload(query)


def ember_get_daily_report(
    *, report_date: str = "latest", include_style: bool = True,
) -> dict[str, Any]:
    """Return Ember-owned daily evidence and style without mutating system state."""
    return ember_daily_report.get_daily_report(
        report_date=report_date,
        include_style=include_style,
    )


def ember_get_weekly_report(
    *, report_week: str = "latest", include_style: bool = True,
    include_details: bool = True,
) -> dict[str, Any]:
    """Return Ember-owned weekly evidence and organization proposals read-only."""
    return ember_weekly_report.get_weekly_report(
        report_week=report_week,
        include_style=include_style,
        include_details=include_details,
    )


def ember_get_weekly_organization(
    *, report_week: str = "latest", include_style: bool = True,
) -> dict[str, Any]:
    """Read the frozen weekly organization task and its current report."""
    return ember_weekly_organization.handoff(
        report_week=report_week, include_style=include_style,
    )


def ember_record_weekly_feedback(
    *, task_id: str, revision_id: str, run_id: str, decisions: list[dict[str, Any]],
    close_round: bool = False,
) -> dict[str, Any]:
    """Record caller-reported Evan feedback under an authorized run; technical user identity is unavailable."""
    return ember_weekly_organization.record_feedback(
        task_id=task_id, revision_id=revision_id, run_id=run_id, decisions=decisions,
        close_round=close_round,
    )


def ember_execute_weekly_organization(
    *, task_id: str, revision_id: str, run_id: str,
) -> dict[str, Any]:
    """Execute only deterministic, Evan-confirmed weekly actions under an authorized Agent run."""
    return ember_weekly_organization.execute_confirmed(
        task_id, revision_id, run_id,
    )


def ember_get_weekly_execution_status(*, report_week: str = "latest") -> dict[str, Any]:
    """Return canonical receipt counts and completion readiness for one weekly round."""
    return ember_weekly_organization.execution_status(report_week)


def ember_record_weekly_execution_receipt(
    *, task_id: str, revision_id: str, item_id: str, confirmation_key: str,
    run_id: str, state: str, summary: str, result_refs: list[str] | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one semantic organization result produced by the authorized material manager."""
    return ember_weekly_organization.record_execution_receipt(
        task_id, revision_id, item_id, confirmation_key, run_id, state, summary,
        result_refs, verification,
    )


def ember_finalize_weekly_organization(
    *, task_id: str, revision_id: str, run_id: str,
) -> dict[str, Any]:
    """Finalize the canonical weekly task only after every confirmed item has succeeded."""
    return ember_weekly_organization.finalize_organization(
        task_id, revision_id, run_id,
    )


def _replace_top_scalar(text: str, key: str, value: str) -> str:
    line = f'{key}: "{value}"' if key.endswith("_at") else f"{key}: {value}"
    pattern = rf"^{re.escape(key)}:\s*.*$"
    return re.sub(pattern, line, text, count=1, flags=re.MULTILINE) if re.search(pattern, text, re.MULTILINE) else text


def _replace_nested_block(text: str, parent: str, fields: dict[str, Any]) -> str:
    lines = [f"{parent}:"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"  {key}:")
            lines.extend(f"    - {item}" for item in value)
        elif value not in (None, ""):
            lines.append(f"  {key}: {value}")
    block = "\n".join(lines)
    header, marker, body = text.partition("\n---\n")
    if not marker:
        raise ValueError("task frontmatter missing")
    if re.search(rf"^{re.escape(parent)}:[ \t]*\S", header, re.MULTILINE):
        raise ValueError(f"legacy scalar {parent} cannot be replaced automatically")
    pattern = rf"^{re.escape(parent)}:[ \t]*\n(?:  [^\n]*\n?)*"
    existing = re.search(pattern, header, re.MULTILINE)
    if existing:
        revised = existing.group(0).rstrip("\n")
        for key, value in fields.items():
            if not isinstance(value, str):
                raise ValueError("bridge progress fields must be scalars")
            line = f"  {key}: {value}"
            child = rf"^  {re.escape(key)}:[^\n]*$"
            revised = re.sub(child, lambda _: line, revised, count=1, flags=re.MULTILINE) if re.search(child, revised, re.MULTILINE) else revised + "\n" + line
        header = header[:existing.start()] + revised + "\n" + header[existing.end():]
        header = header.rstrip("\n")
    else:
        header += "\n" + block
    return header + marker + body


def _append_log(text: str, event: str, timestamp: str) -> str:
    revised = ember_task.prepend_execution_log_entry(
        text, f"{timestamp}：{event.strip()}"
    )
    return re.sub(r"^## 执行日志[ \t]*\n(?:[ \t]*\n)*", "## 执行日志\n\n", revised, count=1, flags=re.MULTILINE)


def _mutate(task_id: str, callback: Any) -> dict[str, Any]:
    bridge.validate_task_id(task_id)
    root = shared_task_root()
    if not root.is_dir() or (str(root.parent).startswith("/Volumes/") and not os.path.ismount(root.parent)):
        raise RuntimeError("shared task root unavailable; no local write fallback")
    with _shared_bridge_lock(f"task-{task_id}"):
        found = ember_task.find_task(task_id)
        if not found or found[1] != "active":
            raise ValueError("only an active Ember task may be updated")
        if found[2].is_symlink() or not found[2].resolve().is_relative_to(root.resolve()):
            raise ValueError("task mutations require the canonical shared task card")
        _preflight(task_id)
        before = found[2].stat()
        text = found[2].read_text(encoding="utf-8")
        fm, _ = ember_task.frontmatter(text)
        if ember_task.top_value(fm, "status") == "completed":
            raise ValueError("completed task metadata is read-only")
        successor = ember_task.top_value(fm, "merged_into")
        if successor:
            raise ValueError(f"retired merged source is read-only; continue {successor}")
        revised = callback(text)
        if revised != text:
            after = found[2].stat()
            if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
                raise RuntimeError("task changed concurrently; retry result registration only")
            _atomic_write(found[2], revised)
        _preflight(task_id)
    return ember_task_get(task_id)


def ember_task_append_event(*, task_id: str, event: str) -> dict[str, Any]:
    """Append one timestamped audit event; no arbitrary section editing."""
    event = bridge.summary(event) or ""
    if not event:
        raise ValueError("event is required")
    timestamp = now_beijing()
    return _mutate(task_id, lambda text: _append_log(
        _replace_top_scalar(text, "updated_at", timestamp), event, timestamp
    ))


def ember_task_register_external_result(
    *, task_id: str, external_system: str, job_id: str, state: str,
    canonical_paths: list[str] | None = None,
    validations: list[str] | None = None,
    current_result: str | None = None, next_step: str | None = None,
) -> dict[str, Any]:
    """Upsert one system/job receipt, preserving outputs, project and lifecycle. Retry registration, not successful external work."""
    if not re.fullmatch(r"[a-z0-9._-]{1,80}", external_system) or not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 200 or any(ord(c) < 32 for c in job_id):
        raise ValueError("a system identifier and stable bounded job_id are required")
    if not isinstance(state, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", state):
        raise ValueError("invalid external state")
    for values in (canonical_paths, validations):
        if values is not None and (not isinstance(values, list) or len(values) > 50 or any(not isinstance(x, str) or len(x) > 3000 for x in values)):
            raise ValueError("result references and validations must be bounded string lists")
    canonical_paths = list(dict.fromkeys(canonical_paths or []))
    validations = list(dict.fromkeys(validations or []))
    current_result, next_step = bridge.summary(current_result), bridge.summary(next_step)
    if current_result == "":
        raise ValueError("current_result cannot remove the required current-result section")
    timestamp = now_beijing()
    receipt = {"system": external_system, "job_id": job_id, "state": state, "canonical_paths": canonical_paths, "validations": validations}

    def update(text: str) -> str:
        entries = bridge.receipts(text)
        prior = next((item for item in entries if (item["system"], item["job_id"]) == (external_system, job_id)), None)
        if prior and prior["state"] in {"success", "succeeded", "integrated", "completed"}:
            if prior.get("canonical_paths", []) != canonical_paths or prior["state"] != state:
                raise ValueError("a successful job cannot be overwritten or downgraded; use a new job_id for a new revision")
        incoming = dict(receipt)
        if prior:
            incoming["validations"] = list(dict.fromkeys(prior.get("validations", []) + validations))
            if len(incoming["validations"]) > 50:
                raise ValueError("too many validations for one job; use a new job_id")
        if prior and all(prior.get(key) == value for key, value in incoming.items()):
            return text  # A late retry must not roll back a newer adopted result or next step.
        revised = bridge.update_section(text, "当前结果", current_result)
        revised = bridge.update_section(revised, "下一步", next_step)
        if prior:
            if not set(prior.get("canonical_paths", [])).issubset(canonical_paths):
                raise ValueError("registration retry cannot discard prior result references")
            entries[entries.index(prior)] = dict(incoming, recorded_at=timestamp)
        else:
            entries.append(dict(incoming, recorded_at=timestamp))
        fm, _ = ember_task.frontmatter(text)
        recorded_system = _external_value(fm, "system")
        recorded_job = _external_value(fm, "job_id")
        # Native tasks keep no fabricated external origin; side jobs cannot replace an origin job.
        if recorded_system == external_system and (not recorded_job or recorded_job == job_id):
            progress = {"job_id": json.dumps(job_id, ensure_ascii=False), "state": state}
            revised = _replace_nested_block(revised, "external", progress)
        revised = bridge.write_receipts(revised, entries)
        if not bridge.output_block(text) and ember_task.top_value(fm, "artifact_mode") == "external" and (not recorded_system or recorded_system == external_system):
            revised = revised.replace("outputs:\n", "outputs:\n  owner: " + external_system + "\n", 1)
        revised = _replace_top_scalar(revised, "updated_at", timestamp)
        return _append_log(revised, f"登记 {external_system} 外部结果：job_id={job_id}，state={state}", timestamp)

    return _mutate(task_id, update)


gstudio_task_route = ember_task_route
gstudio_task_ensure = ember_task_ensure
gstudio_task_get = ember_task_get
gstudio_search = ember_search
gstudio_get_daily_report = ember_get_daily_report
gstudio_get_weekly_report = ember_get_weekly_report
gstudio_get_weekly_organization = ember_get_weekly_organization
gstudio_record_weekly_feedback = ember_record_weekly_feedback
gstudio_execute_weekly_organization = ember_execute_weekly_organization
gstudio_get_weekly_execution_status = ember_get_weekly_execution_status
gstudio_record_weekly_execution_receipt = ember_record_weekly_execution_receipt
gstudio_finalize_weekly_organization = ember_finalize_weekly_organization
gstudio_task_append_event = ember_task_append_event
gstudio_task_register_external_result = ember_task_register_external_result


def build_server() -> Any:
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("ember", instructions="Restricted 余烬 · Ember task registry with governed weekly-organization execution; no arbitrary file access.")
    server.tool()(ember_task_route)
    server.tool(name="gstudio_task_route")(ember_task_route)
    server.tool()(ember_task_ensure)
    server.tool(name="gstudio_task_ensure")(ember_task_ensure)
    server.tool()(ember_task_get)
    server.tool(name="gstudio_task_get")(ember_task_get)
    server.tool()(ember_search)
    server.tool(name="gstudio_search")(ember_search)
    server.tool()(ember_get_daily_report)
    server.tool(name="gstudio_get_daily_report")(ember_get_daily_report)
    server.tool()(ember_get_weekly_report)
    server.tool(name="gstudio_get_weekly_report")(ember_get_weekly_report)
    server.tool()(ember_get_weekly_organization)
    server.tool(name="gstudio_get_weekly_organization")(ember_get_weekly_organization)
    server.tool()(ember_record_weekly_feedback)
    server.tool(name="gstudio_record_weekly_feedback")(ember_record_weekly_feedback)
    server.tool()(ember_execute_weekly_organization)
    server.tool(name="gstudio_execute_weekly_organization")(ember_execute_weekly_organization)
    server.tool()(ember_get_weekly_execution_status)
    server.tool(name="gstudio_get_weekly_execution_status")(ember_get_weekly_execution_status)
    server.tool()(ember_record_weekly_execution_receipt)
    server.tool(name="gstudio_record_weekly_execution_receipt")(ember_record_weekly_execution_receipt)
    server.tool()(ember_finalize_weekly_organization)
    server.tool(name="gstudio_finalize_weekly_organization")(ember_finalize_weekly_organization)
    server.tool()(ember_task_append_event)
    server.tool(name="gstudio_task_append_event")(ember_task_append_event)
    server.tool()(ember_task_register_external_result)
    server.tool(name="gstudio_task_register_external_result")(ember_task_register_external_result)
    return server


def main() -> int:
    build_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
