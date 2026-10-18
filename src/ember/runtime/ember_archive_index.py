#!/usr/bin/env python3
"""Build a shallow, read-only index of the canonical NAS project archive."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import errno
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .workspace_paths import current_environment_name, project_archive_root

ROOT = _deployment_root()
CONFIG_PATH = ROOT / "config" / "ember-archive.json"
CACHE_PATH = ROOT / "task-cards" / "archive-cache" / "nas-project-archive.json"
PUBLISH_SCAN_PATH = ROOT / "task-cards" / "archive-cache" / "publish-archive-scan.json"


class ArchiveIndexError(RuntimeError):
    pass


class ArchiveIndexBusy(ArchiveIndexError):
    pass


def config() -> dict[str, object]:
    settings = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings["display_root"] = str(project_archive_root())
    return settings


def _index_lock_path() -> Path:
    return CACHE_PATH.with_suffix(CACHE_PATH.suffix + ".lock")


@contextmanager
def _index_write_lock():
    lock_path = _index_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock_path.open("a+b")
    except OSError as exc:
        raise ArchiveIndexError(f"归档索引写锁无法打开：{exc}") from exc
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise ArchiveIndexBusy("归档索引正在刷新，请稍后重试。") from exc
            raise ArchiveIndexError(f"归档索引写锁无法获取：{exc}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def archive_root() -> Path:
    return project_archive_root().expanduser()


def _safe_directory(raw_path: str | Path) -> Path:
    root = archive_root().resolve()
    raw = Path(str(raw_path))
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ArchiveIndexError("归档路径超出 NAS 项目归档区。")
    if not candidate.is_dir():
        raise ArchiveIndexError(f"NAS 归档目录不存在或未挂载：{candidate}")
    return candidate


def display_remote_path(path: str | Path, name: str = "") -> str:
    base = _safe_directory(path)
    return str(base / name) if name else str(base)


def list_remote(remote_path: str | Path) -> list[dict[str, object]]:
    """Compatibility API: list one canonical NAS directory level."""
    directory = _safe_directory(remote_path)
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise ArchiveIndexError(f"NAS 归档目录无法读取：{directory}：{exc}") from exc
    items: list[dict[str, object]] = []
    for entry in sorted(entries, key=lambda item: (not item.is_dir(), item.name.casefold())):
        if entry.name.startswith("."):
            continue
        try:
            stat = entry.stat()
        except OSError as exc:
            raise ArchiveIndexError(f"NAS 归档条目无法读取：{entry}：{exc}") from exc
        items.append({
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
            "size": 0 if entry.is_dir() else int(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            "remote_path": str(entry),
        })
    return items


def _build_project(item: dict[str, object], project_slug: str, scan_depth: int, errors: list[dict[str, str]]) -> dict[str, object]:
    try:
        children = list_remote(str(item["remote_path"]))
    except ArchiveIndexError as exc:
        children = []
        errors.append({"project": str(item["name"]), "error": str(exc)})

    def attach_descendants(items: list[dict[str, object]], depth: int) -> None:
        if depth >= scan_depth:
            return
        for child in items:
            if child.get("type") != "directory":
                continue
            try:
                descendants = list_remote(str(child["remote_path"]))
            except ArchiveIndexError as exc:
                descendants = []
                errors.append({"project": str(item["name"]), "error": str(exc)})
            child["children"] = descendants
            child["child_count"] = len(descendants)
            attach_descendants(descendants, depth + 1)

    attach_descendants(children, 2)
    return {**item, "gstudio_project": project_slug, "children": children, "child_count": len(children)}


def build_index() -> dict[str, object]:
    settings = config()
    mappings = settings.get("project_mappings") if isinstance(settings.get("project_mappings"), dict) else {}
    scan_depth = max(2, min(int(settings.get("scan_depth", 4)), 4))
    root_items = list_remote(archive_root())
    errors: list[dict[str, str]] = []
    projects = [
        _build_project(item, str(mappings[str(item["name"])]), scan_depth, errors)
        for item in root_items
        if item.get("type") == "directory" and str(item.get("name")) in mappings
    ]
    return {
        "schema_version": 2,
        "provider": "nas_smb",
        "transport": "mounted_smb",
        "environment": current_environment_name(),
        "remote_root": str(archive_root()),
        "canonical_root": str(settings.get("canonical_root") or "/vol1/@team/项目归档区"),
        "scan_depth": scan_depth,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "partial" if errors else "ok",
        "project_count": len(projects),
        "projects": projects,
        "errors": errors,
    }


def refresh_project(project_key: str) -> dict[str, object]:
    with _index_write_lock():
        settings = config()
        mappings = settings.get("project_mappings") if isinstance(settings.get("project_mappings"), dict) else {}
        match = next(((str(name), str(slug)) for name, slug in mappings.items() if project_key in {str(name), str(slug)}), None)
        if not match:
            raise ArchiveIndexError("未找到当前 NAS 归档项目映射。")
        project_name, project_slug = match
        project_path = archive_root() / project_name
        if not project_path.is_dir():
            raise ArchiveIndexError(f"NAS 归档项目不存在：{project_name}")
        stat = project_path.stat()
        root_item = {"name": project_name, "type": "directory", "size": 0, "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"), "remote_path": str(project_path)}
        errors: list[dict[str, str]] = []
        scan_depth = max(2, min(int(settings.get("scan_depth", 4)), 4))
        refreshed = _build_project(root_item, project_slug, scan_depth, errors)
        payload = load_index()
        projects = [item for item in payload.get("projects", []) if isinstance(item, dict) and item.get("gstudio_project") != project_slug]
        projects.append(refreshed)
        order = {str(slug): index for index, slug in enumerate(mappings.values())}
        projects.sort(key=lambda item: order.get(str(item.get("gstudio_project") or ""), len(order)))
        payload.update({"schema_version": 2, "provider": "nas_smb", "transport": "mounted_smb", "remote_root": str(archive_root()), "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "status": "partial" if errors else "ok", "project_count": len(projects), "projects": projects, "errors": errors})
        _save_index_unlocked(payload)
        return payload


def _save_index_unlocked(payload: dict[str, object]) -> Path:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{CACHE_PATH.name}.", suffix=".tmp", dir=CACHE_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, CACHE_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return CACHE_PATH


def save_index(payload: dict[str, object]) -> Path:
    with _index_write_lock():
        return _save_index_unlocked(payload)


def refresh_all() -> dict[str, object]:
    with _index_write_lock():
        payload = build_index()
        _save_index_unlocked(payload)
        return payload


def load_index() -> dict[str, object]:
    if not CACHE_PATH.exists():
        return {"schema_version": 2, "provider": "nas_smb", "transport": "mounted_smb", "remote_root": str(archive_root()), "status": "missing", "project_count": 0, "projects": [], "errors": []}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveIndexError(f"归档索引损坏：{exc}") from exc


def build_publish_scan() -> dict[str, object]:
    settings = config()
    mappings = settings.get("project_mappings") if isinstance(settings.get("project_mappings"), dict) else {}
    folders: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for project_name, project_slug in mappings.items():
        base = archive_root() / str(project_name) / "发布归档"
        if not base.is_dir():
            continue
        try:
            for first in list_remote(base):
                if first.get("type") != "directory":
                    continue
                if re.fullmatch(r"20\d{2}", str(first.get("name") or "")):
                    for month in list_remote(str(first["remote_path"])):
                        if month.get("type") == "directory":
                            for entry in list_remote(str(month["remote_path"])):
                                if entry.get("type") == "directory":
                                    folders.append({"project": str(project_slug), "name": str(entry.get("name") or ""), "remote_path": str(entry.get("remote_path") or ""), "modified_at": str(entry.get("modified_at") or "")})
                else:
                    folders.append({"project": str(project_slug), "name": str(first.get("name") or ""), "remote_path": str(first.get("remote_path") or ""), "modified_at": str(first.get("modified_at") or "")})
        except ArchiveIndexError as exc:
            errors.append({"project": str(project_slug), "error": str(exc)})
    return {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "status": "partial" if errors else "ok", "folders": folders, "errors": errors}


def save_publish_scan(payload: dict[str, object]) -> Path:
    PUBLISH_SCAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLISH_SCAN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return PUBLISH_SCAN_PATH


def load_publish_scan() -> dict[str, object]:
    if not PUBLISH_SCAN_PATH.exists():
        return {"status": "missing", "folders": [], "errors": []}
    try:
        return json.loads(PUBLISH_SCAN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "error", "folders": [], "errors": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read and cache the canonical NAS project archive")
    parser.add_argument("command", choices=("refresh", "status"))
    args = parser.parse_args()
    try:
        payload = refresh_all() if args.command == "refresh" else load_index()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("status") in {"ok", "partial"} else 1
    except ArchiveIndexError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
