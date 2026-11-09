"""Install the portable system contract; never use private runtime configuration."""
from __future__ import annotations

from pathlib import Path

from . import __version__
from . import language as lang

PACKAGE = Path(__file__).resolve().parent
CONTRACT_FILES = ("AGENTS.md", "SOUL.md", "MEMORY.md", "RESOLVER.md", "WORKBENCH_DESIGN.md", "templates/task-card.md")
INIT_ROUTE = "- 首次安装或建立新工作区：读取 [ember-init](../.agents/skills/ember-init/SKILL.md)。"
INIT_ROOT_ROUTE = "| 首次安装 Skill | 系统目录 .agents/skills/ember-init/SKILL.md |"
# Translations of a template or Skill file live beside it under locale/<language>/ and replace it there.
LOCALE = "locale"
BUNDLED_SKILLS = (("ember-init", "首次安装、新手实操与确认完成后的引导清理"), ("ember", "按系统规则处理日常任务、资料与交付"),
                  ("ember-project", "确认建项方案，登记业务项目或系统工作区"), ("ember-review", "每周整理与所选任务整理，确认后晋级或收口"),
                  ("ember-skill-authoring", "按统一结构新建或修改用户自己的 Skill 并登记"))
# Added in 0.22.0: workspaces created earlier may lack them, so they are checked only once registered.
OPTIONAL_SKILLS = ("ember-review", "ember-skill-authoring")


def init_routes(language: str = lang.DEFAULT) -> tuple[str, str]:
    return lang.text(language, INIT_ROUTE), lang.text(language, INIT_ROOT_ROUTE)


