"""Project workspace page: the project header (focus, counts, overview and timeline, work locations
and entries, location strip), the 任务 / 交付文件 / 输入资料 tabs and the filterable task list.
ember_ui/static/project.js and project.css drive and style it. render(page) takes one dictionary and
returns markup only. Keys (optional ones may be omitted):

  title, eyebrow ("PROJECT"), launcher (control, see task_detail.control), hero_actions_html,
  desc_html, focus, stats {active, groups, completed}
  overview   {state: "ok", layout_id, primary_label, primary_html, timeline_html,
              sections: [{title, html} | {title, entries: [part]}]} or {state: "message", message}
             where a part is {html} or {rows: [{label, environment, value, kind, note, actions_html}]}
  strip      {items: [{label, value, wide, strong}], actions: [{href, label}]}
  counts     {tasks, delivery, input}; task_search_label; has_delivery
  rows       [{task_id, title, href, task_line, description, status, status_label, important, group,
               has_delivery, search}]
  materials_html  the file browser shown by the 交付文件 / 输入资料 tabs
"""
from __future__ import annotations

import html
import re
from urllib.parse import unquote, urlsplit

from ..markdown import inline
from .task_detail import control


def locator_kind(value: str) -> str | None:
    """Classify one literal locator; descriptions never grant arbitrary open actions."""
    if not value or re.search(r"[\x00-\x1f\x7f-\x9f]", value):
        return None
    if value.startswith("/") and not value.startswith("//"):
        return "path"
    if re.search(r"\s|\\", value) or re.search(r"[\x00-\x1f\x7f-\x9f]", unquote(value)):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        parsed.port  # Invalid ports are not browser links.
    except ValueError:
        return None
    return "url"


def entry_parts(markdown: str) -> list[str | list[list[str]]]:
    """Recognize the four-column description table, preserving other Markdown."""
    parts: list[str | list[list[str]]] = []
    prose: list[str] = []
    lines = markdown.splitlines()
    index = 0

    def cells(line: str) -> list[str]:
        if not line.strip().startswith("|") or not line.strip().endswith("|"):
            return []
        return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip()[1:-1])]

    while index < len(lines):
        header = cells(lines[index])
        divider = cells(lines[index + 1]) if index + 1 < len(lines) else []
        if header != ["类型", "环境", "路径或网址", "用途与访问说明"] or len(divider) != 4 or not all(re.fullmatch(r":?-{3,}:?", value.replace(" ", "")) for value in divider):
            prose.append(lines[index])
            index += 1
            continue
        if prose:
            parts.append("\n".join(prose))
            prose = []
        index += 2
        rows: list[list[str]] = []
        while index < len(lines):
            row = cells(lines[index])
            if len(row) != 4:
                break
            locator = row[2]
            if locator.startswith("`") and locator.endswith("`"):
                locator = locator[1:-1]
            else:
                link = re.fullmatch(r"\[[^\]]*\]\(([^\n]+)\)", locator)
                if link:
                    locator = link.group(1)
                    if locator.startswith("<") and locator.endswith(">"):
                        locator = locator[1:-1]
            row[2] = locator
            rows.append(row)
            index += 1
        parts.append(rows)
    if prose:
        parts.append("\n".join(prose))
    return parts


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def entries(parts) -> str:
    """Work locations and entries: readable rows with an exact copy value for real locators."""
    result = []
    for part in parts:
        if "html" in part:
            result.append(part["html"])
            continue
        rows = []
        for row in part["rows"]:
            literal = _esc(row["value"])
            locator = f'<code class="project-entry-locator">{literal}</code>'
            if row.get("kind") == "url":
                locator = f'<a class="project-entry-url" href="{literal}" target="_blank" rel="noopener noreferrer">{locator}</a>'
            actions = (f'<button type="button" class="button ghost" data-project-entry-copy="{literal}" aria-label="复制{_esc(row["label"])}">复制</button>'
                       if row.get("kind") else "") + row.get("actions_html", "")
            rows.append(
                '<div class="project-entry-row">'
                f'<div class="project-entry-label"><strong>{html.escape(row["label"])}</strong><small>{html.escape(row["environment"])}</small></div>'
                f'<div class="project-entry-content">{locator}<div class="project-entry-note">{inline(row["note"])}</div></div>'
                f'<div class="project-entry-actions">{actions}</div></div>'
            )
        result.append(f'<div class="project-entry-list">{"".join(rows)}</div>')
    return "".join(result)


