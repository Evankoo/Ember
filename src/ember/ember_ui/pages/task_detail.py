"""Task detail page: the task narrative on the left, its materials (delivery/input files, divider,
preview, drawer) on the right. ember_ui/static/task-detail.js wires the materials once rendered.

render(page) takes one dictionary and returns markup only; it reads no files, makes no requests and
emits no inline style or script, so every edition can serve it under its own policy. Each edition
builds the dictionary from its own data. Keys (optional ones may be omitted):

  task_id, title, status, status_label, project_title, project_href, updated_label
  parent           {title, href} of the task line this task belongs to
  body_html        the rendered narrative (markdown.markdown_to_html)
  after_body_html  edition block shown after the narrative
  technical        summary texts, e.g. ["Skill …", "执行器 …"]
  log              {entries: [(time, text)], machine_prefixes: [...]}; omitted when the task has none
  related          task line members: [{task_id, title, href, status, status_label}] or {task_id, missing: True}
  heading_tools_html  edition controls placed before the continue action
  continue         control (see control()) whose form submits the continue action
  folder_control   the delivery folder control, shown in the heading when there are no materials
  materials        {delivery, attrs: [(name, value)], input_count, folder_controls: [control],
                    inputs: [{name, preview, meta, control}]}; omitted when the task has no materials
"""
from __future__ import annotations

import html
import re

from ..markdown import inline
from ..marks import execution_confirm_button

LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})(?::\d{2})?(?:[+-]\d{2}:?\d{2})?\s*[：｜|:]\s*(.*)$")


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _attrs(pairs) -> str:
    """Attributes in order; a value of None renders a bare boolean attribute."""
    return "".join(f" {name}" if value is None else f' {name}="{_esc(value)}"' for name, value in pairs or ())


def control(spec: dict) -> str:
    """A button, or a posting form around it when the edition acts through forms.

    spec: {label, class ("button ghost"), disabled, disabled_reason, attrs: [(name, value)],
           form: {action (None: no action), hidden: [(name, value)], attrs: [(name, value)]},
           confirm_label: render the AI execution key instead of a text button}
    """
    css = spec.get("class", "button ghost")
    disabled = " disabled" if spec.get("disabled") else ""
    form = spec.get("form")
    if spec.get("confirm_label"):
        button = execution_confirm_button(spec["confirm_label"])
    else:
        button = f'<button class="{_esc(css)}" type="{"submit" if form else "button"}"{_attrs(spec.get("attrs"))}{disabled}>{_esc(spec["label"])}</button>'
    if form:
        action = f' method="post" action="{_esc(form["action"])}"' if form.get("action") else ""
        hidden = "".join(f'<input type="hidden" name="{_esc(name)}" value="{_esc(value)}">' for name, value in form.get("hidden", ()))
        button = f'<form class="action-form"{action}{_attrs(form.get("attrs"))}>{hidden}{button}</form>'
    reason = spec.get("disabled_reason") if spec.get("disabled") else ""
    if reason:
        return f'<span class="task-folder-disabled" title="{_esc(reason)}">{button}<small>{_esc(reason)}</small></span>'
    return button


def split_log_text(text: str) -> tuple[str, str]:
    """(time, text) of one log entry written as "YYYY-MM-DD HH:MM[:SS][+08:00]：text"."""
    match = LOG_LINE.match(text)
    return (match.group(1).replace("T", " "), match.group(2)) if match else ("", text)


def parse_log_section(section: str) -> list[tuple[str, str]]:
    """Split a Markdown 执行日志 section into (time, text) entries regardless of blank lines or separator style."""
    entries: list[list[str]] = []
    for line in section.splitlines():
        if re.match(r"^#{1,6}\s", line):
            continue
        if re.match(r"^[-*]\s+", line):
            entries.append([re.sub(r"^[-*]\s+", "", line).strip()])
        elif line.strip() and entries:
            entries[-1].append(line.strip())
        elif line.strip():
            entries.append([line.strip()])
    return [split_log_text(" ".join(parts)) for parts in entries]


