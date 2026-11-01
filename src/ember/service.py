"""Keep the workbench running after login, per user and without administrator rights."""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .store import WorkspaceError

LABEL = "com.evankoo.ember.workbench"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "EmberWorkbench"
RESTART_DELAY_SECONDS = 5


def _config(home=None) -> Path:
    return Path(home or Path.home()).absolute() / ".config/ember"


def _serve_argv(python, workspace, port) -> list[str]:
    return [str(python), "-m", "ember", "serve", "--workspace", str(workspace), "--port", str(port)]


def _save_settings(home, settings) -> None:
    _config(home).mkdir(parents=True, exist_ok=True)
    (_config(home) / "service.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _settings(home=None) -> dict:
    try:
        return json.loads((_config(home) / "service.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise WorkspaceError("常驻服务尚未安装：请先运行 ember service install。") from None
    except (OSError, ValueError):
        raise WorkspaceError("常驻服务配置不可读，原文件保留。") from None


def _healthy(port) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _hidden_python() -> Path:
    """pythonw.exe has no console window; a venv always has it beside python.exe."""
    return Path(sys.executable).with_name("pythonw.exe")


def _pid_path(home=None) -> Path:
    return _config(home) / "service.pid"


def _running_pid(home=None) -> int | None:
    try:
        pid = int(_pid_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    return pid if f'"{pid}"' in result.stdout else None


def supervise(home=None) -> None:
    """Windows has no per-user service restart without administrator rights, so this loop provides it."""
    settings = _settings(home)
    _pid_path(home).write_text(str(os.getpid()), encoding="utf-8")
    logs = _config(home) / "logs"
    logs.mkdir(exist_ok=True)
    while True:
        with open(logs / "service.log", "ab") as log:
            result = subprocess.run(_serve_argv(sys.executable.replace("pythonw.exe", "python.exe"), settings["workspace"], settings["port"]),
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            return
        time.sleep(RESTART_DELAY_SECONDS)


def _windows_start(home=None) -> None:
    if _running_pid(home) is None:
        subprocess.Popen([str(_hidden_python()), "-m", "ember.service"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def _windows_stop(home=None) -> None:
    pid = _running_pid(home)
    if pid is not None:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    _pid_path(home).unlink(missing_ok=True)


def _plist_path(home=None) -> Path:
    return Path(home or Path.home()).absolute() / "Library/LaunchAgents" / f"{LABEL}.plist"


def _launchctl(*arguments) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/launchctl", *arguments], capture_output=True, text=True, timeout=15)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(workspace, port=8783, *, home=None) -> dict:
    _require_supported()
    python = Path(sys.executable).absolute()
    _save_settings(home, {"workspace": str(workspace), "port": port})
    if sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, subprocess.list2cmdline([str(_hidden_python()), "-m", "ember.service"]))
        _windows_stop(home)
        _windows_start(home)
    else:
        logs = _config(home) / "logs"
        logs.mkdir(exist_ok=True)
        plist = _plist_path(home)
        plist.parent.mkdir(parents=True, exist_ok=True)
        _launchctl("bootout", f"{_domain()}/{LABEL}")
        plist.write_bytes(plistlib.dumps({"Label": LABEL, "ProgramArguments": _serve_argv(python, workspace, port), "RunAtLoad": True,
                                          "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": RESTART_DELAY_SECONDS,
                                          "StandardOutPath": str(logs / "service.log"), "StandardErrorPath": str(logs / "service.log")}))
        result = _launchctl("bootstrap", _domain(), str(plist))
        if result.returncode:
            raise WorkspaceError(f"常驻服务未能启动：{result.stderr.strip()[:300]}")
    return status(home=home, wait=10)


def uninstall(*, home=None) -> dict:
    _require_supported()
    if sys.platform == "win32":
        import winreg
        _windows_stop(home)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass
    else:
        _launchctl("bootout", f"{_domain()}/{LABEL}")
        _plist_path(home).unlink(missing_ok=True)
    (_config(home) / "service.json").unlink(missing_ok=True)
    return {"installed": False, "running": False}


def start(*, home=None) -> dict:
    _require_supported()
    _settings(home)
    if sys.platform == "win32":
        _windows_start(home)
    else:
        result = _launchctl("kickstart", f"{_domain()}/{LABEL}")
        if result.returncode:
            result = _launchctl("bootstrap", _domain(), str(_plist_path(home)))
        if result.returncode:
            raise WorkspaceError(f"常驻服务未能启动：{result.stderr.strip()[:300]}")
    return status(home=home, wait=10)


def stop(*, home=None) -> dict:
    _require_supported()
    _settings(home)
    if sys.platform == "win32":
        _windows_stop(home)
    else:
        _launchctl("bootout", f"{_domain()}/{LABEL}")
    return status(home=home)


def status(*, home=None, wait=0) -> dict:
    settings = _settings(home)
    deadline = time.monotonic() + wait
    running = _healthy(settings["port"])
    while not running and time.monotonic() < deadline:
        time.sleep(0.5)
        running = _healthy(settings["port"])
    return {"installed": True, "running": running, "url": f"http://127.0.0.1:{settings['port']}/",
            "workspace": settings["workspace"], "log": str(_config(home) / "logs" / "service.log")}


def _require_supported() -> None:
    if sys.platform not in ("darwin", "win32"):
        raise WorkspaceError("常驻服务目前支持 macOS 与 Windows；Linux 请用系统自己的服务管理器运行 ember serve。")


if __name__ == "__main__":
    supervise()
