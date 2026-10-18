#!/usr/bin/env python3
"""Shared metadata queue for the Ember archive center.

The queue never stores file contents and never performs uploads.  It provides
the concurrency, validation and immutable batch-manifest boundary consumed by
the Codex/Kimi project-intake executors.
"""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import ember_archive_inbox as archive_inbox
from .workspace_paths import current_environment, current_environment_name, shared_workspace_root

SCHEMA_VERSION = 1
QUEUE_STATES = {
    "pending_classification", "needs_details", "ready", "archiving", "archived",
    "source_changed", "conflict", "failed_retryable", "receipt_pending",
}
ARCHIVE_TYPES = {
    "publish", "activity", "project_material", "data_asset", "theme_product",
    "professional_knowledge", "external_cooperation",
}
SOURCE_KINDS = {"inbox", "workspace", "downloads", "delivery"}
CLEANUP_MODES = {"keep", "mark_deletable", "move_to_deletable"}
PathResolver = Callable[[dict[str, object]], Optional[Path]]
TargetBuilder = Callable[[dict[str, object]], str]


class ArchiveQueueError(ValueError):
    pass


class RevisionConflict(ArchiveQueueError):
    pass


def queue_path() -> Path:
    override = ember_env("EMBER_ARCHIVE_QUEUE_PATH")
    if override:
        return Path(override).expanduser()
    return shared_workspace_root() / "管理中心" / "运行状态" / "归档队列" / "archive-queue.json"


def _empty_queue() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "revision": 0, "updated_at": "", "items": [], "batches": []}


