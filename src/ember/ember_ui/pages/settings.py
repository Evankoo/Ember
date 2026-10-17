"""设置: the page shell (head, actions, section links) and the Skills module (summary, shared
dependency groups, category rail, search and issue filter, rows). ember_ui/static/settings.js
filters the Skills list. Sections each edition owns (execution software, health, catalogs) are
passed in as markup. render(page) returns markup only. Keys (optional ones may be omitted):

  intro            the sentence under the title
  actions_html     controls in the head
  nav              [{href, label, attrs: [(name, value)]}] section links
  execution_html, health_html, modules_html   edition sections, in that order around the Skills module
  skills           {snapshot, summary, dependencies: {note, groups: [{profile, title, guidance, detail,
                    count}]}, categories: [{key, label, count, note}], rows: [{name, display_name,
                    description, category, category_label, profile, state, state_label,
                    details: [(label, value)]}]}
"""
from __future__ import annotations

import html

from .task_detail import _attrs

ISSUE_STATES = ("needs-config", "unavailable", "unverified")


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def head(page: dict) -> str:
    links = "".join(f'<a href="{_esc(link["href"])}"{_attrs(link.get("attrs"))}>{html.escape(link["label"])}</a>' for link in page.get("nav", ()))
    return (
        f'<header class="settings-hub-head"><div><h1>设置</h1><p>{html.escape(page.get("intro", ""))}</p></div><div class="settings-hub-actions">{page.get("actions_html", "")}</div></header>\n    '
        f'<nav class="settings-section-nav" aria-label="设置页内导航">{links}</nav>'
    )


def _row(row: dict) -> str:
    details = "".join(f'<span>{html.escape(label)} <code>{html.escape(value)}</code></span>' if label else f"<span>{html.escape(value)}</span>" for label, value in row.get("details", ()))
    search = " ".join((row["name"], row["display_name"], row["category_label"], row["description"])).lower()
    return (
        f'<details class="compact-skill-row" data-compact-skill data-skill-category="{_esc(row["category"])}" data-skill-profile="{_esc(row["profile"])}" data-skill-state="{_esc(row["state"])}" data-skill-search="{_esc(search)}">'
        f'<summary><span class="setting-identity"><strong>{html.escape(row["display_name"])}</strong><small>{html.escape(row["description"])}</small></span><span class="setting-category">{html.escape(row["category_label"])}</span>'
        f'<span class="skill-status {_esc(row["state"])}">{html.escape(row["state_label"])}</span><span class="skill-detail-toggle"><span>登记信息</span><span>收起</span></span></summary>'
        f'<div class="compact-skill-detail">{details}</div></details>'
    )


def skills(data: dict) -> str:
    rows = data.get("rows", [])
    dependencies = data.get("dependencies") or {}
    groups = dependencies.get("groups", ())
    dependency_html = (
        f'<div class="settings-dependency-summary"><div class="settings-dependency-heading"><strong>{len(groups)} 组共用依赖</strong><small>{html.escape(dependencies.get("note", ""))}</small></div>'
        + "".join(
            f'<article class="settings-dependency-row" data-capability-dependency="{_esc(group["profile"])}" data-capability-skill-count="{int(group["count"])}"><div><strong>{html.escape(group["title"])}<small>{int(group["count"])} 项能力</small></strong>'
            f'<p>{html.escape(group["guidance"])}</p><small>{html.escape(group["detail"])}</small></div>'
            f'<button class="button" type="button" data-skill-profile-filter="{_esc(group["profile"])}" aria-pressed="false">查看这组 {int(group["count"])} 项</button></article>'
            for group in groups
        ) + "</div>"
        if groups else ""
    )
    buttons = [f'<button class="skill-category-button active" type="button" data-skill-category-filter="all" aria-pressed="true"><span>全部 Skills</span><b>{len(rows)}</b></button>']
    buttons += [
        f'<button class="skill-category-button" type="button" data-skill-category-filter="{_esc(category["key"])}" aria-pressed="false"><span>{html.escape(category["label"])}</span><b>{int(category["count"])}</b><small>{html.escape(category["note"])}</small></button>'
        for category in data.get("categories", ())
    ]
    issues = sum(row["state"] in ISSUE_STATES for row in rows)
    snapshot = f' data-capability-snapshot="{_esc(data["snapshot"])}"' if data.get("snapshot") else ""
    return (
        f'<section class="settings-skills-module" id="skills"{snapshot}><div class="settings-skills-head"><div><h2>Skills</h2><p>按分类浏览能力；搜索、待核对和共用依赖筛选只影响列表，不会执行配置。</p></div>'
        f'<div><strong>{len(rows)} 项已登记</strong><span>{html.escape(data.get("summary", ""))}</span></div></div>{dependency_html}'
        f'<div class="settings-skill-workspace"><nav class="skill-category-rail" aria-label="Skill 分类">{"".join(buttons)}</nav><div class="skill-results"><div class="settings-skill-tools">'
        '<input id="compactSkillSearch" type="search" placeholder="搜索 Skill 名称或用途" aria-label="搜索 Skill 名称或用途">'
        f'<button class="skill-issue-filter" id="compactSkillIssueFilter" type="button" aria-pressed="false">只看待核对 {issues}</button><span id="compactSkillCount">{len(rows)} 项</span></div>'
        f'<div class="compact-skill-list" id="compactSkillList">{"".join(_row(row) for row in rows)}</div><div class="library-empty" id="compactSkillEmpty" hidden>没有匹配的 Skill。</div></div></div></section>'
    )


def render(page: dict) -> str:
    return (
        f'<section class="settings-hub paper-management-page">\n    {head(page)}\n    {page.get("execution_html", "")}\n    {page.get("health_html", "")}\n    '
        f'{skills(page.get("skills") or {})}\n    {page.get("modules_html", "")}\n    </section>'
    )
