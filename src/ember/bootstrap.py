"""Install the portable system contract; never use private runtime configuration."""
from __future__ import annotations

from pathlib import Path

from . import __version__

PACKAGE = Path(__file__).resolve().parent
CONTRACT_FILES = ("AGENTS.md", "SOUL.md", "MEMORY.md", "RESOLVER.md", "WORKBENCH_DESIGN.md", "templates/task-card.md")
INIT_ROUTE = "- 首次安装或建立新工作区：读取 [ember-init](../.agents/skills/ember-init/SKILL.md)。"
INIT_ROOT_ROUTE = "| 首次安装 Skill | 系统目录 .agents/skills/ember-init/SKILL.md |"


def install_workspace_contract(workspace):
    from .store import _parse_markdown

    for name in CONTRACT_FILES:
        workspace._atomic_text(name, (PACKAGE / "templates" / name).read_text(encoding="utf-8"), new=True)
    skills = []
    for name, purpose in (("ember-init", "首次安装、新手实操与确认完成后的引导清理"), ("ember", "按系统规则处理日常任务、资料与交付"), ("ember-project", "确认建项方案，登记业务项目或系统工作区")):
        skill_root = PACKAGE / "skills" / name
        for source in sorted(skill_root.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                relative = source.relative_to(skill_root).as_posix()
                workspace._atomic_text(f".agents/skills/{name}/" + relative, source.read_text(encoding="utf-8"), new=True)
        header, _ = _parse_markdown((skill_root / "SKILL.md").read_text(encoding="utf-8"), name)
        skills.append({"name": name, "version": header["version"], "path": f".agents/skills/{name}/SKILL.md", "purpose": purpose})
    workspace._write_json("skills/manifest.json", {"version": 1, "skills": skills}, new=True)
    workspace._atomic_text("skills/RESOLVER.md", "# Skills Resolver\n\n- 首次安装或建立新工作区：读取 [ember-init](../.agents/skills/ember-init/SKILL.md)。\n- 日常任务入口与只读检索：读取 [ember](../.agents/skills/ember/SKILL.md)，先判断是否需要任务卡；跟随系统级 [AGENTS.md](../AGENTS.md)、项目说明与原任务。\n- 新建业务项目或系统工作区：读取 [ember-project](../.agents/skills/ember-project/SKILL.md)，先查重、展示方案并取得确认；不迁移资料或重分配任务。\n- 其他业务 Skill 只在实际需要且可用时调用，不随余烬安装。\n- 初始化 Skill 不重置、迁移或升级现有工作区。\n", new=True)
    # A user's chosen name is local data, not an installation default in source code.
    if not workspace._safe("config/workspace.json").exists():
        workspace._write_json("config/workspace.json", {"name": "余烬"}, new=True)


def verify_workspace_contract(workspace):
    from .store import WorkspaceError
    with workspace._lock:
        required = [*CONTRACT_FILES, ".agents/skills/ember/SKILL.md", ".agents/skills/ember-project/SKILL.md", ".agents/skills/ember-project/scripts/project.py", "skills/manifest.json", "skills/RESOLVER.md"]
        manifest = workspace._json("skills/manifest.json")
        from .onboarding_completion import PENDING, validate_completion
        if workspace._safe(PENDING).exists():
            raise WorkspaceError("初始化 Skill 清理尚未完成，请按原任务重试清理。", 409)
        names = ["ember", "ember-project"]
        if "onboarding_completion" in manifest:
            validate_completion(workspace, manifest["onboarding_completion"])
            if workspace._safe(".agents/skills/ember-init").exists() or any(
                    isinstance(item, dict) and item.get("name") == "ember-init" for item in manifest.get("skills", [])):
                raise WorkspaceError("初始化完成记录与现有 Skill 不一致。")
            if INIT_ROUTE in workspace._text("skills/RESOLVER.md") or INIT_ROOT_ROUTE in workspace._text("RESOLVER.md"):
                raise WorkspaceError("初始化 Skill 已清理，但路由尚未更新。")
        else:
            names.insert(0, "ember-init")
            required += [".agents/skills/ember-init/SKILL.md", ".agents/skills/ember-init/scripts/bootstrap.py"]
        for name in required:
            path = workspace._safe(name, exists=True)
            if not path.is_file() or not path.stat().st_size:
                raise WorkspaceError(f"初始化契约缺失或为空：{name}")
        for name in names:
            if not any(item.get("name") == name and item.get("path") == f".agents/skills/{name}/SKILL.md" for item in manifest.get("skills", []) if isinstance(item, dict)):
                raise WorkspaceError(f"Skill 注册信息不完整：{name}")
        return {"version": __version__, "contract_files": len(required), "skills": names}
