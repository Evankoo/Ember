"""Machine-local pointer to the default workspace, so AI tools in any folder can find it."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .bootstrap import PACKAGE, verify_workspace_contract
from .store import Workspace, WorkspaceError

DAILY_SKILL = "ember"
# User-level Skills folders of common AI tools; only used to find copies that already exist.
KNOWN_SKILL_DIRS = (".claude/skills", ".agents/skills", ".codex/skills", ".config/opencode/skills")


def config_path(home=None) -> Path:
    return Path(home or Path.home()).absolute() / ".config/ember/workspace.json"


def _write_private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=f".{path.stem}-", delete=False, encoding="utf-8") as output:
        os.chmod(output.name, 0o600)
        output.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(output.name, path)


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
    record = {"version": 1, "workspace": str(workspace.path), "documents": str(workspace.docs),
              "python": str(Path(python or sys.executable).absolute()),
              "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if existing and all(existing.get(key) == record[key] for key in ("workspace", "documents", "python")):
        return existing
    _write_private_json(config_path(home), record)
    return record


def resolve_workspace(value=None, home=None) -> Workspace:
    if value is not None:
        return Workspace(value)
    stored = read_default(home)
    if stored is None:
        raise WorkspaceError("尚未登记默认工作区：请用 --workspace 指定，或运行 ember use <工作区>。")
    return Workspace(stored["workspace"])


def fingerprint(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b"\0" + hashlib.sha256(files[name]).digest())
    return digest.hexdigest()


def _read_tree(root: Path) -> dict[str, bytes]:
    """Skill files that define its behavior; the LICENSE shipped in the initial ZIP is not one of them."""
    files = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
             if p.is_file() and p.name != ".DS_Store" and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    files.pop("LICENSE", None)
    return files


def _source_tree() -> dict[str, bytes]:
    return _read_tree(PACKAGE / "skills" / DAILY_SKILL)


def _official_fingerprints() -> dict[str, str]:
    """Released copies that may be replaced without asking; anything else may hold local edits."""
    stored = json.loads((PACKAGE / "skills/official-fingerprints.json").read_text(encoding="utf-8"))
    return stored[DAILY_SKILL]


def _targets_path(home=None) -> Path:
    return config_path(home).with_name("skill-targets.json")


def remembered_targets(home=None) -> list[str]:
    try:
        stored = json.loads(_targets_path(home).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise WorkspaceError(f"Skill 安装记录不可读，原文件保留：{_targets_path(home)}") from None
    return [item for item in stored.get("targets", []) if isinstance(item, str)]


def refresh_targets(home=None) -> list[str]:
    """Remembered folders plus known folders that already hold a copy (installed before 0.6.0)."""
    base = Path(home or Path.home()).absolute()
    found = [str(base / name) for name in KNOWN_SKILL_DIRS if (base / name / DAILY_SKILL).is_dir()]
    return list(dict.fromkeys(remembered_targets(home) + found))


def install_skill(target, home=None) -> dict:
    target = Path(target).expanduser().absolute()
    destination = target / DAILY_SKILL
    if destination.is_symlink():
        raise WorkspaceError(f"{destination} 是符号链接，未写入；请改为普通目录或手动维护。")
    files = _source_tree()
    version, previous = skill_version(), None
    if destination.exists():
        installed = fingerprint(_read_tree(destination))
        if installed == fingerprint(files):
            _remember(target, home)
            return {"status": "unchanged", "path": str(destination), "version": version}
        previous = next((name for name, value in _official_fingerprints().items() if value == installed), None)
        if previous is None:
            raise WorkspaceError(f"目标已有内容不同、也不是官方旧版本的 {DAILY_SKILL}，未覆盖：{destination}。请先比较本地修改。", 409)
    target.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{DAILY_SKILL}-new-", dir=target))
    retired = None
    try:
        for name, data in files.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if previous:
            retired = target / f".{DAILY_SKILL}-old-{os.getpid()}"
            os.rename(destination, retired)
        try:
            os.rename(staging, destination)
        except OSError:
            if retired:
                os.rename(retired, destination)
                retired = None
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if retired:
            shutil.rmtree(retired, ignore_errors=True)
    _remember(target, home)
    result = {"status": "upgraded" if previous else "installed", "path": str(destination), "version": version}
    if previous:
        result["from"] = previous
    return result


def skill_version() -> str:
    header = (PACKAGE / "skills" / DAILY_SKILL / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
    return next(line.split(":", 1)[1].strip() for line in header.splitlines() if line.startswith("version:"))


def _remember(target: Path, home=None) -> None:
    targets = remembered_targets(home)
    if str(target) not in targets:
        _write_private_json(_targets_path(home), {"version": 1, "targets": targets + [str(target)]})
