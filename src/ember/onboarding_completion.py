"""Remove only the official workspace init Skill after explicit final acceptance."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

from .bootstrap import INIT_ROOT_ROUTE, INIT_ROUTE, PACKAGE
from .store import Workspace, WorkspaceError, _now, _tree

INIT = ".agents/skills/ember-init"
PENDING = ".ember/init-skill-removal"
DOCUMENTS = ("skills/manifest.json", "skills/RESOLVER.md", "RESOLVER.md")


def _accepted_task(workspace, task_id):
    task_id = workspace._identifier(task_id, "task_id")
    # _task -> _task_cards -> _verify_inputs verifies every snapshot's owned
    # inputs/<task_id> path, byte size and SHA-256 before we trust its JSON.
    _, task, _ = workspace._task(task_id)
    if (task["project"] != "ember" or task["work_type"] != "system" or task["status"] != "completed"
            or workspace._project("ember")["kind"] != "system"
            or not {"ember", "ember-project"}.issubset(task["skills_used"])):
        raise WorkspaceError("请先完成日常任务与建项目实操，并由用户明确确认安装任务完成。", 409)
    receipts = [item for item in task.get("inputs", {}).get("items", [])
                if item.get("source_locator") == "ember-init:installation-receipt"]
    if len(receipts) != 1 or receipts[0].get("storage") != "snapshot":
        raise WorkspaceError("任务缺少本次安装记录的唯一输入快照。")
    receipt = workspace._json(receipts[0]["path"])
    # A workspace copied by migrate-layout keeps its original installation receipt.
    origins = {str(workspace.path), workspace._json("config/workspace.json", {}).get("migrated_from")}
    if (receipt.get("workspace") not in origins or receipt.get("status") != "ready"
            or receipt.get("system_project_id") != "ember"):
        raise WorkspaceError("安装记录不属于本工作区或尚未安装就绪。")
    return task_id


def validate_completion(workspace, record):
    """A missing init directory alone never counts as deliberate completion."""
    if (not isinstance(record, dict) or set(record) != {"task_id", "completed_at", "removed_skill"}
            or record.get("removed_skill") != INIT or not isinstance(record.get("completed_at"), str)):
        raise WorkspaceError("初始化完成记录不完整。")
    try:
        stamp = datetime.fromisoformat(record["completed_at"])
        if stamp.tzinfo is None:
            raise ValueError
    except ValueError as error:
        raise WorkspaceError("初始化完成时间无效。") from error
    _accepted_task(workspace, record.get("task_id"))


def _official_tree(path, *, complete=True):
    """Refuse edits, extra files (including unknown bytecode), and all links."""
    source = PACKAGE / "skills/ember-init"
    expected = {p.relative_to(source).as_posix(): p.read_bytes() for p in _tree(source)
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    actual = {}
    directories = {str(Path(name).parent) for name in expected}
    directories |= {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}
    for item in _tree(path):
        relative = item.relative_to(path).as_posix()
        if item.is_dir():
            if relative not in directories:
                raise WorkspaceError("初始化 Skill 含额外目录，保留现场，不自动删除。")
        elif relative not in expected or item.read_bytes() != expected[relative]:
            raise WorkspaceError("初始化 Skill 已修改或含额外文件，保留现场，不自动删除。")
        else:
            actual[relative] = expected[relative]
    if complete and actual != expected:
        raise WorkspaceError("初始化 Skill 文件不完整，保留现场，不自动删除。")


def _updated_documents(original, record):
    try:
        manifest = json.loads(original["skills/manifest.json"])
    except (ValueError, KeyError) as error:
        raise WorkspaceError("清理记录中的原始 Skill 注册表无效。") from error
    if not isinstance(manifest, dict) or "onboarding_completion" in manifest or not isinstance(manifest.get("skills"), list):
        raise WorkspaceError("清理记录中的原始 Skill 注册表无效。")
    entries = [item for item in manifest["skills"] if isinstance(item, dict) and item.get("name") == "ember-init"]
    if len(entries) != 1 or entries[0].get("path") != INIT + "/SKILL.md":
        raise WorkspaceError("初始化 Skill 登记不唯一或不完整。")
    manifest["skills"] = [item for item in manifest["skills"] if item not in entries]
    manifest["onboarding_completion"] = record
    updated = {"skills/manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"}
    for name, route in (("skills/RESOLVER.md", INIT_ROUTE), ("RESOLVER.md", INIT_ROOT_ROUTE)):
        lines = original[name].splitlines(keepends=True)
        if sum(line.rstrip("\r\n") == route for line in lines) != 1:
            raise WorkspaceError("初始化 Skill 路由已修改，保留现场，不自动删除。")
        updated[name] = "".join(line for line in lines if line.rstrip("\r\n") != route)
    return updated


def remove_init_skill(workspace, payload):
    """Call through the token-protected server, or hold workspace_lock offline."""
    with workspace._lock:
        workspace._payload(payload)
        if set(payload) != {"task_id", "confirmation"} or payload.get("confirmation") is not True:
            raise WorkspaceError("移除初始化 Skill 需要 task_id 和用户明确确认 confirmation:true。")
        task_id = _accepted_task(workspace, payload.get("task_id"))
        pending = workspace._safe(PENDING)
        journal_path = PENDING + "/transaction.json"
        if pending.is_dir() and not any(pending.iterdir()):
            # A failed journal creation or final rmdir has not left files to remove.
            pending.rmdir()
        if not pending.exists():
            from .bootstrap import verify_workspace_contract
            verify_workspace_contract(workspace)
            manifest = workspace._json("skills/manifest.json")
            if "onboarding_completion" in manifest:
                if manifest["onboarding_completion"]["task_id"] != task_id:
                    raise WorkspaceError("已由另一安装任务完成引导清理。", 409)
                return {"removed": True, "already_removed": True, **manifest["onboarding_completion"]}
            _official_tree(workspace._safe(INIT, exists=True))
            record = {"task_id": task_id, "completed_at": _now(), "removed_skill": INIT}
            original = {name: workspace._text(name) for name in DOCUMENTS}
            _updated_documents(original, record)  # Validate every mutation before staging anything.
            workspace._write_json(journal_path, {"record": record, "original": original}, new=True)
        journal = workspace._json(journal_path)
        if set(journal) != {"record", "original"} or not isinstance(journal["original"], dict) or set(journal["original"]) != set(DOCUMENTS):
            raise WorkspaceError("清理事务记录无效，请保留现场。")
        record, original = journal["record"], journal["original"]
        validate_completion(workspace, record)
        if record["task_id"] != task_id or any(not isinstance(value, str) for value in original.values()):
            raise WorkspaceError("清理事务与当前安装任务不一致。", 409)
        updated = _updated_documents(original, record)
        for name in DOCUMENTS:
            if workspace._text(name) not in (original[name], updated[name]):
                raise WorkspaceError("清理期间登记或路由发生其他修改，请保留现场。", 409)
        if {item.name for item in pending.iterdir()} - {"transaction.json", "skill"}:
            raise WorkspaceError("清理事务目录含额外文件，请保留现场。")
        live, staged = workspace._safe(INIT), workspace._safe(PENDING + "/skill")
        committed = workspace._text("skills/manifest.json") == updated["skills/manifest.json"]
        if live.exists():
            if staged.exists() or committed:
                raise WorkspaceError("清理副本与活动 Skill 状态冲突，请保留现场。")
            _official_tree(live)
            live.rename(staged)
        elif not staged.exists() and not committed:
            raise WorkspaceError("清理副本缺失，拒绝伪造完成记录。")
        if staged.exists():
            _official_tree(staged, complete=not committed)
        try:
            for name in ("RESOLVER.md", "skills/RESOLVER.md", "skills/manifest.json"):
                if workspace._text(name) != updated[name]:
                    workspace._atomic_text(name, updated[name])
            if staged.exists():
                shutil.rmtree(staged)
            workspace._safe(journal_path, exists=True).unlink()
            pending.rmdir()
        except (OSError, WorkspaceError) as error:
            raise WorkspaceError("初始化 Skill 清理尚未完成；原登记与待清理副本保留在 .ember/init-skill-removal，请使用同一任务重试。", 409) from error
        return {"removed": True, "already_removed": False, **record}


def main(argv=None):
    parser = argparse.ArgumentParser(description="用户确认新手引导完成后，仅清理工作区内的官方初始化 Skill")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    try:
        workspace = Workspace(args.workspace)
        from .server import workspace_lock
        with workspace_lock(workspace):
            result = remove_init_skill(workspace, {"task_id": args.task_id, "confirmation": args.confirm})
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (WorkspaceError, OSError, ValueError) as error:
        print(f"初始化 Skill 清理失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
