#!/usr/bin/env python3
"""Install and manage the Monday 03:00 Ember weekly-organization LaunchAgent."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root, current_deployment, require_host_changes
from ..process import module_command, installed_package

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = _deployment_root()
from .install_ember_workbench import _service_python
from .workspace_paths import current_environment_name

CFG = json.loads((ROOT / "config" / "weekly-organization.json").read_text(encoding="utf-8"))
LABEL = str(CFG["launch_agent_label"])
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path(str(CFG["log_directory"])).expanduser()
SERVICE = ROOT / "scripts" / "ember_weekly_organization.py"
DOMAIN = f"gui/{os.getuid()}"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def plist_payload(service_python: str | None = None) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": module_command("ember.launch", "weekly", "generate", "--week", "latest", python=service_python or _service_python()),
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {"EMBER_ENVIRONMENT": current_environment_name(),
            "EMBER_DEPLOYMENT_PROFILE": str(current_deployment().profile), "PYTHONUNBUFFERED": "1"},
        "StartCalendarInterval": {
            "Weekday": int(CFG["weekday"]), "Hour": int(CFG["hour"]), "Minute": int(CFG["minute"]),
        },
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_DIR / "weekly-organization.log"),
        "StandardErrorPath": str(LOG_DIR / "weekly-organization.error.log"),
    }


def loaded() -> bool:
    return run("/bin/launchctl", "print", f"{DOMAIN}/{LABEL}", check=False).returncode == 0


def install() -> int:
    if current_environment_name() != "mac_mini":
        print("Weekly organization scheduler is Mac mini only; installation refused.", file=sys.stderr)
        return 1
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(plist_payload(), fmt=plistlib.FMT_XML, sort_keys=False))
    run("/bin/launchctl", "bootout", DOMAIN, str(PLIST), check=False)
    result = run("/bin/launchctl", "bootstrap", DOMAIN, str(PLIST), check=False)
    if result.returncode:
        print(result.stderr.strip() or "launchctl bootstrap failed", file=sys.stderr)
        return 1
    print("Ember weekly organization installed: Monday 03:00 Asia/Shanghai")
    return 0 if loaded() else 1


def status() -> int:
    print(f"loaded={str(loaded()).lower()} plist={PLIST}")
    return 0 if loaded() else 1


def uninstall() -> int:
    run("/bin/launchctl", "bootout", DOMAIN, str(PLIST), check=False)
    PLIST.unlink(missing_ok=True)
    print("Ember weekly organization LaunchAgent removed. Logs were preserved.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the weekly-organization LaunchAgent")
    parser.add_argument("command", choices=("install", "status", "uninstall"))
    args = parser.parse_args()
    if args.command != "status":
        require_host_changes()
    return {"install": install, "status": status, "uninstall": uninstall}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
