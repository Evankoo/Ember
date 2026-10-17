#!/usr/bin/env python3
"""Audit recent canonical NAS archives against the Baidu backup replica."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import gstudio_archive_index as archive_index
from .workspace_paths import project_archive_root, shared_workspace_root

STATUS_PATH = shared_workspace_root() / "管理中心" / "归档管理" / "归档记录" / "项目归档备份状态.json"
QUEUE_PATH = shared_workspace_root() / "管理中心" / "运行状态" / "归档队列" / "archive-queue.json"


class BackupAuditError(RuntimeError):
    pass


def _parse_time(value: object) -> dt.datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _recent_targets(days: int, now: dt.datetime) -> list[Path]:
    try:
        payload = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cutoff = now - dt.timedelta(days=days)
    root = project_archive_root().resolve()
    targets: set[Path] = set()
    for batch in payload.get("batches", []) or []:
        for package in batch.get("packages", []) or []:
            if str(package.get("status") or "") != "archived":
                continue
            updated = _parse_time(package.get("updated_at") or batch.get("updated_at"))
            if not updated or updated < cutoff:
                continue
            target = Path(str(package.get("final_target_uri") or package.get("target_uri") or "")).resolve()
            if target == root or root in target.parents:
                targets.add(target)
    return sorted(targets)


def _local_files(targets: list[Path]) -> dict[str, int]:
    root = project_archive_root().resolve()
    files: dict[str, int] = {}
    for target in targets:
        candidates = [target] if target.is_file() else target.rglob("*") if target.is_dir() else []
        for path in candidates:
            if path.is_file() and not path.name.startswith("."):
                files[path.relative_to(root).as_posix()] = path.stat().st_size
    return files


def _rclone_command() -> str:
    command = os.environ.get("GSTUDIO_RCLONE_COMMAND") or shutil.which("rclone")
    if not command:
        fallback = Path.home() / ".local" / "bin" / "rclone"
        command = str(fallback) if fallback.is_file() else ""
    if not command:
        raise BackupAuditError("当前机器没有找到 rclone。")
    return command


def _remote_files(targets: list[Path], *, runner=subprocess.run) -> dict[str, int]:
    settings = archive_index.config()
    remote = str(settings.get("backup_rclone_remote") or "alist:baidu").rstrip("/")
    root = str(settings.get("backup_remote_root") or "100项目").strip("/")
    local_root = project_archive_root().resolve()
    relative_targets = [target.relative_to(local_root).as_posix() for target in targets]
    commands = (
        [[_rclone_command(), "lsjson", f"{remote}/{root}/{relative}", "--recursive", "--files-only"] for relative in relative_targets]
        if relative_targets else [[_rclone_command(), "lsjson", f"{remote}/{root}", "--max-depth", "1", "--dirs-only"]]
    )
    files: dict[str, int] = {}
    for index, command in enumerate(commands):
        try:
            result = runner(command, capture_output=True, text=True, timeout=int(settings.get("command_timeout_seconds", 60)), check=False)
        except subprocess.TimeoutExpired as exc:
            raise BackupAuditError("百度备份核验超时。") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "rclone lsjson failed").strip().splitlines()[-1]
            raise BackupAuditError(f"百度备份无法读取：{detail}")
        try:
            rows = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise BackupAuditError("百度备份目录返回无效数据。") from exc
        prefix = relative_targets[index].rstrip("/") if relative_targets else ""
        for row in rows:
            if not isinstance(row, dict) or row.get("IsDir") or not row.get("Path"):
                continue
            path = str(row["Path"]).strip("/")
            files[f"{prefix}/{path}".strip("/")] = int(row.get("Size") or 0)
    return files


def audit(*, days: int | None = None, now: dt.datetime | None = None, runner=subprocess.run) -> dict[str, object]:
    settings = archive_index.config()
    now = now or dt.datetime.now().astimezone()
    days = days or int(settings.get("backup_audit_days") or 7)
    targets = _recent_targets(days, now)
    local = _local_files(targets)
    remote = _remote_files(targets, runner=runner)
    missing = sorted(path for path in local if path not in remote)
    different = sorted(path for path, size in local.items() if path in remote and remote[path] != size)
    status = "ok" if not missing and not different else "exception"
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "checked_at": now.isoformat(timespec="seconds"),
        "audit_days": days,
        "backup_task": str(settings.get("backup_task_name") or ""),
        "backup_schedule": str(settings.get("backup_schedule") or ""),
        "last_confirmed_fnos_run_at": str(settings.get("backup_last_confirmed_run_at") or ""),
        "last_confirmed_fnos_run_status": str(settings.get("backup_last_confirmed_run_status") or "unknown"),
        "recent_target_count": len(targets),
        "checked_file_count": len(local),
        "missing_files": missing,
        "different_size_files": different,
    }
    save_status(payload)
    return payload


def save_status(payload: dict[str, object]) -> Path:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{STATUS_PATH.name}.", suffix=".tmp", dir=STATUS_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, STATUS_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return STATUS_PATH


def load_status() -> dict[str, object]:
    if not STATUS_PATH.is_file():
        settings = archive_index.config()
        return {"status": "not_audited", "backup_task": settings.get("backup_task_name", ""), "backup_schedule": settings.get("backup_schedule", ""), "last_confirmed_fnos_run_at": settings.get("backup_last_confirmed_run_at", ""), "last_confirmed_fnos_run_status": settings.get("backup_last_confirmed_run_status", "unknown")}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "error", "error": "备份状态记录损坏"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit recent NAS project archives against Baidu backup")
    parser.add_argument("command", choices=("audit", "status"))
    parser.add_argument("--days", type=int)
    args = parser.parse_args()
    try:
        payload = audit(days=args.days) if args.command == "audit" else load_status()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("status") in {"ok", "not_audited"} else 1
    except BackupAuditError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