def localized_tree(root: Path, language: str = lang.DEFAULT) -> dict[str, bytes]:
    """Files of a template or Skill folder as installed in a workspace of `language`."""
    files = {}
    for source in sorted(root.rglob("*")):
        relative = source.relative_to(root)
        if (source.is_file() and "__pycache__" not in relative.parts and source.suffix != ".pyc"
                and source.name != ".DS_Store" and relative.parts[0] != LOCALE):
            files[relative.as_posix()] = source.read_bytes()
    translated = root / LOCALE / language
    if language != lang.DEFAULT and translated.is_dir():
        for source in sorted(translated.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                files[source.relative_to(translated).as_posix()] = source.read_bytes()
    return files


def skill_tree(name: str, language: str = lang.DEFAULT) -> dict[str, bytes]:
    return localized_tree(PACKAGE / "skills" / name, language)


def install_workspace_contract(workspace):
    from .store import _parse_markdown

    language = workspace.language
    templates = localized_tree(PACKAGE / "templates", language)
    for name in CONTRACT_FILES:
        workspace._atomic_text(name, templates[name].decode("utf-8"), new=True)
    skills = []
    for name, purpose in BUNDLED_SKILLS:
        files = skill_tree(name, language)
        for relative, data in files.items():
            workspace._atomic_text(f".agents/skills/{name}/" + relative, data.decode("utf-8"), new=True)
        header, _ = _parse_markdown(files["SKILL.md"].decode("utf-8"), name)
        skills.append({"name": name, "version": header["version"], "path": f".agents/skills/{name}/SKILL.md", "purpose": workspace._w(purpose)})
    workspace._write_json("skills/manifest.json", {"version": 1, "skills": skills}, new=True)
    workspace._atomic_text("skills/RESOLVER.md", workspace._w(RESOLVER), new=True)
    # A user's chosen name is local data, not an installation default in source code.
    if not workspace._safe("config/workspace.json").exists():
        workspace._write_json("config/workspace.json", {"name": workspace._w("余烬")}, new=True)


RESOLVER = ("# Skills Resolver\n\n- 首次安装或建立新工作区：读取 [ember-init](../.agents/skills/ember-init/SKILL.md)。\n- 日常任务入口与只读检索：读取 [ember](../.agents/skills/ember/SKILL.md)，先判断是否需要任务卡；跟随系统级 [AGENTS.md](../AGENTS.md)、项目说明与原任务。\n- 新建业务项目或系统工作区：读取 [ember-project](../.agents/skills/ember-project/SKILL.md)，先查重、展示方案并取得确认；不迁移资料或重分配任务。\n- 每周整理或整理所选任务：读取 [ember-review](../.agents/skills/ember-review/SKILL.md)，只保存建议报告，逐项确认后晋级或收口。\n- 新建或修改自己的 Skill：读取 [ember-skill-authoring](../.agents/skills/ember-skill-authoring/SKILL.md)，不改自带 Skill。\n- 其他业务 Skill 只在实际需要且可用时调用，不随余烬安装。\n- 初始化 Skill 不重置、迁移或升级现有工作区。\n")


def skill_route(name: str, language: str = lang.DEFAULT) -> str:
    """The workspace Resolver line for a bundled Skill, as `RESOLVER` writes it."""
    prefix = "- "
    for line in lang.text(language, RESOLVER).splitlines():
        if f"/{name}/SKILL.md" in line and line.startswith(prefix):
            return line
    raise KeyError(name)


def add_bundled_skills(workspace) -> dict:
    """Add bundled Skills an older workspace lacks; only adds, never overwrites a folder or entry."""
    from .store import WorkspaceError, _parse_markdown
    with workspace._lock:
        verify_workspace_contract(workspace)
        manifest = workspace._json("skills/manifest.json")
        registered = {item.get("name") for item in manifest.get("skills", []) if isinstance(item, dict)}
        purposes = dict(BUNDLED_SKILLS)
        added, present = [], []
        for name in OPTIONAL_SKILLS:
            if name in registered:
                present.append(name)
                continue
            if workspace._safe(f".agents/skills/{name}").exists():
                raise WorkspaceError(f"系统目录已有未登记的 .agents/skills/{name}，未覆盖；请先比较后自行登记或改名。", 409)
            files = skill_tree(name, workspace.language)
            for relative, data in files.items():
                workspace._atomic_text(f".agents/skills/{name}/" + relative, data.decode("utf-8"), new=True)
            header, _ = _parse_markdown(files["SKILL.md"].decode("utf-8"), name)
            manifest.setdefault("skills", []).append({"name": name, "version": header["version"], "path": f".agents/skills/{name}/SKILL.md",
                                                      "purpose": workspace._w(purposes[name])})
            added.append(name)
        if added:
            routes = workspace._text("skills/RESOLVER.md").rstrip("\n").splitlines()
            missing = [skill_route(name, workspace.language) for name in added]
            missing = [line for line in missing if line not in routes]
            anchor = next((index for index, line in enumerate(routes) if "/ember-project/SKILL.md" in line), len(routes) - 1)
            routes[anchor + 1:anchor + 1] = missing
            workspace._write_json("skills/manifest.json", manifest)
            workspace._atomic_text("skills/RESOLVER.md", "\n".join(routes) + "\n")
        verify_workspace_contract(workspace)
        return {"added": added, "already_present": present}


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
            init_route, init_root_route = init_routes(workspace.language)
            if init_route in workspace._text("skills/RESOLVER.md") or init_root_route in workspace._text("RESOLVER.md"):
                raise WorkspaceError("初始化 Skill 已清理，但路由尚未更新。")
        else:
            names.insert(0, "ember-init")
            required += [".agents/skills/ember-init/SKILL.md", ".agents/skills/ember-init/scripts/bootstrap.py"]
        registered = {item.get("name") for item in manifest.get("skills", []) if isinstance(item, dict)}
        for name in OPTIONAL_SKILLS:
            if name in registered:
                names.append(name)
                required.append(f".agents/skills/{name}/SKILL.md")
        for name in required:
            path = workspace._safe(name, exists=True)
            if not path.is_file() or not path.stat().st_size:
                raise WorkspaceError(f"初始化契约缺失或为空：{name}")
        for name in names:
            if not any(item.get("name") == name and item.get("path") == f".agents/skills/{name}/SKILL.md" for item in manifest.get("skills", []) if isinstance(item, dict)):
                raise WorkspaceError(f"Skill 注册信息不完整：{name}")
        return {"version": __version__, "contract_files": len(required), "skills": names}
