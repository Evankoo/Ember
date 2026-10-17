"""Page data for the shared interface templates (ember_ui, copied verbatim from the full workbench).

Each function reads this local workspace's snapshot and returns the dictionary a template takes;
the template, not this module, decides the markup. Controls that act on the workspace are plain
buttons handled by app.js; task mutations follow the daily Skill workflow.
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote

from .ember_ui.markdown import markdown_to_html
from datetime import datetime

from .ember_ui.pages import home, library as library_template, project as project_template, projects as projects_template, review as review_template, settings as settings_template, shell as shell_template, system as system_template, task_detail

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
    task_folder = {**_button("打开交付文件夹", ("data-action", "reveal-folder"), ("data-id", ident), ("data-folder", "delivery"), disabled=not outputs),
                   "disabled_reason": "尚无交付文件夹"}
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
            "body_html": markdown_to_html(_body_markdown(task)), "detail_url": task_href(task["id"]),
            "status": task["status"], "has_delivery": bool(task.get("outputs"))}


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


FOUR_COLUMNS = "| 类型 | 环境 | 路径或网址 | 用途与访问说明 |\n| --- | --- | --- | --- |"


def card_sections(markdown: str) -> dict[str, str]:
    """The project card's level-two sections; "" holds the text before the first one."""
    body = re.sub(r"^#\s+.*\n?", "", str(markdown or ""), count=1)
    parts = re.split(r"(?m)^##\s+(.+?)\s*$", body)
    sections = {"": parts[0].strip()}
    for index in range(1, len(parts), 2):
        sections[parts[index]] = (parts[index + 1] if index + 1 < len(parts) else "").strip()
    return sections


def _entry_markdown(markdown: str) -> str:
    """Older cards used a three-column table without the environment; read it as this machine."""
    lines, out, index = markdown.splitlines(), [], 0
    while index < len(lines):
        if re.fullmatch(r"\|\s*类型\s*\|\s*路径或网址\s*\|\s*用途\s*\|\s*", lines[index]) and index + 1 < len(lines):
            out.append(FOUR_COLUMNS)
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", lines[index].strip()[1:-1])]
                out.append(f"| {cells[0]} | 本机 | {cells[1] if len(cells) > 1 else ''} | {cells[2] if len(cells) > 2 else ''} |")
                index += 1
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


def _entry_parts(markdown: str, project: dict) -> list[dict]:
    parts = []
    for part in project_template.entry_parts(_entry_markdown(markdown)):
        if isinstance(part, str):
            parts.append({"html": markdown_to_html(part)})
            continue
        rows = []
        for label, environment, value, note in part:
            kind = project_template.locator_kind(value)
            actions = ""
            if kind == "path" and value in (project.get("locations") or []):
                actions = (f'<button type="button" class="button ghost" data-action="reveal-location" data-id="{html.escape(project["id"], quote=True)}" '
                           f'data-location="{html.escape(value, quote=True)}">打开目录</button>')
            rows.append({"label": label, "environment": environment, "value": value, "kind": kind, "note": note, "actions_html": actions})
        parts.append({"rows": rows})
    return parts


