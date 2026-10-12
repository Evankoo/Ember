"""Machine-local pointer to the default workspace, so AI tools in any folder can find it."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

from .bootstrap import PACKAGE, verify_workspace_contract
from .store import Workspace, WorkspaceError

DAILY_SKILL = "gstudio-core"


def config_path(home=None) -> Path:
    return Path(home or Path.home()).absolute() / ".config/gstudio-core/workspace.json"


def read_default(home=None) -> dict | None:
    path = config_path(home)
    if path.is_symlink() or path.parent.is_symlink():
        raise WorkspaceError("默认工作区配置不能使用符号链接。")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise WorkspaceError(f"默认工作区配置不可读，原文件保留：{path}") from None
    if not isinstance(stored, dict) or stored.get("version") != 1 or not isinstance(stored.get("workspace"), str):
        raise WorkspaceError(f"默认工作区配置格式不正确，原文件保留：{path}")
    return stored


def register_default(workspace: Workspace, python=None, *, replace=False, home=None) -> dict:
    verify_workspace_contract(workspace)
    existing = read_default(home)
    if existing and existing["workspace"] != str(workspace.path) and not replace:
        raise WorkspaceError(f"本机已登记另一个默认工作区：{existing['workspace']}。如需切换，请明确使用 --replace。", 409)
    record = {"version": 1, "workspace": str(workspace.path),
              "python": str(Path(python or sys.executable).absolute()),
              "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if existing and all(existing.get(key) == record[key] for key in ("workspace", "python")):
        return existing
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".workspace-", delete=False, encoding="utf-8") as output:
        os.chmod(output.name, 0o600)
        output.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    os.replace(output.name, path)
    return record


def resolve_workspace(value=None, home=None) -> Workspace:
    if value is not None:
        return Workspace(value)
    stored = read_default(home)
    if stored is None:
        raise WorkspaceError("尚未登记默认工作区：请用 --workspace 指定，或运行 gstudio use <工作区>。")
    return Workspace(stored["workspace"])


def install_skill(target) -> dict:
    destination = Path(target).expanduser().absolute() / DAILY_SKILL
    if destination.is_symlink():
        raise WorkspaceError(f"{destination} 是符号链接，未写入；请改为普通目录或手动维护。")
    source = PACKAGE / "skills" / DAILY_SKILL
    files = {p.relative_to(source).as_posix(): p.read_bytes() for p in sorted(source.rglob("*"))
             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    if destination.exists():
        present = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
        if present == set(files) and all((destination / name).read_bytes() == data for name, data in files.items()):
            return {"status": "unchanged", "path": str(destination)}
        raise WorkspaceError(f"目标已有内容不同的 {DAILY_SKILL}，未覆盖：{destination}。请先比较本地修改。", 409)
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
    return {"status": "installed", "path": str(destination)}