def overview(data) -> str:
    """The project card's overview with its sections on the left and the dated timeline on the right."""
    if not data or data.get("state") != "ok":
        return f'<div class="context-overview-unavailable">{html.escape((data or {}).get("message", ""))}</div>'
    sections = []
    for section in data.get("sections", ()):
        content = entries(section["entries"]) if "entries" in section else section["html"]
        sections.append(f'<section class="project-description-section"><h3>{html.escape(section["title"])}</h3>{content}</section>')
    timeline = data.get("timeline_html", "")
    timeline_html = (
        f'<section class="context-reader-timeline"><h3>时间线</h3><div class="context-overview-copy">{timeline}</div></section>'
        if timeline else '<section class="context-reader-timeline"><h3>时间线</h3><p class="context-reader-empty">暂无有日期意义的变化。</p></section>'
    )
    return (
        f'<section class="context-overview-panel" data-context-layout="{_esc(data.get("layout_id", "context"))}" aria-labelledby="contextOverviewTitle" tabindex="0">'
        f'<section class="context-overview-primary"><h2 id="contextOverviewTitle">{html.escape(data["primary_label"])}</h2>'
        f'<div class="context-overview-copy">{data["primary_html"]}{"".join(sections)}</div></section><hr>{timeline_html}</section>'
    )


def location_strip(strip) -> str:
    items = (strip or {}).get("items", ())
    actions = (strip or {}).get("actions", ())
    if not items and not actions:
        return ""
    item_html = "".join(
        f'<span class="project-location-item{" wide" if item.get("wide") else ""}"><small>{html.escape(item["label"])}</small>'
        + (f'<strong>{html.escape(item["value"])}</strong>' if item.get("strong") else f'<code>{html.escape(item["value"])}</code>') + '</span>'
        for item in items
    )
    action_html = "".join(f'<a class="button ghost" href="{_esc(action["href"])}">{html.escape(action["label"])}</a>' for action in actions)
    return (
        '<div class="project-location-strip" aria-label="项目位置">'
        f'<div class="project-location-items">{item_html}</div>'
        f'<div class="project-location-actions">{action_html}</div></div>'
    )


def hero(page: dict) -> str:
    stats = page.get("stats", {})
    launcher = f'<div class="project-task-launcher">{control(page["launcher"])}</div>' if page.get("launcher") else ""
    focus = page.get("focus", "")
    focus_html = f'<div class="project-current-focus"><small>当前重点</small><strong>{html.escape(focus)}</strong></div>' if focus else ""
    return (
        f'<section class="panel project-intro-card project-workspace-hero"><div class="intro-head"><div><span class="eyebrow">{html.escape(page.get("eyebrow", "PROJECT"))}</span>'
        f'<h1>{html.escape(page["title"])}</h1></div><div class="project-hero-actions">{page.get("hero_actions_html", "")}{launcher}</div></div>'
        f'<div class="intro-desc">{page.get("desc_html", "")}</div><div class="project-hero-summary">{focus_html}<div class="project-hero-stats">'
        f'<span><b>{int(stats.get("active", 0))}</b>进行中</span><span><b>{int(stats.get("groups", 0))}</b>任务主线</span><span><b>{int(stats.get("completed", 0))}</b>已完成</span></div></div>'
        f'{overview(page.get("overview"))}{location_strip(page.get("strip"))}</section>'
    )