def project_page(snapshot: dict, project_id: str) -> dict | None:
    """The project workspace page; the file tabs are filled by the page's own browser."""
    project = next((item for item in snapshot["projects"] if item["id"] == project_id), None)
    if project is None:
        return None
    system = project.get("kind") == "system"
    entity = "系统" if system else "项目"
    tasks = sorted((item for item in snapshot["tasks"] if item["project"] == project_id),
                   key=lambda item: str(item.get("updated_at") or item.get("date") or ""), reverse=True)
    files = [item for item in snapshot["files"] if item.get("project") == project_id]
    sections = card_sections(project.get("overview") or "")
    primary_label = next((name for name in ("项目总览", "当前概况", "系统总览") if name in sections), "当前概况" if system else "项目总览")
    entry_label = next((name for name in ("工作位置与入口", "系统入口") if name in sections), "")
    primary = markdown_to_html(sections.get(primary_label) or sections.get("") or project.get("description") or "")
    extra = []
    if entry_label and sections.get(entry_label):
        extra.append({"title": entry_label, "entries": _entry_parts(sections[entry_label], project)})
    extra += [{"title": name, "html": markdown_to_html(sections[name])} for name in ("范围与要求", "当前阶段") if sections.get(name)]
    # Older registries kept the timeline in the project registry instead of the card.
    timeline = markdown_to_html(sections["时间线"]) if sections.get("时间线") else "".join(
        ["<ul>"] + [f"<li>{html.escape(str(item.get('date', '')))}：{html.escape(str(item.get('title', '')))}"
                    + (f"。{html.escape(str(item['text']))}" if item.get("text") else "") + "</li>" for item in project.get("timeline") or []] + ["</ul>"]
    ) if project.get("timeline") else ""
    described = sections.get(entry_label, "") if entry_label else ""
    locations = [path for path in project.get("locations") or [] if path not in described]
    return {
        "title": project["name"], "eyebrow": "SYSTEM" if system else "PROJECT",
        "hero_actions_html": f'<button class="button ghost" type="button" data-action="new-task" data-project="{html.escape(project_id, quote=True)}">新建任务</button>',
        "launcher": {"confirm_label": f"开始{entity}任务并确认执行器", "form": {
            "hidden": [("project_id", project_id)], "attrs": [("data-execution-confirm", None), ("data-execution-label", f"开始{entity}任务")]}},
        "focus": project.get("focus") or "",
        "stats": {"active": sum(item["status"] in ("active", "waiting_user", "blocked") for item in tasks),
                  "groups": sum(item.get("kind") == "task_line" for item in tasks),
                  "completed": sum(item["status"] == "completed" for item in tasks)},
        "overview": {"state": "ok", "layout_id": "context", "primary_label": primary_label, "primary_html": primary,
                     "sections": extra, "timeline_html": timeline} if primary else {"state": "message", "message": "项目说明暂无已确认的概览内容。"},
        # As in the full workbench, the strip first names where the description lives: this workspace.
        "strip": {"items": [{"label": "说明正本", "value": "余烬", "strong": True}] + [{"label": "本机工作目录", "value": path, "wide": True} for path in locations], "actions": []},
        "counts": {"tasks": len(tasks), "delivery": sum(item["kind"] in ("draft", "formal") for item in files),
                   "input": sum(item["kind"] == "input" for item in files)},
        "task_search_label": f"搜索{entity}任务", "has_delivery": True,
        "rows": [{"task_id": item["id"], "title": item["title"], "href": task_href(item["id"]), "task_line": item.get("kind") == "task_line",
                  "description": item.get("description") or item.get("goal") or "", "status": item["status"],
                  "status_label": STATUS_NAMES.get(item["status"], item["status"]), "important": bool(item.get("important")),
                  "group": item.get("kind") == "task_line", "has_delivery": bool(item.get("outputs")),
                  "search": " ".join(str(item.get(key) or "") for key in ("title", "description", "goal", "id")).casefold()} for item in tasks],
        "materials_html": library_template.pane({"materials": library_materials(snapshot, project_id), "project": (project_id, project["name"]),
                                                 "forms": LIBRARY_FORMS, "browser": {"sync_url": False, "controller": "GStudioProjectMaterialSwitch"}}),
    }


