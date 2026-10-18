#!/usr/bin/env python3
"""State transitions and duplicate-sync ledger for the shared archive Inbox."""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root

import fcntl
import hashlib
import json
import os
import shutil
import stat as stat_module
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .workspace_paths import archive_inbox_root, current_environment_name, shared_workspace_root

SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1
RUNTIME_ROOT = _deployment_root()
INBOX_SNAPSHOT_PATH = RUNTIME_ROOT / "task-cards" / "archive-cache" / "archive-inbox-snapshot.json"
INBOX_SNAPSHOT_TTL_SECONDS = 60
INBOX_SNAPSHOT_RETRY_SECONDS = 15
INBOX_SNAPSHOT_MAX_ENTRIES_PER_STATE = 5000
STATE_FOLDERS = {
    "processing": "处理中",
    "pending_archive": "待归档",
    "deletable": "可删除",
}
STATE_ORDER = ("unclassified", "processing", "pending_archive", "deletable")
STATES = set(STATE_ORDER)


class ArchiveInboxError(ValueError):
    pass


def ledger_path() -> Path:
    override = ember_env("EMBER_ARCHIVE_INBOX_LEDGER_PATH")
    if override:
        return Path(override).expanduser()
    return shared_workspace_root() / "管理中心" / "运行状态" / "归档队列" / "archive-inbox-ledger.json"


def _empty_ledger() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "updated_at": "", "records": []}


def load(path: Path | None = None) -> dict[str, object]:
    target = path or ledger_path()
    if not target.is_file():
        return _empty_ledger()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveInboxError(f"归档收件箱指纹台账无法读取：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ArchiveInboxError("归档收件箱指纹台账格式无效。")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("updated_at", "")
    return payload


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
    fd, temporary = tempfile.mkstemp(prefix=".archive-inbox-ledger-", suffix=".json", dir=path.parent)
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


def state_base(root: Path, state: str) -> Path:
    """Return a legacy physical state path.

    State is metadata-only now.  This helper remains for Finder compatibility
    with folders created by older releases; new transitions never write there.
    """
    if state not in STATES:
        raise ArchiveInboxError("收件箱状态无效。")
    resolved = root.expanduser().resolve()
    return resolved if state == "unclassified" else resolved / STATE_FOLDERS[state]


def sync_fingerprint(
    path: Path,
    *,
    stat_result: os.stat_result | None = None,
    is_dir: bool | None = None,
) -> str:
    """Cheap signature for spotting a source that an upload-only job resent."""
    metadata = stat_result or path.stat()
    directory = stat_module.S_ISDIR(metadata.st_mode) if is_dir is None else is_dir
    seed = f"{path.name}\0{int(metadata.st_size)}\0{metadata.st_mtime_ns}\0{int(directory)}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def resolve(root: Path, state: str, relative_path: str) -> Path:
    if state not in STATES:
        raise ArchiveInboxError("收件箱状态无效。")
    base = root.expanduser().resolve()
    relative = Path(relative_path or ".")
    if relative.is_absolute() or ".." in relative.parts:
        raise ArchiveInboxError("收件箱路径无效。")
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise ArchiveInboxError("收件箱路径超出 Inbox。") from exc
    if not candidate.exists():
        raise ArchiveInboxError("收件箱来源不存在。")
    return candidate


def _record_state(records: list[dict[str, object]], fingerprint: str) -> tuple[str, dict[str, object] | None]:
    for record in reversed(records):
        signature = str(record.get("sync_fingerprint") or record.get("fingerprint") or "")
        state = str(record.get("state") or "")
        if signature == fingerprint and state in STATES:
            return state, record
    return "", None


def _record_indexes(
    records: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, list[dict[str, object]]]]:
    """Index current labels and recent distinct locators in one reverse pass."""
    state_by_fingerprint: dict[str, dict[str, object]] = {}
    locations_by_fingerprint: dict[str, list[dict[str, object]]] = {}
    seen_locations: dict[str, set[str]] = {}
    for record in reversed(records):
        fingerprint = str(record.get("sync_fingerprint") or record.get("fingerprint") or "")
        if not fingerprint:
            continue
        state = str(record.get("state") or "")
        if state in STATES and fingerprint not in state_by_fingerprint:
            state_by_fingerprint[fingerprint] = record
        relative = str(record.get("relative_path") or "")
        seen = seen_locations.setdefault(fingerprint, set())
        recent = locations_by_fingerprint.setdefault(fingerprint, [])
        if relative not in seen and len(recent) < 2:
            recent.append(record)
            seen.add(relative)
    return state_by_fingerprint, locations_by_fingerprint


