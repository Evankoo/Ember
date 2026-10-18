#!/usr/bin/env python3
"""Install the per-Mac Ember Central execution bridge LaunchAgent."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root, current_deployment, require_host_changes

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from . import workspace_paths
from ..process import module_command, installed_package

ROOT = _deployment_root()
LABEL = "com.ember.execution-bridge"
TEMPLATE = ROOT / "config" / "launchagents" / f"{LABEL}.plist"
TARGET = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
DOMAIN = f"gui/{os.getuid()}"


def python_path() -> Path:
    candidates = [
        Path(sys.executable),
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3",
        Path("/usr/bin/python3"),
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK) and installed_package(candidate):
            return candidate
    raise RuntimeError("no usable Python interpreter")


def payload() -> dict[str, object]:
    value = plistlib.loads(TEMPLATE.read_bytes())
    replacements = {
        "__PYTHON__": str(python_path()),
        "__RUNTIME__": str(ROOT),
        "__HOME__": str(Path.home()),
    }

    def replace(item):
        if isinstance(item, str):
            for source, target in replacements.items():
                item = item.replace(source, target)
        elif isinstance(item, list):
            item = [replace(value) for value in item]
        elif isinstance(item, dict):
            item = {key: replace(value) for key, value in item.items()}
        return item

    result = replace(value)
    result["ProgramArguments"] = module_command("ember.launch", "execution-bridge", python=python_path())
    result.setdefault("EnvironmentVariables", {})["EMBER_DEPLOYMENT_PROFILE"] = str(current_deployment().profile)
    return result


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def install() -> int:
    config = workspace_paths.local_config_root() / "central.json"
    if not config.is_file():
        print(f"missing private bridge config: {config}", file=sys.stderr)
        return 2
    (Path.home() / "Library" / "Logs" / "Ember").mkdir(parents=True, exist_ok=True)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(plistlib.dumps(payload(), fmt=plistlib.FMT_XML, sort_keys=False))
    run("/bin/launchctl", "bootout", DOMAIN, str(TARGET), check=False)
    result = run("/bin/launchctl", "bootstrap", DOMAIN, str(TARGET), check=False)
    if result.returncode:
        print(result.stderr.strip() or "launchctl bootstrap failed", file=sys.stderr)
        return 1
    run("/bin/launchctl", "kickstart", "-k", f"{DOMAIN}/{LABEL}", check=False)
    print(f"Ember execution bridge installed: {TARGET}")
    return 0


def uninstall() -> int:
    run("/bin/launchctl", "bootout", DOMAIN, str(TARGET), check=False)
    TARGET.unlink(missing_ok=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "uninstall", "print"])
    args = parser.parse_args()
    if args.command not in {"status", "print", "self-check"}:
        require_host_changes()
    if args.command == "install":
        return install()
    if args.command == "uninstall":
        return uninstall()
    print(plistlib.dumps(payload(), fmt=plistlib.FMT_XML, sort_keys=False).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