def system_page(snapshot: dict, project_id: str) -> dict | None:
    """A system registered in this workspace, shown with the full workbench's system workspace layout."""
    page = project_page(snapshot, project_id)
    if page is None:
        return None
    tasks = sorted((item for item in snapshot["tasks"] if item["project"] == project_id),
                   key=lambda item: str(item.get("updated_at") or item.get("date") or ""), reverse=True)
    active = [item for item in tasks if item["status"] in ("active", "waiting_user", "blocked")]
    lines = [item for item in tasks if item.get("kind") == "task_line" and item not in active]
    recent = [item for item in tasks if item["status"] == "completed" and item not in lines][:8]
    visible = {item["id"] for item in (active + lines + recent)[:10]}
    project = next(item for item in snapshot["projects"] if item["id"] == project_id)
    return {
        "title": page["title"], "eyebrow": "AI SYSTEM", "description_html": "", "focus": page["focus"], "actions": [],
        "launcher": page["launcher"],
        "health": {"label": "正常", "detail": "本机工作区可读取"},
        "stats": {"active": len(active), "lines": len(lines), "records": len(tasks)},
        "overview": page["overview"], "strip": page["strip"],
        "rows": [row for row in page["rows"] if row["task_id"] in visible],
        "all_tasks": {"href": "#review", "attrs": [("data-action", "review-project"), ("data-id", project["id"])]},
    }


def render_project(snapshot: dict, project_id: str) -> dict | None:
    """The project page, or the system workspace for a registered system."""
    project = next((item for item in snapshot["projects"] if item["id"] == project_id), None)
    if project is None:
        return None
    if project.get("kind") == "system":
        return {"kind": "system", "html": system_template.render(system_page(snapshot, project_id))}
    return {"kind": "project", "html": project_template.render(project_page(snapshot, project_id))}


def _days_ago(task: dict, now: float) -> float:
    stamp = _epoch(task.get("updated_at") or task.get("date") or "")
    return (now - stamp) / 86400 if stamp else float("inf")


def _project_health(tasks: list[dict], now: float) -> tuple[str, str, str]:
    active = [task for task in tasks if task["status"] == "active"]
    if any(task["status"] == "blocked" for task in tasks):
        return "attention", "需要关注", "有受阻任务"
    if any(task["status"] == "waiting_user" for task in tasks):
        return "waiting", "等待确认", "有任务等待确认"
    if active and sum(_days_ago(task, now) > 21 for task in active) * 2 > len(active):
        return "stalled", "推进放缓", "过半进行中任务超过 21 天未更新"
    return ("normal", "正常推进", "有近期更新") if active else ("normal", "暂无进行中", "当前没有进行中的任务")


