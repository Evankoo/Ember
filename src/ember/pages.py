"""Page data for the shared interface templates (ember_ui, copied verbatim from the full workbench).

Each function reads this local workspace's snapshot and returns the dictionary a template takes;
the template, not this module, decides the markup. Controls that act on the workspace are plain
buttons handled by app.js; only the 任务操作 menu is open-source-only markup.
"""
from __future__ import annotations

import html
from urllib.parse import quote

from .ember_ui.markdown import markdown_to_html
from .ember_ui.pages import home, task_detail

STATUS_NAMES = {"active": "进行中", "waiting_user": "待确认", "blocked": "受阻", "completed": "已完成"}
EXECUTOR_NAMES = {"codex": "Codex", "opencode": "OpenCode", "claude-code": "Claude Code", "workbuddy": "WorkBuddy",
                  "qianwen-office": "千问办公", "doubao-work": "豆包工作", "external": "外部", "manual": "人工"}
# Entries the program writes itself; consecutive ones of the same kind fold into one row.
MACHINE_LOG_KINDS = ("添加输入快照", "添加草稿交付", "登记输入引用")
BODY_SECTIONS = (("任务目标", "goal"), ("任务描述", "description"), ("当前结果", "current"), ("下一步", "next"))
WORK_NAMES = {"text": "文字", "image": "图片", "video": "视频", "audio": "音频", "data": "数据", "mixed": "混合", "system": "系统"}
KIND_NAMES = {"input": "输入资料", "draft": "草稿交付", "formal": "正式交付", "inbox": "收件箱"}
# 任务检视 is the open-source page for organizing tasks; there is no archive center here.
HOME_INTENTS = [{"pattern": "整理|任务主线|合并|拆分", "label": "看起来像任务整理", "href": "#review", "target": "任务检视"}]


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


def _body_markdown(task: dict) -> str:
    return "\n\n".join(f"## {title}\n\n{task[key]}" for title, key in BODY_SECTIONS if str(task.get(key) or "").strip())


def _project_name(projects: dict, project_id: str) -> str:
    project = projects.get(project_id)
    return project["name"] if project else "独立任务"


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
    body = _body_markdown(task)
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


def home_page_data(snapshot: dict) -> dict:
    """The home page: request input, task metadata for search rows, and the 全部任务 browser."""
    projects = {item["id"]: item for item in snapshot["projects"]}
    tasks = sorted(snapshot["tasks"], key=lambda item: str(item.get("updated_at") or item.get("date") or ""), reverse=True)
    rows, project_options = [], {}
    for task in tasks:
        project_label = _project_name(projects, task["project"])
        project_options.setdefault(task["project"], project_label)
        status, work_type = task["status"], task.get("work_type") or ""
        rows.append({
            "task_id": task["id"], "title": task["title"], "href": task_href(task["id"]), "task_line": task.get("kind") == "task_line",
            "description": task.get("description") or task.get("goal") or "", "project_slug": task["project"], "project_label": project_label,
            "status": status, "status_label": STATUS_NAMES.get(status, status), "work_type": work_type,
            "type_label": "任务线" if task.get("kind") == "task_line" else WORK_NAMES.get(work_type, work_type),
            "updated": str(task.get("updated_at") or task.get("date") or "")[:16],
            "search": " ".join(str(value or "") for value in (task["title"], task.get("description"), task.get("goal"), project_label,
                                                             task["project"], task["id"], work_type, status)).lower(),
        })
    return {
        "form": {"hidden": []},
        "task_meta": {row["task_id"]: {"title": row["title"], "project": row["project_label"], "status": row["status"],
                                       "status_label": row["status_label"], "updated": row["updated"] or "未记录"} for row in rows},
        "intents": HOME_INTENTS,
        "configure_href": "#settings", "task_href_base": "#task/", "review_href": "#review",
        "overview": {
            "rows": rows,
            "projects": sorted(((slug, label) for slug, label in project_options.items() if slug), key=lambda item: item[1]),
            "types": [(key, label) for key, label in WORK_NAMES.items() if any(task.get("work_type") == key for task in tasks)],
        },
    }


