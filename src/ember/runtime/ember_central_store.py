#!/usr/bin/env python3
"""Lock-protected execution queue and allowlisted remote delivery writes."""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .workspace_paths import shared_workspace_root


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RELATIVE_RE = re.compile(r"^[^\\\x00]+$")
UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def state_root() -> Path:
    configured = ember_env("EMBER_CENTRAL_STATE_ROOT")
    return Path(configured).expanduser() if configured else shared_workspace_root() / "管理中心" / "运行状态" / "执行桥"


def queue_path() -> Path:
    return state_root() / "requests.json"


@contextlib.contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _load(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": 1, "revision": 0, "requests": [], "bridges": {}}
    return value if isinstance(value, dict) else {"version": 1, "revision": 0, "requests": [], "bridges": {}}


def _save(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["revision"] = int(payload.get("revision") or 0) + 1
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def register_bridge(machine_id: str, *, label: str = "", executors: list[str] | None = None) -> dict[str, object]:
    if not ID_RE.fullmatch(machine_id):
        raise ValueError("invalid machine id")
    path = queue_path()
    with _locked(path):
        payload = _load(path)
        bridges = payload.setdefault("bridges", {})
        if not isinstance(bridges, dict):
            bridges = payload["bridges"] = {}
        bridges[machine_id] = {
            "machine_id": machine_id,
            "label": label or machine_id,
            "executors": sorted(set(executors or [])),
            "last_seen_at": _iso(),
        }
        _save(path, payload)
        return dict(bridges[machine_id])


def live_bridges(*, max_age_seconds: int = 90) -> list[dict[str, object]]:
    payload = _load(queue_path())
    cutoff = _now() - timedelta(seconds=max_age_seconds)
    result = []
    for bridge in (payload.get("bridges") or {}).values():
        if not isinstance(bridge, dict):
            continue
        try:
            seen = datetime.fromisoformat(str(bridge.get("last_seen_at") or ""))
        except ValueError:
            continue
        if seen >= cutoff:
            result.append(dict(bridge))
    return sorted(result, key=lambda item: str(item.get("label") or item.get("machine_id")))


def enqueue(
    *,
    executor: str,
    title: str,
    prompt: str,
    task_id: str = "",
    target_machine: str = "",
    nas_path: str = "",
) -> dict[str, object]:
    if executor not in {"codex", "opencode", "finder"}:
        raise ValueError("unsupported executor")
    if task_id and not ID_RE.fullmatch(task_id):
        raise ValueError("invalid task id")
    if target_machine and not ID_RE.fullmatch(target_machine):
        raise ValueError("invalid target machine")
    if nas_path:
        relative = Path(nas_path)
        if relative.is_absolute() or ".." in relative.parts or not RELATIVE_RE.fullmatch(nas_path):
            raise ValueError("invalid NAS path")
    if executor == "finder" and not nas_path:
        raise ValueError("finder request requires NAS path")
    request = {
        "request_id": f"req-{_now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}",
        "status": "pending",
        "executor": executor,
        "title": title[:160],
        "prompt": prompt,
        "task_id": task_id,
        "target_machine": target_machine,
        "created_at": _iso(),
    }
    if nas_path:
        request["nas_path"] = nas_path
    path = queue_path()
    with _locked(path):
        payload = _load(path)
        requests = payload.setdefault("requests", [])
        if not isinstance(requests, list):
            requests = payload["requests"] = []
        requests.append(request)
        _save(path, payload)
    return dict(request)


def pending(machine_id: str) -> list[dict[str, object]]:
    if not ID_RE.fullmatch(machine_id):
        raise ValueError("invalid machine id")
    result = []
    for request in _load(queue_path()).get("requests", []):
        if not isinstance(request, dict) or request.get("status") != "pending":
            continue
        target = str(request.get("target_machine") or "")
        if not target or target == machine_id:
            result.append(dict(request))
    return result[:20]


def transition(request_id: str, *, machine_id: str, status: str, error: str = "") -> dict[str, object]:
    if not ID_RE.fullmatch(request_id) or not ID_RE.fullmatch(machine_id):
        raise ValueError("invalid request or machine id")
    if status not in {"claimed", "completed", "failed"}:
        raise ValueError("invalid request status")
    path = queue_path()
    with _locked(path):
        payload = _load(path)
        for request in payload.get("requests", []):
            if not isinstance(request, dict) or request.get("request_id") != request_id:
                continue
            current = str(request.get("status") or "")
            owner = str(request.get("claimed_by") or "")
            if status == "claimed" and current != "pending":
                raise ValueError("request is no longer pending")
            if status in {"completed", "failed"} and (current != "claimed" or owner != machine_id):
                raise ValueError("request is not owned by this bridge")
            request["status"] = status
            request["claimed_by"] = machine_id
            request[f"{status}_at"] = _iso()
            if error:
                request["error"] = error[:1000]
            _save(path, payload)
            return dict(request)
    raise ValueError("request not found")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def draft_path(task_id: str, relative_path: str) -> Path:
    if not ID_RE.fullmatch(task_id) or not relative_path or not RELATIVE_RE.fullmatch(relative_path):
        raise ValueError("invalid task or relative path")
    root = (shared_workspace_root() / "交付" / "草稿" / task_id).resolve()
    target = (root / relative_path).resolve()
    if target == root or root not in target.parents:
        raise ValueError("path escapes task draft")
    return target


def write_draft(task_id: str, relative_path: str, content: bytes, *, expected_sha256: str) -> dict[str, object]:
    if len(content) > int(ember_env("EMBER_REMOTE_WRITE_MAX_BYTES", str(256 * 1024 * 1024))):
        raise ValueError("file exceeds remote write limit")
    target = draft_path(task_id, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = sha256(target) if target.is_file() else ""
    if expected_sha256 == "*":
        if target.exists():
            raise ValueError("target already exists")
    elif not expected_sha256 or not hmac_compare(current, expected_sha256):
        raise ValueError("remote file changed; pull the latest task workspace before retrying")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return {"task_id": task_id, "path": relative_path, "size": len(content), "sha256": sha256(target)}


def hmac_compare(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)