def _read(path: Path) -> dict[str, object]:
    if not path.is_file():
        return _empty_queue()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveQueueError(f"归档队列无法读取：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ArchiveQueueError("归档队列格式无效。")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("revision", 0)
    payload.setdefault("batches", [])
    return payload


def load(path: Path | None = None) -> dict[str, object]:
    return _read(path or queue_path())


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    with lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".archive-queue-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _mutate(expected_revision: int, callback: Callable[[dict[str, object]], object], path: Path | None = None) -> dict[str, object]:
    target = path or queue_path()
    with _locked(target):
        payload = _read(target)
        revision = int(payload.get("revision") or 0)
        if revision != expected_revision:
            raise RevisionConflict(f"归档队列已由另一台机器更新（当前 revision {revision}），请刷新后重试。")
        callback(payload)
        payload["revision"] = revision + 1
        payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _atomic_write(target, payload)
        return payload


def lightweight_fingerprint(path: Path) -> str:
    stat = path.stat()
    seed = f"{path.name}\0{int(stat.st_size)}\0{stat.st_mtime_ns}\0{int(path.is_dir())}"
    if path.is_dir():
        try:
            children = sorted((child.name, child.stat().st_size, child.stat().st_mtime_ns) for child in path.iterdir())[:200]
            seed += "\0" + json.dumps(children, ensure_ascii=False, separators=(",", ":"))
        except OSError:
            pass
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _path_meta(path: Path) -> dict[str, object]:
    stat = path.stat()
    size = int(stat.st_size)
    file_count = 1 if path.is_file() else 0
    if path.is_dir():
        size = 0
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    size += (Path(root) / name).stat().st_size
                    file_count += 1
                except OSError:
                    continue
    return {
        "name": path.name,
        "kind": "folder" if path.is_dir() else "file",
        "size": size,
        "file_count": file_count,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
        "fingerprint": lightweight_fingerprint(path),
    }


def path_item(source_kind: str, source_root: Path, selected: Path, *, machine: str | None = None) -> dict[str, object]:
    if source_kind not in {"inbox", "workspace", "downloads"}:
        raise ArchiveQueueError("本地来源类型无效。")
    root = source_root.expanduser().resolve()
    path = selected.expanduser().resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ArchiveQueueError("来源路径不在允许的根目录内。") from exc
    if not relative or relative == ".":
        raise ArchiveQueueError("不能把整个来源根目录加入队列。")
    if source_kind == "workspace" and relative.split("/", 1)[0] == "可删除":
        raise ArchiveQueueError("“可删除”目录不进入归档候选。")
    if not path.exists():
        raise ArchiveQueueError("来源文件不存在。")
    return {
        "item_id": uuid.uuid4().hex,
        "source_kind": source_kind,
        "source_machine": machine or ("shared" if source_kind == "inbox" else current_environment_name()),
        "locator": {"relative_path": relative},
        **_path_meta(path),
        "project": "",
        "task_id": "",
        "delivery_state": "",
        "archive_type": "",
        "cleanup_mode": "",
        "metadata": {},
        "package_id": "",
        "state": "pending_classification",
        "error": "",
        "receipt_ref": "",
    }


def delivery_item(path: Path, *, task_id: str, project: str, delivery_state: str, relative_path: str) -> dict[str, object]:
    if delivery_state not in {"draft", "final"}:
        raise ArchiveQueueError("交付状态无效。")
    return {
        "item_id": uuid.uuid4().hex,
        "source_kind": "delivery",
        "source_machine": "shared",
        "locator": {"task_id": task_id, "delivery_state": delivery_state, "relative_path": relative_path},
        **_path_meta(path),
        "project": project,
        "task_id": task_id,
        "delivery_state": delivery_state,
        "archive_type": "",
        "cleanup_mode": "keep",
        "metadata": {},
        "package_id": "",
        "state": "pending_classification",
        "error": "",
        "receipt_ref": "",
    }


def _locator_key(item: dict[str, object]) -> tuple[str, str, str]:
    locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
    source = str(item.get("source_kind") or "")
    scope = str(item.get("task_id") or item.get("source_machine") or "")
    relative = str(locator.get("relative_path") or "").strip("/")
    return source, scope, relative


def deduplicate(items: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    ordered = sorted((dict(item) for item in items), key=lambda item: (_locator_key(item)[0:2], _locator_key(item)[2].count("/"), _locator_key(item)[2]))
    kept: list[dict[str, object]] = []
    for item in ordered:
        source, scope, relative = _locator_key(item)
        if any(source == old_source and scope == old_scope and (relative == old_relative or relative.startswith(old_relative + "/")) for old_source, old_scope, old_relative in map(_locator_key, kept)):
            continue
        kept.append(item)
    return kept


def duplicate_fingerprint_record(payload: dict[str, object], fingerprint: str) -> dict[str, object] | None:
    """Return an existing active or archived record for an Inbox fingerprint."""
    if not fingerprint:
        return None
    for item in reversed(list(payload.get("items") or [])):
        if item.get("source_kind") == "inbox" and item.get("fingerprint") == fingerprint:
            return item
    for batch in reversed(list(payload.get("batches") or [])):
        for package in reversed(list(batch.get("packages") or [])):
            for item in reversed(list(package.get("items") or [])):
                if item.get("source_kind") == "inbox" and item.get("fingerprint") == fingerprint:
                    return {**item, "state": package.get("status") or batch.get("status") or item.get("state")}
    return None


def add_items(expected_revision: int, new_items: list[dict[str, object]], path: Path | None = None) -> dict[str, object]:
    if not new_items:
        raise ArchiveQueueError("请至少选择一个文件或文件夹。")
    def change(payload: dict[str, object]) -> None:
        for item in new_items:
            if item.get("source_kind") != "inbox":
                continue
            previous = duplicate_fingerprint_record(payload, str(item.get("fingerprint") or ""))
            previous_state = str(previous.get("state") or "") if previous else ""
            terminal_or_locked = previous_state in {"confirmed", "archiving", "archived", "receipt_pending"}
            if previous and (_locator_key(previous) != _locator_key(item) or terminal_or_locked):
                raise ArchiveQueueError(
                    f"{item.get('name')} 与既有收件箱记录指纹相同（{previous_state or '已记录'}），"
                    "已阻止重复加入归档队列。"
                )
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        combined = list(payload.get("items") or []) + [dict(item, created_at=now, updated_at=now) for item in new_items]
        payload["items"] = deduplicate(combined)
    return _mutate(expected_revision, change, path)


def remove_items(expected_revision: int, item_ids: list[str], path: Path | None = None) -> dict[str, object]:
    selected = set(item_ids)
    return _mutate(expected_revision, lambda payload: payload.update(items=[item for item in payload.get("items", []) if item.get("item_id") not in selected]), path)


def sync_inbox_transition(
    source_state: str,
    target_state: str,
    relative_paths: Iterable[str],
    apply_transition: Callable[[], dict[str, object]],
    item_builder: Callable[[str], dict[str, object]] | None = None,
    path: Path | None = None,
) -> dict[str, object]:
    """Keep the derived Inbox queue in lockstep with metadata-label changes."""
    relative_set = {str(value).strip("/") for value in relative_paths if str(value).strip("/")}
    if not relative_set:
        raise ArchiveQueueError("请至少选择一个收件箱文件或文件夹。")
    target = path or queue_path()
    with _locked(target):
        payload = _read(target)
        locked_relatives: set[str] = set()
        for batch in payload.get("batches", []):
            for package in batch.get("packages", []):
                if str(package.get("status") or "confirmed") not in {"confirmed", "archiving", "receipt_pending"}:
                    continue
                for item in package.get("items", []):
                    if item.get("source_kind") != "inbox":
                        continue
                    locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
                    locked_relatives.add(str(locator.get("relative_path") or "").strip("/"))
        if source_state == "pending_archive" and target_state != "pending_archive":
            locked = sorted(relative_set & locked_relatives)
            if locked:
                raise ArchiveQueueError(
                    f"{Path(locked[0]).name} 已进入确认或执行阶段，不能直接取消待归档标签。"
                )

        candidates: dict[str, dict[str, object]] = {}
        if target_state == "pending_archive":
            if not item_builder:
                raise ArchiveQueueError("待归档入队缺少来源构建器。")
            for relative in relative_set:
                item = item_builder(relative)
                item["cleanup_mode"] = "mark_deletable"
                previous = duplicate_fingerprint_record(payload, str(item.get("fingerprint") or ""))
                previous_state = str(previous.get("state") or "") if previous else ""
                if previous and (
                    _locator_key(previous) != _locator_key(item)
                    or previous_state in {"confirmed", "archiving", "archived", "receipt_pending"}
                ):
                    raise ArchiveQueueError(
                        f"{item.get('name')} 与既有收件箱记录指纹相同（{previous_state or '已记录'}），"
                        "已阻止重复加入归档队列。"
                    )
                candidates[relative] = item

        transition_result = apply_transition()
        updated_relatives = {
            str(item.get("relative_path") or "").strip("/")
            for item in transition_result.get("updated", [])
            if isinstance(item, dict)
        }
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        current_items = list(payload.get("items") or [])
        queued = 0
        removed = 0
        normalized = 0

        if target_state == "pending_archive":
            for relative in sorted(updated_relatives):
                candidate = candidates.get(relative)
                if not candidate:
                    continue
                existing = [
                    item for item in current_items
                    if item.get("source_kind") == "inbox"
                    and str((item.get("locator") or {}).get("relative_path") or "").strip("/") == relative
                ]
                matching = next(
                    (
                        item for item in existing
                        if str(item.get("fingerprint") or "") == str(candidate.get("fingerprint") or "")
                    ),
                    None,
                )
                if matching:
                    if matching.get("cleanup_mode") != "mark_deletable":
                        matching["cleanup_mode"] = "mark_deletable"
                        matching["updated_at"] = now
                        normalized += 1
                    continue
                current_items = [item for item in current_items if item not in existing]
                current_items.append(dict(candidate, created_at=now, updated_at=now))
                queued += 1
            payload["items"] = deduplicate(current_items)
        elif source_state == "pending_archive":
            before = len(current_items)
            payload["items"] = [
                item for item in current_items
                if not (
                    item.get("source_kind") == "inbox"
                    and str((item.get("locator") or {}).get("relative_path") or "").strip("/") in updated_relatives
                )
            ]
            removed = before - len(payload["items"])

        if queued or removed or normalized:
            payload["revision"] = int(payload.get("revision") or 0) + 1
            payload["updated_at"] = now
            _atomic_write(target, payload)
        transition_result.update({
            "queue_revision": int(payload.get("revision") or 0),
            "queued": queued,
            "removed_from_queue": removed,
            "normalized": normalized,
        })
        return transition_result


def required_details(item: dict[str, object]) -> list[str]:
    missing: list[str] = []
    project = str(item.get("project") or "")
    kind = str(item.get("archive_type") or "")
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if not project:
        missing.append("项目")
    if kind not in ARCHIVE_TYPES:
        missing.append("归档类型")
    archive_month = str(
        metadata.get("archive_month")
        or metadata.get("publish_month")
        or metadata.get("activity_month")
        or (str(metadata.get("published_at") or "")[:7] if kind == "publish" else "")
        or ""
    ).strip()
    if not archive_month:
        missing.append("月份")
    else:
        try:
            datetime.strptime(archive_month, "%Y-%m")
        except ValueError:
            missing.append("月份格式 YYYY-MM")
    for key in ("subproject", "topic", "activity_name", "target_subdir", "material_name"):
        value = str(metadata.get(key) or "").strip()
        if value and (Path(value).is_absolute() or ".." in Path(value).parts):
            missing.append(f"{key} 不能包含绝对路径或 ..")
    if item.get("source_kind") == "delivery":
        if item.get("cleanup_mode") != "keep": missing.append("任务交付必须复制并保留")
    elif item.get("source_kind") == "inbox":
        if item.get("cleanup_mode") != "mark_deletable": missing.append("NAS Inbox 归档成功后必须标记可删除")
    elif item.get("cleanup_mode") not in CLEANUP_MODES:
        missing.append("来源处理方式")
    return missing


def update_items(expected_revision: int, item_ids: list[str], changes: dict[str, object], path: Path | None = None) -> dict[str, object]:
    selected = set(item_ids)
    allowed = {"project", "archive_type", "cleanup_mode", "metadata"}
    safe = {key: value for key, value in changes.items() if key in allowed}
    def change(payload: dict[str, object]) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        for item in payload.get("items", []):
            if item.get("item_id") not in selected:
                continue
            if item.get("source_kind") == "delivery" and safe.get("cleanup_mode") not in {None, "", "keep"}:
                raise ArchiveQueueError("任务交付固定为复制并保留。")
            metadata_changes = safe.get("metadata") if isinstance(safe.get("metadata"), dict) else None
            item.update({key: value for key, value in safe.items() if key != "metadata" and value != ""})
            if metadata_changes:
                existing_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                item["metadata"] = {**existing_metadata, **metadata_changes}
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            source_name = Path(str(item.get("name") or "归档内容")).stem.strip() or "归档内容"
            month = str(metadata.get("archive_month") or metadata.get("publish_month") or metadata.get("activity_month") or "").strip()
            if month:
                metadata["archive_month"] = month
                if item.get("archive_type") == "publish":
                    metadata["publish_month"] = month
                elif item.get("archive_type") == "activity":
                    metadata["activity_month"] = month
            if item.get("archive_type") == "activity" and not str(metadata.get("activity_name") or "").strip():
                metadata["activity_name"] = source_name
            if item.get("archive_type") in {"project_material", "data_asset", "theme_product", "professional_knowledge", "external_cooperation"} and not str(metadata.get("target_subdir") or metadata.get("material_name") or "").strip():
                metadata["target_subdir"] = source_name
            if item.get("project") == "small-project-pool" and not str(metadata.get("subproject") or "").strip():
                metadata["subproject"] = source_name
            item["metadata"] = metadata
            if item.get("source_kind") == "delivery": item["cleanup_mode"] = "keep"
            elif item.get("source_kind") == "inbox": item["cleanup_mode"] = "mark_deletable"
            elif item.get("source_kind") in {"workspace", "downloads"} and item.get("cleanup_mode") not in CLEANUP_MODES:
                item["cleanup_mode"] = "keep"
            item["updated_at"] = now
            item["state"] = "needs_details" if required_details(item) else "ready"
            item["error"] = ""
    return _mutate(expected_revision, change, path)


def recheck_sources(
    expected_revision: int,
    item_ids: list[str],
    resolver: PathResolver,
    path: Path | None = None,
) -> dict[str, object]:
    """Re-resolve changed sources without accepting different content.

    The resolver may repair an unambiguous locator, but the original locked
    fingerprint remains authoritative.  A different fingerprint must stay in
    ``source_changed`` until the user removes and adds the source again.
    """
    selected = set(item_ids)
    result = {"checked": 0, "recovered": 0, "unresolved": 0}

    def change(payload: dict[str, object]) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        matched = False
        for item in payload.get("items", []):
            if item.get("item_id") not in selected:
                continue
            matched = True
            result["checked"] += 1
            source = resolver(item)
            if not source or not source.exists():
                item["state"] = "source_changed"
                item["error"] = "source missing"
                item["updated_at"] = now
                result["unresolved"] += 1
                continue
            if lightweight_fingerprint(source) != item.get("fingerprint"):
                item["state"] = "source_changed"
                item["error"] = "fingerprint changed"
                item["updated_at"] = now
                result["unresolved"] += 1
                continue
            item["state"] = "needs_details" if required_details(item) else "ready"
            item["error"] = ""
            item["updated_at"] = now
            result["recovered"] += 1
        if not matched:
            raise ArchiveQueueError("未找到需要重新定位的来源。")

    payload = _mutate(expected_revision, change, path)
    return {**result, "revision": int(payload.get("revision") or 0)}


def package_groups(items: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, object]]] = {}
    for item in items:
        locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
        task_id = str(item.get("task_id") or "")
        source_group = task_id or str(locator.get("relative_path") or "").split("/", 1)[0]
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        target = str(metadata.get("target_subdir") or metadata.get("activity_name") or metadata.get("topic") or "")
        key = (str(item.get("project") or ""), str(item.get("archive_type") or ""), target, source_group)
        groups.setdefault(key, []).append(item)
    packages: list[dict[str, object]] = []
    for index, (key, grouped) in enumerate(groups.items(), 1):
        project, archive_type, target, _ = key
        package_id = "pkg-" + hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:10]
        packages.append({"package_id": package_id, "project": project, "archive_type": archive_type, "target_label": target, "items": grouped, "item_count": len(grouped), "size": sum(int(item.get("size") or 0) for item in grouped), "order": index})
    return packages


