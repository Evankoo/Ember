#!/usr/bin/env python3
"""Keep each Mac's task index current with the shared task-card truth."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import fcntl
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = _deployment_root()

from . import gstudio_task
from .workspace_paths import current_environment_name, shared_task_root

CONFIG_PATH = ROOT / "config" / "task-index-sync.json"
STATE_PATH = ROOT / "task-cards" / "task-index-sync-status.json"
LOCK_PATH = ROOT / "task-cards" / ".task-index-sync.lock"


def now_string() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def config() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_state() -> dict[str, object]:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _manifest_fingerprint(manifest: dict[str, dict[str, int]]) -> str:
    digest = hashlib.sha256()
    for key in sorted(manifest):
        item = manifest[key]
        digest.update(f"{key}\0{item['size']}\0{item['mtime_ns']}\n".encode("utf-8"))
    return digest.hexdigest()


def _scan_task_snapshot(
    root: Path,
) -> tuple[str, int, set[str], dict[str, dict[str, int]], dict[str, Path]]:
    manifest: dict[str, dict[str, int]] = {}
    paths: dict[str, Path] = {}
    task_ids: set[str] = set()
    for state in ("active", "completed"):
        folder = root / state
        if not folder.is_dir():
            raise RuntimeError(f"共享任务目录不可用：{folder}")
        try:
            files = sorted(folder.glob("*.md"), key=lambda item: item.name)
        except OSError as exc:
            raise RuntimeError(f"无法扫描共享任务目录：{folder}: {exc}") from exc
        for path in files:
            stat = path.stat()
            key = f"{state}/{path.name}"
            manifest[key] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            paths[key] = path
            task_ids.add(path.stem)
    if not manifest:
        raise RuntimeError(
            f"共享任务目录返回空快照，拒绝覆盖最近成功缓存：{root}"
        )
    return _manifest_fingerprint(manifest), len(manifest), task_ids, manifest, paths


def _task_snapshot(
    root: Path | None = None,
) -> tuple[str, int, set[str], dict[str, dict[str, int]], dict[str, Path]]:
    root = root or shared_task_root()
    last_error: OSError | None = None
    for attempt in range(2):
        try:
            return _scan_task_snapshot(root)
        except OSError as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.05)
    raise RuntimeError(f"扫描任务卡时文件发生变化，重试后仍失败：{last_error}") from last_error


def task_fingerprint(root: Path | None = None) -> tuple[str, int]:
    fingerprint, count, _task_ids, _manifest, _paths = _task_snapshot(root)
    return fingerprint, count


def _state_manifest(value: object) -> dict[str, dict[str, int]] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, dict[str, int]] = {}
    for raw_key, raw_item in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_item, dict):
            return None
        try:
            result[raw_key] = {
                "size": int(raw_item["size"]),
                "mtime_ns": int(raw_item["mtime_ns"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    return result


def _manifest_task_ids(manifest: dict[str, dict[str, int]]) -> set[str]:
    return {Path(key).stem for key in manifest}


def _error_state(previous: dict[str, object], exc: Exception) -> dict[str, object]:
    return {
        **previous,
        "machine": current_environment_name(),
        "state": "error",
        "last_check_at": now_string(),
        "error": str(exc),
    }


def _local_index_health(
    *,
    source_task_count: int,
    expected_record_count: int | None,
    expected_task_ids: set[str] | None = None,
) -> dict[str, object]:
    """Check that the on-disk cache agrees with the shared-card snapshot.

    The status file is advisory; the index that the workbench actually reads
    is authoritative for cache health.  Checking both task-card count and
    total record count catches a deleted/truncated index even when the shared
    fingerprint has not changed.
    """
    index_path = gstudio_task.TASK_INDEX_JSON
    if not index_path.is_file():
        return {
            "consistent": False,
            "reason": "local_index_missing",
            "record_count": 0,
            "task_record_count": 0,
        }
    try:
        records = gstudio_task.load_index()
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
        return {
            "consistent": False,
            "reason": f"local_index_unreadable:{exc}",
            "record_count": 0,
            "task_record_count": 0,
        }
    record_count = len(records)
    task_ids = [
        str(record.get("task_id") or "")
        for record in records
        if isinstance(record, dict) and record.get("record_type") == "task_card"
    ]
    task_record_count = len(task_ids)
    unique_task_ids = {task_id for task_id in task_ids if task_id}
    if task_record_count != source_task_count:
        reason = (
            "local_task_count_mismatch:"
            f"expected={source_task_count},actual={task_record_count}"
        )
        consistent = False
    elif len(unique_task_ids) != task_record_count:
        reason = (
            "local_task_ids_duplicated_or_missing:"
            f"records={task_record_count},unique={len(unique_task_ids)}"
        )
        consistent = False
    elif expected_task_ids is not None and unique_task_ids != expected_task_ids:
        missing = sorted(expected_task_ids - unique_task_ids)
        unexpected = sorted(unique_task_ids - expected_task_ids)
        reason = (
            "local_task_ids_mismatch:"
            f"missing={','.join(missing[:3]) or '-'},"
            f"unexpected={','.join(unexpected[:3]) or '-'}"
        )
        consistent = False
    elif expected_record_count is not None and record_count != expected_record_count:
        reason = (
            "local_record_count_mismatch:"
            f"expected={expected_record_count},actual={record_count}"
        )
        consistent = False
    else:
        reason = ""
        consistent = True
    return {
        "consistent": consistent,
        "reason": reason,
        "record_count": record_count,
        "task_record_count": task_record_count,
    }


def _advisory_count(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def refresh_once(*, force: bool = False, root: Path | None = None) -> dict[str, object]:
    root = root or shared_task_root()
    previous = load_state()
    scan_lock_path = LOCK_PATH.parent / "source-cache" / ".task-index-scan.lock"
    scan_lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with scan_lock_path.open("a+", encoding="utf-8") as scan_lock:
            try:
                fcntl.flock(scan_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("本机已有任务目录巡检正在运行") from exc
            fingerprint, source_count, source_task_ids, manifest, paths = _task_snapshot(root)
            fcntl.flock(scan_lock.fileno(), fcntl.LOCK_UN)
    except Exception as exc:
        atomic_json(STATE_PATH, _error_state(previous, exc))
        raise

    cache_consistent: bool | None = None
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("本机已有任务索引刷新正在运行") from exc
        try:
            previous = load_state()
            shared_changed = fingerprint != previous.get("fingerprint")
            expected_record_count = _advisory_count(previous.get("record_count"))
            previous_manifest = _state_manifest(previous.get("tasks"))
            health_task_ids = _manifest_task_ids(previous_manifest) if previous_manifest is not None else source_task_ids
            health = _local_index_health(
                source_task_count=len(health_task_ids),
                expected_record_count=expected_record_count,
                expected_task_ids=health_task_ids,
            )
            cache_consistent = bool(health["consistent"])
            rebuild_reasons: list[str] = []
            if force:
                rebuild_reasons.append("forced")
            if previous_manifest is None:
                rebuild_reasons.append("manifest_missing")
            if not cache_consistent:
                rebuild_reasons.append(str(health["reason"]) or "local_index_inconsistent")
            rebuild = bool(rebuild_reasons)
            changed_keys = {
                key for key, value in manifest.items()
                if previous_manifest is None or previous_manifest.get(key) != value
            }
            removed_keys = set(previous_manifest or {}) - set(manifest)
            incremental = shared_changed and not rebuild
            last_success_at = str(previous.get("last_success_at") or "")
            if rebuild:
                records = gstudio_task.sync_index_records(
                    publish_shared=False,
                    expected_task_count=source_count,
                    sync_delivery_metadata=False,
                )
            elif incremental:
                records = gstudio_task.sync_changed_task_records(
                    [paths[key] for key in sorted(changed_keys)],
                    removed_task_ids={Path(key).stem for key in removed_keys},
                    expected_task_count=source_count,
                    publish_shared=False,
                    sync_delivery_metadata=False,
                )
            else:
                records = gstudio_task.load_index()
            if rebuild or incremental:
                health = _local_index_health(
                    source_task_count=source_count,
                    expected_record_count=len(records),
                    expected_task_ids=source_task_ids,
                )
                cache_consistent = bool(health["consistent"])
                if not cache_consistent:
                    raise RuntimeError(
                        "本地任务索引重建后仍不一致："
                        f"{health['reason']}"
                    )
                last_success_at = now_string()
            record_count = int(health["record_count"])
            payload: dict[str, object] = {
                "machine": current_environment_name(),
                "state": "ok",
                "last_check_at": now_string(),
                "last_success_at": last_success_at,
                "fingerprint": fingerprint,
                "tasks": manifest,
                "source_task_count": source_count,
                "record_count": record_count,
                "changed": rebuild or incremental,
                "shared_changed": shared_changed,
                "cache_rebuilt": rebuild,
                "cache_incremental": incremental,
                "cache_consistent": True,
                "rebuild_reason": ",".join(rebuild_reasons),
                "error": "",
            }
            atomic_json(STATE_PATH, payload)
            return payload
        except Exception as exc:
            payload = _error_state(previous, exc)
            if cache_consistent is not None:
                payload["cache_consistent"] = cache_consistent
            atomic_json(STATE_PATH, payload)
            raise
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def refresh_tasks(task_paths: list[Path]) -> list[dict[str, object]]:
    """Refresh selected canonical cards without scanning every shared card."""
    paths = [Path(path) for path in task_paths]
    if not paths:
        return gstudio_task.load_index()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    touched_ids = {path.stem for path in paths}
    try:
        with LOCK_PATH.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                records = gstudio_task.sync_changed_task_records(
                    paths,
                    publish_shared=True,
                    sync_delivery_metadata=False,
                )
                previous = load_state()
                manifest = _state_manifest(previous.get("tasks"))
                if manifest is not None:
                    for path in paths:
                        resolved = path.resolve(strict=True)
                        state = resolved.parent.name
                        for key in list(manifest):
                            if Path(key).stem == resolved.stem:
                                manifest.pop(key)
                        stat = resolved.stat()
                        manifest[f"{state}/{resolved.name}"] = {
                            "size": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns,
                        }
                payload = {
                    **previous,
                    "machine": current_environment_name(),
                    "state": "ok",
                    "last_check_at": now_string(),
                    "last_success_at": now_string(),
                    "record_count": len(records),
                    "changed": True,
                    "shared_changed": True,
                    "cache_rebuilt": False,
                    "cache_incremental": True,
                    "cache_consistent": True,
                    "rebuild_reason": "",
                    "error": "",
                }
                if manifest is not None:
                    payload["fingerprint"] = _manifest_fingerprint(manifest)
                    payload["tasks"] = manifest
                    payload["source_task_count"] = len(manifest)
                    payload.pop("manifest_pending", None)
                else:
                    payload.pop("fingerprint", None)
                    payload.pop("tasks", None)
                    payload.pop("source_task_count", None)
                    payload["manifest_pending"] = True
                atomic_json(STATE_PATH, payload)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except gstudio_task.LocalIndexError:
        refresh_once(force=True)
        records = gstudio_task.load_index()
    # Delivery metadata is a secondary cache. Refresh it after releasing the
    # task-index lock so a slow or reconnecting SMB delivery folder cannot
    # block index recovery or another task-card update.
    gstudio_task.sync_delivery_cache_tasks(records, touched_ids)
    return records


def run_daemon(interval: int) -> int:
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            refresh_once()
        except Exception as exc:
            print(f"task-index-sync: {exc}", file=sys.stderr, flush=True)
        deadline = time.monotonic() + interval
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the local GStudio task index when shared cards change")
    sub = parser.add_subparsers(dest="command", required=True)
    once = sub.add_parser("once")
    once.add_argument("--force", action="store_true")
    daemon = sub.add_parser("daemon")
    daemon.add_argument("--interval", type=int)
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(load_state(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "once":
        try:
            print(json.dumps(refresh_once(force=args.force), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
    interval = args.interval or int(config().get("interval_seconds", 60))
    if interval < 5:
        parser.error("interval must be at least 5 seconds")
    return run_daemon(interval)


if __name__ == "__main__":
    raise SystemExit(main())
