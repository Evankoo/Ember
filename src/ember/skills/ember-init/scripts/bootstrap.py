#!/usr/bin/env python3
"""Install into the fixed system folder and document library; retain partial state on failure.

Defaults match the full system's split: ~/Ember holds rules, Skills, configuration
and the program (app/); ~/Ember文档 holds only tasks, inputs, deliveries and projects.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION = "0.22.0"
WHEEL = f"ember-{VERSION}-py3-none-any.whl"
# The release's one file; the wheel sits in it under ember-init/assets/.
PACKAGE = f"ember-init-{VERSION}.zip"
# GitHub first, then the same file on the maintainer's download mirror for networks where GitHub is unreliable.
RELEASES = (f"https://github.com/Evankoo/Ember/releases/download/v{VERSION}/{PACKAGE}",
            f"https://ai.evan-manual.com/ember/download/v{VERSION}/{PACKAGE}")
# Tried once when installing dependencies from PyPI fails.
PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
# The workspace language is chosen once, before anything is created. This script runs before the
# program is installed, so it carries its own English messages.
LANGUAGE = "zh"
DOCUMENTS_SUFFIX = {"zh": "文档", "en": "Docs"}
DEFAULT_NAME = {"zh": "余烬", "en": "Ember"}
ENGLISH = {
    "目录不能是符号链接：{0}": "The folder cannot be a symbolic link: {0}",
    "目录必须为空或不存在：{0}": "The folder must be empty or not exist yet: {0}",
    "下载余烬程序包失败：{0}": "Could not download the Ember package: {0}",
    "需要 Python 3.10 或更新版本": "Python 3.10 or newer is required",
    "此版本支持 macOS、Linux 和 Windows": "This version supports macOS, Linux and Windows",
    "系统目录和文档库必须独立，不能互相包含": "The system folder and the document library must be separate and must not contain each other",
    "程序目录应为系统目录下的 app，且不能与文档库互相包含": "The program folder must be app inside the system folder and must not overlap the document library",
    "工作区名称应为 1–80 字符": "The workspace name must be 1–80 characters",
    "executor 应为真实执行工具的单行名称，不是模型名称": "executor must be the one-line name of the actual AI tool, not a model name",
    "端口应为 1–65535": "The port must be between 1 and 65535",
    "source 应为本地源码目录或 wheel 文件": "source must be a local source folder or a wheel file",
    "安装源不能位于新系统目录、程序目录或文档库中": "The installation source cannot be inside the new system folder, program folder or document library",
    "安装阶段子进程失败": "An installation step failed",
    "1/5 在 {0} 建立程序与 Python 环境": "1/5 Creating the program and its Python environment in {0}",
    "2/5 安装余烬程序与三项基础 Skill": "2/5 Installing Ember and its three basic Skills",
    "从 PyPI 安装依赖失败，改用国内镜像 {0} 重试一次": "Installing dependencies from PyPI failed; retrying once with the mirror {0}",
    "3/5 建立系统目录 {0} 与文档库 {1}": "3/5 Creating the system folder {0} and the document library {1}",
    "4/5 登记余烬系统项目；安装记录保存在程序目录": "4/5 Registering the Ember system project; the installation record is kept in the program folder",
    "5/5 检查系统目录与文档库；在隔离目录验证任务、交付和 HTTP，保存安装报告": "5/5 Checking the system folder and document library; verifying tasks, deliverables and HTTP in a separate folder; saving the installation report",
    "安装收据：{0}\n安装报告：{1}\n启动：{2}\n停止：在服务进程按 Ctrl+C\n下一步：打开工作台并配置当前 AI 工具；由 ember 将当前对话建成第一张任务卡，用户检查 OK 后再通过 ember-project 建立练习项目。":
        "Installation receipt: {0}\nInstallation report: {1}\nStart: {2}\nStop: press Ctrl+C in the server process\nNext: open the workbench and set up the current AI tool; ember turns this conversation into the first task card, and after the user checks it, ember-project creates a practice project.",
    "本机默认：系统目录 {0}，文档库 {1}（记录在 ~/.config/ember/workspace.json）": "Default on this computer: system folder {0}, document library {1} (recorded in ~/.config/ember/workspace.json)",
    "本机已有另一个默认工作区，未替换：{0}": "This computer already has another default workspace; it was not replaced: {0}",
    "安装失败（{0}）：{1}\n现场及收据保留：{2}": "Installation failed ({0}): {1}\nThe files and the receipt were kept: {2}",
    "初始化前检查失败：{0}": "The pre-installation check failed: {0}",
}


def say(message, *values):
    """A message in the chosen language."""
    return (ENGLISH.get(message, message) if LANGUAGE == "en" else message).format(*values)


def child_env():
    """Children speak UTF-8 regardless of the Windows code page, so Chinese paths survive the pipe."""
    return {**os.environ, "PYTHONUTF8": "1"}


def new_directory(value):
    original = Path(value).expanduser().absolute()
    if original.is_symlink():
        raise ValueError(say("目录不能是符号链接：{0}", original))
    result = original.resolve()
    if result.exists() and (not result.is_dir() or any(result.iterdir())):
        raise ValueError(say("目录必须为空或不存在：{0}", result))
    return result


def contains(parent, child):
    return parent == child or parent in child.parents


def download(target):
    """Take the wheel out of the release package from the first source that answers; a partial file never stays behind."""
    failures = []
    for url in RELEASES:
        try:
            # The mirror's host refuses Python's default User-Agent as a bot.
            request = urllib.request.Request(url, headers={"User-Agent": f"Ember/{VERSION}"})
            with tempfile.TemporaryFile() as package:
                with urllib.request.urlopen(request, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        package.write(chunk)
                with zipfile.ZipFile(package) as archive, target.open("xb") as output:
                    output.write(archive.read(f"ember-init/assets/{WHEEL}"))
            return target
        except (OSError, zipfile.BadZipFile, KeyError) as error:
            target.unlink(missing_ok=True)
            failures.append(f"{url}：{getattr(error, 'reason', None) or error}")
    raise RuntimeError(say("下载余烬程序包失败：{0}", "；".join(failures)))


def validate(args):
    if sys.version_info < (3, 10):
        raise ValueError(say("需要 Python 3.10 或更新版本"))
    if platform.system() not in {"Darwin", "Linux", "Windows"}:
        raise ValueError(say("此版本支持 macOS、Linux 和 Windows"))
    workspace = new_directory(args.workspace or Path.home() / "Ember")
    documents = new_directory(args.documents or workspace.parent / (workspace.name + DOCUMENTS_SUFFIX[LANGUAGE]))
    app = new_directory(args.app_dir or workspace / "app")
    if contains(workspace, documents) or contains(documents, workspace):
        raise ValueError(say("系统目录和文档库必须独立，不能互相包含"))
    if contains(app, documents) or contains(documents, app) or (app != workspace / "app" and (contains(app, workspace) or contains(workspace, app))):
        raise ValueError(say("程序目录应为系统目录下的 app，且不能与文档库互相包含"))
    if not args.name.strip() or len(args.name.strip()) > 80:
        raise ValueError(say("工作区名称应为 1–80 字符"))
    executor = getattr(args, "executor", "manual")
    if not isinstance(executor, str) or not executor.strip() or len(executor) > 80 or any(c in executor for c in ("\n", "\r", "\x00")):
        raise ValueError(say("executor 应为真实执行工具的单行名称，不是模型名称"))
    if not 1 <= args.port <= 65535:
        raise ValueError(say("端口应为 1–65535"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    source = None
    if args.source:
        source = Path(args.source).expanduser().resolve(strict=True)
        if not ((source.is_dir() and (source / "pyproject.toml").is_file()) or
                (source.is_file() and source.suffix == ".whl")):
            raise ValueError(say("source 应为本地源码目录或 wheel 文件"))
        if any(contains(root, source) for root in (app, workspace, documents)):
            raise ValueError(say("安装源不能位于新系统目录、程序目录或文档库中"))
    return app, workspace, documents, source


SMOKE = r'''
from pathlib import Path
import sys, threading, urllib.request, json
from ember.store import Workspace
from ember.bootstrap import verify_workspace_contract
from ember.server import LocalServer
directory, language = sys.argv[1], sys.argv[2]
w = Workspace(Path(directory) / "Ember", language=language)
w.initialize()
w.create_project({"name": "验证项目", "id": "check", "description": "临时验证"})
t = w.create_task({"title": "验证正式交付", "project": "check", "goal": "验证真实文件保存"})
w.add_material(t["id"], {"kind": "input", "name": "输入.md", "content": "验证输入"})
w.add_material(t["id"], {"kind": "draft", "name": "成果.md", "content": "验证交付"})
w.promote_task(t["id"], {"confirmation": True})
r = w.create_task({"title": "验证无文件完成", "project": "independent", "goal": "无需文件", "artifact_mode": "none"})
w.add_reference(r["id"], {"path": f"{w.v.formal}/{t['id']}/成果.md", "purpose": "验证引用不复制"})
w.complete_task(r["id"], {"confirmation": True})
state = w.snapshot()
assert len(state["tasks"]) == 2 and all(t["status"] == "completed" for t in state["tasks"])
assert (w.docs / w.v.formal / t["id"] / "成果.md").read_text(encoding="utf-8") == "验证交付"
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
    app, workspace, documents, source = validate(args)
    receipt = {"version": VERSION, "status": "installing", "stage": "environment",
               "app_dir": str(app), "workspace": str(workspace), "documents": str(documents), "mode": args.mode,
               "name": args.name.strip(), "executor": getattr(args, "executor", "manual").strip(),
               "checks": [], "created_at": datetime.now(timezone.utc).isoformat()}
    app.mkdir(parents=True, exist_ok=True)
    receipt_path = app / "installation.json"

    def save():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def command(argv):
        subprocess.run([str(item) for item in argv], check=True, env=child_env())

    def quiet(argv, keep=1):
        """Run a step whose own hints target manual installs; show only its first lines, or everything on failure."""
        result = subprocess.run([str(item) for item in argv], capture_output=True, text=True, encoding="utf-8", errors="replace", env=child_env())
        if result.returncode:
            sys.stderr.write(result.stdout + result.stderr)
            raise subprocess.CalledProcessError(result.returncode, argv, result.stdout, result.stderr)
        for line in result.stdout.splitlines()[:keep]:
            print(line, flush=True)

    def capture(argv):
        result = subprocess.run([str(item) for item in argv], capture_output=True, text=True, encoding="utf-8", errors="replace", env=child_env())
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[:4000] or say("安装阶段子进程失败"))
        return json.loads(result.stdout)

    def write_back():
        result = capture([python, "-m", "ember.onboarding", "record", "--workspace", workspace, "--receipt", receipt_path])
        receipt.update(result, writeback_status="verified")
        save()

    save()
    try:
        print(say("1/5 在 {0} 建立程序与 Python 环境", app), flush=True)
        command([sys.executable, "-m", "venv", app / ".venv"])
        python = app / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        receipt["stage"] = "package"
        save()
        print(say("2/5 安装余烬程序与三项基础 Skill"), flush=True)
        if source is None:
            bundled = Path(__file__).resolve().parents[1] / "assets" / WHEEL
            if bundled.is_file():
                source = bundled
            else:
                source = download(app / WHEEL)
        install = [python, "-m", "pip", "install", "--disable-pip-version-check", source]
        try:
            command(install)
        except subprocess.CalledProcessError:
            print(say("从 PyPI 安装依赖失败，改用国内镜像 {0} 重试一次", PYPI_MIRROR), flush=True)
            command(install + ["--index-url", PYPI_MIRROR])
        receipt["stage"] = "workspace"
        save()
        print(say("3/5 建立系统目录 {0} 与文档库 {1}", workspace, documents), flush=True)
        init = [python, "-m", "ember", "init", workspace, "--documents", documents, "--name", args.name.strip(), "--language", LANGUAGE]
        if args.mode == "example":
            init.append("--example")
        quiet(init)
        receipt["stage"] = "system-project"
        save()
        print(say("4/5 登记余烬系统项目；安装记录保存在程序目录"), flush=True)
        receipt.update(capture([python, "-m", "ember.onboarding", "begin", "--workspace", workspace,
                               "--app-dir", app, "--executor", receipt["executor"], "--mode", args.mode]))
        save()
        check = [str(python), "-m", "ember", "check", "--workspace", str(workspace)]
        start = [str(python), "-m", "ember", "serve", "--workspace", str(workspace), "--port", str(args.port)]
        receipt.update(stage="verification", check_argv=check, startup_argv=start)
        save()
        write_back()
        print(say("5/5 检查系统目录与文档库；在隔离目录验证任务、交付和 HTTP，保存安装报告"), flush=True)
        command(check)
        receipt["checks"].append("workspace-contract")
        verification = Path(tempfile.mkdtemp(prefix="ember-init-check-"))
        receipt.update(stage="workflow-verification", verification_workspace=str(verification))
        save()
        write_back()
        command([python, "-c", SMOKE, verification, LANGUAGE])
        receipt["checks"].extend(["persisted-workflow", "loopback-health"])
        shutil.rmtree(verification)
        receipt["verification_workspace_cleaned"] = True
        receipt.update(status="ready", stage="complete", service_running=False,
                       skill_path=str(workspace / ".agents/skills/ember-init/SKILL.md"),
                       writeback_status="pending")
        save()
        write_back()
        command(check)
        # Let AI tools in any folder find this workspace; never replace a different existing default.
        registered = subprocess.run([str(python), "-m", "ember", "use", str(workspace)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=child_env())
        receipt["default_workspace"] = "registered" if registered.returncode == 0 else "kept-existing"
        if registered.returncode:
            receipt["default_workspace_note"] = registered.stderr.strip()[:1000]
        save()
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        print(say("安装收据：{0}\n安装报告：{1}\n启动：{2}\n停止：在服务进程按 Ctrl+C\n下一步：打开工作台并配置当前 AI 工具；由 ember 将当前对话建成第一张任务卡，用户检查 OK 后再通过 ember-project 建立练习项目。",
                  receipt_path, receipt["report_path"], (subprocess.list2cmdline if os.name == "nt" else shlex.join)(start)))
        if receipt["default_workspace"] == "registered":
            print(say("本机默认：系统目录 {0}，文档库 {1}（记录在 ~/.config/ember/workspace.json）", workspace, documents))
        else:
            print(say("本机已有另一个默认工作区，未替换：{0}", receipt["default_workspace_note"]))
        return 0
    except Exception as error:
        if receipt.get("writeback_status") == "pending":
            receipt["stage"] = "result-writeback"
        receipt.update(status="failed", error=str(error))
        save()
        if receipt.get("system_project_id"):
            try:
                write_back()
            except Exception as writeback_error:
                receipt.update(writeback_status="failed", writeback_error=str(writeback_error))
                save()
        print(say("安装失败（{0}）：{1}\n现场及收据保留：{2}", receipt["stage"], error, receipt_path), file=sys.stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装余烬到固定位置并验证初始化：系统目录 ~/Ember，文档库 ~/Ember文档")
    parser.add_argument("--workspace", help="系统目录；默认 ~/Ember")
    parser.add_argument("--documents", help="文档库；默认与系统目录同级的“<系统目录名>文档”")
    parser.add_argument("--app-dir", help="程序目录；默认系统目录下的 app")
    parser.add_argument("--mode", choices=("empty", "example"), required=True)
    parser.add_argument("--name", help="工作区名称；默认 余烬（中文）或 Ember（英文） / workspace name; default 余烬 or Ember")
    parser.add_argument("--language", choices=("zh", "en"), required=True,
                        help="工作区语言，建好后不能更改 / workspace language; cannot be changed later")
    parser.add_argument("--port", type=int, default=8783)
    parser.add_argument("--source", help="本地源码目录或 wheel；默认使用附带 wheel 或官方发行版")
    parser.add_argument("--executor", default="manual", help="真实调用本 Skill 的工具名称；未知则 manual，不填模型")
    args = parser.parse_args(argv)
    global LANGUAGE
    LANGUAGE = args.language
    if args.name is None:
        args.name = DEFAULT_NAME[LANGUAGE]
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")  # A legacy Windows code page must not end the install over one character.
    try:
        return run(args)
    except (ValueError, OSError) as error:
        print(say("初始化前检查失败：{0}", error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
