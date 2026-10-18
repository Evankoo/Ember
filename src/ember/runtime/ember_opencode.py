#!/usr/bin/env python3
"""OpenCode executable discovery and safe Otty launcher for Ember."""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import ember_kimi
from . import workspace_paths

ROOT = _deployment_root()
EXAMPLE_CONFIG_PATH = ROOT / "config" / "ember-executors.example.json"
USER_CONFIG_PATH = workspace_paths.local_config_root() / "executors.json"
DEFAULT_COMMAND_CANDIDATES = (
    "/opt/homebrew/bin/opencode",
    "/usr/local/bin/opencode",
    "~/.opencode/bin/opencode",
    "~/.local/bin/opencode",
    "~/.local/share/opencode/bin/opencode",
)


class OpenCodeIntegrationError(RuntimeError):
    pass


def _payload(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def config() -> dict[str, object]:
    configured = ember_env("EMBER_EXECUTOR_CONFIG")
    path = Path(configured).expanduser() if configured else USER_CONFIG_PATH
    payload = _payload(path)
    settings = payload.get("opencode")
    if not isinstance(settings, dict):
        settings = _payload(EXAMPLE_CONFIG_PATH).get("opencode")
    settings = dict(settings) if isinstance(settings, dict) else {}
    if "local_executors" in payload:
        from .ember_executor_settings import SettingsError, executor_definition, read_settings
        view = read_settings()
        if any(entry["id"] == "opencode" for entry in view["executors"]):
            try:
                settings["path"] = executor_definition("opencode")["path"]
            except SettingsError as error:
                raise OpenCodeIntegrationError("已登记的 OpenCode 路径不可用，未改用旧路径。") from error
    return settings


def opencode_command() -> Path:
    explicit = config().get("path", "")
    if explicit:
        from .ember_executor_settings import SettingsError, validate_software_path
        try:
            return validate_software_path("opencode", explicit)
        except SettingsError as error:
            raise OpenCodeIntegrationError("设置中的 OpenCode 路径不可用，请重新核对；未改用其他程序。") from error
    candidates: list[str] = []
    configured = ember_env("EMBER_OPENCODE_COMMAND")
    if configured:
        candidates.append(configured)
    found = shutil.which("opencode")
    if found:
        candidates.append(found)
    configured_candidates = config().get("command_candidates")
    if isinstance(configured_candidates, list):
        candidates.extend(str(value) for value in configured_candidates)
    candidates.extend(DEFAULT_COMMAND_CANDIDATES)
    for value in candidates:
        path = Path(value).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise OpenCodeIntegrationError("当前机器没有找到可执行的 OpenCode CLI。")


def launch_in_otty(*, title: str = "", prompt: str = "", executable: Path | None = None, runner=subprocess.run) -> None:
    try:
        ember_kimi.launch_command_in_otty(
            executable=executable if executable is not None else opencode_command(),
            settings=config(),
            executor_label="OpenCode",
            title=title,
            prompt=prompt,
            cwd=ROOT,
            runner=runner,
        )
    except ember_kimi.KimiIntegrationError as exc:
        raise OpenCodeIntegrationError(str(exc)) from exc
