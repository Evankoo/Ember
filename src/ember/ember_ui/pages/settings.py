"""设置: the page shell (head, actions, section links) and the Skills module (summary, shared
dependency groups, category rail, search and issue filter, rows). ember_ui/static/settings.js
filters the Skills list. Sections each edition owns (execution software, health, catalogs) are
passed in as markup. render(page) returns markup only. Keys (optional ones may be omitted):

  intro            optional sentence under the title
  actions_html     controls in the head
  nav              [{href, label, attrs: [(name, value)]}] section links
  execution_html, health_html, modules_html   edition sections, in that order around the Skills module

execution(page) renders the 执行环境 section that ember_ui/static/executor-settings.js drives:
  environment      {executors: [{id, label, kind, path}], default_executor, ready, registry_readable, error}
  config_path      where this machine keeps the list (optional; omitted from normal view)
  form             {action, check_action (both None: the script's hooks save and check),
                    hidden: [(name, value)]}
  copy             optional wording: ready_help, default_hint, save_hint
  compact          optional: a ready saved environment shows name, state and type, with its path
                    and inventory in a collapsed 技术信息 disclosure
  skills           {snapshot, summary, dependencies: {note, groups: [{profile, title, guidance, detail,
                    count}]}, categories: [{key, label, count, note}], rows: [{name, display_name,
                    description, category, category_label, profile, state, state_label,
                    details: [(label, value)]}], browse_collapsed (optional: the full inventory sits
                    in a closed 查看全部 disclosure below the shared-dependency rows)}
"""
from __future__ import annotations

import html
import json

from .task_detail import _attrs

