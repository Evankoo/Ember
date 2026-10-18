#!/usr/bin/env python3
"""Execute item-level confirmed project and task-line organization changes."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
import re
from pathlib import Path

from . import ember_agent
from . import ember_task as tasks
from . import ember_workbench as workbench
from .time_format import now_iso_string
from .ember_central_store import _locked
from .workspace_paths import shared_workspace_root, shared_workspace_status


class OrganizationError(RuntimeError):
    pass


def _scalar(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*?)\s*$", frontmatter, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else ""


def _load_active(task_id: str) -> tuple[Path, str, str]:
    found = tasks.find_task(task_id)
    if not found or found[1] != "active":
        raise OrganizationError(f"active task not found: {task_id}")
    text = found[2].read_text(encoding="utf-8", errors="replace")
    frontmatter, body = tasks.frontmatter(text)
    return found[2], frontmatter, body


def _load_task(task_id: str) -> tuple[Path, str, str]:
    found = tasks.find_task(task_id)
    if not found or found[1] not in {"active", "completed"}:
        raise OrganizationError(f"task not found: {task_id}")
    text = found[2].read_text(encoding="utf-8", errors="replace")
    frontmatter, body = tasks.frontmatter(text)
    return found[2], frontmatter, body


def _require_confirmation(organization_task_id: str, action: str, task_id: str, target: str) -> Path:
    path, frontmatter, body = _load_active(organization_task_id)
    if _scalar(frontmatter, "work_type") != "organize":
        raise OrganizationError("controlling task must use work_type: organize")
    if tasks.nested_value(frontmatter, "confirmations", "assignments_confirmed").lower() != "true":
        raise OrganizationError("assignments_confirmed is not true")
    expected = f"- assignment: {action} | task: {task_id} | target: {target}"
    if expected not in body.splitlines():
        raise OrganizationError(f"exact item-level confirmation is missing: {expected}")
    return path


def _task_groups_containing(task_id: str) -> list[str]:
    groups: list[str] = []
    for record in workbench.record_map().values():
        if record.get("task_kind") == "task_group" and task_id in {
            str(value) for value in record.get("related_task_ids") or []
        }:
            groups.append(str(record.get("task_id") or ""))
    return [value for value in groups if value]


def _shared_task_path(task_id: str, *, active: bool = False) -> Path:
    if not shared_workspace_status()["primary_available"]:
        raise OrganizationError("canonical NAS workspace is unavailable")
    found = tasks.find_task(task_id)
    if not found or found[1] not in ({"active"} if active else {"active", "completed"}):
        raise OrganizationError(f"task not found: {task_id}")
    path = found[2]
    root = shared_workspace_root().resolve() / "tasks"
    if path.is_symlink() or path.resolve().parent not in {root / "active", root / "completed"}:
        raise OrganizationError(f"task is not a canonical NAS card or is a symlink: {task_id}")
    return path


def assign_project(*, run_id: str, organization_task_id: str, task_id: str, project: str, expected_sha256: str = "") -> dict[str, str]:
    ember_agent.require_run(run_id=run_id, mode="task_organization", task_id=organization_task_id)
    control = _shared_task_path(organization_task_id, active=True)
    _require_confirmation(organization_task_id, "project", task_id, project)
    path = _shared_task_path(task_id)
    before_bytes = path.read_bytes()
    before_hash = sha256(before_bytes).hexdigest()
    if expected_sha256 and expected_sha256 != before_hash:
        raise OrganizationError("task card changed since the confirmed source snapshot")
    before = before_bytes.decode("utf-8")

    # Stable ordering protects both the current confirmation and selected card.
    with ExitStack() as locks:
        for item in sorted({control, path}, key=str):
            locks.enter_context(_locked(item))
        ember_agent.require_run(run_id=run_id, mode="task_organization", task_id=organization_task_id)
        if _shared_task_path(organization_task_id, active=True) != control or _shared_task_path(task_id) != path:
            raise OrganizationError("task card path changed while acquiring locks")
        _require_confirmation(organization_task_id, "project", task_id, project)
        if path.read_bytes() != before_bytes:
            raise OrganizationError("task card changed while acquiring locks")
        frontmatter, _ = tasks.frontmatter(before)
        if _scalar(frontmatter, "task_kind") == "task_group":
            raise OrganizationError("task lines cannot be reassigned by this command")
        if _task_groups_containing(task_id):
            raise OrganizationError("remove the task from its task line before changing project")
        projects, _ = tasks.project_registry()
        if project != "independent" and project not in projects:
            raise OrganizationError(f"unregistered project: {project}")
        if not re.search(r"^project:", frontmatter, re.MULTILINE):
            raise OrganizationError("task card is missing project field")
        timestamp = now_iso_string()
        updated = re.sub(r"^project:[^\n]*$", f"project: {project}", before, count=1, flags=re.MULTILINE)
        if updated == before:
            raise OrganizationError("task card already uses the target project")
        updated = re.sub(r"^updated_at:[^\n]*$", f'updated_at: "{timestamp}"', updated, count=1, flags=re.MULTILINE)
        updated = tasks.prepend_execution_log_entry(
            updated,
            f"{timestamp}：经 Evan 逐项确认，项目归属调整为 `{project}`；控制任务 `{organization_task_id}`。",
        )
        updated_bytes = updated.encode("utf-8")
        _shared_task_path(task_id)
        if path.read_bytes() != before_bytes:
            raise OrganizationError("task card changed before atomic replacement")
        committed = False
        try:
            tasks.atomic_write(path, updated)
            committed = True
            tasks.sync_changed_task_records([path], publish_shared=True)
            if path.read_bytes() != updated_bytes:
                raise OrganizationError("task card changed during index refresh")
        except Exception as exc:
            # Raw editors may ignore flock. Never roll their newer bytes back.
            current = path.read_bytes()
            if current == updated_bytes:
                if _shared_task_path(task_id) != path:
                    raise OrganizationError("task card path changed before rollback; repair required") from exc
                if path.read_bytes() != updated_bytes:
                    message = "assignment failed; concurrent card change preserved"
                else:
                    try:
                        tasks.atomic_write(path, before)
                    except Exception as rollback_error:
                        raise OrganizationError("assignment failed; atomic rollback failed, repair required") from rollback_error
                    message = "assignment failed; task change rolled back"
                committed = True
            elif current != before_bytes:
                message = "assignment failed; concurrent card change preserved"
                committed = True
            else:
                message = "assignment failed; task card unchanged"
            if committed:
                try:
                    tasks.sync_changed_task_records([path], publish_shared=True)
                except Exception as recovery_error:
                    raise OrganizationError(f"{message}; cache recovery failed, repair required") from recovery_error
            raise OrganizationError(message) from exc
    return {
        "run_id": run_id, "task_id": task_id, "action": "project", "target": project,
        "path": str(path), "before_sha256": before_hash, "after_sha256": sha256(updated_bytes).hexdigest(),
    }


def group_relation(*, run_id: str, organization_task_id: str, group_task_id: str, task_id: str, action: str) -> dict[str, str]:
    ember_agent.require_run(run_id=run_id, mode="task_organization")
    confirmation_action = "group_add" if action == "add" else "group_remove"
    _require_confirmation(organization_task_id, confirmation_action, task_id, group_task_id)
    _, group_frontmatter, _ = _load_active(group_task_id)
    _, task_frontmatter, _ = _load_task(task_id)
    if _scalar(group_frontmatter, "task_kind") != "task_group":
        raise OrganizationError("target is not a task line")
    if _scalar(task_frontmatter, "task_kind") == "task_group":
        raise OrganizationError("task lines cannot be nested")
    if _scalar(group_frontmatter, "project") != _scalar(task_frontmatter, "project"):
        raise OrganizationError("task and task line must belong to the same project")
    if action == "add":
        other_groups = [value for value in _task_groups_containing(task_id) if value != group_task_id]
        if other_groups:
            raise OrganizationError(f"task already belongs to another task line: {', '.join(other_groups)}")
    workbench.update_task_group_relations(group_task_id, [task_id], action)
    return {"run_id": run_id, "task_id": task_id, "action": confirmation_action, "target": group_task_id}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    project = sub.add_parser("assign-project")
    project.add_argument("--run-id", required=True)
    project.add_argument("--organization-task-id", required=True)
    project.add_argument("--task-id", required=True)
    project.add_argument("--project", required=True)
    project.add_argument("--expected-sha256", default="", help="Expected confirmed source-card SHA-256; a mismatch stops before writing")
    group = sub.add_parser("group-relation")
    group.add_argument("--run-id", required=True)
    group.add_argument("--organization-task-id", required=True)
    group.add_argument("--group-task-id", required=True)
    group.add_argument("--task-id", required=True)
    group.add_argument("--action", choices=("add", "remove"), required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "assign-project":
        result = assign_project(
            run_id=args.run_id, organization_task_id=args.organization_task_id,
            task_id=args.task_id, project=args.project, expected_sha256=args.expected_sha256
        )
    else:
        result = group_relation(
            run_id=args.run_id, organization_task_id=args.organization_task_id, group_task_id=args.group_task_id,
            task_id=args.task_id, action=args.action,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