def confirm_batch(expected_revision: int, item_ids: list[str], resolver: PathResolver, path: Path | None = None, target_builder: TargetBuilder | None = None) -> dict[str, object]:
    selected = set(item_ids)
    result: dict[str, object] = {}
    def change(payload: dict[str, object]) -> None:
        items = [item for item in payload.get("items", []) if item.get("item_id") in selected]
        if not items:
            raise ArchiveQueueError("没有选中可确认的队列项。")
        source_error = ""
        for item in items:
            missing = required_details(item)
            if missing:
                raise ArchiveQueueError(f"{item.get('name')} 仍缺少：{'、'.join(missing)}。")
            if item.get("source_kind") == "downloads" and item.get("source_machine") != current_environment_name():
                raise ArchiveQueueError(f"{item.get('name')} 属于另一台机器的 Downloads，只能在来源机器执行。")
            source = resolver(item)
            if not source or not source.exists():
                item["state"] = "source_changed"
                item["error"] = "source missing"
                source_error = source_error or f"{item.get('name')} 的来源已不存在。"
                continue
            current = lightweight_fingerprint(source)
            if current != item.get("fingerprint"):
                item["state"] = "source_changed"
                item["error"] = "fingerprint changed"
                source_error = source_error or f"{item.get('name')} 的来源已变化，请刷新后重新确认。"
        if source_error:
            result["error"] = source_error
            return
        packages = package_groups(items)
        for package in packages:
            package["target_uri"] = target_builder(package["items"][0]) if target_builder else ""
        batch_id = "batch-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        manifest = {
            "batch_id": batch_id,
            "confirmed_revision": int(payload.get("revision") or 0) + 1,
            "confirmed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_machine": current_environment_name(),
            "machine_label": current_environment().get("label"),
            "status": "confirmed",
            "packages": packages,
        }
        payload.setdefault("batches", []).append(manifest)
        for package in packages:
            for item in package["items"]:
                item["package_id"] = package["package_id"]
                item["state"] = "ready"
        result.update(manifest)
    _mutate(expected_revision, change, path)
    if result.get("error"):
        raise ArchiveQueueError(str(result["error"]))
    return result