ISSUE_STATES = ("needs-config", "unavailable", "unverified")


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def head(page: dict) -> str:
    links = "".join(f'<a href="{_esc(link["href"])}"{_attrs(link.get("attrs"))}>{html.escape(link["label"])}</a>' for link in page.get("nav", ()))
    intro = str(page.get("intro") or "").strip()
    intro_html = f"<p>{html.escape(intro)}</p>" if intro else ""
    return (
        f'<header class="settings-hub-head"><div><h1>设置</h1>{intro_html}</div><div class="settings-hub-actions">{page.get("actions_html", "")}</div></header>\n    '
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


def _category_button(category: dict) -> str:
    note = str(category.get("note") or "").strip()
    note_html = f"<small>{html.escape(note)}</small>" if note and "无异常" not in note and note != "已登记" else ""
    return (
        f'<button class="skill-category-button" type="button" data-skill-category-filter="{_esc(category["key"])}" aria-pressed="false">'
        f'<span>{html.escape(category["label"])}</span><b>{int(category["count"])}</b>{note_html}</button>'
    )


def skills(data: dict) -> str:
    rows = data.get("rows", [])
    dependencies = data.get("dependencies") or {}
    groups = dependencies.get("groups", ())
    note = str(dependencies.get("note") or "").strip()
    dependency_html = (
        f'<div class="settings-dependency-summary"><div class="settings-dependency-heading"><strong>{len(groups)} 组共用依赖</strong>{f"<small>{html.escape(note)}</small>" if note else ""}</div>'
        + "".join(
            f'<article class="settings-dependency-row" data-capability-dependency="{_esc(group["profile"])}" data-capability-skill-count="{int(group["count"])}"><div><strong>{html.escape(group["title"])}<small>{int(group["count"])} 项</small></strong>'
            f'<small>{html.escape(group["detail"])}</small></div>'
            f'<button class="button" type="button" data-skill-profile-filter="{_esc(group["profile"])}" aria-pressed="false">查看这组 {int(group["count"])} 项</button></article>'
            for group in groups
        ) + "</div>"
        if groups else ""
    )
    buttons = [f'<button class="skill-category-button active" type="button" data-skill-category-filter="all" aria-pressed="true"><span>全部 Skills</span><b>{len(rows)}</b></button>']
    buttons += [_category_button(category) for category in data.get("categories", ())]
    issues = sum(row["state"] in ISSUE_STATES for row in rows)
    snapshot = f' data-capability-snapshot="{_esc(data["snapshot"])}"' if data.get("snapshot") else ""
    workspace = (
        f'<div class="settings-skill-workspace"><nav class="skill-category-rail" aria-label="Skill 分类">{"".join(buttons)}</nav><div class="skill-results"><div class="settings-skill-tools">'
        '<input id="compactSkillSearch" type="search" placeholder="搜索 Skill 名称或用途" aria-label="搜索 Skill 名称或用途">'
        f'<button class="skill-issue-filter" id="compactSkillIssueFilter" type="button" aria-pressed="false">只看待核对 {issues}</button><span id="compactSkillCount">{len(rows)} 项</span></div>'
        f'<div class="compact-skill-list" id="compactSkillList">{"".join(_row(row) for row in rows)}</div><div class="library-empty" id="compactSkillEmpty" hidden>没有匹配的 Skill。</div></div></div>'
    )
    if data.get("browse_collapsed"):
        workspace = f'<details class="settings-skill-browser" id="compactSkillBrowser"><summary>查看全部 {len(rows)} 项 Skills</summary>{workspace}</details>'
    return (
        f'<section class="settings-skills-module" id="skills"{snapshot}><div class="settings-skills-head"><div><h2>Skills</h2></div>'
        f'<div><strong>{len(rows)} 项已登记</strong><span>{html.escape(data.get("summary", ""))}</span></div></div>{dependency_html}'
        f'{workspace}</section>'
    )


EXECUTION_COPY = {
    "ready_help": "",
    "default_hint": "",
    "save_hint": "",
}


def execution(page: dict) -> str:
    saved, copy = page.get("environment") or {}, {**EXECUTION_COPY, **(page.get("copy") or {})}
    entries, default = list(saved.get("executors") or []), str(saved.get("default_executor") or "")
    readable = bool(saved.get("registry_readable", True))
    ready = bool(saved.get("ready")) and readable
    current = next((item for item in entries if item["id"] == default), None)
    state = "saved" if ready else "unavailable" if default or not readable else "empty"
    title = "配置暂不可读" if not readable else "已配置 · 软件路径可用" if ready else "需要修复" if default else "尚未配置"
    name = current["label"] if current else "暂无法读取默认软件" if not readable else "未选择默认软件"
    kind = ("桌面应用" if current["kind"] == "app" else "命令行程序") if current else "未选择"
    path = current["path"] if current else "请先核对本机配置文件。" if not readable else "添加本机软件后，选择一个默认软件。"
    help_text = str(copy["ready_help"] if ready else (saved.get("error") or "添加本机软件，选择默认软件，再检查并保存。")).strip()
    help_html = f"<p>{html.escape(help_text)}</p>" if help_text else ""
    inventory = f"已登记 {len(entries)} 个软件 · 模型和登录由软件管理" if readable else "本机软件清单暂不可读"
    status = "与已保存配置一致；修改后请检查并保存。" if ready else "当前配置暂不可读；请先核对配置文件，未保存任何更改。" if not readable else "添加本机软件 → 选择默认软件 → 检查并保存。"
    badge = "registered" if ready else "unavailable" if state == "unavailable" else "unverified"
    edit_label = "修改配置" if ready else "修复配置" if state == "unavailable" else "开始配置"
    options = '<option value="">请选择本机软件</option>' + "".join(
        f'<option value="{_esc(item["id"])}"{" selected" if item["id"] == default else ""}>{html.escape(item["label"])}</option>' for item in entries)
    form = page.get("form") or {}
    action = f' method="post" action="{_esc(form["action"])}"' if form.get("action") else ""
    check = f' formaction="{_esc(form["check_action"])}"' if form.get("check_action") else ""
    hidden = "".join(f'<input type="hidden" name="{_esc(key)}" value="{_esc(value)}">' for key, value in form.get("hidden", ()))
    registry = _esc(json.dumps(entries, ensure_ascii=False))
    default_hint = str(copy.get("default_hint") or "").strip()
    default_hint_html = f"<small>{html.escape(default_hint)}</small>" if default_hint else ""
    save_hint = str(copy.get("save_hint") or "").strip()
    save_hint_html = f'<p class="executor-editor-hint">{html.escape(save_hint)}</p>' if save_hint else ""
    compact = bool(page.get("compact")) and ready
    if compact:
        # A working saved environment needs no path or inventory on screen; both stay one click away.
        path_html = (f'<div class="executor-current-path"><span>{kind}</span></div>'
                     f'<details class="settings-tech-detail"><summary>技术信息</summary><code>{html.escape(path)}</code><small>{inventory}</small></details>')
        title, inventory_html = "可用", ""
    else:
        path_html = f'<div class="executor-current-path"><span>{kind}</span><code>{html.escape(path)}</code></div>'
        inventory_html = f"<small>{inventory}</small>"
    summary = f'''<div class="executor-current-environment" id="executorCurrentEnvironment" data-environment-state="{state}">
    <div class="executor-current-main"><div class="executor-current-heading"><h3>{html.escape(name)}</h3><span class="skill-status {badge}">{title}</span></div>{path_html}{help_html}</div>
    <div class="executor-current-actions"><button class="button" id="executorSettingsEdit" type="button" aria-controls="executorSettingsEditor" aria-expanded="{"false" if ready else "true"}">{edit_label}</button>{inventory_html}</div></div>'''
    editor = f'''<form class="action-form executor-settings-form" id="executorSettingsForm"{action}>
    {hidden}
    <input type="hidden" name="executors" value="{registry}">
    <div class="executor-editor-section-head"><strong>1 · 添加本机软件</strong><button class="button ghost" id="executorDiscoverSoftware" type="button">自动查找软件</button></div>
    <div class="executor-discovery" id="executorDiscovery" hidden><div class="executor-discovery-head"><small id="executorDiscoveryStatus" role="status" aria-live="polite"></small><button class="button ghost" id="executorDiscoveryClose" type="button">收起</button></div><div id="executorDiscoveryCandidates"></div></div>
    <div class="executor-local-list" id="executorLocalList"></div>
    <div class="executor-add-fields"><label>软件名称<input id="executorSoftwareName" maxlength="80" placeholder="例如：我的 AI 助手"></label><label>软件类型<select id="executorSoftwareKind"><option value="app">桌面应用（.app）</option><option value="command">命令行程序</option></select></label><label>软件路径<input id="executorSoftwarePath" maxlength="4096" spellcheck="false" placeholder="/Applications/软件.app 或可执行文件路径"></label><button class="button ghost" id="executorAddSoftware" type="button">手工添加</button></div>
    <label class="executor-default-field" id="executorDefaultField">2 · 选择默认软件<select name="default_executor" id="executorDefaultSoftware">{options}</select>{default_hint_html}</label>
    <small class="executor-settings-state" id="executorSettingsState" role="status" aria-live="polite" data-state="unchanged">{status}</small>
    <div class="executor-settings-actions"><button class="button ghost" type="submit"{check} data-executor-check>检查软件路径</button><button class="button primary" type="submit" data-executor-save>保存配置</button><button class="button ghost" id="executorSettingsCancel" type="button">取消修改</button></div>
    {save_hint_html}</form>'''
    scope = "" if page.get("compact") else "<span>本机生效</span>"
    return (f'<section class="settings-execution-strip" id="execution"><div class="settings-section-head"><div><h2>执行环境</h2></div>{scope}</div>'
            f'{summary}<div class="executor-settings-editor" id="executorSettingsEditor"{" hidden" if ready else ""}>{editor}</div></section>')


def render(page: dict) -> str:
    return (
        f'<section class="settings-hub paper-management-page">\n    {head(page)}\n    {page.get("execution_html", "")}\n    {page.get("health_html", "")}\n    '
        f'{skills(page.get("skills") or {})}\n    {page.get("modules_html", "")}\n    </section>'
    )