def projects_page_data(snapshot: dict) -> dict:
    """项目视图: one card per project plus independent tasks, each with a three-column board."""
    now = datetime.now().timestamp()
    projects, tasks = snapshot["projects"], snapshot["tasks"]
    newest = lambda task: str(task.get("updated_at") or task.get("date") or "")  # noqa: E731
    recent = lambda items, days: [task for task in items if task["status"] == "completed" and _days_ago(task, now) <= days]  # noqa: E731
    row = lambda task: {"task_id": task["id"], "title": task["title"], "href": task_href(task["id"]), "task_line": task.get("kind") == "task_line",  # noqa: E731
                        "return_column": task["status"] if task["status"] in ("active", "completed") else ""}

    def board(items):
        important = [task for task in items if task.get("important")]
        rest = [task for task in sorted(items, key=newest, reverse=True) if not task.get("important")]
        return [{"key": "important", "label": "当前重要事项", "empty": "拖动任务到这里", "rows": [row(task) for task in important]},
                {"key": "active", "label": "进行中", "empty": "无进行中任务", "rows": [row(task) for task in rest if task["status"] == "active"]},
                {"key": "completed", "label": "近 30 天完成", "empty": "近 30 天无完成", "rows": [row(task) for task in recent(rest, 30)]}]

    def review(project_id):
        return {"label": "任务整理", "href": "#review", "attrs": [("data-action", "review-project"), ("data-id", project_id)]}

    cards, attention = [], 0
    for project in projects:
        items = [task for task in tasks if task["project"] == project["id"]]
        key, label, reason = _project_health(items, now)
        attention += key != "normal"
        href = f"#project/{quote(project['id'], safe='')}"
        cards.append({"slug": project["id"], "title": project["name"], "href": href,
                      "category": f"c:{project['category']}" if project.get("category") else "other",
                      "status_key": key, "status_label": label, "focus": project.get("focus") or "暂无明确推进主线",
                      "stats": [(sum(task["status"] == "active" for task in items), "进行中"), (len(recent(items, 7)), "近 7 天完成")],
                      "lines": [f"最近更新 {max((newest(task)[:16] for task in items), default='') or '暂无'}"], "note": f"状态说明：{reason}",
                      "actions": [{"label": "进入项目", "href": href, "primary": True}, review(project["id"])], "columns": board(items)})
    independent = [task for task in tasks if (task["project"] or "independent") == "independent"]
    mainline = max((task for task in independent if task["status"] == "active" and task.get("kind") == "task_line"), key=newest, default=None)
    cards.append({"slug": "independent", "title": "独立任务", "href": "#review", "title_attrs": [("data-action", "review-project"), ("data-id", "independent")],
                  "category": "independent", "independent": True,
                  "focus": mainline["title"] if mainline else "尚未形成任务主线", "focus_href": task_href(mainline["id"]) if mainline else "",
                  "stats": [(sum(task["status"] == "active" for task in independent), "进行中"), (len(recent(independent, 30)), "近 30 天完成")],
                  "note": "独立任务可整理，并逐步形成项目。", "board_label": "独立任务看板",
                  "actions": [{"label": "查看独立任务", "href": "#review", "primary": True, "attrs": [("data-action", "review-project"), ("data-id", "independent")]}, review("independent")],
                  "columns": board(independent)})
    names = list(dict.fromkeys(project["category"] for project in projects if project.get("category")))
    uncategorized = sum(not project.get("category") for project in projects)
    filters = [("all", "全部", len(projects) + 1)] + [(f"c:{name}", name, sum(project.get("category") == name for project in projects)) for name in names]
    if names and uncategorized:
        filters.append(("other", "未分类", uncategorized))
    filters.append(("independent", "独立任务", 1))
    return {"counts": {"projects": len(projects), "active": sum(task["status"] == "active" for task in tasks), "attention": attention},
            "head_actions_html": '<button id="new-project-button" class="button ghost" type="button" data-action="new-project">新建项目</button>',
            "filters": filters, "empty_html": "该分类尚未登记项目。", "cards": cards}


def render_projects(snapshot: dict) -> str:
    return projects_template.render(projects_page_data(snapshot))


def _task_text(task: dict) -> str:
    logs = " ".join(str(log.get("text") or "") for log in task.get("logs") or [])
    return " ".join(str(task.get(key) or "") for key in ("title", "goal", "description", "current", "next", "id")) + " " + logs


def _epoch(value: str) -> int:
    try:
        return int(datetime.fromisoformat(str(value).replace(" ", "T")).timestamp())
    except ValueError:
        return 0


def review_page_data(snapshot: dict) -> dict:
    """任务检视: every task, filter choices and the saved organization reports."""
    projects = {item["id"]: item for item in snapshot["projects"]}
    tasks = sorted(snapshot["tasks"], key=lambda item: str(item.get("updated_at") or item.get("date") or ""), reverse=True)
    used_projects = []
    for task in tasks:
        if task["project"] not in used_projects:
            used_projects.append(task["project"])
    return {
        "stats": {"tasks": len(tasks), "active": sum(task["status"] == "active" for task in tasks), "focus": sum(bool(task.get("important")) for task in tasks)},
        # Open-source only: save the organization result as a report in this workspace.
        "head_html": '<button id="save-report-button" class="button ghost" type="button" data-action="new-report">保存整理报告</button>',
        "form": {"hidden": []},
        "projects": [(slug, _project_name(projects, slug)) for slug in used_projects],
        "types": [(key, label) for key, label in WORK_NAMES.items() if any(task.get("work_type") == key for task in tasks)],
        "statuses": list(STATUS_NAMES.items()),
        "tasks": [{"task_id": task["id"], "title": task["title"], "task_line": task.get("kind") == "task_line", "project": task["project"],
                   "project_label": _project_name(projects, task["project"]), "work_type": task.get("work_type") or "",
                   "type_label": WORK_NAMES.get(task.get("work_type") or "", task.get("work_type") or ""),
                   "status": task["status"], "status_label": STATUS_NAMES.get(task["status"], task["status"]),
                   "updated": str(task.get("updated_at") or task.get("date") or "")[:16] or "未记录",
                   "updated_sort": _epoch(task.get("updated_at") or task.get("date") or ""), "search": _task_text(task)} for task in tasks],
        "finder": {"hidden": [("task_id", "")], "attrs": [("data-task-folder-reveal", None)]},
        "reports": [{"task_id": report["id"], "title": report["title"], "mode": "weekly" if report.get("mode") == "weekly" else "selected",
                     "mode_label": "按周整理" if report.get("mode") == "weekly" else "按任务整理", "status": "completed", "status_label": "已保存",
                     "updated": str(report.get("date") or "")[:16] or "未记录", "missing_report": False} for report in snapshot.get("reports") or []],
    }