def return_batch_to_queue(
    expected_revision: int,
    batch_id: str,
    path: Path | None = None,
) -> dict[str, object]:
    """Unlock one unstarted confirmed batch and restore its items for editing."""
    result: dict[str, object] = {}

    def change(payload: dict[str, object]) -> None:
        batch = next(
            (item for item in payload.get("batches", []) if item.get("batch_id") == batch_id),
            None,
        )
        if not batch:
            raise ArchiveQueueError("未找到要返回队列的确认批次。")
        if str(batch.get("status") or "confirmed") != "confirmed":
            raise ArchiveQueueError("只有尚未执行的确认批次可以返回队列修改。")
        packages = list(batch.get("packages") or [])
        if any(str(package.get("status") or "confirmed") != "confirmed" for package in packages):
            raise ArchiveQueueError("归档包已经进入执行或结果处理阶段，不能返回队列修改。")

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        queue_items = {
            str(item.get("item_id") or ""): item
            for item in payload.get("items", [])
            if item.get("item_id")
        }
        restored = 0
        for package in packages:
            for confirmed_item in package.get("items", []):
                item_id = str(confirmed_item.get("item_id") or "")
                if not item_id:
                    continue
                queue_item = queue_items.get(item_id)
                if queue_item is None:
                    queue_item = dict(confirmed_item)
                    payload.setdefault("items", []).append(queue_item)
                    queue_items[item_id] = queue_item
                queue_item["package_id"] = ""
                queue_item["state"] = "needs_details" if required_details(queue_item) else "ready"
                queue_item["error"] = ""
                queue_item["updated_at"] = now
                restored += 1
            package["status"] = "returned_to_queue"
            package["updated_at"] = now
        batch["status"] = "returned_to_queue"
        batch["returned_at"] = now
        result.update({"batch_id": batch_id, "restored": restored})

    payload = _mutate(expected_revision, change, path)
    return {**result, "revision": int(payload.get("revision") or 0)}


