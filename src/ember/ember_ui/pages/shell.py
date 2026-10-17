"""Page shell: the document around every page, the sidebar (brand, page links, workspace projects
grouped by category with favorites, bottom status) and the execution confirmation dialog.

ember_ui/static/sidebar-state.js and sidebar.js drive the sidebar; execution-confirm.js drives the
dialog. Each function takes plain data and returns markup; edition-specific modules (scripts, forms,
extra controls) come in through the `*_html` slots and are placed as given.

project_row(row)    row = {slug, title, href, category, active, saved, link_attrs, button_attrs}
workspace_nav(nav)  nav = {favorites: [row], favorites_empty, sections: [{key, label, active, rows,
                    empty_html}]}; a section with no rows shows `empty_html`, or is left out without it
sidebar(page)       page = {brand: {href, label, name, subtitle}, aside_attrs, nav_id, nav_attrs,
                    nav_prefix_html, primary: [{label, href, active, attrs}], workspace_html,
                    workspace_id (wraps the workspace in an element with this id), bottom_html,
                    runtime_label, runtime_html}
execution_dialog(d) d = {default_executor, configure_href}
document(page)      page = {title, icon: {href, type}, meta: [(name, content)], stylesheets:
                    [(href, attrs)], body_class, sidebar_html, sidebar_after_html, main: {class,
                    attrs}, content_html, after_main_html, scripts: [{src} or {html}]}
`attrs` values are [(name, value)]; a value of None writes the bare attribute.
"""
from __future__ import annotations

import html

from ..marks import brand_mark_svg


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _attrs(pairs) -> str:
    return "".join(f" {_esc(name)}" if value is None else f' {_esc(name)}="{_esc(value)}"' for name, value in pairs or ())


def _current(active: bool) -> str:
    return ' aria-current="page"' if active else ""


def project_row(row: dict) -> str:
    title, saved, active = row["title"], bool(row.get("saved")), bool(row.get("active"))
    label = f"{'取消收藏' if saved else '收藏置顶'} · {title}"
    return (f'<div class="sidebar-project-row" data-sidebar-project="{_esc(row["slug"])}" data-favorite="{"0" if saved else "1"}">'
            f'<a class="{"active" if active else ""}" href="{_esc(row["href"])}"{_attrs(row.get("link_attrs"))}{_current(active)}>'
            f'<span class="sidebar-dot {_esc(row.get("category", "other"))}"></span><span class="sidebar-project-title">{html.escape(title)}</span></a>'
            f'<button type="button" class="sidebar-favorite-button {"saved" if saved else ""}"{_attrs(row.get("button_attrs"))} aria-label="{_esc(label)}" aria-pressed="{str(saved).lower()}">{"★" if saved else "☆"}</button></div>')


def workspace_nav(nav: dict) -> str:
    favorites = "".join(project_row(row) for row in nav.get("favorites", ()))
    empty = f'<span class="sidebar-favorites-empty">{html.escape(nav.get("favorites_empty", "点星标收藏"))}</span>'
    parts = ['<details class="sidebar-section sidebar-favorites" data-sidebar-favorites open><summary>收藏项目</summary>'
             f'<div class="sidebar-children">{favorites or empty}</div></details>']
    for section in nav.get("sections", ()):
        rows = "".join(project_row(row) for row in section.get("rows", ())) or section.get("empty_html", "")
        if not rows:
            continue
        parts.append(f'<details class="sidebar-section" data-work-category-section="{_esc(section["key"])}" open>'
                     f'<summary class="{"active" if section.get("active") else ""}">{html.escape(section["label"])}</summary>'
                     f'<div class="sidebar-children">{rows}</div></details>')
    return "".join(parts)


def sidebar(page: dict) -> str:
    brand, nav_id = page.get("brand") or {}, page.get("nav_id", "sidebarNav")
    primary = "".join(
        f'<a class="sidebar-primary {"active" if link.get("active") else ""}" href="{_esc(link["href"])}"{_attrs(link.get("attrs"))}{_current(bool(link.get("active")))}>'
        f'<span class="sidebar-primary-marker" aria-hidden="true">·</span>{html.escape(link["label"])}</a>'
        for link in page.get("primary", ())
    )
    workspace = page.get("workspace_html", "")
    if page.get("workspace_id"):
        workspace = f'<div id="{_esc(page["workspace_id"])}">{workspace}</div>'
    return (f'<aside class="app-sidebar" data-mobile-sidebar{_attrs(page.get("aside_attrs"))}><header class="sidebar-identity">'
            f'<a class="brand" href="{_esc(brand.get("href", "/"))}" aria-label="{_esc(brand.get("label", ""))}">{brand_mark_svg("brand-mark")}'
            f'<span class="brand-copy">{html.escape(brand.get("name", ""))} <span class="brand-subtitle">{html.escape(brand.get("subtitle", ""))}</span></span></a>'
            f'<button class="sidebar-mobile-toggle" type="button" aria-expanded="false" aria-controls="{_esc(nav_id)}">菜单</button></header>'
            f'<nav class="sidebar-nav" id="{_esc(nav_id)}"{_attrs(page.get("nav_attrs"))}><div class="sidebar-nav-main">{page.get("nav_prefix_html", "")}{primary}'
            f'<div class="sidebar-group">工作区</div>{workspace}</div>'
            f'<div class="sidebar-bottom">{page.get("bottom_html", "")}<div class="sidebar-runtime-status" aria-label="{_esc(page.get("runtime_label", "当前状态"))}">{page.get("runtime_html", "")}</div></div>'
            '</nav></aside>')


