#!/usr/bin/env python3
"""Machine-local software paths. Client models and authentication are not ours."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path


class SettingsError(ValueError):
    pass


def configuration_paths(*, home: Path | None = None) -> dict[str, Path]:
    override = os.environ.get("GSTUDIO_EXECUTOR_CONFIG", "") if home is None else ""
    if override:
        return {"executors": Path(override).expanduser()}
    if home is not None:
        return {"executors": home / ".config/gstudio/executors.json"}
    from . import workspace_paths
    return {"executors": workspace_paths.local_config_root() / "executors.json"}


def _read(path: Path) -> bytes | None:
    if path.is_symlink() or path.parent.is_symlink():
        raise SettingsError("配置文件不能是符号链接。")
    if not path.exists():
        return None
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise SettingsError("配置文件类型或大小不正确。")
        content = path.read_bytes()
        content.decode("utf-8")
        return content
    except (OSError, UnicodeError) as error:
        raise SettingsError("无法安全读取 余烬 · Ember 配置文件。") from error


def _object(content: bytes | None) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=unique) if content is not None else {}
        if not isinstance(result, dict):
            raise ValueError("not an object")
        return result
    except (ValueError, UnicodeError) as error:
        raise SettingsError("余烬 · Ember 配置不是有效且字段唯一的 JSON；未修改。") from error


def validate_software_path(executor: str, value: str, *, home: Path | None = None) -> Path:
    label = "Codex 应用" if executor == "codex" else "应用" if executor == "app" else "程序"
    if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise SettingsError(f"{label}路径不能为空，也不能包含命令参数或控制字符。")
    text = value.strip()
    path = (home / text[2:]) if home is not None and text.startswith("~/") else Path(text).expanduser()
    if not path.is_absolute():
        raise SettingsError(f"{label}需要绝对路径或 ~/ 开头的路径。")
    try:
        if executor in {"codex", "app"}:
            if path.suffix.lower() != ".app" or not path.is_dir():
                raise SettingsError("应用路径需要指向实际的 .app 应用。")
            info_path = path / "Contents/Info.plist"
            if info_path.stat().st_size > 2 * 1024 * 1024:
                raise SettingsError("应用信息不正确。")
            info = plistlib.loads(info_path.read_bytes())
            entry = info.get("CFBundleExecutable")
            if not isinstance(entry, str) or not entry or Path(entry).name != entry or any(ord(c) < 32 for c in entry):
                raise SettingsError("应用的启动程序信息不正确。")
            if executor == "codex" and info.get("CFBundleIdentifier") != "com.openai.codex":
                raise SettingsError("该应用不是可识别的 Codex 应用。")
            executable = path / "Contents/MacOS" / entry
        else:
            executable = path
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise SettingsError(f"{label}不存在或不可执行。")
        return path
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError) as error:
        if isinstance(error, SettingsError):
            raise
        raise SettingsError(f"无法验证{label}路径。") from error


def _detect(executor: str, *, home: Path | None = None) -> str:
    base = home or Path.home()
    candidates = ["/Applications/Codex.app", "/Applications/ChatGPT.app"] if executor == "codex" else [
        os.environ.get("GSTUDIO_OPENCODE_COMMAND", ""), shutil.which("opencode") or "",
        str(base / ".opencode/bin/opencode"), str(base / ".local/bin/opencode"),
        "/opt/homebrew/bin/opencode", "/usr/local/bin/opencode",
        str(base / ".local/share/opencode/bin/opencode"),
    ]
    for candidate in candidates:
        if candidate:
            try:
                return str(validate_software_path(executor, candidate, home=home))
            except SettingsError:
                pass
    return ""


DISCOVERY_ENTRY_LIMIT = 1200
DISCOVERY_DIRECTORY_LIMIT = 32
DISCOVERY_DEPTH_LIMIT = 2
COMMON_AI_COMMANDS = ("opencode", "codex", "claude", "gemini", "aider", "kimi", "pi", "amp", "goose", "ollama")
COMMON_AI_APPS = {"codex", "opencode", "claude", "chatgpt", "cursor", "windsurf", "lm studio", "jan", "ollama"}


def discover_software(*, home: Path | None = None, application_roots=None, command_dirs=None) -> dict:
    """Bounded local metadata discovery; never execute software or touch preferences."""
    base = home or Path.home()
    roots = application_roots if application_roots is not None else [Path('/Applications'), base / 'Applications', Path('/System/Applications')]
    if command_dirs is None:
        command_dirs = [base / '.opencode/bin', base / '.local/bin', Path('/opt/homebrew/bin'),
                        Path('/usr/local/bin'), base / '.local/share/opencode/bin']
        command_dirs += [Path(item) for item in os.environ.get('PATH', '').split(os.pathsep) if item]
        override = os.environ.get('GSTUDIO_OPENCODE_COMMAND', '')
        if override:
            command_dirs.append(Path(override).expanduser().parent)
    result = {'candidates': [], 'warnings': [], 'limited': False, 'authentication_verified': False,
              'scope': '仅查找常见应用目录（最多两层）和命令安装目录中的常见 AI 软件；不是完整软件清单，不启动软件、不读取客户端配置、不保存。'}
    seen = set()
    started = time.monotonic()
    visited = 0

    def exhausted():
        if visited >= DISCOVERY_ENTRY_LIMIT or time.monotonic() - started > 2:
            result['limited'] = True
            return True
        return False

    def add(executor, path, source, *, label="", kind="command"):
        try:
            validated = validate_software_path("codex" if executor == "codex" and kind == "app" else kind, str(path), home=home)
            identity = (kind, str(validated.resolve()))
            if identity not in seen:
                seen.add(identity)
                identifier = 'local-' + hashlib.sha256((kind + ':' + identity[1]).encode()).hexdigest()[:16]
                result['candidates'].append({'id': identifier, 'executor': executor, 'kind': kind,
                                             'label': label or executor, 'path': str(validated), 'source': source})
        except (SettingsError, OSError, RuntimeError):
            pass

    for root in list(roots)[:3]:
        pending = [(Path(root), 0)]
        while pending and not exhausted():
            folder, depth = pending.pop()
            if not folder.is_absolute() or folder.is_symlink():
                continue
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if exhausted():
                            break
                        visited += 1
                        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                            continue
                        path = Path(entry.path)
                        if path.suffix.lower() == '.app':
                            try:
                                validated = validate_software_path('app', str(path), home=home)
                                info = plistlib.loads((validated / 'Contents/Info.plist').read_bytes())
                                if info.get('CFBundleIdentifier') == 'com.openai.codex':
                                    add('codex', path, '应用目录', label='Codex', kind='app')
                                elif path.stem.casefold() in COMMON_AI_APPS:
                                    add('app', path, '应用目录', label=path.stem, kind='app')
                            except (SettingsError, OSError, ValueError, plistlib.InvalidFileException):
                                pass
                        elif depth < DISCOVERY_DEPTH_LIMIT and not entry.name.startswith('.'):
                            pending.append((path, depth + 1))
            except FileNotFoundError:
                pass
            except OSError:
                if not result['warnings']:
                    result['warnings'].append('部分应用目录无法读取；结果可能不完整，可手动填写路径。')
    directories = list(dict.fromkeys(str(Path(item).expanduser()) for item in command_dirs))
    if len(directories) > DISCOVERY_DIRECTORY_LIMIT:
        result['limited'] = True
    for directory in directories[:DISCOVERY_DIRECTORY_LIMIT]:
        if exhausted():
            break
        visited += 1
        path = Path(directory)
        if path.is_absolute():
            try:
                path.stat()
                for command in COMMON_AI_COMMANDS:
                    if exhausted():
                        break
                    visited += 1
                    candidate = path / command
                    try:
                        candidate.stat()
                        add(command, candidate, '命令安装目录', label='OpenCode' if command == 'opencode' else command)
                    except (FileNotFoundError, NotADirectoryError):
                        pass
            except (FileNotFoundError, NotADirectoryError):
                pass
            except OSError:
                warning = '部分命令目录无法读取；结果可能不完整，可手动填写路径。'
                if warning not in result['warnings']:
                    result['warnings'].append(warning)
    result['candidates'].sort(key=lambda item: (item['label'].casefold(), item['path'].casefold()))
    return result


def _registry_entries(value, *, home: Path | None = None, check_paths: bool = False) -> list[dict]:
    if isinstance(value, str):
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = item
            return result
        try:
            value = json.loads(value, object_pairs_hook=unique)
        except ValueError as error:
            raise SettingsError("软件列表不是有效的 JSON。") from error
    if not isinstance(value, list) or len(value) > 32:
        raise SettingsError("软件列表需要是最多 32 项的列表。")
    result, identifiers, paths = [], set(), set()
    for item in value:
        if not isinstance(item, dict):
            raise SettingsError("软件条目格式不正确。")
        identifier, label, kind, text = (item.get(key, "") for key in ("id", "label", "kind", "path"))
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier) or identifier in identifiers or identifier == "kimi":
            raise SettingsError("软件标识不正确或重复。")
        if not isinstance(label, str) or not label.strip() or len(label) > 80 or any(ord(c) < 32 for c in label):
            raise SettingsError("请填写有效的软件名称。")
        if not isinstance(kind, str) or kind not in {"app", "command"} or not isinstance(text, str) or not text.strip() or len(text) > 4096 or any(ord(c) < 32 for c in text):
            raise SettingsError("软件类型或路径不正确。")
        if identifier == "codex" and kind != "app" or identifier == "opencode" and kind != "command":
            raise SettingsError("已有软件标识与类型不匹配。")
        path = home / text.strip()[2:] if home is not None and text.strip().startswith("~/") else Path(text.strip()).expanduser()
        if not path.is_absolute():
            raise SettingsError("软件需要绝对路径或 ~/ 开头的路径。")
        if check_paths:
            path = validate_software_path("codex" if identifier == "codex" else kind, str(path), home=home)
        try:
            identity = (kind, str(path.resolve()))
        except (OSError, RuntimeError) as error:
            raise SettingsError("软件路径无法安全定位。") from error
        if identity in paths:
            raise SettingsError("同一个软件路径不能重复登记。")
        identifiers.add(identifier)
        paths.add(identity)
        result.append({"id": identifier, "label": label.strip(), "kind": kind, "path": str(path)})
    return result


def _stored_entries(stored: dict, *, home: Path | None = None) -> list[dict]:
    if "local_executors" in stored:
        return _registry_entries(stored["local_executors"], home=home)
    entries = []
    for identifier, label, kind in (("codex", "Codex", "app"), ("opencode", "OpenCode", "command")):
        block = stored.get(identifier, {})
        if not isinstance(block, dict) or not isinstance(block.get("path", ""), str):
            raise SettingsError("已有软件路径配置格式不正确。")
        if block.get("path"):
            entries.append({"id": identifier, "label": label, "kind": kind, "path": block["path"]})
    return _registry_entries(entries, home=home)


def executor_definition(identifier: str, *, home: Path | None = None) -> dict:
    stored = _object(_read(configuration_paths(home=home)["executors"]))
    for entry in _stored_entries(stored, home=home):
        if entry["id"] == identifier:
            validate_software_path("codex" if identifier == "codex" else entry["kind"], entry["path"], home=home)
            return entry
    raise SettingsError("该软件未在本机设置中登记，请先在设置页添加并保存。")


def _prepare(payload: dict, *, home: Path | None = None):
    default = payload.get("default_executor", "")
    path = configuration_paths(home=home)["executors"]
    before = _read(path)
    stored = _object(before)
    if "executors" in payload:
        entries = _registry_entries(payload["executors"], home=home, check_paths=True)
        if not isinstance(default, str) or (entries and default not in {item["id"] for item in entries}) or (not entries and default):
            raise SettingsError("请从已添加的软件中选择默认软件。")
        stored.update({"local_executors": entries, "default_executor": default})
        normalized = {"default_executor": default, "executors": entries, "authentication_verified": False}
        after = (json.dumps(stored, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return normalized, path, before, after
    if "local_executors" in stored:
        raise SettingsError("配置已使用软件列表，请刷新设置页后再保存。")
    if not isinstance(default, str) or default not in {"codex", "opencode"}:
        raise SettingsError("请选择已登记的软件作为默认执行器。")
    normalized = {"default_executor": default, "authentication_verified": False}
    for executor in ("codex", "opencode"):
        value = payload.get(executor + "_path", "")
        if not isinstance(value, str):
            raise SettingsError("软件路径必须是文本。")
        value = str(validate_software_path(executor, value, home=home)) if value.strip() else ""
        if executor == default and not value:
            raise SettingsError("请填写默认执行器的软件路径。")
        normalized[executor + "_path"] = value
        block = stored.get(executor, {})
        if not isinstance(block, dict):
            raise SettingsError("已有执行器配置格式不正确；未修改。")
        stored[executor] = {**block, "path": value}
    stored["default_executor"] = default
    after = (json.dumps(stored, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return normalized, path, before, after


def validate_settings(payload: dict, *, home: Path | None = None) -> dict:
    return _prepare(payload, home=home)[0]


def read_settings(*, home: Path | None = None) -> dict:
    result = {"default_executor": "", "executors": [], "local_registry": False, "registry_readable": False, "codex_path": "", "opencode_path": "", "ready": False, "error": ""}
    try:
        stored = _object(_read(configuration_paths(home=home)["executors"]))
        result["local_registry"] = "local_executors" in stored
        default = stored.get("default_executor", "")
        if not isinstance(default, str):
            raise SettingsError("默认执行器配置不正确。")
        result["default_executor"] = default
        result["executors"] = _stored_entries(stored, home=home)
        for executor in ("codex", "opencode"):
            block = stored.get(executor, {})
            if not isinstance(block, dict) or not isinstance(block.get("path", ""), str):
                raise SettingsError("软件路径配置格式不正确。")
            result[executor + "_path"] = block.get("path", "") or _detect(executor, home=home)
        result["registry_readable"] = True
        if not default:
            result["error"] = "请在设置页添加本机软件，选择默认软件并保存。"
        else:
            executor_definition(default, home=home)
            result["ready"] = True
    except SettingsError as error:
        result["error"] = str(error)
    return result


def _atomic_write(path: Path, content: bytes):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".executor-settings-", delete=False) as temporary:
        name = Path(temporary.name)
        try:
            os.chmod(name, 0o600)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.replace(name, path)
        finally:
            name.unlink(missing_ok=True)


def save_settings(payload: dict, *, home: Path | None = None) -> dict:
    _, path, _, _ = _prepare(payload, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / ".executor-settings.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        normalized, path, before, after = _prepare(payload, home=home)
        if before == after:
            return {**normalized, "changed_files": 0, "backup_folder": ""}
        backup_root = path.parent / "executor-backups"
        if backup_root.is_symlink():
            raise SettingsError("私有备份目录不能是符号链接。")
        backup = backup_root / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        receipt = {"state": "prepared", "path": str(path), "existed": before is not None,
                   "sha256": hashlib.sha256(before).hexdigest() if before is not None else None}
        attempted = False
        try:
            backup.mkdir(parents=True, mode=0o700)
            os.chmod(backup, 0o700)
            if before is not None:
                _atomic_write(backup / "executors.json", before)
            _atomic_write(backup / "receipt.json", json.dumps(receipt).encode("utf-8"))
            if _read(path) != before:
                raise SettingsError("配置已被其他操作修改，请重新加载后再保存。")
            attempted = True
            _atomic_write(path, after)
            _atomic_write(backup / "receipt.json", json.dumps({**receipt, "state": "saved"}).encode("utf-8"))
        except Exception as error:
            if attempted:
                try:
                    if _read(path) == after:
                        if before is None:
                            path.unlink()
                        else:
                            _atomic_write(path, before)
                except (OSError, SettingsError):
                    pass
            raise SettingsError("未能安全保存 余烬 · Ember 软件路径；客户端配置未修改。") from error
        return {**normalized, "changed_files": 1, "backup_folder": str(backup)}
