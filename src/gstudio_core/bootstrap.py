"""Install the portable system contract; never use private runtime configuration."""
from __future__ import annotations

from pathlib import Path

from . import __version__

PACKAGE = Path(__file__).resolve().parent
CONTRACT_FILES = ("AGENTS.md", "SOUL.md", "MEMORY.md", "RESOLVER.md", "WORKBENCH_DESIGN.md", "templates/task-card.md")


def install_workspace_contract(workspace):
    from .store import _parse_markdown

    for name in CONTRACT_FILES:
        workspace._atomic_text(name, (PACKAGE / "templates" / name).read_text(encoding="utf-8"), new=True)
    skills = []
    for name, purpose in (("gstudio-init", "首次安装引导、系统首任务与隔离验收"), ("gstudio-core", "按系统规则处理日常任务、资料与交付"), ("gstudio-project", "确认建项方案，登记业务项目或系统工作区")):
        skill_root = PACKAGE / "skills" / name
        for source in sorted(skill_root.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                relative = source.relative_to(skill_root).as_posix()
                workspace._atomic_text(f".agents/skills/{name}/" + relative, source.read_text(encoding="utf-8"), new=True)
        header, _ = _parse_markdown((skill_root / "SKILL.md").read_text(encoding="utf-8"), name)
        skills.append({"name": name, "version": header["version"], "path": f".agents/skills/{name}/SKILL.md", "purpose": purpose})
    workspace._write_json("skills/manifest.json", {"version": 1, "skills": skills}, new=True)
    workspace._atomic_text("skills/RESOLVER.md", "# Skills Resolver\n\n- 首次安装或建立新工作区：读取 [gstudio-init](../.agents/skills/gstudio-init/SKILL.md)。\n- 日常任务入口与只读检索：读取 [gstudio-core](../.agents/skills/gstudio-core/SKILL.md)，先判断是否需要任务卡；跟随系统级 [AGENTS.md](../AGENTS.md)、项目说明与原任务。\n- 新建业务项目或系统工作区：读取 [gstudio-project](../.agents/skills/gstudio-project/SKILL.md)，先查重、展示方案并取得确认；不迁移资料或重分配任务。\n- 其他业务 Skill 只在实际需要且可用时调用，不随 Core 安装。\n- 初始化 Skill 不重置、迁移或升级现有工作区。\n", new=True)
    # A user's chosen name is local data, not an installation default in source code.
    if not workspace._safe("config/workspace.json").exists():
        workspace._write_json("config/workspace.json", {"name": "GStudio"}, new=True)


def verify_workspace_contract(workspace):
    from .store import WorkspaceError
    required = (*CONTRACT_FILES, ".agents/skills/gstudio-init/SKILL.md", ".agents/skills/gstudio-init/scripts/bootstrap.py", ".agents/skills/gstudio-core/SKILL.md", ".agents/skills/gstudio-project/SKILL.md", ".agents/skills/gstudio-project/scripts/project.py", "skills/manifest.json", "skills/RESOLVER.md")
    for name in required:
        path = workspace._safe(name, exists=True)
        if not path.is_file() or not path.stat().st_size:
            raise WorkspaceError(f"初始化契约缺失或为空：{name}")
    manifest = workspace._json("skills/manifest.json")
    names = ["gstudio-init", "gstudio-core", "gstudio-project"]
    for name in names:
        if not any(item.get("name") == name and item.get("path") == f".agents/skills/{name}/SKILL.md" for item in manifest.get("skills", []) if isinstance(item, dict)):
            raise WorkspaceError(f"Skill 注册信息不完整：{name}")
    return {"version": __version__, "contract_files": len(required), "skills": names}