def execution_log(entries: list[tuple[str, str]], machine_prefixes=()) -> str:
    """The log, newest first as written; consecutive entries from one program writer fold into one row."""
    rows: list[str] = []
    index = 0
    while index < len(entries):
        stamp, text = entries[index]
        prefix = next((value for value in machine_prefixes if text.startswith(value)), "")
        end = index + 1
        while prefix and end < len(entries) and entries[end][1].startswith(prefix):
            end += 1
        time_html = f'<time>{html.escape(stamp)}</time>' if stamp else '<time></time>'
        if end - index > 1:
            items = "".join(f'<li>{inline(item_text)}</li>' for _, item_text in entries[index:end])
            rows.append(
                f'<li class="task-log-entry task-log-machine">{time_html}<details><summary>{html.escape(prefix)} · {end - index} 条</summary><ul>{items}</ul></details></li>'
            )
        else:
            rows.append(f'<li class="task-log-entry{" task-log-machine" if prefix else ""}">{time_html}<div>{inline(text)}</div></li>')
        index = end
    return f'<section class="task-execution-log" aria-label="执行日志"><h3>执行日志</h3><ol class="task-log-list">{"".join(rows)}</ol></section>'


def input_panel(inputs: list[dict]) -> str:
    """Input material rows; a row with `preview` opens in the preview pane."""
    rows = []
    for item in inputs:
        if item.get("preview"):
            name = (f'<button class="task-input-name" type="button" data-task-input-preview="{_esc(item["preview"])}" '
                    f'title="{_esc(item["preview"])}">{html.escape(item["name"])}</button>')
        else:
            name = f'<span class="task-input-name">{html.escape(item["name"])}</span>'
        action = control(item["control"]) if item.get("control") else ""
        rows.append(f'<div class="task-input-row"><span class="task-input-icon">↳</span><div class="task-input-copy">{name}<span>{html.escape(item["meta"])}</span></div>{action}</div>')
    empty = '<div class="task-input-empty">当前任务没有登记输入资料。</div>'
    return (
        '<section class="task-input-panel task-file-pane" id="taskInputPanel" role="tabpanel" aria-labelledby="taskInputTab" hidden>'
        f'<div class="task-input-list">{"".join(rows) if rows else empty}</div></section>'
    )


def _related(related: list[dict]) -> str:
    rows = []
    for item in related:
        if item.get("missing"):
            rows.append(f'<div class="group-related-row missing"><span class="group-related-dot" aria-hidden="true"></span><strong>{html.escape(item["task_id"])}</strong><span class="group-related-status">任务卡缺失</span></div>')
        else:
            rows.append(f'<a class="group-related-row {_esc(item["status"])}" href="{_esc(item["href"])}"><span class="group-related-dot" aria-hidden="true"></span><strong>{html.escape(item["title"])}</strong><span class="group-related-status">{html.escape(item["status_label"])}</span><span class="group-related-arrow" aria-hidden="true">›</span></a>')
    markup = "".join(rows) or '<div class="subtitle">暂无相关任务。</div>'
    return f'<details class="task-group-related" aria-label="相关任务索引"><summary class="task-group-related-head"><strong>相关任务</strong><span>{len(rows)} 项 · 展开</span></summary><div class="task-group-related-list">{markup}</div></details>'


