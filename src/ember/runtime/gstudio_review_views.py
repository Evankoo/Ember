#!/usr/bin/env python3
"""Shared, presentation-only task views for the GStudio workbench."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import datetime
import fcntl
import json
import os
import re
import secrets
from pathlib import Path
from typing import Callable

from .workspace_paths import shared_workspace_root


STATE_PATH = Path(
    os.environ.get("GSTUDIO_REVIEW_VIEWS_PATH")
    or shared_workspace_root() / "管理中心" / "运行状态" / "任务视图" / "workbench-views.json"
).expanduser()


class RevisionConflict(ValueError):
    """Raised when a client writes against an obsolete shared revision."""


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _blank() -> dict[str, object]:
    return {
        "version": 1,
        "revision": 0,
        "focus_task_ids": [],
        "views": [],
        "migrations": [],
        "updated_at": "",
    }


def _task_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _normalize(payload: object) -> dict[str, object]:
    result = _blank()
    if not isinstance(payload, dict):
        return result
    result["revision"] = max(0, int(payload.get("revision") or 0))
    result["focus_task_ids"] = _task_ids(payload.get("focus_task_ids"))
    result["migrations"] = _task_ids(payload.get("migrations"))
    result["updated_at"] = str(payload.get("updated_at") or "")
    views: list[dict[str, object]] = []
    used_ids: set[str] = set()
    used_names: set[str] = set()
    raw_views = payload.get("views") if isinstance(payload.get("views"), list) else []
    for position, raw in enumerate(raw_views):
        if not isinstance(raw, dict):
            continue
        view_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        key = name.casefold()
        if not view_id or not name or view_id in used_ids or key in used_names:
            continue
        used_ids.add(view_id)
        used_names.add(key)
        views.append({
            "id": view_id,
            "name": name,
            "position": position,
            "task_ids": _task_ids(raw.get("task_ids")),
            "created_at": str(raw.get("created_at") or ""),
            "updated_at": str(raw.get("updated_at") or ""),
        })
    result["views"] = views
    return result


def load(path: Path | None = None) -> dict[str, object]:
    target = path or STATE_PATH
    try:
        return _normalize(json.loads(target.read_text(encoding="utf-8")))
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
        return _blank()


def _write(target: Path, payload: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def mutate(
    callback: Callable[[dict[str, object]], None],
    *,
    expected_revision: int | None = None,
    path: Path | None = None,
) -> dict[str, object]:
    target = path or STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            payload = load(target)
            revision = int(payload.get("revision") or 0)
            if expected_revision is not None and expected_revision != revision:
                raise RevisionConflict(f"标签已经更新（当前 revision {revision}），请刷新后重试。")
            callback(payload)
            payload = _normalize(payload)
            payload["revision"] = revision + 1
            payload["updated_at"] = _now()
            _write(target, payload)
            return payload
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def migrate_local_focus(local_path: Path, machine: str, *, path: Path | None = None) -> dict[str, object]:
    """Union one machine's legacy project priorities into shared focus once."""
    marker = f"project-priority-v1:{machine}"
    current = load(path)
    if marker in current.get("migrations", []):
        return current
    legacy_ids: list[str] = []
    try:
        payload = json.loads(local_path.read_text(encoding="utf-8"))
        projects = payload.get("projects") if isinstance(payload, dict) else {}
        if isinstance(projects, dict):
            for values in projects.values():
                legacy_ids.extend(_task_ids(values))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass

    def apply(state: dict[str, object]) -> None:
        state["focus_task_ids"] = list(dict.fromkeys(_task_ids(state.get("focus_task_ids")) + legacy_ids))
        state["migrations"] = list(dict.fromkeys(_task_ids(state.get("migrations")) + [marker]))

    return mutate(apply, path=path)


def set_focus_task(task_id: str, important: bool, *, expected_revision: int | None = None, path: Path | None = None) -> dict[str, object]:
    task_id = task_id.strip()
    if not task_id:
        raise ValueError("任务 ID 不能为空。")

    def apply(state: dict[str, object]) -> None:
        values = [value for value in _task_ids(state.get("focus_task_ids")) if value != task_id]
        if important:
            values.insert(0, task_id)
        state["focus_task_ids"] = values

    return mutate(apply, expected_revision=expected_revision, path=path)


