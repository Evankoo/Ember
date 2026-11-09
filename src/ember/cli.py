"""Explicit local initialization and loopback-only startup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from . import language
from .language import LANGUAGES
from .locator import install_skill, read_default, refresh_targets, register_default, resolve_workspace
from .store import Workspace, WorkspaceError

LANGUAGE_QUESTION = ("请选择这个工作区的语言 / Choose the language of this workspace:\n"
                     "  1. 中文\n  2. English\n"
                     "选定后，文件夹名称、任务卡、工作台和 AI 回复都使用这种语言，建好后不能再更改。\n"
                     "Folder names, task cards, the workbench and AI replies will use it. It cannot be changed later.\n> ")


def ask_language(read=input) -> str:
    """No silent default: without --language, ask on a terminal and refuse otherwise."""
    if not sys.stdin or not sys.stdin.isatty():
        raise WorkspaceError("请用 --language zh 或 --language en 选择工作区语言 / Choose the workspace language with --language zh or --language en.")
    while True:
        answer = read(LANGUAGE_QUESTION).strip().lower()
        if answer in ("1", "zh", "中文"):
            return "zh"
        if answer in ("2", "en", "english"):
            return "en"


def main(argv=None):
    parser = argparse.ArgumentParser(description="余烬本地任务工作台")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="初始化系统目录与文档库，拒绝覆盖非空目录")
    init.add_argument("workspace", type=Path, help="系统目录（规则、Skill、配置）")
    init.add_argument("--documents", type=Path, help="文档库；默认与系统目录同级的“<系统目录名>文档”")
    init.add_argument("--example", action="store_true", help="安装完整虚构示例")
    init.add_argument("--name", help="工作区名称")
    init.add_argument("--language", choices=LANGUAGES,
                      help="工作区语言 zh 或 en，建好后不能更改 / workspace language, zh or en; cannot be changed later")
    serve = commands.add_parser("serve", help="启动本机工作台")
    serve.add_argument("--workspace", type=Path, help="默认使用本机登记的工作区")
    serve.add_argument("--port", type=int, default=8783)
    check = commands.add_parser("check", help="读取并校验工作区")
    check.add_argument("--workspace", type=Path, help="默认使用本机登记的工作区")
    use = commands.add_parser("use", help="把工作区登记为本机默认，供任意目录的 AI 找到")
    use.add_argument("workspace", type=Path)
    use.add_argument("--replace", action="store_true", help="明确替换已登记的另一个默认工作区")
    commands.add_parser("where", help="显示本机登记的默认工作区")
    skill = commands.add_parser("install-skill", help="把日常 Skill 安装到 AI 工具的全局 Skills 目录")
    skill.add_argument("--target", type=Path, help="AI 工具的用户级 Skills 目录；省略时更新以前安装过的全部目录")
    addskills = commands.add_parser("add-skills", help="为旧工作区补装新版自带的 Skill；只新增，不覆盖")
    addskills.add_argument("--workspace", type=Path, help="默认使用本机登记的工作区")
    which = commands.add_parser("which-project", help="查找某个目录对应的项目")
    which.add_argument("--dir", type=Path, default=Path.cwd(), help="默认当前目录")
    which.add_argument("--workspace", type=Path, help="默认使用本机登记的工作区")
    location = commands.add_parser("project-location", help="为项目登记或移除本机工作目录")
    location.add_argument("project")
    location.add_argument("dir", type=Path)
    location.add_argument("--remove", action="store_true")
    location.add_argument("--workspace", type=Path, help="默认使用本机登记的工作区")
    category = commands.add_parser("project-category", help="设置或清除项目分类")
    category.add_argument("project")
    category.add_argument("name", nargs="?", default="")
    category.add_argument("--clear", action="store_true")
    category.add_argument("--workspace", type=Path, help="默认使用本机登记的工作区")
    commands.add_parser("skill-path", help="显示可安装或读取的初始化 Skill 目录")
    migrate = commands.add_parser("migrate-layout", help="把旧版单目录工作区复制为系统目录与文档库两处；原目录保留不动")
    migrate.add_argument("old", type=Path, help="旧版单目录工作区")
    migrate.add_argument("workspace", type=Path, help="新系统目录（必须为空或不存在）")
    migrate.add_argument("--documents", type=Path, help="新文档库；默认与系统目录同级的“<系统目录名>文档”")
    service = commands.add_parser("service", help="让工作台在登录后常驻后台（macOS 与 Windows）")
    service.add_argument("action", choices=("install", "uninstall", "start", "stop", "status"))
    service.add_argument("--workspace", type=Path, help="默认使用本机登记的工作区")
    service.add_argument("--port", type=int, default=8783)
    args = parser.parse_args(argv)
    # Chinese output must not crash a console or pipe using a legacy Windows code page.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if args.command == "skill-path":
        print(Path(__file__).resolve().parent / "skills" / "ember-init")
        return 0
    try:
        if args.command == "install-skill":
            if args.target:
                print(json.dumps(install_skill(args.target), ensure_ascii=False))
                return 0
            targets = refresh_targets()
            if not targets:
                raise WorkspaceError("还没有安装过日常 Skill：请用 --target 指定 AI 工具的 Skills 目录。")
            print(json.dumps([install_skill(target) for target in targets], ensure_ascii=False, indent=2))
            return 0
        if args.command == "service":
            from . import service as background
            if args.action == "install":
                print(json.dumps(background.install(resolve_workspace(args.workspace).path, args.port), ensure_ascii=False, indent=2))
            else:
                print(json.dumps(getattr(background, args.action)(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "add-skills":
            from .bootstrap import add_bundled_skills
            print(json.dumps(add_bundled_skills(resolve_workspace(args.workspace)), ensure_ascii=False, indent=2))
            return 0
        if args.command == "which-project":
            print(json.dumps(resolve_workspace(args.workspace).project_for_directory(args.dir), ensure_ascii=False))
            return 0
        if args.command == "project-category":
            if bool(args.name) == args.clear:
                raise WorkspaceError("请提供分类名称，或使用 --clear 清除。")
            result = resolve_workspace(args.workspace).update_project_category(args.project, {"category": args.name})
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "project-location":
            change = {"remove" if args.remove else "add": str(args.dir.expanduser().absolute())}
            print(json.dumps(resolve_workspace(args.workspace).update_project_locations(args.project, change), ensure_ascii=False))
            return 0
        if args.command == "where":
            stored = read_default()
            if stored is None:
                raise WorkspaceError("尚未登记默认工作区：运行 ember use <工作区>。")
            from .bootstrap import verify_workspace_contract
            try:
                verify_workspace_contract(Workspace(stored["workspace"]))
            except WorkspaceError as error:
                raise WorkspaceError(f"已登记的默认工作区不可用：{stored['workspace']}（{error}）") from None
            print(json.dumps(stored, ensure_ascii=False, indent=2))
            return 0
        if args.command == "migrate-layout":
            from .migrate import migrate_layout
            print(json.dumps(migrate_layout(args.old, args.workspace, args.documents), ensure_ascii=False, indent=2))
            return 0
        if args.command == "use":
            print(json.dumps(register_default(Workspace(args.workspace), replace=args.replace), ensure_ascii=False, indent=2))
            return 0
        if args.command == "init":
            workspace = Workspace(args.workspace, args.documents, language=args.language or ask_language())
        else:
            workspace = resolve_workspace(args.workspace)
        say = lambda message: print(language.finished(workspace.language, message))
        if args.command == "init":
            if args.name is not None and (not args.name.strip() or len(args.name.strip()) > 80):
                raise WorkspaceError("工作区名称应为 1–80 字符")
            workspace.initialize(example=args.example)
            if args.name is not None:
                workspace._write_json("config/workspace.json", {**workspace._json("config/workspace.json"), "name": args.name.strip()})
            say(f"系统目录已建立：{workspace.path}")
            say(f"文档库已建立：{workspace.docs}")
            say(f"启动：ember serve --workspace {args.workspace} --port 8783")
            say(f"设为本机默认（让任意目录的 AI 找到它）：ember use {args.workspace}")
        elif args.command == "check":
            from .bootstrap import verify_workspace_contract
            verify_workspace_contract(workspace)
            state = workspace.snapshot()
            say(f"校验通过：{len(state['projects'])} 项目 / {len(state['tasks'])} 任务 / {len(state['files'])} 文件")
        else:
            if not 0 <= args.port <= 65535:
                parser.error("端口应在 0–65535 内")
            from .bootstrap import verify_workspace_contract
            verify_workspace_contract(workspace)
            workspace.snapshot()  # Missing/unreadable data must not look like an empty workspace.
            from .server import run
            run(workspace, port=args.port)
    except (WorkspaceError, OSError) as error:
        current = locals().get("workspace")
        message = f"余烬：{error}"
        print(language.finished(current.language, message) if isinstance(current, Workspace) else message, file=sys.stderr)
        return 1
    return 0