def execution_dialog(dialog: dict | None = None) -> str:
    dialog = dialog or {}
    default = f' data-default-executor="{_esc(dialog["default_executor"])}"' if dialog.get("default_executor") is not None else ""
    return (f'<dialog class="execution-confirm-dialog" id="executionConfirmDialog" aria-labelledby="executionConfirmTitle"{default}><div class="execution-confirm-shell">'
            '<header class="execution-confirm-head"><div><h2 id="executionConfirmTitle">确认执行</h2><p id="executionConfirmAction">—</p></div><button class="execution-confirm-close" id="executionConfirmClose" type="button" aria-label="关闭">×</button></header>'
            '<div class="execution-confirm-body"><section class="execution-prompt-pane"><div class="execution-confirm-label"><span>固定提示词</span><small id="executionPromptMeta">五段 · 只读</small></div><div class="execution-confirm-prompt markdown-body" id="executionConfirmFixed">正在生成…</div></section>'
            '<aside class="execution-confirm-context"><section class="execution-task-editor"><div class="execution-confirm-label"><label for="executionTaskInput">任务</label><small id="executionTaskMeta">0 / 4000</small></div><textarea id="executionTaskInput" maxlength="4000" rows="8" placeholder="输入本轮任务提示词"></textarea><button class="link-button" id="executionTaskReset" type="button">恢复默认任务</button></section>'
            '<div class="execution-confirm-facts"><div class="execution-confirm-fact"><small>选择范围</small><span id="executionConfirmScope">—</span></div></div></aside></div>'
            '<footer class="execution-confirm-foot"><button class="button ghost" id="executionConfirmCopy" type="button" disabled>复制提示词</button><button class="button ghost" id="executionConfirmBack" type="button">返回修改</button>'
            f'<div class="execution-confirm-runner"><span class="execution-confirm-runner-name" id="executionConfirmExecutor" role="status">正在读取设置…</span><a class="button ghost execution-confirm-configure" id="executionConfirmConfigure" href="{_esc(dialog.get("configure_href", "/settings#execution"))}" hidden>去配置</a>'
            f'<button class="button primary gstudio-execute-key" id="executionConfirmDispatch" type="button" aria-label="确认执行" title="确认执行" disabled>{brand_mark_svg()}</button></div></footer></div></dialog>')


def document(page: dict) -> str:
    icon = page.get("icon") or {}
    meta = "".join(f'<meta name="{_esc(name)}" content="{_esc(content)}">' for name, content in page.get("meta", ()))
    icon_link = f'<link rel="icon" href="{_esc(icon["href"])}"{_attrs([("type", icon["type"])] if icon.get("type") else ())}>' if icon.get("href") else ""
    styles = "".join(f'<link rel="stylesheet" href="{_esc(href)}"{_attrs(attrs)}>' for href, attrs in page.get("stylesheets", ()))
    scripts = "".join(item["html"] if "html" in item else f'<script src="{_esc(item["src"])}"></script>' for item in page.get("scripts", ()))
    body_class = f' class="{_esc(page["body_class"])}"' if page.get("body_class") else ""
    main = page.get("main") or {}
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}'
            f'<title>{html.escape(page.get("title", ""))}</title>{icon_link}{styles}</head><body{body_class}>'
            '<a class="skip-link" href="#main-content">跳到主要内容</a>'
            f'<div class="app-shell">{page.get("sidebar_html", "")}{page.get("sidebar_after_html", "")}'
            f'<main class="{_esc(main.get("class", "shell app-main"))}" id="main-content"{_attrs(main.get("attrs"))}>{page.get("content_html", "")}</main></div>'
            f'{page.get("after_main_html", "")}{scripts}</body></html>')
