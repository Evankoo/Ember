"""Keep one real installation task; technical probes stay in a separate workspace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

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
               "skills/RESOLVER.md", ".gstudio/views.json", ".gstudio/inbox.json", ".gstudio/service.lock"}
    for name in ("gstudio-init", "gstudio-core", "gstudio-project"):
        source = PACKAGE / "skills" / name
        allowed.update(f".agents/skills/{name}/{p.relative_to(source).as_posix()}" for p in source.rglob("*")
                       if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    if mode == "empty":
        if state["projects"] or state["tasks"] or state["files"] or state["reports"]:
            raise WorkspaceError("首任务引导只适用于新工作区；已有业务不得重新初始化。", 409)
    else:
        source = PACKAGE / "examples/workspace"
        for path in _tree(source):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                allowed.add(relative)
                if relative != "config/workspace.json" and workspace._safe(relative, exists=True).read_bytes() != path.read_bytes():
                    raise WorkspaceError("示例已修改，拒绝将其视为新安装。", 409)
    if any(p.relative_to(workspace.path).as_posix() not in allowed for p in _tree(workspace.path) if p.is_file()):
        raise WorkspaceError("工作区已有额外文件，停止首任务引导并保留现场。", 409)


def begin_installation(workspace: Workspace, *, app_dir: Path, executor: str = "manual", mode: str = "empty") -> dict:
    executor = Workspace._executor(executor)
    original = Path(app_dir).expanduser().absolute()
    if original.is_symlink() or not original.is_dir():
        raise WorkspaceError("应用目录必须是实际存在的独立目录。")
    app = original.resolve()
    if app == workspace.path or app in workspace.path.parents or workspace.path in app.parents:
        raise WorkspaceError("应用目录和工作区不能互相包含。")
    with workspace._lock:
        _factory_workspace(workspace, mode)
        proposal = plan_project(workspace, {"id": "gstudio", "name": "GStudio", "kind": "system",
                               "description": "管理本机 GStudio Core 的安装、验收和后续独立系统维护；不代替业务项目。",
                               "focus": "完成本次首次安装与人工验收",
                               "overview": "# GStudio\n\n## 系统用途\n\n本机 GStudio Core 的安装、验收与维护入口。业务目标使用独立业务项目。\n\n## 边界\n\n只管理本地工作区；不配置模型凭据、不自动运行 AI，也不提供归档或删除接口。\n"})
        if not proposal["can_create"]:
            raise WorkspaceError("GStudio 系统项目已存在；继续原任务，不重复创建。", 409)
        workspace.create_project(proposal["project"])
        task = workspace.create_task({"title": "GStudio初始化验收", "project": "gstudio", "work_type": "system",
                                     "task_kind": "task", "executor": executor,
                                     "skills_used": ["gstudio-init", "gstudio-project"], "artifact_mode": "delivery",
                                     "goal": "安装独立程序环境、工作区和三项基础 Skill；验证真实任务、输入、交付及本机 HTTP 流程，留下安装证据；启动工作台并完成人工验收后，再确认正式交付。",
                                     "description": "这是本次真实安装任务，不是示例。已确认新应用目录、工作区和初始化模式。技术测试在隔离工作区执行，只把结果写回本任务；业务建项另由用户确认，不自动迁移资料、调用模型或完成任务。"})
        choices = {"app_dir": str(app), "workspace": str(workspace.path), "mode": mode, "executor": executor}
        workspace.add_material(task["id"], {"kind": "input", "name": "安装计划.json",
                               "content": json.dumps(choices, ensure_ascii=False, indent=2) + "\n",
                               "purpose": "本次由初始化脚本录入的用户已确认安装选择；不是密码或客户端配置。",
                               "source_locator": "gstudio-init:confirmed-choices"})
        workspace.update_task(task["id"], {"current": "已建立 GStudio 系统项目及本次真实安装任务，安装选择已登记为输入；技术验证尚未执行。",
                              "next": "执行工作区检查与隔离测试，将真实结果写回原安装任务。",
                              "log_entry": "按已确认首次安装范围建立系统项目和首任务；保留 active 状态，未创建空交付目录。"})
        return {"system_project_id": "gstudio", "task_id": task["id"],
                "task_path": f"tasks/active/{task['id']}.md", "system_project_path": "projects/gstudio.md"}


def record_installation(workspace: Workspace, receipt: dict) -> dict:
    workspace._payload(receipt)
    if receipt.get("workspace") != str(workspace.path) or receipt.get("version") != __version__:
        raise WorkspaceError("安装收据不属于本工作区或本版本，拒绝写回。")
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
    task_id = workspace._identifier(receipt.get("task_id"), "task id")
    with workspace._lock:
        _, metadata, _ = workspace._task(task_id)
        plan = next((x for x in metadata.get("inputs", {}).get("items", [])
                     if x.get("source_locator") == "gstudio-init:confirmed-choices"), None)
        if metadata["project"] != "gstudio" or metadata["work_type"] != "system" or not plan:
            raise WorkspaceError("目标不是本次安装任务。")
        if metadata["status"] == "completed":
            raise WorkspaceError("已验收完成的安装任务不接受自动写回。", 409)
        original = json.loads(workspace._safe(plan["path"], exists=True).read_text(encoding="utf-8"))
        if original["app_dir"] != receipt.get("app_dir") or original["mode"] != receipt.get("mode"):
            raise WorkspaceError("安装收据与登记的安装选择不同。")
        result = {"task_id": task_id}
        current = f"正在执行安装阶段：{stage}；已完成检查：{'、'.join(checks) or '尚无'}。"
        next_step = "继续本任务的安装与隔离验证；失败时保留现场，不重建工作区。"
        if status in ("ready", "failed"):
            error = workspace._string(receipt, "error", limit=5000)
            current = ("技术检查全部通过，结果已写入安装验收草稿；工作台常驻服务尚未启动，人工验收尚未完成。" if status == "ready"
                       else f"安装在 {stage} 阶段失败：{error}。已保留现场和原任务，不声称验证通过。")
            next_step = ("按启动命令打开工作台，回读 GStudio 系统项目、首任务和三项 Skill；按需要确认第一个业务项目，再由用户人工验收和确认正式交付。" if status == "ready"
                         else "检查保留的收据、失败日志及隔离测试目录；修复后继续原任务，禁止覆盖安装目录或假定成功。")
            name = "安装验收.md" if status == "ready" else "安装失败说明.md"
            content = (f"# GStudio Core 安装记录\n\n- 版本：{__version__}\n- 安装状态：{status}\n- 阶段：{stage}\n"
                       f"- 应用目录：{original['app_dir']}\n- 工作区：{workspace.path}\n- 模式：{original['mode']}\n"
                       f"- 检查：{'、'.join(checks) or '尚无'}\n\n{current}\n\n"
                       "技术测试使用隔离工作区；不向真实工作区添加模拟测试任务。此记录不是用户验收，不自动完成或正式交付。\n\n"
                       f"## 下一步\n\n{next_step}\n")
            relative = f"delivery/draft/{task_id}/{name}"
            path = workspace._safe(relative)
            if path.exists():
                if path.read_text(encoding="utf-8") != content:
                    raise WorkspaceError("安装记录已存在且内容不同，保留原证据并停止覆盖。", 409)
            else:
                workspace.add_material(task_id, {"kind": "draft", "name": name, "content": content})
            result["report_path"] = relative
        workspace.update_task(task_id, {"current": current, "next": next_step,
                              "log_entry": f"安装阶段 {stage}：{status}；已完成检查：{'、'.join(checks) or '尚无'}。未自动完成任务。"})
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="首次安装首任务与真实结果写回；不重置已有工作区")
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
            result = (begin_installation(workspace, app_dir=Path(args.app_dir), executor=args.executor, mode=args.mode)
                      if args.action == "begin" else record_installation(workspace, json.loads(Path(args.receipt).read_text(encoding="utf-8"))))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (WorkspaceError, OSError, ValueError) as error:
        print(f"首次安装记录失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