def reconfirm_recovery_batch(
    expected_revision: int,
    batch_id: str,
    resolver: PathResolver,
    path: Path | None = None,
) -> dict[str, object]:
    """Re-lock an exception batch after revalidating its unchanged sources."""
    recovery_states = {"conflict", "failed_retryable", "receipt_pending"}
    target = path or queue_path()
    with _locked(target):
        payload = _read(target)
        revision = int(payload.get("revision") or 0)
        if revision != expected_revision:
            raise RevisionConflict(
                f"归档队列已由另一台机器更新（当前 revision {revision}），请刷新后重新确认。"
            )
        batch = next(
            (item for item in payload.get("batches", []) if item.get("batch_id") == batch_id),
            None,
        )
        if not batch:
            raise ArchiveQueueError("未找到要重新确认的异常批次。")
        if str(batch.get("status") or "confirmed") not in recovery_states:
            raise ArchiveQueueError("只有冲突、可重试失败或回执待补批次可以重新确认恢复。")

        queue_items = {
            str(item.get("item_id") or ""): item
            for item in payload.get("items", [])
            if item.get("item_id")
        }
        locked_fields = (
            "source_kind", "source_machine", "locator", "name", "kind", "size",
            "file_count", "modified_at", "fingerprint", "project", "archive_type",
            "cleanup_mode", "metadata", "task_id", "delivery_state", "package_id",
        )
        checked = 0
        for package in batch.get("packages", []):
            if str(package.get("status") or "confirmed") == "archived":
                continue
            package_id = str(package.get("package_id") or "")
            for locked_item in package.get("items", []):
                item_id = str(locked_item.get("item_id") or "")
                current = queue_items.get(item_id)
                if not current:
                    raise ArchiveQueueError(f"{locked_item.get('name')} 已不在当前归档队列，不能沿用旧批次。")
                expected = dict(locked_item)
                expected["package_id"] = package_id
                changed = [field for field in locked_fields if current.get(field) != expected.get(field)]
                if changed:
                    raise ArchiveQueueError(
                        f"{locked_item.get('name')} 的队列信息已变化（{', '.join(changed)}），请重新建立确认批次。"
                    )
                source = resolver(current)
                if not source or not source.exists():
                    raise ArchiveQueueError(f"{locked_item.get('name')} 的来源已不存在，不能重新确认。")
                if lightweight_fingerprint(source) != locked_item.get("fingerprint"):
                    raise ArchiveQueueError(f"{locked_item.get('name')} 的来源指纹已变化，不能重新确认。")
                checked += 1

        previous_revision = int(batch.get("confirmed_revision") or 0)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        batch["confirmed_revision"] = revision
        batch["confirmed_at"] = now
        batch["reconfirmed_from_revision"] = previous_revision
        batch["reconfirmed_at"] = now
        batch["updated_at"] = now
        payload["updated_at"] = now
        _atomic_write(target, payload)
        return {
            "batch_id": batch_id,
            "confirmed_revision": revision,
            "confirmed_at": now,
            "reconfirmed_from_revision": previous_revision,
            "checked": checked,
            "revision": revision,
        }