def update_focus_tasks(
    task_ids: list[str],
    action: str,
    *,
    expected_revision: int | None = None,
    path: Path | None = None,
) -> dict[str, object]:
    normalized = _task_ids(task_ids)
    if not normalized:
        raise ValueError("请至少选择一张任务卡。")
    if action not in {"add", "remove"}:
        raise ValueError("不支持的当前重点操作。")

    def apply(state: dict[str, object]) -> None:
        current = _task_ids(state.get("focus_task_ids"))
        if action == "add":
            state["focus_task_ids"] = list(dict.fromkeys(current + normalized))
        else:
            remove = set(normalized)
            state["focus_task_ids"] = [task_id for task_id in current if task_id not in remove]

    return mutate(apply, expected_revision=expected_revision, path=path)


def _view(state: dict[str, object], view_id: str) -> dict[str, object]:
    for view in state.get("views", []):
        if isinstance(view, dict) and view.get("id") == view_id:
            return view
    raise ValueError("自定义标签不存在。")


def create_view(name: str, *, expected_revision: int | None = None, path: Path | None = None) -> dict[str, object]:
    clean = re.sub(r"\s+", " ", name).strip()
    if not clean or len(clean) > 30:
        raise ValueError("标签名称应为 1–30 个字符。")
    if clean in {"当前重点", "全部任务"}:
        raise ValueError("该名称属于固定标签。")
    created: dict[str, str] = {}

    def apply(state: dict[str, object]) -> None:
        views = state.get("views") if isinstance(state.get("views"), list) else []
        if any(isinstance(view, dict) and str(view.get("name") or "").casefold() == clean.casefold() for view in views):
            raise ValueError("已经存在同名标签。")
        timestamp = _now()
        view_id = "view-" + secrets.token_hex(6)
        views.append({"id": view_id, "name": clean, "task_ids": [], "position": len(views), "created_at": timestamp, "updated_at": timestamp})
        state["views"] = views
        created["id"] = view_id

    result = mutate(apply, expected_revision=expected_revision, path=path)
    result["created_view_id"] = created["id"]
    return result


def rename_view(view_id: str, name: str, *, expected_revision: int | None = None, path: Path | None = None) -> dict[str, object]:
    clean = re.sub(r"\s+", " ", name).strip()
    if not clean or len(clean) > 30:
        raise ValueError("标签名称应为 1–30 个字符。")

    def apply(state: dict[str, object]) -> None:
        if any(isinstance(view, dict) and view.get("id") != view_id and str(view.get("name") or "").casefold() == clean.casefold() for view in state.get("views", [])):
            raise ValueError("已经存在同名标签。")
        view = _view(state, view_id)
        view["name"] = clean
        view["updated_at"] = _now()

    return mutate(apply, expected_revision=expected_revision, path=path)


def delete_view(view_id: str, *, expected_revision: int | None = None, path: Path | None = None) -> dict[str, object]:
    def apply(state: dict[str, object]) -> None:
        before = state.get("views") if isinstance(state.get("views"), list) else []
        after = [view for view in before if not isinstance(view, dict) or view.get("id") != view_id]
        if len(after) == len(before):
            raise ValueError("自定义标签不存在。")
        state["views"] = after

    return mutate(apply, expected_revision=expected_revision, path=path)


def update_view_tasks(
    view_id: str,
    task_ids: list[str],
    action: str,
    *,
    expected_revision: int | None = None,
    path: Path | None = None,
) -> dict[str, object]:
    normalized = _task_ids(task_ids)
    if not normalized:
        raise ValueError("请至少选择一张任务卡。")
    if action not in {"add", "remove"}:
        raise ValueError("不支持的标签成员操作。")

    def apply(state: dict[str, object]) -> None:
        view = _view(state, view_id)
        current = _task_ids(view.get("task_ids"))
        if action == "add":
            current = list(dict.fromkeys(current + normalized))
        else:
            remove = set(normalized)
            current = [task_id for task_id in current if task_id not in remove]
        view["task_ids"] = current
        view["updated_at"] = _now()

    return mutate(apply, expected_revision=expected_revision, path=path)
