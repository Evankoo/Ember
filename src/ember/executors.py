"""Machine-local software metadata and explicitly confirmed, non-AI launches."""

import fcntl
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .store import WorkspaceError

DISCOVERY_ENTRY_LIMIT = 1200
DISCOVERY_DIRECTORY_LIMIT = 32
COMMON_COMMANDS = ("opencode", "codex", "claude", "gemini", "aider", "kimi", "pi", "amp", "goose", "ollama")
COMMON_APPS = {"codex", "opencode", "claude", "chatgpt", "cursor", "windsurf", "lm studio", "jan", "ollama"}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkspaceError("本机软件配置包含重复字段，请核对原文件。")
        result[key] = value
    return result


def _atomic_write(path, contents):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".executors-", delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, 0o600)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _software_path(kind, value, home):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise WorkspaceError("请填写有效的本机软件绝对路径，不要填写启动参数。")
    value = value.strip()
    path = home / value[2:] if value.startswith("~/") else Path(value)
    if not path.is_absolute():
        raise WorkspaceError("软件路径须为绝对路径或 ~/ 开头的路径。")
    try:
        if kind == "app":
            info = path / "Contents/Info.plist"
            if path.suffix.lower() != ".app" or not path.is_dir() or info.is_symlink() or info.stat().st_size > 262144:
                raise ValueError()
            metadata = plistlib.loads(info.read_bytes())
            if not isinstance(metadata, dict):
                raise ValueError()
            name = metadata.get("CFBundleExecutable")
            if not isinstance(name, str) or not name or Path(name).name != name or any(ord(c) < 32 for c in name):
                raise ValueError()
            executable = path / "Contents/MacOS" / name
        else:
            executable = path
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError()
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        raise WorkspaceError("软件路径不存在、类型不匹配或不可执行；没有改用其他软件。") from None
    return path


