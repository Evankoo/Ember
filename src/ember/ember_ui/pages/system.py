"""System workspace page: an AI system shown as an operating surface (health, counts, overview,
locations) above its current and recent tasks. ember_ui/static/system.css and system.js style and
drive it. render(page) takes one dictionary and returns markup only. Keys (optional ones may be
omitted):

  title, eyebrow ("AI SYSTEM"), description_html, focus
  actions          [{href, label}] links before the launcher, e.g. the system's own workbench
  launcher         control (see task_detail.control)
  health           {label, detail}
  stats            {active, lines, records}
  overview, strip  as in project.py
  rows             task rows as in project.py (shown without delivery labels)
  all_tasks        {href, attrs: [(name, value)]} of 查看全部任务
"""
from __future__ import annotations

import html

from . import project
from .task_detail import _attrs, control


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render(page: dict) -> str:
    focus = page.get("focus", "")
    focus_html = f'<div class="system-current-focus"><small>当前重点</small><strong>{html.escape(focus)}</strong></div>' if focus else ""
    actions = "".join(f'<a class="button ghost" href="{_esc(action["href"])}">{html.escape(action["label"])}</a>' for action in page.get("actions", ()))
    launcher = f'<div class="project-task-launcher">{control(page["launcher"])}</div>' if page.get("launcher") else ""
    health, stats = page.get("health", {}), page.get("stats", {})
    all_tasks = page.get("all_tasks", {"href": "/review"})
    return (
        f'<section class="panel system-workspace-hero"><div class="system-hero-copy"><span class="eyebrow">{html.escape(page.get("eyebrow", "AI SYSTEM"))}</span>'
        f'<h1>{html.escape(page["title"])}</h1><div class="system-description">{page.get("description_html", "")}</div>{focus_html}</div>'
        f'<div class="system-hero-action" aria-label="从该系统开始">{actions}{launcher}</div>'
        f'<div class="system-meta-row"><div class="system-health" aria-label="系统健康"><small>健康</small><strong>{html.escape(health.get("label", ""))}</strong><span>{html.escape(health.get("detail", ""))}</span></div>'
        f'<div class="system-stats"><span><b>{int(stats.get("active", 0))}</b>进行中</span><span><b>{int(stats.get("lines", 0))}</b>任务主线</span><span><b>{int(stats.get("records", 0))}</b>全部记录</span></div></div>'
        f'{project.overview(page.get("overview"))}{project.location_strip(page.get("strip"))}</section>\n    '
        '<section class="panel system-task-surface"><header><div><span class="eyebrow">CURRENT WORK</span><h2>当前与近期任务</h2></div><div class="system-task-tools">'
        '<input id="projectTaskSearch" class="project-pane-search" type="search" placeholder="搜索当前任务" aria-label="搜索当前任务">'
        f'<a class="button ghost" href="{_esc(all_tasks["href"])}"{_attrs(all_tasks.get("attrs"))}>查看全部任务</a></div></header>'
        f'<div class="project-task-list system-task-list" id="projectTaskList">{project.task_rows(page.get("rows", []), show_artifacts=False)}</div></section>'
    )
