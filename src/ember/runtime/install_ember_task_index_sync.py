#!/usr/bin/env python3
"""Install and manage the per-user task-index sync LaunchAgent."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root, current_deployment, require_host_changes
from ..process import module_command, installed_package

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = _deployment_root()
from .install_ember_workbench import _launch_agent_can_read, _python_candidates
from .workspace_paths import current_environment_name, shared_workspace_root

CFG = json.loads((ROOT / "config" / "task-index-sync.json").read_text(encoding="utf-8"))
LABEL = str(CFG.get("launch_agent_label", "com.ember.task-index-sync"))
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path(str(CFG.get("log_directory", "~/Library/Logs/Ember"))).expanduser()
SERVICE = ROOT / "scripts" / "ember_task_index_sync.py"
DOMAIN = f"gui/{os.getuid()}"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def _service_python() -> str:
    target = shared_workspace_root()
    for candidate in _python_candidates():
        if installed_package(candidate) and _launch_agent_can_read(candidate, target):
            return candidate
    raise RuntimeError(
        f"没有可从 LaunchAgent 读取共享工作区的 Python：{target}。"
        "请先在 macOS 隐私设置中授权 Codex 访问文稿。"
    )


def plist_payload(service_python: str | None = None) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": module_command("ember.launch", "task-index", "daemon", python=service_python or _service_python()),
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {
            "EMBER_ENVIRONMENT": current_environment_name(),
            "EMBER_DEPLOYMENT_PROFILE": str(current_deployment().profile),
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Interactive",
        "StandardOutPath": str(LOG_DIR / "task-index-sync.log"),
        "StandardErrorPath": str(LOG_DIR / "task-index-sync.error.log"),
    }


def loaded() -> bool:
    return run("/bin/launchctl", "print", f"{DOMAIN}/{LABEL}", check=False).returncode == 0


def install() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(plist_payload(), fmt=plistlib.FMT_XML, sort_keys=False))
    run("/bin/launchctl", "bootout", DOMAIN, str(PLIST), check=False)
    result = run("/bin/launchctl", "bootstrap", DOMAIN, str(PLIST), check=False)
    if result.returncode:
        print(result.stderr.strip() or "launchctl bootstrap failed", file=sys.stderr)
        return 1
    run("/bin/launchctl", "kickstart", "-k", f"{DOMAIN}/{LABEL}", check=False)
    time.sleep(0.5)
    print(f"Ember task-index sync installed: interval={CFG.get('interval_seconds', 60)}s")
    return 0 if loaded() else 1


def status() -> int:
    state_path = ROOT / "task-cards" / "task-index-sync-status.json"
    state = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else "{}"
    print(f"loaded={str(loaded()).lower()} state={state}")
    return 0 if loaded() else 1


def restart() -> int:
    result = run("/bin/launchctl", "kickstart", "-k", f"{DOMAIN}/{LABEL}", check=False)
    if result.returncode:
        print("Service is not installed; run install first.", file=sys.stderr)
        return 1
    return 0


def uninstall() -> int:
    run("/bin/launchctl", "bootout", DOMAIN, str(PLIST), check=False)
    PLIST.unlink(missing_ok=True)
    print("Ember task-index sync LaunchAgent removed. Logs were preserved.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the Ember task-index sync LaunchAgent")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("install", "status", "restart", "uninstall"):
        sub.add_parser(command)
    args = parser.parse_args()
    if args.command != "status":
        require_host_changes()
    return {"install": install, "status": status, "restart": restart, "uninstall": uninstall}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