class ExecutorRegistry:
    def __init__(self, home=None):
        self.home = Path(home or Path.home()).absolute()
        self.path = self.home / ".config/ember/executors.json"

    def _read(self):
        if any(path.is_symlink() for path in (self.path, self.path.parent, self.path.parent.parent)):
            raise WorkspaceError("本机软件配置不能使用符号链接。")
        try:
            with os.fdopen(os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as source:
                attributes = os.fstat(source.fileno())
                if not stat.S_ISREG(attributes.st_mode) or attributes.st_size > 262144:
                    raise WorkspaceError("本机软件配置不是可读取的小型普通文件。")
                return source.read(262145)
        except FileNotFoundError:
            return None
        except OSError:
            raise WorkspaceError("本机软件配置暂不可读，请核对文件权限。") from None

    def _load(self):
        contents = self._read()
        try:
            stored = json.loads(contents.decode("utf-8"), object_pairs_hook=_unique_pairs) if contents is not None else {}
            if not isinstance(stored, dict) or type(stored.get("version", 1)) is not int or stored.get("version", 1) != 1:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise WorkspaceError("本机软件配置格式不可读；原文件保留，未当作空配置。") from None
        return contents, stored

    @staticmethod
    def _revision(contents):
        return hashlib.sha256(contents or b"").hexdigest()

    def _entries(self, entries, check_paths=False):
        if not isinstance(entries, list) or len(entries) > 32:
            raise WorkspaceError("请提供最多 32 项本机软件。")
        result, ids, paths = [], set(), set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"id", "label", "kind", "path"}:
                raise WorkspaceError("软件登记只接受名称、类型、路径和本地标识。")
            identifier, label, kind, value = (entry.get(key) for key in ("id", "label", "kind", "path"))
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier) or identifier in ids:
                raise WorkspaceError("软件标识无效或重复。")
            if not isinstance(label, str) or not label.strip() or len(label) > 80 or any(ord(c) < 32 for c in label):
                raise WorkspaceError("请填写不超过 80 字的单行软件名称。")
            if not isinstance(kind, str) or kind not in {"app", "command"}:
                raise WorkspaceError("软件类型只能是 macOS 应用或命令行程序。")
            if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(ord(c) < 32 for c in value):
                raise WorkspaceError("请填写有效的软件路径。")
            path = self.home / value.strip()[2:] if value.strip().startswith("~/") else Path(value.strip())
            if not path.is_absolute():
                raise WorkspaceError("软件路径须为绝对路径。")
            if check_paths:
                path = _software_path(kind, str(path), self.home)
            try:
                key = (kind, str(path.resolve()))
            except (OSError, RuntimeError):
                raise WorkspaceError("软件路径无法解析。") from None
            if key in paths:
                raise WorkspaceError("同一软件路径已经登记，请修改现有条目。")
            ids.add(identifier)
            paths.add(key)
            result.append({"id": identifier, "label": label.strip(), "kind": kind, "path": str(path)})
        return result

    def snapshot(self):
        view = {"executors": [], "default_executor": "", "revision": None, "ready": False,
                "registry_readable": False, "error": "", "config_path": str(self.path)}
        try:
            contents, stored = self._load()
            entries = self._entries(stored.get("executors", []))
            default = stored.get("default_executor", "")
            if not isinstance(default, str) or (default and default not in {entry["id"] for entry in entries}):
                raise WorkspaceError("默认软件不在已保存的本机清单中。")
            view.update(executors=entries, default_executor=default, revision=self._revision(contents), registry_readable=True)
            selected = next((entry for entry in entries if entry["id"] == default), None)
            if selected is not None:
                _software_path(selected["kind"], selected["path"], self.home)
                view["ready"] = True
        except WorkspaceError as error:
            view["error"] = str(error)
        return view

    def validate(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"executors", "default_executor", "expected_revision"}:
            raise WorkspaceError("软件配置包含不支持的字段。")
        self._load()
        entries = self._entries(payload.get("executors"), check_paths=True)
        default = payload.get("default_executor")
        if not isinstance(default, str) or (entries and default not in {entry["id"] for entry in entries}) or (not entries and default):
            raise WorkspaceError("请从本机已添加清单选择默认软件。")
        return {"executors": entries, "default_executor": default, "authentication_verified": False}

    def save(self, payload):
        normalized = self.validate(payload)
        before, stored = self._load()
        if payload.get("expected_revision") != self._revision(before):
            raise WorkspaceError("本机配置已改变，请刷新后重新修改。", 409)
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(self.path.parent / ".executors.lock", flags, 0o600), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                before, stored = self._load()
                if payload.get("expected_revision") != self._revision(before):
                    raise WorkspaceError("本机配置已改变，请刷新后重新修改。", 409)
                stored.update(version=1, executors=normalized["executors"], default_executor=normalized["default_executor"])
                after = (json.dumps(stored, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                if before == after:
                    return {**self.snapshot(), "changed_files": 0, "backup_folder": ""}
                backup = None
                if before is not None:
                    folder = self.path.parent / "backups"
                    if folder.is_symlink():
                        raise WorkspaceError("配置备份目录不能使用符号链接。")
                    folder.mkdir(mode=0o700, exist_ok=True)
                    backup = folder / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                    backup.mkdir(mode=0o700)
                    _atomic_write(backup / "executors.json", before)
                if self._read() != before:
                    raise WorkspaceError("本机配置已改变，未覆盖其他修改。", 409)
                try:
                    _atomic_write(self.path, after)
                except OSError:
                    if self._read() == after:
                        if before is None:
                            self.path.unlink()
                        else:
                            _atomic_write(self.path, before)
                    raise
                return {**self.snapshot(), "changed_files": 1, "backup_folder": str(backup or "")}
        except OSError:
            raise WorkspaceError("本机软件配置保存失败；原配置和备份保留，请核对权限后重试。") from None

    def open_software(self, payload, workspace):
        if not isinstance(payload, dict) or set(payload) != {"executor_id", "expected_revision", "confirmation"} or payload.get("confirmation") is not True:
            raise WorkspaceError("仅接受明确确认后的已登记软件标识，不接受路径、提示词或模型参数。")
        view = self.snapshot()
        if not view["registry_readable"] or not view["ready"]:
            raise WorkspaceError(view["error"] or "请先在设置页保存有效的默认软件。")
        if payload["expected_revision"] != view["revision"] or payload["executor_id"] != view["default_executor"]:
            raise WorkspaceError("默认软件或本机配置已改变，请重新查看上下文与执行确认。", 409)
        selected = next(entry for entry in view["executors"] if entry["id"] == payload["executor_id"])
        path = _software_path(selected["kind"], selected["path"], self.home)
        workspace = Path(workspace).resolve()
        if not workspace.is_dir():
            raise WorkspaceError("所选工作区已不可用，未启动软件。")
        try:
            if selected["kind"] == "app":
                if sys.platform != "darwin":
                    raise WorkspaceError(".app 打开仅支持 macOS，请使用本机命令行软件或手工打开。")
                subprocess.run(["/usr/bin/open", "-a", str(path)], check=True, timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "darwin":
                command = "cd " + shlex.quote(str(workspace)) + " && exec " + shlex.quote(str(path))
                script = 'tell application "Terminal"\nactivate\ndo script ' + json.dumps(command, ensure_ascii=False) + '\nend tell'
                subprocess.run(["/usr/bin/osascript", "-"], input=script, text=True, check=True, timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("linux"):
                terminal = next((value for name in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm") if (value := shutil.which(name))), None)
                if not terminal or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                    raise WorkspaceError("没有可用的图形终端；上下文保留，请手工打开软件。")
                flag = "--" if Path(terminal).name == "gnome-terminal" else "-e"
                command = "cd " + shlex.quote(str(workspace)) + " && exec " + shlex.quote(str(path))
                subprocess.Popen([terminal, flag, "/bin/sh", "-c", command], cwd=workspace,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                raise WorkspaceError("当前系统不支持软件打开；上下文保留，请手工执行。")
        except (OSError, subprocess.SubprocessError):
            raise WorkspaceError("软件未能打开；上下文保留，请在软件中手工粘贴执行。") from None
        return {"opened": True, "label": selected["label"], "submitted": False, "model_called": False}

    def discover(self, *, application_roots=None, command_dirs=None):
        roots = list(application_roots) if application_roots is not None else [Path("/Applications"), self.home / "Applications", Path("/System/Applications")]
        directories = list(command_dirs) if command_dirs is not None else [self.home / ".opencode/bin", self.home / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"), self.home / ".local/share/opencode/bin", *(Path(value) for value in os.environ.get("PATH", "").split(os.pathsep) if value)]
        candidates, warnings, seen = [], [], set()
        started, visited, searched, limited = time.monotonic(), 0, 0, False

        def budget():
            nonlocal limited
            if visited >= DISCOVERY_ENTRY_LIMIT or searched >= DISCOVERY_DIRECTORY_LIMIT or time.monotonic() - started > 2:
                limited = True
                return False
            return True

        def add(kind, path, label, source):
            try:
                path = _software_path(kind, str(path), self.home)
                key = kind + ":" + str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    candidates.append({"id": "local-" + hashlib.sha256(key.encode()).hexdigest()[:16],
                                       "kind": kind, "label": label, "path": str(path), "source": source})
            except (WorkspaceError, OSError, RuntimeError):
                pass

        def scan(folder, depth):
            nonlocal visited, searched
            if not budget():
                return
            searched += 1
            try:
                with os.scandir(folder) as entries:
                    for item in entries:
                        if not budget():
                            break
                        visited += 1
                        if item.name.startswith(".") or not item.is_dir(follow_symlinks=False):
                            continue
                        path = Path(item.path)
                        if path.suffix.lower() == ".app":
                            if path.stem.casefold() in COMMON_APPS:
                                add("app", path, path.stem, "应用目录")
                        elif depth < 2:
                            scan(path, depth + 1)
            except (FileNotFoundError, NotADirectoryError):
                pass
            except OSError:
                warnings.append("部分应用目录不可读，结果可能不完整，可手工添加。")

        for root in roots[:3]:
            scan(Path(root), 0)
        for folder in dict.fromkeys(str(value) for value in directories):
            if not budget():
                break
            path = Path(folder)
            if not path.is_absolute():
                continue
            searched += 1
            try:
                path.stat()
                for name in COMMON_COMMANDS:
                    if not budget():
                        break
                    visited += 1
                    candidate = path / name
                    try:
                        candidate.stat()
                        add("command", candidate, name, "命令安装目录")
                    except (FileNotFoundError, NotADirectoryError):
                        pass
            except (FileNotFoundError, NotADirectoryError):
                pass
            except OSError:
                warnings.append("部分命令目录不可读，结果可能不完整，可手工添加。")
        return {"candidates": sorted(candidates, key=lambda entry: (entry["label"].casefold(), entry["path"])),
                "warnings": list(dict.fromkeys(warnings)), "limited": limited,
                "scope": "只查找常见应用目录（最多两层）和命令安装目录；不启动、不安装、不读取客户端配置、不保存。"}
