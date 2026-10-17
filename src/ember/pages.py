"""Page data for the shared interface templates (ember_ui, copied verbatim from the full workbench).

Each function reads this local workspace's snapshot and returns the dictionary a template takes;
the template, not this module, decides the markup. Controls that act on the workspace are plain
buttons handled by app.js; only the 任务操作 menu is open-source-only markup.
"""
from __future__ import annotations

import html
from urllib.parse import quote

from .ember_ui.markdown import markdown_to_html
from .ember_ui.pages import task_detail

STATUS_NAMES = {"active": "进行中", "waiting_user": "待确认", "blocked": "受阻", "completed": "已完成"}
EXECUTOR_NAMES = {"codex": "Codex", "opencode": "OpenCode", "claude-code": "Claude Code", "workbuddy": "WorkBuddy",
                  "qianwen-office": "千问办公", "doubao-work": "豆包工作", "external": "外部", "manual": "人工"}
# Entries the program writes itself; consecutive ones of the same kind fold into one row.
MACHINE_LOG_KINDS = ("添加输入快照", "添加草稿交付", "登记输入引用")
BODY_SECTIONS = (("任务目标", "goal"), ("任务描述", "description"), ("当前结果", "current"), ("下一步", "next"))


def size_label(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.1f} KB" if n >= 1024 else f"{n or 0} B"


def task_href(task_id: str) -> str:
    return f"#task/{quote(task_id, safe='')}"


def _button(label: str, *attrs: tuple[str, str], disabled: bool = False) -> dict:
    return {"label": label, "attrs": list(attrs), "disabled": disabled}


def _manage_menu(task: dict) -> str:
    """Open-source-only: changes the full workbench leaves to the AI workflow."""
    ident = html.escape(task["id"], quote=True)
    items = []
    if task["status"] != "completed":
        items.append(f'<button type="button" role="menuitem" data-action="edit-task" data-id="{ident}">更新任务记录</button>'
                     f'<button type="button" role="menuitem" data-action="add-material" data-id="{ident}">添加资料</button>')
        items.append(f'<button id="promote-task-button" type="button" role="menuitem" data-action="promote" data-id="{ident}">正式交付并完成</button>'
                     if task.get("artifact_mode") == "delivery" else
                     f'<button id="complete-task-button" type="button" role="menuitem" data-action="complete" data-id="{ident}">完成任务</button>')
    important = bool(task.get("important"))
    items.append(f'<button type="button" role="menuitem" data-action="important" data-id="{ident}" aria-pressed="{str(important).lower()}">{"移出重点" if important else "设为重点"}</button>')
    return (f'<details class="task-manage-menu"><summary class="button ghost" aria-label="任务操作">任务操作</summary>'
            f'<div class="task-manage-list" role="menu">{"".join(items)}</div></details>')


def _log_entries(task: dict) -> list[tuple[str, str]]:
    entries = []
    for log in task.get("logs") or []:
        date, text = str(log.get("date") or ""), str(log.get("text") or "")
        entries.append((date.replace("T", " ")[:16], text) if date else task_detail.split_log_text(text))
    return entries


def task_page(snapshot: dict, task_id: str) -> dict | None:
    """The task detail page data, or None when the task is not in this workspace."""
    tasks = {item["id"]: item for item in snapshot["tasks"]}
    task = tasks.get(task_id)
    if task is None:
        return None
    files = {item["id"]: item for item in snapshot["files"]}
    projects = {item["id"]: item for item in snapshot["projects"]}
    outputs = [files[value] for value in task.get("outputs") or [] if value in files]
    inputs = [files[value] for value in task.get("inputs") or [] if value in files]
    delivery = outputs[0]["kind"] if outputs else ("draft" if task.get("artifact_mode") == "delivery" else "")
    related_tasks = [tasks[value] for value in task.get("related") or [] if value in tasks] if task.get("kind") == "task_line" else []
    project = projects.get(task["project"])
    parent = next((item for item in snapshot["tasks"] if item.get("kind") == "task_line" and task_id in (item.get("related") or [])), None)
    body = "\n\n".join(f"## {title}\n\n{task[key]}" for title, key in BODY_SECTIONS if str(task.get(key) or "").strip())
    ident = task["id"]
    task_folder = _button("打开任务文件夹", ("data-action", "reveal-folder"), ("data-id", ident), ("data-folder", "delivery"), disabled=not outputs)
    has_input_snapshot = any(item["taskId"] == ident and item["kind"] == "input" for item in inputs)
    input_folder = _button("打开输入目录", ("data-action", "reveal-folder"), ("data-id", ident), ("data-folder", "input"), disabled=not has_input_snapshot)
    open_task = task["status"] != "completed"
    has_materials = bool(delivery or inputs or related_tasks)
    logs = _log_entries(task)
    return {
        "task_id": ident, "title": task["title"], "status": task["status"],
        "status_label": STATUS_NAMES.get(task["status"], task["status"]),
        "project_title": project["name"] if project else "独立任务",
        "project_href": f"#project/{quote(task['project'], safe='')}" if project else "#review",
        "updated_label": str(task.get("updated_at") or task.get("date") or "")[:16],
        "parent": {"title": parent["title"], "href": task_href(parent["id"])} if parent else None,
        "body_html": markdown_to_html(body),
        "technical": [f"Skill {'、'.join(task.get('skills_used') or []) or '未记录'}",
                      f"执行器 {EXECUTOR_NAMES.get(task.get('executor') or '', task.get('executor') or '未记录')}"],
        "log": {"entries": logs, "machine_prefixes": MACHINE_LOG_KINDS} if logs else None,
        "related": [{"task_id": item["id"], "title": item["title"], "href": task_href(item["id"]), "status": item["status"],
                     "status_label": STATUS_NAMES.get(item["status"], item["status"])} for item in related_tasks] if task.get("kind") == "task_line" else None,
        "heading_tools_html": _manage_menu(task),
        "continue": {"confirm_label": "核对提示词并继续任务" if open_task else "基于已完成任务新建", "form": {
            "hidden": [("task_id", ident)],
            "attrs": [("data-task-continue-form", None), ("data-execution-confirm", None),
                      ("data-execution-label", "继续当前任务" if open_task else "基于已完成任务新建")]}},
        "folder_control": task_folder,
        "materials": {
            "delivery": delivery,
            "input_count": len(inputs),
            "folder_controls": [input_folder, task_folder],
            # Input rows carry the file ID, which the page's preview adapter resolves.
            "inputs": [{"name": item["name"], "preview": item["id"],
                        "meta": f"{'快照' if item['taskId'] == ident and item['kind'] == 'input' else '引用'} · {size_label(item['bytes'])}"
                                + (f" · {item['purpose']}" if item.get("purpose") else ""),
                        "control": _button("Finder", ("data-action", "reveal"), ("data-id", item["id"]), ("data-mode", "reveal"))}
                       for item in inputs],
        } if has_materials else None,
    }


def render_task(snapshot: dict, task_id: str) -> str | None:
    page = task_page(snapshot, task_id)
    return None if page is None else task_detail.render(page)