def record_package_result(
    expected_revision: int,
    batch_id: str,
    package_id: str,
    state: str,
    *,
    final_target_uri: str = "",
    verification: object = "",
    receipt_ref: str = "",
    error: str = "",
    path: Path | None = None,
    inbox_root: Path | None = None,
    inbox_ledger: Path | None = None,
) -> dict[str, object]:
    """Atomically write executor status without changing manifest revision."""
    allowed = {"archiving", "archived", "conflict", "failed_retryable", "receipt_pending"}
    if state not in allowed:
        raise ArchiveQueueError("不支持的归档执行状态。")
    if state == "archived" and (not final_target_uri or not verification or not receipt_ref):
        raise ArchiveQueueError("标记已归档必须提供最终目标、远端校验和回执引用。")
    target = path or queue_path()
    with _locked(target):
        payload = _read(target)
        revision = int(payload.get("revision") or 0)
        if revision != expected_revision:
            raise RevisionConflict(f"归档队列已由另一台机器更新（当前 revision {revision}），请停止写回并复核。")
        batch = next((item for item in payload.get("batches", []) if item.get("batch_id") == batch_id), None)
        if not batch:
            raise ArchiveQueueError("未找到锁定批次。")
        package = next((item for item in batch.get("packages", []) if item.get("package_id") == package_id), None)
        if not package:
            raise ArchiveQueueError("未找到归档包。")
        if state == "archived":
            inbox_relatives = [
                str((item.get("locator") or {}).get("relative_path") or "").strip("/")
                for item in package.get("items", [])
                if item.get("source_kind") == "inbox"
            ]
            inbox_relatives = [relative for relative in inbox_relatives if relative]
            if inbox_relatives:
                try:
                    archive_inbox.transition(
                        "pending_archive",
                        "deletable",
                        inbox_relatives,
                        root=inbox_root,
                        path=inbox_ledger,
                        allow_already_target=True,
                    )
                except archive_inbox.ArchiveInboxError as exc:
                    raise ArchiveQueueError(f"归档已验证，但来源未能标记为可删除：{exc}") from exc
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        package.update({
            "status": state,
            "final_target_uri": final_target_uri or str(package.get("final_target_uri") or ""),
            "verification": verification or package.get("verification") or "",
            "receipt_ref": receipt_ref or str(package.get("receipt_ref") or ""),
            "error": error,
            "updated_at": now,
        })
        for item in package.get("items", []):
            item["state"] = state
            item["error"] = error
            if state == "archived" and item.get("source_kind") == "inbox":
                item["cleanup_mode"] = "mark_deletable"
            if receipt_ref:
                item["receipt_ref"] = receipt_ref
            item["updated_at"] = now
        package_item_ids = {str(item.get("item_id") or "") for item in package.get("items", [])}
        for item in payload.get("items", []):
            if str(item.get("item_id") or "") not in package_item_ids:
                continue
            item["state"] = state
            item["error"] = error
            if state == "archived" and item.get("source_kind") == "inbox":
                item["cleanup_mode"] = "mark_deletable"
            if receipt_ref:
                item["receipt_ref"] = receipt_ref
            item["updated_at"] = now
        package_states = [str(item.get("status") or "confirmed") for item in batch.get("packages", [])]
        if package_states and all(value == "archived" for value in package_states):
            batch["status"] = "archived"
        else:
            batch["status"] = next((value for value in ("receipt_pending", "conflict", "failed_retryable", "archiving") if value in package_states), "confirmed")
        batch["updated_at"] = now
        payload["updated_at"] = now
        _atomic_write(target, payload)
        return payload


