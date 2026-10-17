#!/usr/bin/env python3
"""Allowlisted large-file transfers between the two GStudio Macs."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root
import json, os, shlex, subprocess
from pathlib import Path, PurePosixPath
from . import workspace_paths
ROOT = _deployment_root()
CONFIG_PATH = ROOT / "config" / "gstudio-workbench.json"
class TransferError(RuntimeError): pass
def config(): return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("large_file_transfer", {})
def _safe_relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts: raise TransferError("文件路径不在允许的交付目录内。")
    return path
def local_destination(task_id, delivery_key, relative_path):
    if delivery_key not in {"draft", "final"} or not task_id.startswith("20") or "/" in task_id: raise TransferError("任务或交付类型无效。")
    relative = _safe_relative(relative_path); root = Path.home() / "Downloads" / "GStudio" / task_id; destination = (root / Path(*relative.parts)).resolve()
    if root.resolve() not in destination.parents: raise TransferError("本地下载路径无效。")
    return destination
def remote_path(task_id, delivery_key, relative_path):
    remote_root = PurePosixPath(str(config().get("remote_gstudio_root", "/nonexistent/retired-transfer"))); kind = "草稿" if delivery_key == "draft" else "正式交付" if delivery_key == "final" else ""
    if not kind: raise TransferError("交付类型无效。")
    return str(remote_root / "交付" / kind / task_id / _safe_relative(relative_path))
def download_delivery_file(task_id, delivery_key, relative_path):
    settings = config()
    if not settings.get("enabled"):
        raise TransferError("WireGuard 跨机直传已退役；请从 NAS 规范交付目录访问文件。")
    identity = Path(str(settings.get("identity_file", ""))).expanduser()
    if not identity.is_file() or identity.stat().st_mode & 0o077: raise TransferError("专用 SSH 私钥不存在或权限不安全。")
    destination = local_destination(task_id, delivery_key, relative_path); destination.parent.mkdir(parents=True, exist_ok=True)
    ssh = f"/usr/bin/ssh -i {identity} -oBatchMode=yes -oConnectTimeout=10"; source = f"{settings.get('user', '')}@{settings.get('host', '')}:{shlex.quote(remote_path(task_id, delivery_key, relative_path))}"
    result = subprocess.run(["/usr/bin/rsync", "-a", "--partial", "-e", ssh, source, str(destination)], text=True, capture_output=True, timeout=3600, check=False)
    if result.returncode: raise TransferError((result.stderr or result.stdout or "rsync 传输失败").strip())
    state = workspace_paths.local_config_root() / "transfers.json"; state.parent.mkdir(parents=True, exist_ok=True); state.write_text(json.dumps({"last_download": str(destination)}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"); os.chmod(state, 0o600)
    return destination
