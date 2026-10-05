"""Install the portable system contract; never use private runtime configuration."""
from __future__ import annotations

from pathlib import Path

from . import __version__

PACKAGE = Path(__file__).resolve().parent
CONTRACT_FILES = ("AGENTS.md", "SOUL.md", "MEMORY.md", "RESOLVER.md", "WORKBENCH_DESIGN.md", "templates/task-card.md")


def install_workspace_contract(workspace):
    for name in CONTRACT_FILES:
        workspace._atomic_text(name, (PACKAGE / "templates" / name).read_text(encoding="utf-8"), new=True)
    skills = []
    for name, purpose in (("gstudio-init", "初始化 GStudio Core 新安装与工作区"), ("gstudio-core", "按系统规则处理日常任务、资料与交付")):
        skill_root = PACKAGE / "skills" / name
        for source in sorted(skill_root.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                relative = source.relative_to(skill_root).as_posix()
                workspace._atomic_text(f".agents/skills/{name}/" + relative, source.read_text(encoding="utf-8"), new=True)
        skills.append({"name": name, "path": f".agents/skills/{name}/SKILL.md", "purpose": purpose})
    workspace._write_json("skills/manifest.json", {"version": 1, "skills": skills}, new=True)
    workspace._atomic_text("skills/RESOLVER.md", "# Skills Resolver\n\n- 初始化新的 GStudio Core：读取 [gstudio-init](../.agents/skills/gstudio-init/SKILL.md)。\n- 日常任务、资料与交付：读取 [gstudio-core](../.agents/skills/gstudio-core/SKILL.md)，遵循系统级 [AGENTS.md](../AGENTS.md) 与任务卡正本。\n- 初始化 Skill 不重置现有工作区。\n", new=True)
    # A user's chosen name is local data, not an installation default in source code.
    if not workspace._safe("config/workspace.json").exists():
        workspace._write_json("config/workspace.json", {"name": "GStudio"}, new=True)


def verify_workspace_contract(workspace):
    from .store import WorkspaceError
    required = (*CONTRACT_FILES, ".agents/skills/gstudio-init/SKILL.md", ".agents/skills/gstudio-init/scripts/bootstrap.py", ".agents/skills/gstudio-core/SKILL.md", "skills/manifest.json", "skills/RESOLVER.md")
    for name in required:
        path = workspace._safe(name, exists=True)
        if not path.is_file() or not path.stat().st_size:
            raise WorkspaceError(f"初始化契约缺失或为空：{name}")
    manifest = workspace._json("skills/manifest.json")
    names = ["gstudio-init", "gstudio-core"]
    for name in names:
        if not any(item.get("name") == name and item.get("path") == f".agents/skills/{name}/SKILL.md" for item in manifest.get("skills", []) if isinstance(item, dict)):
            raise WorkspaceError(f"Skill 注册信息不完整：{name}")
    return {"version": __version__, "contract_files": len(required), "skills": names}