def execution_manifest(batch: dict[str, object]) -> dict[str, object]:
    """Return the locked execution fields without redundant queue bookkeeping."""
    packages: list[dict[str, object]] = []
    for package in batch.get("packages", []):
        items: list[dict[str, object]] = []
        for item in package.get("items", []):
            compact_item: dict[str, object] = {
                "item_id": item.get("item_id"),
                "source_kind": item.get("source_kind"),
                "source_machine": item.get("source_machine"),
                "locator": item.get("locator"),
                "name": item.get("name"),
                "kind": item.get("kind"),
                "size": item.get("size"),
                "file_count": item.get("file_count"),
                "modified_at": item.get("modified_at"),
                "fingerprint": item.get("fingerprint"),
                "cleanup_mode": item.get("cleanup_mode"),
                "metadata": item.get("metadata") or {},
            }
            for optional in ("task_id", "delivery_state"):
                if item.get(optional):
                    compact_item[optional] = item.get(optional)
            items.append(compact_item)
        packages.append({
            "package_id": package.get("package_id"),
            "project": package.get("project"),
            "archive_type": package.get("archive_type"),
            "target_uri": package.get("final_target_uri") or package.get("target_uri"),
            "item_count": package.get("item_count"),
            "size": package.get("size"),
            "order": package.get("order"),
            "items": items,
        })
    return {
        "batch_id": batch.get("batch_id"),
        "confirmed_revision": batch.get("confirmed_revision"),
        "confirmed_at": batch.get("confirmed_at"),
        "source_machine": batch.get("source_machine"),
        "packages": packages,
    }


