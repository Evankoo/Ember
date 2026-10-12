#!/usr/bin/env python3
"""Install into two new local directories; retain partial state on failure."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request

VERSION = "0.3.0"
WHEEL = f"gstudio_core-{VERSION}-py3-none-any.whl"
RELEASE = f"https://github.com/Evankoo/GStudio-Core/releases/download/v{VERSION}/{WHEEL}"


def new_directory(value):
    original = Path(value).expanduser().absolute()
    if original.is_symlink():
        raise ValueError(f"目录不能是符号链接：{original}")
    result = original.resolve()
    if result.exists() and (not result.is_dir() or any(result.iterdir())):
        raise ValueError(f"目录必须为空或不存在：{result}")
    return result


def validate(args):
    if sys.version_info < (3, 10):
        raise ValueError("需要 Python 3.10 或更新版本")
    if platform.system() not in {"Darwin", "Linux"}:
        raise ValueError("此版本支持 macOS 和 Linux")
    app, workspace = new_directory(args.app_dir), new_directory(args.workspace)
    if app == workspace or app in workspace.parents or workspace in app.parents:
        raise ValueError("应用目录和数据目录必须独立，不能互相包含")
    if not args.name.strip() or len(args.name.strip()) > 80:
        raise ValueError("工作区名称应为 1–80 字符")
    if not 1 <= args.port <= 65535:
        raise ValueError("端口应为 1–65535")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    source = None
    if args.source:
        source = Path(args.source).expanduser().resolve(strict=True)
        if not ((source.is_dir() and (source / "pyproject.toml").is_file()) or
                (source.is_file() and source.suffix == ".whl")):
            raise ValueError("source 应为本地源码目录或 wheel 文件")
        if source == app or app in source.parents or source == workspace or workspace in source.parents:
            raise ValueError("安装源不能位于新应用或数据目录中")
    return app, workspace, source


SMOKE = r'''
from pathlib import Path
import sys, threading, urllib.request, json
from gstudio_core.store import Workspace
from gstudio_core.bootstrap import verify_workspace_contract
from gstudio_core.server import LocalServer
directory = sys.argv[1]
w = Workspace(Path(directory) / "workspace")
w.initialize()
w.create_project({"name": "验证项目", "id": "check", "description": "临时验证"})
t = w.create_task({"title": "验证正式交付", "project": "check", "goal": "验证真实文件保存"})
w.add_material(t["id"], {"kind": "input", "name": "输入.md", "content": "验证输入"})
w.add_material(t["id"], {"kind": "draft", "name": "成果.md", "content": "验证交付"})
w.promote_task(t["id"], {"confirmation": True})
r = w.create_task({"title": "验证无文件完成", "project": "independent", "goal": "无需文件", "artifact_mode": "none"})
w.add_reference(r["id"], {"path": f"delivery/formal/{t['id']}/成果.md", "purpose": "验证引用不复制"})
w.complete_task(r["id"], {"confirmation": True})
state = w.snapshot()
assert len(state["tasks"]) == 2 and all(t["status"] == "completed" for t in state["tasks"])
assert (w.path / "delivery/formal" / t["id"] / "成果.md").read_text() == "验证交付"
verify_workspace_contract(w)
server = LocalServer(w, 0)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/health", timeout=5) as response:
        health = json.load(response)
    assert health["ok"] and health["data"]["status"] == "ready", health
finally:
    server.shutdown(); server.server_close(); thread.join()
print("临时工作区验证通过：输入、交付、无文件完成、本机 HTTP 健康检查")
'''


def run(args):
    app, workspace, source = validate(args)
    receipt = {"version": VERSION, "status": "installing", "stage": "environment",
               "app_dir": str(app), "workspace": str(workspace), "mode": args.mode,
               "name": args.name.strip(), "created_at": datetime.now(timezone.utc).isoformat()}
    app.mkdir(parents=True, exist_ok=True)
    receipt_path = app / "installation.json"

    def save():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def command(argv):
        subprocess.run([str(item) for item in argv], check=True)

    save()
    try:
        command([sys.executable, "-m", "venv", app / ".venv"])
        python = app / ".venv/bin/python"
        receipt["stage"] = "package"
        save()
        if source is None:
            bundled = Path(__file__).resolve().parents[1] / "assets" / WHEEL
            if bundled.is_file():
                source = bundled
            else:
                source = app / WHEEL
                with urllib.request.urlopen(RELEASE, timeout=60) as response:
                    with source.open("xb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
        command([python, "-m", "pip", "install", source])
        receipt["stage"] = "workspace"
        save()
        init = [python, "-m", "gstudio_core", "init", workspace, "--name", args.name.strip()]
        if args.mode == "example":
            init.append("--example")
        command(init)
        check = [str(python), "-m", "gstudio_core", "check", "--workspace", str(workspace)]
        start = [str(python), "-m", "gstudio_core", "serve", "--workspace", str(workspace), "--port", str(args.port)]
        receipt.update(stage="verification", check_argv=check, startup_argv=start)
        save()
        command(check)
        verification = Path(tempfile.mkdtemp(prefix="gstudio-init-check-"))
        receipt["verification_workspace"] = str(verification)
        save()
        command([python, "-c", SMOKE, verification])
        shutil.rmtree(verification)
        receipt["verification_workspace_cleaned"] = True
        receipt.update(status="ready", stage="complete", service_running=False,
                       skill_path=str(workspace / ".agents/skills/gstudio-init/SKILL.md"),
                       checks=["workspace-contract", "persisted-workflow", "loopback-health"])
        save()
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        print(f"安装收据：{receipt_path}\n启动：{shlex.join(start)}\n停止：在服务进程按 Ctrl+C")
        return 0
    except Exception as error:
        receipt.update(status="failed", error=str(error))
        save()
        print(f"安装失败（{receipt['stage']}）：{error}\n现场及收据保留：{receipt_path}", file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="在新目录中安装 GStudio Core 并验证初始化")
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--mode", choices=("empty", "example"), required=True)
    parser.add_argument("--name", default="GStudio")
    parser.add_argument("--port", type=int, default=8783)
    parser.add_argument("--source", help="本地源码目录或 wheel；默认使用附带 wheel 或官方发行版")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError) as error:
        print(f"初始化前检查失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
