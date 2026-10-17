"""资料浏览 and the project page's file pane: the file-first material browser (search, project and status
filters, selection for starting work, preview with file actions, a drawer below 1180px).
ember_ui/static/library.js drives it. The materials travel as a JSON data block (not a script);
otherwise these functions return markup only. Keys of `page` (optional ones may be omitted):

  materials      [{kind ("delivery" | "input"), name, relative_path, task_id, task_title, project,
                   project_title, subtype, subtype_label, location, updated_at, previewable, selection, ...}]
  counts         {delivery, input} for the page's kind tabs
  projects       [(slug, label)] for the project filter; project: (slug, label) fixes it instead
  forms          [{kind, action (None: no action), hidden: [(name, value)], label, confirm_label}]
  browser        {csrf, return_to, controller, sync_url} defaults for library.js
"""
from __future__ import annotations

import html
import json

from ..marks import execution_confirm_button


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _forms(forms) -> str:
    result = []
    for index, form in enumerate(forms):
        action = f' method="post" action="{_esc(form["action"])}"' if form.get("action") else ""
        hidden = "".join(f'<input type="hidden" name="{_esc(name)}" value="{_esc(value)}">' for name, value in form.get("hidden", ()))
        result.append(
            f'<form{action} data-library-material-form="{_esc(form["kind"])}" data-execution-confirm data-execution-label="{_esc(form["label"])}"{" hidden" if index else ""}>'
            f'{hidden}{execution_confirm_button(form["confirm_label"], disabled=True)}</form>'
        )
    return "".join(result)


def _browser_attrs(page: dict) -> str:
    browser = page.get("browser") or {}
    return (f' data-library-browser data-csrf="{_esc(browser.get("csrf", ""))}" data-return-to="{_esc(browser.get("return_to", ""))}"'
            f' data-controller="{_esc(browser.get("controller", ""))}" data-sync-url="{"true" if browser.get("sync_url", True) else "false"}"')


def _layout(page: dict) -> str:
    payload = json.dumps(page.get("materials", []), ensure_ascii=False).replace("</", "<\\/")
    return (
        '<div class="library-file-first-layout">'
        '<section class="panel library-material-index"><header class="library-column-head"><div><h2 id="libraryMaterialHeading">交付文件</h2><span class="meta" id="libraryMaterialCount"></span></div>'
        '<button class="button ghost" id="libraryClearSelection" type="button" hidden>清空选择</button></header><div class="library-material-list" id="libraryMaterialList" tabindex="-1"></div>'
        '<footer class="library-selection-bar" id="librarySelectionBar" hidden><div><strong id="librarySelectionCount">已选 0 项</strong><span id="librarySelectionHint">原资料保持只读</span></div>'
        f'{_forms(page.get("forms", ()))}</footer></section>'
        '<section class="panel library-material-preview" id="libraryMaterialPreviewPanel" aria-labelledby="libraryPreviewTitle"><header class="library-column-head"><div class="library-preview-title-block">'
        '<h2 id="libraryPreviewTitle">内容预览</h2><span class="meta" id="libraryPreviewMeta">选择文件后查看内容</span></div><div class="library-preview-head-actions">'
        '<div class="library-preview-toolbar-actions" id="libraryPreviewActions" aria-label="文件操作"></div><button class="library-preview-close" type="button" aria-label="关闭内容预览">×</button></div></header>'
        '<div class="library-source-strip" id="libraryMaterialSource"><span>尚未选择资料。</span></div>'
        '<div class="library-preview-body library-full-preview" id="libraryMaterialPreview"><div class="library-preview-placeholder">从左侧选择文件或输入资料。</div></div></section>'
        '</div><button class="library-preview-backdrop" type="button" aria-label="关闭内容预览" hidden></button>'
        f'<script id="libraryMaterialData" type="application/json">{payload}</script>'
    )


def render(page: dict) -> str:
    """The 资料浏览 page."""
    counts = page.get("counts", {})
    projects = "".join(f'<option value="{_esc(slug)}">{html.escape(label)}</option>' for slug, label in page.get("projects", ()))
    return (
        f'<div class="library-material-page"{_browser_attrs(page)}>'
        '<header class="library-page-head"><div><h1>资料浏览</h1><p>以文件为主浏览交付与输入资料；项目和任务仅作为来源关联。</p></div>'
        '<div class="library-kind-tabs" role="tablist" aria-label="资料类型">'
        f'<button class="active" type="button" role="tab" aria-selected="true" data-library-kind="delivery">交付文件 <span>{int(counts.get("delivery", 0))}</span></button>'
        f'<button type="button" role="tab" aria-selected="false" tabindex="-1" data-library-kind="input">输入资料 <span>{int(counts.get("input", 0))}</span></button></div></header>'
        '<section class="library-file-controls" aria-label="资料筛选"><div class="search-wrap"><span class="search-icon">⌕</span>'
        '<input id="libraryMaterialSearch" type="search" placeholder="搜索文件名、目录、项目或关联任务" aria-label="搜索资料"></div>'
        f'<select id="libraryMaterialProject" aria-label="按项目筛选"><option value="">全部项目</option>{projects}</select><select id="libraryMaterialSubtype" aria-label="按资料状态筛选"></select></section>'
        f'{_layout(page)}</div>'
    )


def pane(page: dict) -> str:
    """The project page's file pane, opened by its 交付文件 / 输入资料 tabs."""
    slug, label = page["project"]
    return (
        f'<div class="project-material-pane library-material-page" data-project-panel="materials" hidden{_browser_attrs(page)}>'
        '<section class="library-file-controls project-material-controls" aria-label="项目资料筛选"><div class="search-wrap"><span class="search-icon">⌕</span>'
        '<input id="libraryMaterialSearch" type="search" placeholder="搜索文件名、目录或关联任务" aria-label="搜索项目资料"></div>'
        f'<select id="libraryMaterialProject" hidden><option value="{_esc(slug)}" selected>{html.escape(label)}</option></select><select id="libraryMaterialSubtype" aria-label="按资料状态筛选"></select></section>'
        f'{_layout(page)}</div>'
    )