def _materials(page: dict, materials: dict) -> str:
    task_id = page["task_id"]
    attrs = [("data-task-id", task_id), ("data-delivery", materials.get("delivery", "")), *materials.get("attrs", ()), ("data-file-mode", "delivery")]
    controls = "".join(control(item) for item in materials.get("folder_controls", ()))
    loading = "正在读取交付文件…" if materials.get("delivery") else "当前任务没有可读取的交付目录。"
    return (
        '<button class="task-drawer-backdrop" id="taskDrawerBackdrop" type="button" aria-label="关闭任务资料" hidden></button>'
        f'<section class="panel task-delivery-workspace" id="taskDeliveryWorkspace"{_attrs(attrs)}>'
        '<section class="task-delivery-shelf"><header class="task-delivery-head"><div class="task-file-tabs" role="tablist" aria-label="任务文件类型">'
        '<button class="active" id="taskDeliveryTab" type="button" role="tab" aria-selected="true" aria-controls="taskDeliveryFiles" data-task-file-mode="delivery">交付文件 <span id="taskDeliveryCount"></span></button>'
        f'<button id="taskInputTab" type="button" role="tab" aria-selected="false" aria-controls="taskInputPanel" data-task-file-mode="input" tabindex="-1">输入资料 <span>{int(materials.get("input_count", 0))}</span></button></div>'
        '<div class="task-delivery-toolbar"><div class="task-delivery-folder-row"><span class="task-file-selection-status" id="taskFileSelectionStatus"></span></div>'
        f'<div class="task-delivery-action-row">{controls}<div class="task-continue-actions"><div class="task-execution-scope" role="radiogroup" aria-label="执行范围"><input id="taskCreateNew" type="checkbox" hidden>'
        '<button class="active" type="button" role="radio" data-task-scope="current" aria-checked="true">继续任务</button>'
        '<button type="button" role="radio" data-task-scope="new" aria-checked="false" tabindex="-1">所选文件新建</button></div></div>'
        '<button class="task-drawer-close" id="taskDrawerClose" type="button" aria-label="关闭任务资料">×</button></div></div></header>'
        f'<div class="task-delivery-files task-file-pane" id="taskDeliveryFiles" role="tabpanel" aria-labelledby="taskDeliveryTab"><div class="task-preview-empty">{loading}</div></div>'
        f'{input_panel(materials.get("inputs", []))}</section>'
        '<div class="task-detail-divider" id="taskDetailDivider" role="separator" aria-label="调整交付文件区高度" aria-orientation="horizontal" aria-valuemin="130" aria-valuenow="190" tabindex="0"></div>'
        '<section class="task-file-preview-pane"><header class="task-preview-head"><strong id="taskFilePreviewTitle">交付文件预览</strong><div class="task-preview-actions" id="taskFilePreviewActions"></div></header>'
        '<div class="task-file-preview" id="taskFilePreview"><div class="task-preview-empty">选择上方交付文件后在这里预览。</div></div></section>'
        '</section>'
    )


def render(page: dict) -> str:
    materials = page.get("materials")
    continue_control = control(page["continue"]) if page.get("continue") else ""
    if materials:
        lead = '<button class="button ghost task-material-toggle" id="taskMaterialToggle" type="button" aria-controls="taskDeliveryWorkspace" aria-expanded="false">任务资料</button>'
    else:
        lead = control(page["folder_control"]) if page.get("folder_control") else ""
    tools = lead + page.get("heading_tools_html", "") + continue_control
    parent = page.get("parent")
    parent_notice = (
        f'<div class="task-parent-group-return"><a class="button ghost task-parent-group-link" aria-label="返回任务主线" href="{_esc(parent["href"])}"><span aria-hidden="true">←</span> 返回任务主线 · {html.escape(parent["title"])}</a></div>'
        if parent else ""
    )
    technical = page.get("technical")
    technical_html = (
        '<section class="task-technical-info" aria-label="技术信息"><h3>技术信息</h3><p class="task-technical-summary">'
        + "".join(f"<span>{html.escape(text)}</span>" for text in technical) + "</p></section>"
        if technical else ""
    )
    log = page.get("log")
    log_html = execution_log(log["entries"], log.get("machine_prefixes", ())) if log else ""
    related = page.get("related")
    status = page.get("status", "")
    return (
        f'<div class="task-detail-workspace {"has-materials" if materials else "no-materials"}">'
        '<section class="panel task-current-pane">'
        f'<header class="task-current-head"><div class="task-current-title-row"><span class="badge {_esc(status)}">{html.escape(page.get("status_label", status))}</span>'
        f'<h1>{html.escape(page["title"])}</h1><div class="task-current-heading-tools">{tools}</div></div>'
        f'<div class="task-current-meta"><a href="{_esc(page["project_href"])}">{html.escape(page["project_title"])}</a><span class="task-current-meta-separator">·</span>'
        f'<code class="task-current-id" title="{_esc(page["task_id"])}">ID {html.escape(page["task_id"])}</code><span class="task-current-meta-separator">·</span>'
        f'<span class="task-current-updated">最近更新 {html.escape(page["updated_label"])}</span></div></header>{parent_notice}'
        f'<article class="task-current-body article md">{page.get("body_html", "")}{page.get("after_body_html", "")}{technical_html}{log_html}</article>'
        f'{_related(related) if related is not None else ""}'
        '</section>'
        f'{_materials(page, materials) if materials else ""}'
        '</div>'
    )
