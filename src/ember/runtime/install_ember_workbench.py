#!/usr/bin/env python3
"""Install and manage the Ember workbench LaunchAgent."""
from __future__ import annotations
from .ember_compat import env as ember_env
from ..deployment import runtime_root as _deployment_root, current_deployment, require_host_changes
from ..process import module_command, installed_package

import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = _deployment_root()
from . import ember_workbench as workbench
from .workspace_paths import current_environment_name, shared_workspace_root

CFG = workbench.config()
LABEL = str(CFG.get("launch_agent_label", "com.ember.task-workbench"))
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path(str(CFG.get("log_directory", "~/Library/Logs/Ember"))).expanduser()
SERVICE = ROOT / "scripts" / "ember_workbench_service.py"
DOMAIN = f"gui/{os.getuid()}"


def _python_candidates() -> list[str]:
    """Return usable interpreters in preference order.

    macOS attributes protected-folder access to the executable launched by
    launchd.  Codex's bundled Python is already the responsible executable for
    workspace operations, while /usr/bin/python3 commonly has no Documents
    permission when started directly by a LaunchAgent.
    """
    candidates: list[Path] = [Path(sys.executable)]
    override = ember_env("EMBER_WORKBENCH_PYTHON", "").strip()
    if override:
        candidates.append(Path(override).expanduser())
    codex_bin = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin"
    if codex_bin.is_dir():
        candidates.append(codex_bin / "python3")
        versioned = (
            candidate
            for candidate in codex_bin.iterdir()
            if re.fullmatch(r"python3(?:\.\d+)+", candidate.name)
        )
        candidates.extend(sorted(versioned, reverse=True))
    candidates.extend((Path(sys.executable), Path("/usr/bin/python3")))
    usable: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate)
        if value in seen or not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        seen.add(value)
        usable.append(value)
    return usable


def _launch_agent_can_read(python: str, target: Path, timeout: float = 4.0) -> bool:
    """Probe protected-folder access from launchd, not the current shell."""
    if not target.is_dir():
        return True
    probe_root = ROOT / "tmp" / "workbench-python-probe"
    probe_root.mkdir(parents=True, exist_ok=True)
    nonce = f"{os.getpid()}-{time.time_ns()}"
    output = probe_root / f"{nonce}.json"
    label = f"com.ember.workbench-python-probe.{os.getpid()}.{time.time_ns()}"
    code = (
        "import json,sys; from pathlib import Path; "
        "target=Path(sys.argv[1]); output=Path(sys.argv[2]); "
        "payload={'ok':False}; "
        "\ntry:\n next(target.iterdir(), None); payload={'ok':True}\n"
        "except Exception as exc:\n payload={'ok':False,'error':repr(exc)}\n"
        "output.write_text(json.dumps(payload),encoding='utf-8')"
    )
    try:
        submitted = run(
            "/bin/launchctl", "submit", "-l", label, "--",
            python, "-c", code, str(target), str(output), check=False,
        )
        if submitted.returncode:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if output.is_file():
                try:
                    return bool(json.loads(output.read_text(encoding="utf-8")).get("ok"))
                except (OSError, json.JSONDecodeError):
                    return False
            time.sleep(0.1)
        return False
    finally:
        run("/bin/launchctl", "remove", label, check=False)
        output.unlink(missing_ok=True)


def _service_python() -> str:
    target = shared_workspace_root()
    for candidate in _python_candidates():
        if installed_package(candidate) and _launch_agent_can_read(candidate, target):
            return candidate
    raise RuntimeError(
        f"没有可从 LaunchAgent 读取共享工作区的 Python：{target}。"
        "请先在 macOS 隐私设置中授权 Codex 访问文稿。"
    )


def _runtime_dependency_bin_dirs(service_python: str) -> tuple[Path, ...]:
    """Return bundled command directories that belong to the selected Python."""
    python_path = Path(service_python).expanduser()
    try:
        dependencies = python_path.parents[2]
    except IndexError:
        return ()
    if dependencies.name != "dependencies":
        return ()
    return tuple(
        candidate
        for candidate in (dependencies / "bin/override", dependencies / "bin/fallback")
        if candidate.is_dir()
    )