def execution_prompt(batch: dict[str, object]) -> str:
    manifest = json.dumps(execution_manifest(batch), ensure_ascii=False, indent=2)
    return f"""# 余烬 · Ember 批量归档执行

严格执行下面的锁定清单，不重组、不扩展范围。必须先读 `project-intake/SKILL.md` 和 `references/batch-archive.md`；细则以它们为准。

## 执行门禁
- 队列当前 `revision` 必须等于 `confirmed_revision`；逐项解析来源并复核 `fingerprint`。不一致只停止受影响的包。
- 多包批次创建一张 `artifact_mode: archive` 任务卡；单项目归该项目，跨项目归 `gstudio`。

## 逐包执行
1. 确定唯一最终目标。发布包在此时按 `publish_month` 分配 `NN`，不得改用执行月份。
2. 先查百度备份同路径：完整同内容可继续；同名异内容或百度多出文件则停止，禁止覆盖、合并或改名。该检查只用于防止飞牛后续覆盖错误副本，不把百度写入当作本包完成条件。
3. 按 `references/nas-primary-archive.md` 复制到 NAS `/vol1/@team/项目归档区`，用本地文件集合、大小和必要 hash 验证；不得直接上传百度。飞牛任务在每日 00:00 单向备份到百度。
4. 任务交付始终复制保留；NAS Inbox 文件保持原路径，绝不删除本机 Downloads 或 NAS 来源。
5. 写物理回执；发布包再把年度发布记录写为 `archived`。
6. 调用 `python3 scripts/ember_archive_queue.py record-result` 写回包状态、最终目标、校验证据和回执引用；当结果为 `archived` 时，该命令自动把 NAS Inbox 来源标记为“可删除”。

## 完成规则
- 各包相互独立；一包失败不回滚已验证包。
- 只有最终 NAS 目标、本地校验和回执齐全才能写 `archived`。
- NAS 复制已验证但回执失败时写 `receipt_pending`；重试只补写回，不重复复制。

## 锁定清单
```json
{manifest}
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Ember archive queue executor results")
    commands = parser.add_subparsers(dest="command", required=True)
    result = commands.add_parser("record-result")
    result.add_argument("--expected-revision", required=True, type=int)
    result.add_argument("--batch-id", required=True)
    result.add_argument("--package-id", required=True)
    result.add_argument("--state", required=True, choices=("archiving", "archived", "conflict", "failed_retryable", "receipt_pending"))
    result.add_argument("--final-target-uri", default="")
    result.add_argument("--verification", default="")
    result.add_argument("--receipt-ref", default="")
    result.add_argument("--error", default="")
    args = parser.parse_args()
    try:
        payload = record_package_result(
            args.expected_revision,
            args.batch_id,
            args.package_id,
            args.state,
            final_target_uri=args.final_target_uri,
            verification=args.verification,
            receipt_ref=args.receipt_ref,
            error=args.error,
        )
        print(json.dumps({"ok": True, "revision": payload.get("revision"), "batch_id": args.batch_id, "package_id": args.package_id, "state": args.state}, ensure_ascii=False))
        return 0
    except ArchiveQueueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