def render_review(snapshot: dict) -> str:
    return review_template.render(review_page_data(snapshot))


def review_search(snapshot: dict, query: str, project: str = "", work_type: str = "", status: str = "") -> dict:
    """Tasks matching every word of the query, with the first matching passage as evidence."""
    words = [word.casefold() for word in str(query or "").split()][:12]
    items = []
    for task in snapshot["tasks"]:
        if (project and task["project"] != project) or (work_type and task.get("work_type") != work_type) or (status and task["status"] != status):
            continue
        text = _task_text(task)
        if not words or not all(word in text.casefold() for word in words):
            continue
        in_title = all(word in task["title"].casefold() for word in words)
        evidence = "" if in_title else next((value for value in [task.get("goal"), task.get("description"), task.get("current"), task.get("next")]
                                             + [log.get("text") for log in task.get("logs") or []] if value and words[0] in str(value).casefold()), "")
        items.append({"task_id": task["id"], "score": 2 if in_title else 1, "evidence": str(evidence)[:80]})
    return {"query": query, "items": items}


def report_preview(snapshot: dict, report_id: str) -> dict | None:
    report = next((item for item in snapshot.get("reports") or [] if item["id"] == report_id), None)
    if report is None:
        return None
    return {"report_available": True, "task_id": report["id"], "title": report["title"],
            "mode_label": "按周整理" if report.get("mode") == "weekly" else "按任务整理", "updated_at": str(report.get("date") or "")[:16] or "未记录",
            "status": "completed", "status_label": "已保存", "body_html": markdown_to_html(report.get("content") or ""),
            "detail_url": "#review", "has_delivery": False}


SUBTYPES = {"draft": ("draft", "草稿交付"), "formal": ("final", "正式交付"), "input": ("snapshot", "快照")}
LIBRARY_FORMS = [
    {"kind": "delivery", "hidden": [], "label": "用所选交付文件开始处理", "confirm_label": "核对所选交付文件并开始处理"},
    {"kind": "input", "hidden": [], "label": "用所选输入资料开始处理", "confirm_label": "核对所选输入资料并开始处理"},
]


def library_materials(snapshot: dict, project_id: str = "") -> list[dict]:
    """Registered materials in the full workbench's material record shape, newest first."""
    projects = {item["id"]: item for item in snapshot["projects"]}
    tasks = {item["id"]: item for item in snapshot["tasks"]}
    records = []
    for item in snapshot["files"]:
        if item["kind"] not in SUBTYPES or not item.get("taskId") or (project_id and item.get("project") != project_id):
            continue
        task = tasks.get(item["taskId"], {})
        subtype, subtype_label = SUBTYPES[item["kind"]]
        inside = item["id"].split(f"/{item['taskId']}/", 1)[-1]
        records.append({
            "kind": "input" if item["kind"] == "input" else "delivery", "name": item["name"], "relative_path": inside,
            "task_id": item["taskId"], "task_title": task.get("title", item["taskId"]), "project": item.get("project") or "independent",
            "project_title": _project_name(projects, item.get("project") or ""), "subtype": subtype, "subtype_label": subtype_label,
            "location": item.get("purpose") or ("输入资料" if item["kind"] == "input" else "交付目录"), "purpose": item.get("purpose") or "",
            "source_locator": item["relative_path"], "size": item.get("bytes", 0), "suffix": ("." + item["name"].rsplit(".", 1)[-1].lower()) if "." in item["name"] else "",
            "updated_at": item.get("updated_at") or "", "sort_time": item.get("updated_at") or "", "previewable": True, "selection": {"file_id": item["id"]},
        })
    records.sort(key=lambda record: record["sort_time"], reverse=True)
    return records