def render_home(snapshot: dict) -> str:
    return home.render(home_page_data(snapshot))


def home_search(snapshot: dict, query: str) -> dict:
    """Tasks and registered materials matching the query, in the full workbench's result shape."""
    query = " ".join(str(query or "").split())[:160]
    needle = query.casefold()
    if not needle:
        return {"query": "", "items": []}
    projects = {item["id"]: item for item in snapshot["projects"]}
    tasks = {item["id"]: item for item in snapshot["tasks"]}
    results = []
    for task in snapshot["tasks"]:
        fields = [task["title"], task.get("goal"), task.get("description"), task.get("current"), task.get("next"), task["id"]]
        matched = next((str(value) for value in fields if value and needle in str(value).casefold()), None)
        if matched is None:
            continue
        results.append((0 if matched == task["title"] else 1, str(task.get("updated_at") or ""), {
            "kind": "task", "kind_label": "任务", "title": task["title"], "task_id": task["id"],
            "project": _project_name(projects, task["project"]), "status": STATUS_NAMES.get(task["status"], task["status"]),
            "updated": str(task.get("updated_at") or "")[:16] or "未记录", "evidence": "" if matched == task["title"] else matched[:120]}))
    for item in snapshot["files"]:
        if item["kind"] == "inbox" or not item.get("taskId"):
            continue
        fields = [item["name"], item["relative_path"], item.get("purpose")]
        if not any(value and needle in str(value).casefold() for value in fields):
            continue
        owner = tasks.get(item["taskId"], {})
        kind = "input" if item["kind"] == "input" else "delivery"
        results.append((0 if needle in item["name"].casefold() else 1, str(item.get("updated_at") or ""), {
            "kind": kind, "kind_label": "输入" if kind == "input" else "交付", "title": item["name"], "task_id": item["taskId"],
            "related_task": owner.get("title", ""), "project": _project_name(projects, item.get("project") or owner.get("project", "")),
            "subtype": KIND_NAMES.get(item["kind"], item["kind"]), "updated": item.get("updated_at") or "未记录",
            "evidence": f"{KIND_NAMES.get(item['kind'], item['kind'])} · {item['relative_path']}", "purpose": item.get("purpose") or "",
            "source_locator": item["relative_path"], "preview_url": f"api/home/file-preview?id={quote(item['id'], safe='')}",
            "previewable": True, "selection": {"file_id": item["id"]}}))
    # Title matches first, tasks before materials, then the most recently updated.
    results.sort(key=lambda entry: (entry[0], entry[2]["kind"] != "task", "".join(chr(0x10FFFF - ord(char)) for char in entry[1])))
    return {"query": query, "items": [entry[2] for entry in results[:80]]}


def task_preview(snapshot: dict, task_id: str) -> dict | None:
    task = next((item for item in snapshot["tasks"] if item["id"] == task_id), None)
    if task is None:
        return None
    projects = {item["id"]: item for item in snapshot["projects"]}
    return {"task_id": task["id"], "title": task["title"], "project": _project_name(projects, task["project"]),
            "status_label": STATUS_NAMES.get(task["status"], task["status"]), "updated_at": str(task.get("updated_at") or "")[:16] or "未记录",
            "body_html": markdown_to_html(_body_markdown(task)), "detail_url": task_href(task["id"])}


def file_preview(meta: dict) -> dict:
    """A material in the shape the shared preview renderers take; `meta` is Workspace.read_file()."""
    kind = meta.get("preview") or "file"
    data = {"name": meta["name"], "mime": meta.get("media_type", ""), "size": meta.get("bytes", 0), "relative_path": meta["relative_path"],
            "raw_url": f"api/preview?id={quote(meta['id'], safe='')}", "kind": kind}
    if isinstance(meta.get("text"), str):
        markdown_file = meta["name"].lower().endswith((".md", ".markdown"))
        data["kind"] = "markdown" if markdown_file else "text"
        data["body_html"] = markdown_to_html(meta["text"]) if markdown_file else f'<pre class="library-text-preview">{html.escape(meta["text"])}</pre>'
    return data
