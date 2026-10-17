#!/usr/bin/env python3
"""Install the isolated GStudio MCP runtime and register trusted local clients."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root, current_deployment, require_host_changes

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from ..process import installed_package, module_command

ROOT = _deployment_root()
VENV = Path(os.environ.get("GSTUDIO_MCP_VENV") or Path.home() / ".local" / "share" / "gstudio" / "mcp-venv").expanduser()
PYTHON = Path(os.environ.get("GSTUDIO_MCP_PYTHON") or sys.executable).expanduser()
SERVER = ROOT / "scripts" / "gstudio_mcp_server.py"
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
CODEX_MARKER = "# GStudio local task MCP; implementation remains under ~/GStudio."


def bootstrap_python() -> Path:
    configured = os.environ.get("GSTUDIO_MCP_PYTHON")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3",
        Path("/opt/homebrew/bin/python3.12"),
        Path(sys.executable),
    ]
    for candidate in candidates:
        if not candidate or not candidate.exists():
            continue
        result = subprocess.run(
            [str(candidate), "-c", "import sys; raise SystemExit(sys.version_info < (3, 10))"]
        )
        if result.returncode == 0:
            return candidate
    raise RuntimeError("GStudio MCP requires Python 3.10 or newer")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def ensure_runtime() -> None:
    if not installed_package(PYTHON):
        raise RuntimeError("The selected interpreter must have the Ember package installed.")
    result = subprocess.run([str(PYTHON), "-I", "-c", "from mcp.server.fastmcp import FastMCP"], capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Install this Ember build with its full extra before registering MCP clients.")


def codex_block() -> str:
    return (f"\n{CODEX_MARKER}\n[mcp_servers.gstudio]\n"
            f"command = {json.dumps(str(PYTHON))}\n"
            'args = ["-m", "ember.launch", "mcp"]\n'
            'startup_timeout_sec = 120\n'
            '[mcp_servers.gstudio.env]\n'
            f'EMBER_DEPLOYMENT_PROFILE = {json.dumps(str(current_deployment().profile))}\n')


def install_codex() -> None:
    text = CODEX_CONFIG.read_text(encoding="utf-8") if CODEX_CONFIG.exists() else ""
    import re
    if re.search(r"(?m)^\[mcp_servers\.(?:gstudio|\"gstudio\"|'gstudio')(?:\.[^]\n]+)?\]", text):
        if CODEX_MARKER not in text:
            raise RuntimeError("existing mcp_servers.gstudio is not installer-managed; refusing to overwrite")
        start = text.index(CODEX_MARKER)
        import re
        end = len(text)
        for section in re.finditer(r"(?m)^\[([^]\n]+)\]", text[start:]):
            if not (section.group(1) == "mcp_servers.gstudio" or section.group(1).startswith("mcp_servers.gstudio.")):
                end = start + section.start()
                break
        text = text[:start].rstrip() + "\n" + text[end:].lstrip("\n")
    backup = CODEX_CONFIG.with_suffix(".toml.gstudio-backup")
    if CODEX_CONFIG.exists() and not backup.exists():
        shutil.copy2(CODEX_CONFIG, backup)
    atomic_write(CODEX_CONFIG, text.rstrip() + "\n" + codex_block())


def install_kimi(workspace: Path) -> Path:
    path = workspace.resolve() / ".kimi-code" / "mcp.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"mcpServers": {}}
    servers = payload.setdefault("mcpServers", {})
    expected = {
        "command": str(PYTHON),
        "args": ["-m", "ember.launch", "mcp"],
        "env": {"EMBER_DEPLOYMENT_PROFILE": str(current_deployment().profile)},
    }
    existing = servers.get("gstudio")
    if existing and existing != expected:
        old_managed = isinstance(existing, dict) and (existing.get("args") == [str(SERVER)] or existing.get("args") == ["-lc", 'exec "$HOME/.local/share/gstudio/mcp-venv/bin/python3" "$HOME/GStudio/scripts/gstudio_mcp_server.py"'])
        if not old_managed and isinstance(existing, dict) and existing.get("args") == expected["args"] and existing.get("env") == expected["env"]:
            # Upgrade only an integrity-checked interpreter registered to this deployment.
            from .. import package_update
            try:
                previous_python = Path(existing["command"])
                release = previous_python.parent.parent.parent
                if previous_python == release / "venv/bin/python" and release.parent == current_deployment().local_config_root / "releases":
                    receipt = json.loads((release / "prepared.json").read_text())
                    package_update._validate_release(receipt, current_deployment())
                    old_managed = receipt["python"] == str(previous_python)
            except (OSError, ValueError, KeyError, TypeError, package_update.UpdateError):
                pass
        if not old_managed:
            raise RuntimeError(f"{path} already has a different gstudio server")
    servers["gstudio"] = expected
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def self_check() -> None:
    ensure_runtime()
    subprocess.run([str(PYTHON), "-I", "-c", "from ember.runtime.gstudio_mcp_server import build_server; assert build_server(); print('GStudio MCP self-check PASS')"], cwd=ROOT, check=True)


def status(workspaces: list[Path]) -> int:
    result = {
        "runtime": str(PYTHON), "runtime_ready": PYTHON.exists(),
        "codex_registered": CODEX_CONFIG.exists() and "[mcp_servers.gstudio]" in CODEX_CONFIG.read_text(encoding="utf-8"),
        "kimi": {},
    }
    for workspace in workspaces:
        path = workspace.resolve() / ".kimi-code" / "mcp.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            ready = "gstudio" in payload.get("mcpServers", {})
        except (OSError, json.JSONDecodeError):
            ready = False
        result["kimi"][str(workspace.resolve())] = ready
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "status", "self-check"))
    parser.add_argument("--client", action="append", choices=("codex", "kimi"), default=[])
    parser.add_argument("--kimi-workspace", action="append", type=Path, default=[])
    args = parser.parse_args()
    if args.command not in {"status", "print", "self-check"}:
        require_host_changes()
    workspaces = args.kimi_workspace or [ROOT]
    if args.command == "status":
        return status(workspaces)
    if args.command == "self-check":
        self_check()
        return 0
    ensure_runtime()
    clients = args.client or ["codex", "kimi"]
    if "codex" in clients:
        install_codex()
    if "kimi" in clients:
        for workspace in workspaces:
            install_kimi(workspace)
    self_check()
    return status(workspaces)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