def render_library(snapshot: dict) -> str:
    materials = library_materials(snapshot)
    projects = {item["id"]: item for item in snapshot["projects"]}
    used = sorted({record["project"] for record in materials})
    return library_template.render({
        "materials": materials,
        "counts": {"delivery": sum(record["kind"] == "delivery" for record in materials), "input": sum(record["kind"] == "input" for record in materials)},
        "projects": [(slug, _project_name(projects, slug)) for slug in used], "forms": LIBRARY_FORMS, "browser": {"sync_url": True},
    })


SETTINGS_HEALTH = (
    '<section id="health-result" class="settings-health-summary"><div class="settings-health-main"><span class="settings-health-state">服务状态</span>'
    '<small>只在点击“检查服务状态”后检查；不会验证软件登录或调用模型。</small></div></section>'
)


# 执行环境 uses the full workbench's editor; saving and checking go through this package's JSON API (app.js).
EXECUTION_COPY = {"ready_help": "确认执行时可复制提示词并打开这个软件；请在软件中手工粘贴、发送。",
                  "default_hint": "确认执行时“复制并打开”会使用这里保存的软件。",
                  "save_hint": "保存才会更新本机余烬配置；不读取或修改软件的模型、登录和权限。"}


def render_settings(skills: list[dict], environment: dict) -> str:
    """设置: the shared shell, Skills module and 执行环境 editor around this package's health section."""
    scroll = lambda target: [("data-action", "scroll-to"), ("data-id", target)]
    return settings_template.render({
        "intro": "本机执行环境与当前文档库的基础 Skill，在这里查看和管理。",
        "actions_html": '<button class="button" type="button" data-action="check-update">检查更新</button>'
                        '<button id="health-check-button" class="button" type="button" data-action="health-check">检查服务状态</button>',
        "nav": [{"href": "#settings", "label": "执行环境", "attrs": scroll("execution")},
                {"href": "#settings", "label": "Skills", "attrs": scroll("skills")}],
        "execution_html": settings_template.execution({"environment": environment, "config_path": environment.get("config_path", ""), "copy": EXECUTION_COPY}),
        "health_html": SETTINGS_HEALTH,
        "skills": {
            # Registration is not proof that a model is signed in or can run; professional Skills are the user's own.
            "summary": "基础 Skill · 登记不代表模型已登录或能够执行",
            "categories": [{"key": "basic", "label": "基础", "count": len(skills), "note": "已登记"}] if skills else [],
            "rows": [{"name": item["name"], "display_name": item["name"], "description": item.get("purpose") or "已登记基础 Skill",
                      "category": "basic", "category_label": "基础", "profile": "always", "state": "available", "state_label": item.get("version") or "未登记版本",
                      "details": [("登记文件", f".agents/skills/{item['name']}/SKILL.md")]} for item in skills],
        },
    })


# ---------- 页面外壳 ----------
# The document and sidebar come from the full workbench's shell template. The workspace list is filled
# by app.js from render_sidebar(), which takes the favorites the browser keeps for this workspace.
SHARED_SCRIPTS = ("ember-ui", "sidebar", "execution-confirm", "task-detail", "home", "task-overview", "projects", "project",
                  "system", "review", "library", "settings", "executor-settings")