def _service_path(service_python: str) -> str:
    """Build a PATH that includes the installing shell's PATH plus common
    user binary locations, so the service can find Kimi, bypy, homebrew,
    and other local tools even when LaunchAgent starts with a minimal
    environment.
    """
    seen: list[str] = []
    user_home = Path.home()
    runtime_bins = _runtime_dependency_bin_dirs(service_python)
    candidates = [
        *(str(path) for path in runtime_bins[:1]),
        *(os.environ.get("PATH") or "").split(os.pathsep),
        str(user_home / ".kimi-code" / "bin"),
        str(user_home / ".local" / "bin"),
        str(user_home / "bin"),
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
        *(str(path) for path in runtime_bins[1:]),
    ]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.append(candidate)
    return os.pathsep.join(seen)


def plist_payload(service_python: str | None = None) -> dict[str, object]:
    selected_python = service_python or _service_python()
    return {
        "Label": LABEL,
        "ProgramArguments": module_command("ember.launch", "workbench", python=selected_python),
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {
            "EMBER_ENVIRONMENT": current_environment_name(),
            "EMBER_DEPLOYMENT_PROFILE": str(current_deployment().profile),
            "PYTHONUNBUFFERED": "1",
            "PATH": _service_path(selected_python),
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "ProcessType": "Interactive",
        "StandardOutPath": str(LOG_DIR / "workbench.log"),
        "StandardErrorPath": str(LOG_DIR / "workbench.error.log"),
    }


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def health(timeout: float = 1.0) -> bool:
    host, port = str(CFG.get("host", "127.0.0.1")), int(CFG.get("port", 8765))
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout) as response:
            return response.status == 200 and b'"ok": true' in response.read()
    except Exception:
        return False


def install(open_page: bool = True, payload: dict[str, object] | None = None) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(payload or plist_payload(), fmt=plistlib.FMT_XML, sort_keys=False))
    run("/bin/launchctl", "bootout", DOMAIN, str(PLIST), check=False)
    result = run("/bin/launchctl", "bootstrap", DOMAIN, str(PLIST), check=False)
    if result.returncode:
        print(result.stderr.strip() or "launchctl bootstrap failed", file=sys.stderr)
        return 1
    run("/bin/launchctl", "kickstart", "-k", f"{DOMAIN}/{LABEL}", check=False)
    for _ in range(20):
        if health():
            print(f"Ember workbench installed: http://127.0.0.1:{CFG.get('port', 8765)}/")
            if open_page:
                subprocess.run(["/usr/bin/open", f"http://127.0.0.1:{CFG.get('port', 8765)}/"], check=False)
            return 0
        time.sleep(0.25)
    print(f"Service did not become healthy. Check {LOG_DIR / 'workbench.error.log'}", file=sys.stderr)
    return 1


def status() -> int:
    loaded = run("/bin/launchctl", "print", f"{DOMAIN}/{LABEL}", check=False).returncode == 0
    healthy = health()
    print(f"loaded={str(loaded).lower()} healthy={str(healthy).lower()} url=http://127.0.0.1:{CFG.get('port', 8765)}/")
    return 0 if loaded and healthy else 1


def restart() -> int:
    desired = plist_payload()
    try:
        current = plistlib.loads(PLIST.read_bytes())
    except (FileNotFoundError, plistlib.InvalidFileException):
        current = {}
    keys = ("ProgramArguments", "WorkingDirectory", "EnvironmentVariables")
    if any(current.get(key) != desired.get(key) for key in keys):
        return install(open_page=False, payload=desired)
    result = run("/bin/launchctl", "kickstart", "-k", f"{DOMAIN}/{LABEL}", check=False)
    if result.returncode:
        print("Service is not installed; run install first.", file=sys.stderr)
        return 1
    for _ in range(20):
        if health():
            print("Ember workbench restarted and healthy.")
            return 0
        time.sleep(0.25)
    print("Service restart did not pass health check.", file=sys.stderr)
    return 1


def uninstall() -> int:
    run("/bin/launchctl", "bootout", DOMAIN, str(PLIST), check=False)
    PLIST.unlink(missing_ok=True)
    print("Ember workbench LaunchAgent removed. Logs were preserved.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the Ember local workbench")
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--no-open", action="store_true")
    sub.add_parser("status")
    sub.add_parser("restart")
    sub.add_parser("uninstall")
    args = parser.parse_args()
    if args.command != "status":
        require_host_changes()
    if args.command == "install":
        return install(not args.no_open)
    if args.command == "status":
        return status()
    if args.command == "restart":
        return restart()
    return uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
