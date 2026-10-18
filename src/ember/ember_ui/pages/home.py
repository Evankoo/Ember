"""Home page: one input that routes a request to a new or existing task, its search results and
content preview, the home execution confirmation, and the browsable list of all tasks.

ember_ui/static/home.js and task-overview.js drive the page once rendered. render(page) takes one
dictionary and returns markup only (no inline script, style or event attribute). Keys (optional
ones may be omitted):

  attention        [(href, text)] shown in the 需要关注 strip
  form             {action (None: no action), hidden: [(name, value)]} of the request form
  task_meta        {task_id: {title, project, status, status_label, updated}} for search rows
  intents          [{pattern, label, href, target}]: a request matching `pattern` (a regular
                   expression) suggests opening another page instead
  configure_href   where 去配置 leads when no execution software is set up
  task_href_base   prefix of a task link ("/tasks/" or "#task/"), used for the preview's detail link
  review_href      fallback link of the preview's detail button
  overview         {rows: [row], projects: [(slug, label)], types: [(key, label)]}; a row is
                   {task_id, title, href, task_line, description, project_slug, project_label,
                    status, status_label, work_type, type_label, updated, search}
"""
from __future__ import annotations

import html
import json

from ..marks import brand_mark_svg

OVERVIEW_BATCH = 50
STATUS_CHOICES = (("all", "全部"), ("active", "进行中"), ("completed", "已完成"), ("waiting_user", "待确认"), ("blocked", "阻塞"))
SEARCH_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>')


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _json_attr(value: object) -> str:
    return _esc(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def attention_strip(items) -> str:
    if not items:
        return ""
    links = "".join(f'<a href="{_esc(href)}">{html.escape(text)}</a>' for href, text in items)
    return f'<div class="attention-strip" role="status"><span class="attention-label">需要关注</span>{links}</div>'


def command_shell(page: dict) -> str:
    form = page.get("form") or {}
    action = f' method="post" action="{_esc(form["action"])}"' if form.get("action") else ""
    hidden = "".join(f'<input type="hidden" name="{_esc(name)}" value="{_esc(value)}">' for name, value in form.get("hidden", ()))
    task_href_base = page.get("task_href_base", "/tasks/")
    return f'''<section class="home-command-shell" aria-labelledby="homeCommandTitle">
      <div class="home-command-heading"><h1 id="homeCommandTitle">想让 <span class="home-command-ai">AI</span> 帮你做什么</h1></div>
      <form class="action-form home-command-form" id="homeCommandForm"{action} autocomplete="off" novalidate data-task-meta="{_json_attr(page.get("task_meta", {}))}" data-intents="{_json_attr(page.get("intents", []))}" data-task-href-base="{_esc(task_href_base)}">
        {hidden}<input type="hidden" id="homeSelectedTaskId" name="task_id" value=""><input type="hidden" id="homeSupplementText" name="user_supplement" value="">
        <div class="home-entry-row">
          <div class="home-entry-main">
            <div class="home-composer" id="homeEntry">
              <textarea id="homeCommandInput" name="request_text" rows="4" placeholder="输入要求，或用 fd 检索 余烬 · Ember 任务与资料…" required></textarea>
              <div class="home-composer-foot">
                <div class="home-input-contexts"><div class="home-context-chip" id="homeContextChip" hidden><span class="home-context-dot" aria-hidden="true"></span><span class="home-context-kind">任务</span><b id="homeContextLabel"></b><button type="button" id="homeContextLink">查看</button><button type="button" id="homeContextClear" aria-label="取消所选任务">×</button></div><div class="home-material-chips" id="homeMaterialChips"></div></div>
                <span class="home-drop-hint">可直接粘贴或拖入文件 · Shift+Enter 换行</span>
              </div>
            </div>
            <div class="home-results" id="homeTaskResults" role="listbox" aria-label="匹配任务与资料，方向键选择，空格预览" hidden></div>
          </div>
          <button class="home-confirm-open ember-action-trigger" id="homeConfirmOpen" type="submit" aria-label="确认 AI 执行" title="确认 AI 执行（Enter）">{brand_mark_svg()}</button>
        </div>
        <div class="home-entry-context"><div class="home-intent-hint" id="homeIntentHint" hidden></div></div>
        <dialog class="paper-dialog home-task-preview-dialog" id="homeTaskPreviewDialog" aria-labelledby="homeTaskPreviewTitle" tabindex="-1">
          <header class="paper-dialog-head home-task-preview-head"><div><span id="homeTaskPreviewKind">内容预览</span><h2 id="homeTaskPreviewTitle">正在读取内容…</h2><p id="homeTaskPreviewMeta"></p></div><button class="home-dialog-close" id="homeTaskPreviewClose" type="button" aria-label="关闭内容预览">×</button></header>
          <div class="paper-reading-pane home-task-preview-body" id="homeTaskPreviewBody"></div>
          <footer class="paper-dialog-foot home-task-preview-foot"><span><kbd>Esc</kbd> 返回搜索结果</span><a class="button ghost" id="homeTaskPreviewDetail" href="{_esc(page.get("review_href", "/review"))}">打开任务详情</a></footer>
        </dialog>
        <dialog class="home-confirm-dialog" id="homeConfirmDialog" aria-labelledby="homeConfirmTitle" tabindex="-1">
          <div class="home-confirm-head"><div><h2 id="homeConfirmTitle">确认执行</h2><p id="homeConfirmTask"></p></div><button class="home-dialog-close" id="homeConfirmClose" type="button" aria-label="关闭确认弹窗">×</button></div>
          <div class="home-confirm-body">
            <div class="home-confirm-workspace">
              <section class="home-prompt-review"><header><span id="homePromptState" class="home-prompt-state">固定提示词</span><small id="homePromptMeta">五段 · 只读</small></header><div class="home-prompt-body article md" id="homePromptPreview"></div></section>
              <div class="home-confirm-decision">
                <section class="home-confirm-task-editor"><div><label for="homeTaskInput">任务</label><small id="homeTaskInputMeta">0 / 4000</small></div><textarea id="homeTaskInput" maxlength="4000" rows="7" placeholder="输入本轮任务提示词"></textarea><button class="link-button" id="homeTaskReset" type="button">恢复默认任务</button></section>
                <fieldset class="home-confirm-routes"><legend>任务路由</legend><label data-home-route-choice><input type="radio" name="route_mode" value="new" checked><span><b>新建任务</b></span></label><label data-home-route-choice><input type="radio" name="route_mode" value="continue"><span><b>继续任务</b></span></label><label data-home-route-choice><input type="radio" name="route_mode" value="derive"><span><b>基于任务新建</b></span></label><p id="homeRouteHelp">建立独立任务上下文</p></fieldset>
                <section class="home-confirm-material-section"><div class="home-confirm-material-head"><span>相关资料 <b id="homeConfirmMaterialCount">0</b></span></div><div class="home-confirm-materials" id="homeConfirmMaterials"></div></section>
              </div>
            </div>
          </div>
          <footer class="execution-confirm-foot home-confirm-foot"><button class="button ghost" id="homePromptCopy" type="button">复制提示词</button><button class="button ghost" id="homeConfirmBack" type="button">返回修改</button><div class="execution-confirm-runner"><span class="execution-confirm-runner-name" id="homeConfirmExecutor" role="status">正在读取设置…</span><a class="button ghost execution-confirm-configure" id="homeConfirmConfigure" href="{_esc(page.get("configure_href", "/settings#execution"))}" hidden>去配置</a><button class="button primary ember-execute-key" id="homeDispatchConfirm" type="button" aria-label="确认执行" title="确认执行" disabled>{brand_mark_svg()}</button></div></footer>
        </dialog>
      </form>
    </section>'''


def task_overview(overview: dict) -> str:
    """The read-only, cross-project task browser; rows past the first batch start hidden."""
    rows = overview.get("rows", [])
    markup = []
    for index, row in enumerate(rows):
        hidden = ' class="hidden"' if index >= OVERVIEW_BATCH else ""
        tag = '<span class="task-group-tag">任务主线</span>' if row.get("task_line") else ""
        description, project = _esc(row["description"]), _esc(row["project_label"])
        markup.append(
            f'<tr{hidden} data-overview-search="{_esc(row["search"])}" data-overview-project="{_esc(row["project_slug"])}" data-overview-type="{_esc(row["work_type"])}" data-overview-status="{_esc(row["status"])}" data-href="{_esc(row["href"])}" tabindex="0"><td class="name"><a class="task-name" href="{_esc(row["href"])}">{html.escape(row["title"])}{tag}</a></td>'
            f'<td class="desc" title="{description}">{description}</td><td class="overview-project" title="{project}">{project}</td>'
            f'<td class="overview-status"><span class="badge {_esc(row["status"])}">{html.escape(row["status_label"])}</span></td>'
            f'<td class="overview-type">{html.escape(row["type_label"])}</td><td class="overview-updated">{html.escape(row["updated"])}</td></tr>'
        )
    projects = "".join(f'<option value="{_esc(slug)}">{html.escape(label)}</option>' for slug, label in overview.get("projects", ()))
    types = "".join(f'<option value="{_esc(key)}">{html.escape(label)}</option>' for key, label in overview.get("types", ()))
    chips = "".join(
        f'<button class="chip{" active" if key == "all" else ""}" type="button" data-overview-status-choice="{key}" aria-pressed="{str(key == "all").lower()}">{label}</button>'
        for key, label in STATUS_CHOICES
    )
    total = len(rows)
    return f'''<section class="home-all-tasks" id="homeAllTasks" aria-labelledby="taskOverviewTitle">
    <div class="task-overview-sticky"><div class="section-head"><div class="task-overview-heading"><h2 id="taskOverviewTitle">全部任务</h2></div><span class="meta" id="taskOverviewCount" role="status" aria-live="polite">显示 {min(OVERVIEW_BATCH, total)} / {total} 条</span></div>
    <div class="task-overview-filters"><div class="search-wrap"><span class="search-icon" aria-hidden="true">{SEARCH_ICON}</span><input id="taskOverviewSearch" type="search" placeholder="搜索任务…" aria-label="搜索任务总览"></div><select id="taskOverviewProject" aria-label="按项目筛选任务总览"><option value="">全部项目</option>{projects}</select><select id="taskOverviewType" aria-label="按类型筛选任务总览"><option value="">全部类型</option>{types}</select></div>
    <div class="task-overview-status-bar"><div class="chips" id="taskOverviewStatus" role="group" aria-label="按状态筛选任务总览">{chips}</div><button id="taskOverviewClear" class="button ghost clear-filters dimmed" type="button">清除筛选</button></div>
    </div>
    <div class="task-overview-scroll" id="taskOverviewScroll"><table class="task-table project-overview-table"><colgroup><col class="overview-name-col"><col class="overview-desc-col"><col class="overview-project-col"><col class="overview-status-col"><col class="overview-type-col"><col class="overview-updated-col"></colgroup><thead><tr><th>任务名称</th><th>任务描述</th><th>项目</th><th>状态</th><th class="overview-type">类型</th><th>更新时间</th></tr></thead><tbody id="taskOverviewRows">{"".join(markup)}</tbody></table>
    <div id="taskOverviewEmpty" class="task-overview-empty" hidden><p>{"没有符合条件的任务" if rows else "还没有任务记录"}</p><button class="button ghost" type="button" data-overview-reset{" hidden" if not rows else ""}>清除筛选</button></div>
    <div id="taskOverviewSentinel" class="task-overview-more"{" hidden" if total <= OVERVIEW_BATCH else ""}><button class="button ghost" id="taskOverviewLoadMore" type="button">显示更多任务</button></div></div></section>'''


def render(page: dict) -> str:
    return attention_strip(page.get("attention")) + command_shell(page) + task_overview(page.get("overview") or {})