PAGE_STYLES = ("task-detail:task", "projects:projects", "project:project", "system:system", "settings:settings", "executor-settings:settings")
PRIMARY_PAGES = (("home", "任务台"), ("projects", "项目视图"), ("review", "任务检视"), ("library", "资料浏览"), ("settings", "设置"))
CATEGORY_CLASSES = ("account_operations", "course_teaching", "novel_writing", "system_building")
WORKBENCH_DIALOG = ('<dialog id="workbench-dialog" class="paper-dialog workbench-dialog" aria-labelledby="dialog-title">'
                    '<header class="paper-dialog-head"><div><h2 id="dialog-title"></h2></div><button id="dialog-close" class="home-dialog-close" type="button" aria-label="关闭弹窗">×</button></header>'
                    '<div id="dialog-body" class="dialog-body"></div></dialog>')


def render_index() -> str:
    sidebar = shell_template.sidebar({
        "brand": {"href": "#home", "label": "余烬首页", "name": "余烬", "subtitle": "本地工作台"},
        "aside_attrs": [("id", "sidebar"), ("aria-label", "工作台导航")],
        "nav_id": "sidebar-nav", "nav_attrs": [("aria-label", "页面与工作区")],
        "primary": [{"label": label, "href": f"#{key}", "attrs": [("data-nav", key)]} for key, label in PRIMARY_PAGES],
        "workspace_id": "workspace-nav",
        "bottom_html": '<button id="update-button" class="sidebar-update-button" type="button" data-action="check-update"><span aria-hidden="true">↻</span>检查更新</button>',
        "runtime_label": "工作区状态",
        "runtime_html": '<span id="workspace-state" class="machine">正在读取工作区…</span><span id="workspace-version" class="sync-state"></span>',
    })
    styles = [("ember_ui/workbench.css", ())]
    styles += [(f"ember_ui/{name}.css", [("data-page-style", key), ("disabled", None)]) for name, key in (item.split(":") for item in PAGE_STYLES)]
    styles += [("assets/workbench-pages.css", ()), ("app.css", ())]
    return shell_template.document({
        "title": "余烬", "meta": [("color-scheme", "light")], "icon": {"href": "assets/brand.svg", "type": "image/svg+xml"},
        "stylesheets": styles, "sidebar_html": sidebar,
        "sidebar_after_html": '<script src="ember_ui/sidebar-state.js"></script>',
        "main": {"class": "shell app-main", "attrs": [("tabindex", "-1")]},
        "content_html": '<div class="loading-state" role="status">正在读取工作区…</div>',
        "after_main_html": WORKBENCH_DIALOG + shell_template.execution_dialog({"configure_href": "#settings"}),
        "scripts": [{"src": f"ember_ui/{name}.js"} for name in SHARED_SCRIPTS] + [{"src": "app.js"}],
    })


def render_sidebar(snapshot: dict, favorites: list[str]) -> str:
    """The sidebar's workspace list: favorites first, then projects by category (or projects and systems)."""
    projects = snapshot["projects"]
    names = list(dict.fromkeys(project["category"] for project in projects if project.get("category")))
    saved = set(favorites)

    def row(project):
        category = CATEGORY_CLASSES[max(0, names.index(project["category"]) if project.get("category") in names else 0) % len(CATEGORY_CLASSES)]
        kind = "系统" if project.get("kind") == "system" else "项目"
        return {"slug": project["id"], "title": project["name"], "href": f"#project/{quote(project['id'], safe='')}", "category": category,
                "saved": project["id"] in saved, "link_attrs": [("data-project-nav", project["id"]), ("aria-label", f"{kind}：{project['name']}")],
                "button_attrs": [("data-action", "favorite"), ("data-id", project["id"])]}

    if names:
        groups = [(name, [p for p in projects if p.get("category") == name]) for name in names] + [("未分类", [p for p in projects if not p.get("category")])]
    else:
        groups = [("项目", [p for p in projects if p.get("kind") != "system"]), ("系统", [p for p in projects if p.get("kind") == "system"])]
    return shell_template.workspace_nav({
        "favorites": [row(project) for project in projects if project["id"] in saved], "favorites_empty": "点击项目旁的星标收藏",
        "sections": [{"key": name, "label": name, "rows": [row(project) for project in members]} for name, members in groups],
    })

