#!/usr/bin/env python3
"""Poll GStudio Central, prepare a task workset, and launch a local executor."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = _deployment_root()
from . import gstudio_opencode
from .workspace_paths import local_config_root, shared_workspace_root


DEFAULT_CONFIG = local_config_root() / "central.json"
DEFAULT_WORK_ROOT = Path.home() / "Library" / "Caches" / "GStudio" / "remote-work"


class BridgeError(RuntimeError):
    pass


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise BridgeError(f"cannot read bridge config: {path}") from exc
    required = ["url", "token", "machine_id"]
    if any(not str(payload.get(key) or "").strip() for key in required):
        raise BridgeError("bridge config requires url, token, and machine_id")
    return payload


def request(
    config: dict[str, object],
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    base = str(config["url"]).rstrip("/")
    data = content
    actual_headers = {"Authorization": f"Bearer {config['token']}", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        actual_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=actual_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise BridgeError(f"central returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(f"cannot reach GStudio Central: {exc.reason}") from exc


def json_request(config: dict[str, object], path: str, **kwargs) -> dict[str, object]:
    value = json.loads(request(config, path, **kwargs).decode("utf-8"))
    if isinstance(value, dict) and value.get("error"):
        raise BridgeError(str(value["error"]))
    return value


def register(config: dict[str, object]) -> dict[str, object]:
    executors = sorted(set(config.get("executors") or ["codex", "opencode"]) | {"finder"})
    return json_request(config, "/api/bridge/register", method="POST", payload={
        "machine_id": config["machine_id"],
        "label": config.get("label") or config["machine_id"],
        "executors": executors,
    })


def work_root(config: dict[str, object], task_id: str) -> Path:
    configured = config.get("work_root")
    return (Path(str(configured)).expanduser() if configured else DEFAULT_WORK_ROOT) / task_id


def pull_task(config: dict[str, object], task_id: str) -> Path:
    root = work_root(config, task_id)
    root.parent.mkdir(parents=True, exist_ok=True)
    archive_data = request(config, f"/api/bridge/tasks/{urllib.parse.quote(task_id)}/bundle")
    with tempfile.TemporaryDirectory(prefix="gstudio-bridge-") as temporary:
        archive_path = Path(temporary) / "bundle.zip"
        archive_path.write_bytes(archive_data)
        extracted = Path(temporary) / "work"
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as bundle:
            for member in bundle.infolist():
                target = (extracted / member.filename).resolve()
                if extracted.resolve() not in target.parents and target != extracted.resolve():
                    raise BridgeError("unsafe path in task bundle")
            bundle.extractall(extracted)
        previous = root.with_name(root.name + ".previous")
        if previous.exists():
            shutil.rmtree(previous)
        if root.exists():
            root.replace(previous)
        shutil.move(str(extracted), str(root))
        if previous.exists():
            shutil.rmtree(previous)
    return root


def launch_codex(prompt: str) -> None:
    subprocess.run(["/usr/bin/pbcopy"], input=prompt, text=True, check=True, timeout=10)
    subprocess.run(["/usr/bin/open", "-b", "com.openai.codex", str(ROOT)], check=True, timeout=10)


def reveal_nas_path(value: str) -> None:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise BridgeError("invalid NAS path")
    root = shared_workspace_root().resolve()
    if not root.is_dir():
        raise BridgeError(f"NAS mount is unavailable: {root}")
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise BridgeError("NAS path escapes the shared workspace")
    if not target.exists():
        raise BridgeError(f"NAS path not found: {target}")
    command = ["/usr/bin/open", str(target)] if target.is_dir() else ["/usr/bin/open", "-R", str(target)]
    subprocess.run(command, check=True, timeout=10)


def launch_request(config: dict[str, object], item: dict[str, object]) -> None:
    executor = str(item.get("executor") or "")
    if executor == "finder":
        reveal_nas_path(str(item.get("nas_path") or ""))
        return
    task_id = str(item.get("task_id") or "")
    local_root = pull_task(config, task_id) if task_id else None
    prompt = str(item.get("prompt") or "")
    if local_root:
        prompt += (
            "\n\n## 余烬 · Ember Central 工作集\n\n"
            f"- 本机按需工作目录：`{local_root}`\n"
            "- `task/`、`inputs/` 和 `delivery/` 是本次领取时的快照。\n"
            "- 新增或修改交付文件后，使用本机 余烬 · Ember 的 "
            "`python3 scripts/gstudio_execution_bridge.py push --task-id <task_id> --file <本地文件> --remote-path <草稿相对路径>` "
            "受控写回 NAS；不要把任务卡快照当作正本直接覆盖。\n"
        )
    if executor == "codex":
        launch_codex(prompt)
    elif executor == "opencode":
        gstudio_opencode.launch_in_otty(title=str(item.get("title") or "余烬 · Ember"), prompt=prompt)
    else:
        raise BridgeError("unsupported executor")


def poll_once(config: dict[str, object]) -> bool:
    register(config)
    machine_id = str(config["machine_id"])
    payload = json_request(config, "/api/bridge/pending?machine_id=" + urllib.parse.quote(machine_id))
    requests = payload.get("requests") or []
    if not requests:
        return False
    item = requests[0]
    request_id = str(item["request_id"])
    json_request(config, f"/api/bridge/requests/{urllib.parse.quote(request_id)}", method="POST", payload={
        "machine_id": machine_id, "status": "claimed"
    })
    try:
        launch_request(config, item)
    except Exception as exc:
        json_request(config, f"/api/bridge/requests/{urllib.parse.quote(request_id)}", method="POST", payload={
            "machine_id": machine_id, "status": "failed", "error": str(exc)
        })
        raise
    json_request(config, f"/api/bridge/requests/{urllib.parse.quote(request_id)}", method="POST", payload={
        "machine_id": machine_id, "status": "completed"
    })
    return True


def push_file(config: dict[str, object], *, task_id: str, file: Path, remote_path: str) -> dict[str, object]:
    if not file.is_file():
        raise BridgeError(f"local file not found: {file}")
    root = work_root(config, task_id)
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        manifest = {"files": []}
    logical = f"delivery/draft/{remote_path}"
    base = next((str(item.get("sha256") or "") for item in manifest.get("files", []) if item.get("path") == logical), "*")
    encoded = "/".join(urllib.parse.quote(part) for part in remote_path.split("/"))
    result = json_request(
        config,
        f"/api/bridge/tasks/{urllib.parse.quote(task_id)}/draft/{encoded}",
        method="PUT",
        content=file.read_bytes(),
        headers={"Content-Type": "application/octet-stream", "X-GStudio-Base-SHA256": base},
    )
    digest = str(result.get("sha256") or hashlib.sha256(file.read_bytes()).hexdigest())
    files = [item for item in manifest.get("files", []) if isinstance(item, dict) and item.get("path") != logical]
    files.append({"path": logical, "sha256": digest, "size": file.stat().st_size})
    manifest["files"] = files
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "once", "register", "pull", "push"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task-id", default="")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--remote-path", default="")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == "register":
            print(json.dumps(register(config), ensure_ascii=False, indent=2))
        elif args.command == "pull":
            print(pull_task(config, args.task_id))
        elif args.command == "push":
            if not args.file or not args.task_id or not args.remote_path:
                raise BridgeError("push requires --task-id, --file, and --remote-path")
            print(json.dumps(push_file(config, task_id=args.task_id, file=args.file, remote_path=args.remote_path), ensure_ascii=False, indent=2))
        elif args.command == "once":
            return 0 if poll_once(config) else 3
        else:
            interval = max(3, int(config.get("poll_interval_seconds") or 10))
            while True:
                try:
                    poll_once(config)
                except BridgeError as exc:
                    print(str(exc), file=sys.stderr, flush=True)
                time.sleep(interval)
    except (BridgeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f"GStudio execution bridge: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
