"""Register the installed system and keep technical evidence in the application directory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from . import __version__
from .bootstrap import CONTRACT_FILES, PACKAGE, verify_workspace_contract
from .project_registration import plan_project
from .store import Workspace, WorkspaceError, _tree


def _factory_workspace(workspace: Workspace, mode: str) -> None:
    verify_workspace_contract(workspace)
    if mode not in ("empty", "example"):
        raise WorkspaceError("初始化模式必须为 empty 或 example。")
    state = workspace.snapshot()
    allowed = {*CONTRACT_FILES, "config/projects.json", "config/workspace.json", "skills/manifest.json",
               "skills/RESOLVER.md", ".gaiora/views.json", ".gaiora/inbox.json", ".gaiora/service.lock"}
    for name in ("gaiora-init", "gaiora", "gaiora-project"):
        source = PACKAGE / "skills" / name
        allowed.update(f".agents/skills/{name}/{p.relative_to(source).as_posix()}" for p in source.rglob("*")
                       if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    if mode == "empty":
        if state["projects"] or state["tasks"] or state["files"] or state["reports"]:
            raise WorkspaceError("安装登记只适用于新工作区；已有业务不得重新初始化。", 409)
    else:
        source = PACKAGE / "examples/workspace"
        for path in _tree(source):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                allowed.add(relative)
                if relative != "config/workspace.json" and workspace._safe(relative, exists=True).read_bytes() != path.read_bytes():
                    raise WorkspaceError("示例已修改，拒绝将其视为新安装。", 409)
    if any(p.relative_to(workspace.path).as_posix() not in allowed for p in _tree(workspace.path) if p.is_file()):
        raise WorkspaceError("工作区已有额外文件，停止安装登记并保留现场。", 409)


def _app_directory(workspace: Workspace, app_dir: Path) -> Path:
    original = Path(app_dir).expanduser().absolute()
    if original.is_symlink() or not original.is_dir():
        raise WorkspaceError("应用目录必须是实际存在的独立目录。")
    app = original.resolve()
    if app == workspace.path or app in workspace.path.parents or workspace.path in app.parents:
        raise WorkspaceError("应用目录和工作区不能互相包含。")
    return app


def begin_installation(workspace: Workspace, *, app_dir: Path, executor: str = "manual", mode: str = "empty") -> dict:
    Workspace._executor(executor)
    _app_directory(workspace, app_dir)
    with workspace._lock:
        _factory_workspace(workspace, mode)
        proposal = plan_project(workspace, {"id": "gaiora", "name": "Gaiora", "kind": "system",
                               "description": "管理本机 Gaiora 的安装、验收和后续独立系统维护；不代替业务项目。",
                               "focus": "完成本次首次安装与人工验收",
                               "overview": "# Gaiora\n\n## 系统用途\n\n本机 Gaiora 的安装、验收与维护入口。业务目标使用独立业务项目。\n\n## 边界\n\n只管理本地工作区；不配置模型凭据、不自动运行 AI，也不提供归档或删除接口。\n"})
        if not proposal["can_create"]:
            raise WorkspaceError("Gaiora 系统项目已存在；保留现有安装，不重复创建。", 409)
        workspace.create_project(proposal["project"])
        return {"system_project_id": "gaiora", "system_project_path": "projects/gaiora.md"}


def record_installation(workspace: Workspace, receipt: dict) -> dict:
    workspace._payload(receipt)
    if receipt.get("workspace") != str(workspace.path) or receipt.get("version") != __version__:
        raise WorkspaceError("安装收据不属于本工作区或本版本，拒绝保存报告。")
    status = receipt.get("status")
    if status not in ("installing", "failed", "ready"):
        raise WorkspaceError("安装收据状态不合法。")
    stage = workspace._string(receipt, "stage", required=True, limit=80)
    checks = receipt.get("checks", [])
    if not isinstance(checks, list) or any(x not in ("workspace-contract", "persisted-workflow", "loopback-health") for x in checks):
        raise WorkspaceError("安装检查清单不合法。")
    if status == "ready" and (set(checks) != {"workspace-contract", "persisted-workflow", "loopback-health"}
                              or receipt.get("verification_workspace_cleaned") is not True or receipt.get("service_running") is not False):
        raise WorkspaceError("技术验证证据不完整，不能报告安装就绪。")
    if receipt.get("mode") not in ("empty", "example") or receipt.get("system_project_id") != "gaiora":
        raise WorkspaceError("安装模式或系统项目登记不合法。")
    app = _app_directory(workspace, Path(workspace._string(receipt, "app_dir", required=True, limit=4096)))
    stored = app / "installation.json"
    if stored.is_symlink() or not stored.is_file():
        raise WorkspaceError("应用目录缺少真实安装收据，拒绝保存报告。")
    if json.loads(stored.read_text(encoding="utf-8")) != receipt:
        raise WorkspaceError("安装收据与应用目录中的记录不同。")
    if status == "installing":
        return {}
    error = workspace._string(receipt, "error", limit=5000)
    current = ("技术检查全部通过；工作台常驻服务尚未启动，首次使用引导尚未完成。" if status == "ready"
               else f"安装在 {stage} 阶段失败：{error}。已保留现场，不声称验证通过。")
    next_step = ("按启动命令打开工作台并配置当前 AI 工具；由 gaiora 使用普通建任务接口，将当前对话建成第一张真实任务卡。用户在工作台检查 OK 后，再通过 gaiora-project 确认并建立练习项目。" if status == "ready"
                 else "检查应用目录中的安装收据、失败说明及保留的隔离测试目录；修复前保留现有证据，不重置工作区。")
    content = (f"# Gaiora 安装记录\n\n- 版本：{__version__}\n- 安装状态：{status}\n- 阶段：{stage}\n"
               f"- 应用目录：{app}\n- 工作区：{workspace.path}\n- 模式：{receipt['mode']}\n"
               f"- 检查：{'、'.join(checks) or '尚无'}\n\n{current}\n\n"
               "技术测试使用隔离工作区。安装记录保存在应用目录，不是任务输入或交付；安装脚本不创建首任务，不调用模型。\n\n"
               f"## 下一步\n\n{next_step}\n")
    path = app / ("installation-report.md" if status == "ready" else "installation-failure.md")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise WorkspaceError("安装报告必须是应用目录中的普通文件，保留现有路径。", 409)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise WorkspaceError("安装记录已存在且内容不同，保留原证据并停止覆盖。", 409)
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=app)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"report_path": str(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="首次安装系统登记与应用目录报告；不创建任务或重置已有工作区")
    sub = parser.add_subparsers(dest="action", required=True)
    begin = sub.add_parser("begin")
    begin.add_argument("--workspace", required=True)
    begin.add_argument("--app-dir", required=True)
    begin.add_argument("--executor", default="manual")
    begin.add_argument("--mode", choices=("empty", "example"), default="empty")
    record = sub.add_parser("record")
    record.add_argument("--workspace", required=True)
    record.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        workspace = Workspace(args.workspace)
        from .server import workspace_lock
        with workspace_lock(workspace):
            if args.action == "begin":
                result = begin_installation(workspace, app_dir=Path(args.app_dir), executor=args.executor, mode=args.mode)
            else:
                source = Path(args.receipt).expanduser().absolute()
                if source.is_symlink() or not source.is_file():
                    raise WorkspaceError("安装收据必须是应用目录中的普通文件。")
                receipt = json.loads(source.read_text(encoding="utf-8"))
                workspace._payload(receipt)
                app = _app_directory(workspace, Path(workspace._string(receipt, "app_dir", required=True, limit=4096)))
                if source.resolve() != app / "installation.json":
                    raise WorkspaceError("只能读取应用目录中的 installation.json。")
                result = record_installation(workspace, receipt)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (WorkspaceError, OSError, ValueError) as error:
        print(f"首次安装记录失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