def _state_from_fingerprint(
    path: Path,
    inbox: Path,
    fingerprint: str,
    state_by_fingerprint: dict[str, dict[str, object]],
) -> str:
    record = state_by_fingerprint.get(fingerprint)
    if record:
        return str(record.get("state") or "unclassified")
    relative = path.relative_to(inbox)
    if relative.parts:
        legacy = {folder: key for key, folder in STATE_FOLDERS.items()}.get(relative.parts[0])
        if legacy:
            return legacy
    return "unclassified"


def effective_state(
    path: Path,
    root: Path,
    payload: dict[str, object] | None = None,
    *,
    fingerprint: str = "",
) -> str:
    """Resolve the current label, inheriting it across same-fingerprint resyncs."""
    records = list((payload or load()).get("records") or [])
    signature = fingerprint or sync_fingerprint(path)
    state, _ = _record_state(records, signature)
    if state:
        return state
    relative = path.relative_to(root.expanduser().resolve())
    if relative.parts:
        legacy = {folder: key for key, folder in STATE_FOLDERS.items()}.get(relative.parts[0])
        if legacy:
            return legacy
    return "unclassified"


def _row(
    path: Path,
    inbox: Path,
    state: str,
    *,
    stat_result: os.stat_result,
    is_dir: bool,
    fingerprint: str,
    locations_by_fingerprint: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    relative = path.relative_to(inbox).as_posix()
    prior = next(
        (
            record
            for record in locations_by_fingerprint.get(fingerprint, [])
            if str(record.get("relative_path") or "") != relative
        ),
        None,
    )
    return {
        "name": path.name,
        "relative_path": relative,
        "state_relative_path": relative,
        "state": state,
        "is_dir": is_dir,
        "size": int(stat_result.st_size),
        "updated_at": datetime.fromtimestamp(stat_result.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "fingerprint": fingerprint,
        "duplicate": bool(prior),
        "duplicate_state": str(prior.get("state") or "") if prior else "",
        "duplicate_recorded_at": str(prior.get("recorded_at") or "") if prior else "",
    }


def _directory_candidates(directory: Path) -> list[tuple[Path, os.stat_result, bool]]:
    """Enumerate one directory with exactly one stat call per visible child."""
    candidates: list[tuple[Path, os.stat_result, bool]] = []
    try:
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if entry.name.startswith("."):
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=True)
                except OSError:
                    continue
                # Build from the already-canonical directory rather than
                # DirEntry.path.  On macOS the latter may retain the /var
                # alias while ``directory`` resolved to /private/var.
                candidates.append((directory / entry.name, metadata, stat_module.S_ISDIR(metadata.st_mode)))
    except OSError as exc:
        raise ArchiveInboxError(f"收件箱目录无法读取：{exc}") from exc
    return candidates


def _scan_grouped_entries(
    inbox: Path,
    ledger_payload: dict[str, object],
    *,
    limit: int,
) -> tuple[
    dict[str, list[dict[str, object]]],
    dict[str, int],
    dict[str, bool],
    str,
]:
    records = [record for record in ledger_payload.get("records", []) if isinstance(record, dict)]
    state_index, location_index = _record_indexes(records)
    candidates: list[tuple[Path, os.stat_result, bool]] = []
    for path, metadata, is_dir in _directory_candidates(inbox):
        if path.name not in STATE_FOLDERS.values() or not is_dir:
            candidates.append((path, metadata, is_dir))
            continue
        candidates.extend(_directory_candidates(path))
    candidates.sort(
        key=lambda item: (
            not item[2],
            item[0].name.casefold(),
            item[0].relative_to(inbox).as_posix().casefold(),
        )
    )

    safe_limit = max(0, int(limit))
    grouped: dict[str, list[dict[str, object]]] = {state: [] for state in STATE_ORDER}
    counts = {state: 0 for state in STATE_ORDER}
    digest = hashlib.sha256()
    digest.update(str(ledger_payload.get("updated_at") or "").encode("utf-8"))
    for path, metadata, is_dir in candidates:
        fingerprint = sync_fingerprint(path, stat_result=metadata, is_dir=is_dir)
        state = _state_from_fingerprint(path, inbox, fingerprint, state_index)
        counts[state] += 1
        relative = path.relative_to(inbox).as_posix()
        digest.update(
            f"{relative}\0{fingerprint}\0{state}\0{int(metadata.st_size)}\0{metadata.st_mtime_ns}\n".encode(
                "utf-8"
            )
        )
        if len(grouped[state]) >= safe_limit:
            continue
        grouped[state].append(
            _row(
                path,
                inbox,
                state,
                stat_result=metadata,
                is_dir=is_dir,
                fingerprint=fingerprint,
                locations_by_fingerprint=location_index,
            )
        )
    truncated = {state: counts[state] > len(grouped[state]) for state in STATE_ORDER}
    return grouped, counts, truncated, digest.hexdigest()[:24]


def grouped_entries(
    root: Path | None = None,
    *,
    limit: int = 200,
    ledger: Path | None = None,
    ledger_payload: dict[str, object] | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Scan the Inbox once and group top-level packages by metadata label.

    Children in legacy physical state folders are flattened into the matching
    label view while retaining their real locator.  No file is moved.
    """
    inbox = (root or archive_inbox_root()).expanduser().resolve()
    ledger_payload = ledger_payload if ledger_payload is not None else load(ledger)
    grouped, _, _, _ = _scan_grouped_entries(inbox, ledger_payload, limit=limit)
    return grouped


def entries(
    root: Path | None = None,
    state: str = "unclassified",
    relative_path: str = "",
    *,
    limit: int = 200,
    ledger: Path | None = None,
    ledger_payload: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    inbox = (root or archive_inbox_root()).expanduser().resolve()
    if state not in STATES:
        raise ArchiveInboxError("收件箱状态无效。")
    if not relative_path:
        return grouped_entries(inbox, limit=limit, ledger=ledger, ledger_payload=ledger_payload)[state]
    path = resolve(inbox, state, relative_path)
    if not path.is_dir():
        raise ArchiveInboxError("收件箱来源不是文件夹。")
    ledger_payload = ledger_payload if ledger_payload is not None else load(ledger)
    records = [record for record in ledger_payload.get("records", []) if isinstance(record, dict)]
    _, location_index = _record_indexes(records)
    children = sorted(
        _directory_candidates(path),
        key=lambda item: (not item[2], item[0].name.casefold()),
    )
    result: list[dict[str, object]] = []
    for child, metadata, is_dir in children[: max(0, int(limit))]:
        fingerprint = sync_fingerprint(child, stat_result=metadata, is_dir=is_dir)
        result.append(
            _row(
                child,
                inbox,
                state,
                stat_result=metadata,
                is_dir=is_dir,
                fingerprint=fingerprint,
                locations_by_fingerprint=location_index,
            )
        )
    return result


def state_counts(root: Path | None = None) -> dict[str, int]:
    inbox = (root or archive_inbox_root()).expanduser().resolve()
    try:
        _, counts, _, _ = _scan_grouped_entries(inbox, load(), limit=0)
    except ArchiveInboxError:
        return {state: 0 for state in STATE_ORDER}
    return counts


def _empty_snapshot() -> dict[str, object]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": "",
        "machine": "",
        "root": "",
        "generated_at": "",
        "last_attempt_at": "",
        "last_error": "",
        "ledger_updated_at": "",
        "covered_invalidation_id": "",
        "counts": {state: 0 for state in STATE_ORDER},
        "entries_by_state": {state: [] for state in STATE_ORDER},
        "truncated_by_state": {state: False for state in STATE_ORDER},
    }


def _snapshot_lock_path(cache_path: Path) -> Path:
    return cache_path.with_name(f".{cache_path.stem}.lock")


def _snapshot_invalidation_path(cache_path: Path) -> Path:
    return cache_path.with_name(f"{cache_path.stem}-invalidation.json")


def _load_invalidation(cache_path: Path) -> dict[str, str]:
    path = _snapshot_invalidation_path(cache_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalidation marker must be an object")
        return {
            "invalidation_id": str(payload.get("invalidation_id") or ""),
            "invalidated_at": str(payload.get("invalidated_at") or ""),
            "invalidated_reason": str(payload.get("invalidated_reason") or ""),
        }
    except FileNotFoundError:
        return {"invalidation_id": "", "invalidated_at": "", "invalidated_reason": ""}
    except (OSError, json.JSONDecodeError, ValueError):
        try:
            marker = f"invalid-{path.stat().st_mtime_ns}"
        except OSError:
            marker = "invalid"
        return {
            "invalidation_id": marker,
            "invalidated_at": "",
            "invalidated_reason": "invalidation marker unreadable",
        }


def _parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _snapshot_storage_payload(payload: dict[str, object]) -> dict[str, object]:
    stored = dict(payload)
    for key in (
        "snapshot_state",
        "usable",
        "refresh_state",
        "invalidation_id",
        "invalidated_at",
        "invalidated_reason",
    ):
        stored.pop(key, None)
    return stored


def _scan_snapshot(
    root: Path,
    ledger_payload: dict[str, object],
    *,
    max_entries_per_state: int,
) -> dict[str, object]:
    """Build one bounded, serial Inbox snapshot in O(N + R)."""
    if max_entries_per_state <= 0:
        raise ValueError("max_entries_per_state must be positive")
    inbox = root.expanduser().resolve()
    grouped, counts, truncated, snapshot_id = _scan_grouped_entries(
        inbox,
        ledger_payload,
        limit=max_entries_per_state,
    )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "machine": current_environment_name(),
        "root": str(inbox),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "last_attempt_at": "",
        "last_error": "",
        "ledger_updated_at": str(ledger_payload.get("updated_at") or ""),
        "covered_invalidation_id": "",
        "counts": counts,
        "entries_by_state": grouped,
        "truncated_by_state": truncated,
    }


def load_snapshot(
    cache_path: Path | None = None,
    *,
    max_age_seconds: int = INBOX_SNAPSHOT_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, object]:
    """Read the machine-local display snapshot without touching the NAS."""
    target = (cache_path or INBOX_SNAPSHOT_PATH).expanduser()
    load_error = ""
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("snapshot must be an object")
        entries = raw.get("entries_by_state")
        counts = raw.get("counts")
        truncated = raw.get("truncated_by_state")
        if not isinstance(entries, dict) or not isinstance(counts, dict) or not isinstance(truncated, dict):
            raise ValueError("snapshot shape is invalid")
        payload = {**_empty_snapshot(), **raw}
        payload["entries_by_state"] = {
            state: list(entries.get(state) or []) if isinstance(entries.get(state), list) else []
            for state in STATE_ORDER
        }
        payload["counts"] = {
            state: max(0, int(counts.get(state) or 0))
            for state in STATE_ORDER
        }
        payload["truncated_by_state"] = {
            state: bool(truncated.get(state))
            for state in STATE_ORDER
        }
    except FileNotFoundError:
        payload = _empty_snapshot()
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        payload = _empty_snapshot()
        load_error = f"本机 Inbox 快照无法读取：{exc}"

    marker = _load_invalidation(target)
    generated = _parse_timestamp(payload.get("generated_at"))
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.now().astimezone().tzinfo)
    invalidated = bool(
        marker["invalidation_id"]
        and marker["invalidation_id"] != str(payload.get("covered_invalidation_id") or "")
    )
    last_error = load_error or str(payload.get("last_error") or "")
    if load_error or (last_error and not generated):
        state = "error"
    elif not generated:
        state = "missing"
    elif last_error:
        state = "error"
    elif invalidated:
        state = "dirty"
    elif max_age_seconds >= 0 and (current - generated).total_seconds() > max_age_seconds:
        state = "stale"
    else:
        state = "fresh"
    return {
        **payload,
        "last_error": last_error,
        "invalidation_id": marker["invalidation_id"],
        "invalidated_at": marker["invalidated_at"],
        "invalidated_reason": marker["invalidated_reason"],
        "snapshot_state": state,
        "usable": bool(generated),
    }


def snapshot_needs_refresh(
    payload: dict[str, object],
    *,
    retry_seconds: int = INBOX_SNAPSHOT_RETRY_SECONDS,
    now: datetime | None = None,
) -> bool:
    if str(payload.get("refresh_state") or "") == "running":
        return False
    state = str(payload.get("snapshot_state") or "missing")
    if state == "fresh":
        return False
    if state == "error":
        attempted = _parse_timestamp(payload.get("last_attempt_at"))
        current = now or datetime.now().astimezone()
        if current.tzinfo is None:
            current = current.replace(tzinfo=datetime.now().astimezone().tzinfo)
        if attempted and (current - attempted).total_seconds() < max(0, retry_seconds):
            return False
    return True


def refresh_snapshot(
    root: Path | None = None,
    *,
    ledger_path: Path | None = None,
    cache_path: Path | None = None,
    max_entries_per_state: int = INBOX_SNAPSHOT_MAX_ENTRIES_PER_STATE,
) -> dict[str, object]:
    """Refresh the local snapshot once, preserving last-good data on error."""
    target = (cache_path or INBOX_SNAPSHOT_PATH).expanduser()
    lock_path = _snapshot_lock_path(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**load_snapshot(target), "refresh_state": "running"}
        try:
            previous = load_snapshot(target)
            attempted_at = datetime.now().astimezone().isoformat(timespec="seconds")
            covered_marker = _load_invalidation(target)["invalidation_id"]
            try:
                ledger_payload = load(ledger_path)
                refreshed = _scan_snapshot(
                    root or archive_inbox_root(),
                    ledger_payload,
                    max_entries_per_state=max_entries_per_state,
                )
            except (ArchiveInboxError, OSError, ValueError) as exc:
                failed = _snapshot_storage_payload(previous)
                failed["last_attempt_at"] = attempted_at
                failed["last_error"] = str(exc)
                _atomic_write(target, failed)
                return {**load_snapshot(target), "refresh_state": "error"}
            refreshed["last_attempt_at"] = attempted_at
            refreshed["covered_invalidation_id"] = covered_marker
            _atomic_write(target, refreshed)
            return {**load_snapshot(target), "refresh_state": "ok"}
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def invalidate_snapshot(
    *,
    cache_path: Path | None = None,
    reason: str,
) -> dict[str, object]:
    """Invalidate display data without waiting for a possibly slow NAS scan."""
    target = (cache_path or INBOX_SNAPSHOT_PATH).expanduser()
    marker = {
        "invalidation_id": uuid.uuid4().hex,
        "invalidated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "invalidated_reason": str(reason or "source changed").strip()[:240],
    }
    _atomic_write(_snapshot_invalidation_path(target), marker)
    return load_snapshot(target)


def snapshot_page(
    payload: dict[str, object],
    state: str,
    *,
    offset: int = 0,
    limit: int = 50,
    query: str = "",
    expected_snapshot_id: str = "",
) -> dict[str, object]:
    """Return one stable page from an immutable snapshot generation."""
    if state not in STATES:
        raise ArchiveInboxError("收件箱状态无效。")
    safe_offset = max(0, int(offset))
    safe_limit = max(1, min(100, int(limit)))
    actual_snapshot_id = str(payload.get("snapshot_id") or "")
    reset = bool(expected_snapshot_id and expected_snapshot_id != actual_snapshot_id)
    if reset:
        safe_offset = 0
    entries_by_state = payload.get("entries_by_state") if isinstance(payload.get("entries_by_state"), dict) else {}
    values = [item for item in entries_by_state.get(state, []) or [] if isinstance(item, dict)]
    normalized_query = str(query or "").strip().casefold()
    if normalized_query:
        values = [
            item
            for item in values
            if normalized_query in f"{item.get('name') or ''} {item.get('relative_path') or ''}".casefold()
        ]
    total = len(values)
    page = values[safe_offset:safe_offset + safe_limit]
    next_offset = safe_offset + len(page) if safe_offset + len(page) < total else None
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    truncated = payload.get("truncated_by_state") if isinstance(payload.get("truncated_by_state"), dict) else {}
    return {
        "source_kind": "inbox",
        "state": state,
        "current_path": "",
        "snapshot_id": actual_snapshot_id,
        "snapshot_state": str(payload.get("snapshot_state") or "missing"),
        "generated_at": str(payload.get("generated_at") or ""),
        "last_error": str(payload.get("last_error") or ""),
        "counts": {key: max(0, int(counts.get(key) or 0)) for key in STATE_ORDER},
        "entries": page,
        "offset": safe_offset,
        "limit": safe_limit,
        "total": total,
        "next_offset": next_offset,
        "has_more": next_offset is not None,
        "truncated": bool(truncated.get(state)),
        "reset": reset,
    }


def _record(payload: dict[str, object], *, fingerprint: str, sync_signature: str, name: str, relative_path: str, state: str, previous_state: str) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    records = list(payload.get("records") or [])
    records.append({
        "fingerprint": fingerprint,
        "sync_fingerprint": sync_signature,
        "name": name,
        "relative_path": relative_path,
        "state": state,
        "previous_state": previous_state,
        "recorded_at": now,
    })
    payload["records"] = records[-10000:]
    payload["updated_at"] = now


def transition(
    source_state: str,
    target_state: str,
    relative_paths: Iterable[str],
    *,
    root: Path | None = None,
    path: Path | None = None,
    allow_already_target: bool = False,
) -> dict[str, object]:
    if source_state not in STATES or target_state not in STATES:
        raise ArchiveInboxError("收件箱状态转换无效。")
    if source_state == target_state:
        raise ArchiveInboxError("来源状态和目标状态相同。")
    selected = [str(value).strip() for value in relative_paths if str(value).strip()]
    if not selected:
        raise ArchiveInboxError("请至少选择一个收件箱文件或文件夹。")
    inbox = (root or archive_inbox_root()).expanduser().resolve()
    ledger = path or ledger_path()
    updated: list[dict[str, object]] = []
    unchanged: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []
    with _locked(ledger):
        payload = load(ledger)
        records = list(payload.get("records") or [])
        for relative in selected:
            source = resolve(inbox, source_state, relative)
            sync_signature = sync_fingerprint(source)
            actual_state = effective_state(source, inbox, payload, fingerprint=sync_signature)
            if allow_already_target and actual_state == target_state:
                unchanged.append({
                    "name": source.name,
                    "relative_path": source.relative_to(inbox).as_posix(),
                    "fingerprint": sync_signature,
                    "state": target_state,
                })
                continue
            if actual_state != source_state:
                raise ArchiveInboxError(f"{source.name} 的标签已变化，请刷新页面后重试。")
            prior = next(
                (
                    record for record in reversed(records)
                    if (record.get("sync_fingerprint") or record.get("fingerprint")) == sync_signature
                ),
                None,
            )
            source_relative = source.relative_to(inbox).as_posix()
            is_resynced_copy = bool(prior and prior.get("relative_path") != source_relative)
            if target_state == "pending_archive" and is_resynced_copy and prior and prior.get("state") in {"processing", "pending_archive", "deletable", "archived"}:
                duplicates.append({"name": source.name, "fingerprint": sync_signature, "prior": prior})
                _record(
                    payload,
                    fingerprint=sync_signature,
                    sync_signature=sync_signature,
                    name=source.name,
                    relative_path=source.relative_to(inbox).as_posix(),
                    state="duplicate_sync",
                    previous_state=source_state,
                )
                records = list(payload.get("records") or [])
                continue
            _record(
                payload,
                fingerprint=sync_signature,
                sync_signature=sync_signature,
                name=source.name,
                relative_path=source_relative,
                state=target_state,
                previous_state=source_state,
            )
            records = list(payload.get("records") or [])
            updated.append({"name": source.name, "relative_path": source_relative, "source_relative_path": source_relative, "fingerprint": sync_signature, "state": target_state})
        _atomic_write(ledger, payload)
    return {
        "updated": updated,
        "moved": updated,
        "unchanged": unchanged,
        "duplicates": duplicates,
        "target_state": target_state,
    }


def delete_deletable(
    relative_paths: Iterable[str],
    *,
    root: Path | None = None,
    path: Path | None = None,
) -> dict[str, object]:
    """Permanently remove explicitly selected Inbox items labeled deletable."""
    selected = [Path(str(value).strip()) for value in relative_paths if str(value).strip()]
    if not selected:
        raise ArchiveInboxError("请至少选择一个可删除文件或文件夹。")
    if any(item.is_absolute() or ".." in item.parts or not item.parts for item in selected):
        raise ArchiveInboxError("收件箱删除路径无效。")

    # Selecting a folder already includes its descendants. Collapse overlapping
    # choices so no child is touched after its selected parent has been removed.
    unique = sorted({item.as_posix(): item for item in selected}.values(), key=lambda item: (len(item.parts), item.as_posix()))
    collapsed: list[Path] = []
    skipped: list[str] = []
    for item in unique:
        if any(item.parts[: len(parent.parts)] == parent.parts for parent in collapsed):
            skipped.append(item.as_posix())
        else:
            collapsed.append(item)

    inbox = (root or archive_inbox_root()).expanduser().resolve()
    ledger = path or ledger_path()
    deleted: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    with _locked(ledger):
        payload = load(ledger)
        validated: list[tuple[Path, Path, str]] = []
        for relative in collapsed:
            lexical = inbox / relative
            if lexical.is_symlink():
                raise ArchiveInboxError(f"{lexical.name} 是符号链接，不能从归档页删除。")
            source = resolve(inbox, "deletable", relative.as_posix())
            top_level = inbox / relative.parts[0]
            actual_state = effective_state(top_level, inbox, payload)
            if actual_state != "deletable":
                raise ArchiveInboxError(f"{source.name} 已不在“可删除”标签，请刷新页面后重试。")
            validated.append((relative, source, sync_fingerprint(source)))

        for relative, source, fingerprint in validated:
            try:
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
            except OSError as exc:
                errors.append({"relative_path": relative.as_posix(), "error": str(exc)})
                continue
            _record(
                payload,
                fingerprint=fingerprint,
                sync_signature=fingerprint,
                name=source.name,
                relative_path=relative.as_posix(),
                state="deleted",
                previous_state="deletable",
            )
            deleted.append({
                "name": source.name,
                "relative_path": relative.as_posix(),
                "fingerprint": fingerprint,
            })
        if deleted:
            _atomic_write(ledger, payload)
    if not deleted and errors:
        raise ArchiveInboxError(f"删除失败：{errors[0]['error']}")
    return {"deleted": deleted, "errors": errors, "skipped_descendants": skipped}