def task_rows(rows, *, show_artifacts: bool = True) -> str:
    """The flat, filterable task list; data attributes feed project.js."""
    if not rows:
        return '<div class="project-task-empty">暂无任务。</div>'
    items = []
    for row in rows:
        label = "主线索引" if row.get("group") else ("有交付文件" if row.get("has_delivery") else "无独立交付文件")
        css = "delivery-label has-delivery" if row.get("has_delivery") else "delivery-label"
        badge = f'<span class="{css}">{html.escape(label)}</span>' if show_artifacts else ""
        tag = '<span class="task-group-tag">任务主线</span>' if row.get("task_line") else ""
        items.append(
            f'<article class="project-task-row" data-task-search="{_esc(row["search"])}" data-task-id="{_esc(row["task_id"])}" data-status="{_esc(row["status"])}" '
            f'data-important="{"1" if row.get("important") else "0"}" data-group="{"1" if row.get("group") else "0"}" data-has-delivery="{"1" if row.get("has_delivery") else "0"}">'
            f'<div class="project-task-row-main"><a href="{_esc(row["href"])}">{html.escape(row["title"])}{tag}</a><div class="subtitle">{html.escape(row["description"])}</div></div>'
            f'<div class="project-task-row-meta"><span class="badge {_esc(row["status"])}">{html.escape(row["status_label"])}</span>{badge}</div></article>'
        )
    return "".join(items)


def workspace(page: dict) -> str:
    counts = page.get("counts", {})
    label = page.get("task_search_label", "搜索项目任务")
    has_delivery = page.get("has_delivery", False)
    delivery_filter = ('<span class="filter-separator" aria-hidden="true"></span><button type="button" class="chip" data-task-filter="delivery" aria-pressed="false">有交付文件</button>'
                       if has_delivery else "")
    rows = page.get("rows", [])
    return f'''<nav class="project-workspace-tabs" role="tablist" aria-label="项目工作区">
      <button class="active" type="button" role="tab" aria-selected="true" data-project-view-target="tasks">任务 <span>{int(counts.get("tasks", len(rows)))}</span></button>
      <button type="button" role="tab" aria-selected="false" tabindex="-1" data-project-view-target="delivery" data-library-kind="delivery">交付文件 <span>{int(counts.get("delivery", 0))}</span></button>
      <button type="button" role="tab" aria-selected="false" tabindex="-1" data-project-view-target="input" data-library-kind="input">输入资料 <span>{int(counts.get("input", 0))}</span></button>
    </nav>
    <section class="panel project-workspace">
      <div class="project-workspace-layout">
        <div class="project-task-pane" data-project-panel="tasks">
          <div class="project-pane-head"><div class="project-pane-title"><h2>项目任务</h2><span>{len(rows)}</span></div><div class="project-pane-tools"><input id="projectTaskSearch" class="project-pane-search" type="search" placeholder="{_esc(label)}" aria-label="{_esc(label)}"></div></div>
          <div class="project-task-filters" id="projectTaskFilters" aria-label="任务筛选">
            <button type="button" class="chip active" data-task-filter="all" aria-pressed="true">全部</button>
            <button type="button" class="chip" data-task-filter="important" aria-pressed="false">当前重点</button>
            <button type="button" class="chip" data-task-filter="groups" aria-pressed="false">任务主线</button>
            <button type="button" class="chip" data-task-filter="active" aria-pressed="false">进行中</button>
            <button type="button" class="chip" data-task-filter="completed" aria-pressed="false">已完成</button>
            {delivery_filter}
          </div>
          <div class="project-task-list" id="projectTaskList">
            {task_rows(rows, show_artifacts=has_delivery)}
          </div>
        </div>
        {page.get("materials_html", "")}
      </div>
    </section>'''


def render(page: dict) -> str:
    return hero(page) + "\n    " + workspace(page)
