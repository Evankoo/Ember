"""Explicit local initialization and loopback-only startup."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .store import Workspace, WorkspaceError


def main(argv=None):
    parser = argparse.ArgumentParser(description="GStudio 本地任务工作台")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="初始化一个新工作区，拒绝覆盖非空目录")
    init.add_argument("workspace", type=Path)
    init.add_argument("--example", action="store_true", help="安装完整虚构示例")
    init.add_argument("--name", help="工作区名称")
    serve = commands.add_parser("serve", help="启动本机工作台")
    serve.add_argument("--workspace", required=True, type=Path)
    serve.add_argument("--port", type=int, default=8783)
    check = commands.add_parser("check", help="读取并校验工作区")
    check.add_argument("--workspace", required=True, type=Path)
    commands.add_parser("skill-path", help="显示可安装或读取的初始化 Skill 目录")
    args = parser.parse_args(argv)
    if args.command == "skill-path":
        print(Path(__file__).resolve().parent / "skills" / "gstudio-init")
        return 0
    try:
        workspace = Workspace(args.workspace)
        if args.command == "init":
            if args.name is not None and (not args.name.strip() or len(args.name.strip()) > 80):
                raise WorkspaceError("工作区名称应为 1–80 字符")
            workspace.initialize(example=args.example)
            if args.name is not None:
                workspace._write_json("config/workspace.json", {"name": args.name.strip()})
            print(f"工作区已建立：{args.workspace.resolve()}")
            print(f"启动：gstudio serve --workspace {args.workspace} --port 8783")
        elif args.command == "check":
            from .bootstrap import verify_workspace_contract
            verify_workspace_contract(workspace)
            state = workspace.snapshot()
            print(f"校验通过：{len(state['projects'])} 项目 / {len(state['tasks'])} 任务 / {len(state['files'])} 文件")
        else:
            if not 0 <= args.port <= 65535:
                parser.error("端口应在 0–65535 内")
            from .bootstrap import verify_workspace_contract
            verify_workspace_contract(workspace)
            workspace.snapshot()  # Missing/unreadable data must not look like an empty workspace.
            from .server import run
            run(workspace, port=args.port)
    except (WorkspaceError, OSError) as error:
        print(f"GStudio：{error}", file=sys.stderr)
        return 1
    return 0
