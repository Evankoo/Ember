"""任务检视: the task list (search, filters, sort, selection for organizing), the task card preview,
and the history of organization reports with its preview; both previews become drawers below 1180px.
ember_ui/static/review.js drives it. render(page) takes one dictionary and returns markup only. Keys
(optional ones may be omitted):

  stats            {tasks, active, focus}
  head_html        edition block in the page head (the full workbench's weekly organization)
  form             {action (None: no action), hidden: [(name, value)]} of the organize form
  projects, types, statuses   [(value, label)] filter choices
  tasks            [{task_id, title, task_line, project, project_label, work_type, type_label,
                     status, status_label, updated, updated_sort, search}]
  group_action     {action, fixed_executor} of 提炼任务主线 for two or more selected tasks
  finder           {action (None: no action), hidden: [(name, value)]} of the preview's folder form
  reports          [{task_id, title, mode ("weekly" | "selected"), mode_label, status, status_label,
                     updated, missing_report}]
  report_tools_html  edition controls beside the report count
"""
from __future__ import annotations

import base64
import html

from ..marks import brand_mark_svg, execution_confirm_button
from .task_detail import _attrs


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _options(choices) -> str:
    return "".join(f'<option value="{_esc(value)}">{html.escape(label)}</option>' for value, label in choices)


def _form_start(form: dict, css: str, extra: str = "") -> str:
    action = f' method="post" action="{_esc(form["action"])}"' if form.get("action") else ""
    hidden = "".join(f'<input type="hidden" name="{_esc(name)}" value="{_esc(value)}">' for name, value in form.get("hidden", ()))
    return f'<form class="{css}"{action}{extra}>{hidden}'


def _task_item(task: dict) -> str:
    title = task["title"]
    search = base64.b64encode(task["search"].lower().encode("utf-8")).decode("ascii")
    tag = '<span class="task-group-tag">任务主线</span>' if task.get("task_line") else ""
    return (
        f'<div class="organize-task-item" data-organize-task data-project="{_esc(task["project"])}" '
        f'data-type="{_esc(task["work_type"])}" data-status="{_esc(task["status"])}" '
        f'data-task-id="{_esc(task["task_id"])}" data-title="{_esc(title.casefold())}" data-updated="{int(task["updated_sort"])}" data-organize-search="{search}">'
        f'<input type="checkbox" name="selected_task_id" value="{_esc(task["task_id"])}" aria-label="选择任务 {_esc(title)}">'
        f'<button class="organize-task-main" type="button" data-organize-preview="{_esc(task["task_id"])}"><span class="organize-task-title-row"><span class="organize-task-title">{html.escape(title)}{tag}</span></span>'
        f'<span class="organize-task-meta">{html.escape(task["project_label"])} · {html.escape(task["type_label"])} · 最近修改 {html.escape(task["updated"])}</span>'
        f'<span class="organize-task-evidence" aria-live="polite"></span></button>'
        f'<span class="badge {_esc(task["status"])}">{html.escape(task["status_label"])}</span></div>'
    )


def _report_item(report: dict) -> str:
    missing = ' · <span class="organization-report-missing">缺少整理报告</span>' if report.get("missing_report") else ""
    return (
        f'<button class="organization-report-item" type="button" data-organization-report="{_esc(report["task_id"])}" data-report-mode="{_esc(report["mode"])}">'
        f'<span><span class="organization-report-title">{html.escape(report["title"])}</span><span class="organization-report-meta">{html.escape(report["mode_label"])} · {html.escape(report["updated"])}{missing}</span></span>'
        f'<span class="badge {_esc(report["status"])}">{html.escape(report["status_label"])}</span></button>'
    )


def _finder(page: dict, form_id: str, label: str) -> str:
    finder = page.get("finder") or {}
    return _form_start(finder, "action-form", f' id="{form_id}" hidden' + _attrs(finder.get("attrs"))) + f'<button class="button" type="submit">{html.escape(label)}</button></form>'


def render(page: dict) -> str:
    stats, tasks, reports = page.get("stats", {}), page.get("tasks", []), page.get("reports", [])
    group = page.get("group_action")
    fixed = f' data-fixed-executor="{_esc(group["fixed_executor"])}"' if group and group.get("fixed_executor") else ""
    group_button = (
        f'<button class="gstudio-action-trigger" id="createOrganizeTaskGroup" type="submit" formaction="{_esc(group["action"])}" data-execution-confirm-trigger{fixed}'
        f' aria-label="提炼任务主线并核对提示词" title="提炼任务主线并核对提示词" hidden disabled>{brand_mark_svg()}</button>'
        if group else ""
    )
    empty = (
        f'<div class="review-task-empty" id="organizeTaskEmpty"{" hidden" if tasks else ""}><strong>{"没有匹配任务" if tasks else "暂无可检视任务"}</strong>'
        f'<span>{"可以调整搜索词或筛选条件。" if tasks else "任务索引同步后会显示在这里。"}</span>'
        f'<button class="button ghost" id="resetReviewSearch" type="button"{" hidden" if not tasks else ""}>重置搜索与筛选</button></div>'
    )
    form = _form_start(page.get("form") or {}, "organize-task-form", ' data-execution-confirm data-execution-label="整理所选任务"')
    organizer = f'''<section class="panel selected-task-organizer"><div class="review-task-head"><div><h2>任务列表</h2><span>{len(tasks)} 项</span></div></div>{form}
      <div class="organize-task-search"><div class="search-wrap"><span class="search-icon" aria-hidden="true">⌕</span><input id="organizeTaskSearch" type="search" placeholder="搜索任务名称、目标、日志或交付线索" aria-label="搜索任务"></div></div>
      <div class="organize-task-filters"><button class="button ghost review-filter-toggle" id="reviewFilterToggle" type="button" aria-expanded="false" aria-controls="reviewFilterFields">筛选 <span id="reviewFilterCount">0</span></button><div class="review-filter-fields" id="reviewFilterFields"><select id="organizeProject" aria-label="按项目筛选"><option value="">全部项目</option>{_options(page.get("projects", ()))}</select><select id="organizeType" aria-label="按任务类型筛选"><option value="">全部任务类型</option>{_options(page.get("types", ()))}</select><select id="organizeStatus" aria-label="按任务状态筛选"><option value="">全部任务状态</option>{_options(page.get("statuses", ()))}</select><button class="button ghost review-filter-reset" id="clearReviewFilters" type="button">重置筛选</button></div><select class="review-sort-control" id="organizeSort" aria-label="任务排序"><option value="recent">最近更新优先</option><option value="oldest">较早更新优先</option><option value="title">按任务名称</option></select></div>
      <div class="library-search-state" id="organizeSearchState" role="status" hidden></div>
      <div class="organize-task-list" id="organizeTaskList">{"".join(_task_item(task) for task in tasks)}{empty}</div>
      <div class="organize-task-footer"><span class="organize-task-count" id="organizeTaskCount">未选择任务</span><div class="organize-task-footer-actions" id="organizeSelectionActions" hidden><button class="button ghost" id="clearOrganizeTasks" type="button">清空选择</button>{group_button}{execution_confirm_button("整理所选任务并核对提示词", disabled=True, css="review-organize-trigger")}</div></div>
    </form></section>'''
    task_preview = (
        '<section class="panel organization-task-preview review-inspector review-responsive-drawer" id="reviewTaskDrawer" data-review-drawer="task"><div class="review-inspector-tabs"><strong>任务卡</strong><button class="review-drawer-close" type="button" data-review-drawer-close aria-label="关闭任务卡">×</button></div>'
        '<div data-review-inspector-panel="task"><div class="organization-preview-placeholder" id="organizationTaskPreviewPlaceholder">点击任务，核对目标、当前判断、执行日志和交付情况。</div>'
        '<div class="organization-preview-content" id="organizationTaskPreviewContent" hidden><div class="organization-preview-head"><div><h2 id="organizationTaskPreviewTitle"></h2><div class="organization-preview-meta" id="organizationTaskPreviewMeta"></div></div><span class="badge" id="organizationTaskPreviewStatus"></span></div>'
        '<div class="organization-preview-body article md" id="organizationTaskPreviewBody"></div><div class="organization-preview-actions"><a class="button ghost" id="organizationTaskPreviewDetail" href="/">查看完整任务详情</a>'
        f'{_finder(page, "organizationTaskPreviewFinder", "在 Finder 打开交付")}</div></div></div></section>'
    )
    no_reports = '<div class="review-task-empty"><strong>暂无整理报告</strong><span>完成一次整理后会在这里保留记录。</span></div>'
    report_rows = "".join(_report_item(report) for report in reports) if reports else no_reports
    report_list = (
        f'<section class="panel organization-report-list-panel"><div class="organization-card-head"><div><h2>历史整理报告</h2><p>查看历次建议、确认结果与验证记录。</p></div><div class="organization-report-tools"><span class="mode-mark">{len(reports)} 份</span>{page.get("report_tools_html", "")}</div></div>'
        '<div class="organization-report-filters" aria-label="筛选历史整理报告"><button class="organization-report-filter active" type="button" data-report-filter="all">全部</button><button class="organization-report-filter" type="button" data-report-filter="weekly">按周</button><button class="organization-report-filter" type="button" data-report-filter="selected">按任务</button></div>'
        f'<div class="organization-report-list" id="organizationReportList">{report_rows}</div></section>'
    )
    report_preview = (
        '<section class="panel organization-report-preview review-responsive-drawer" id="reviewReportDrawer" data-review-drawer="report"><div class="review-inspector-tabs"><strong id="organizationReportPreviewKind">整理报告</strong><button class="review-drawer-close" type="button" data-review-drawer-close aria-label="关闭整理报告">×</button></div>'
        '<div class="organization-preview-placeholder" id="organizationReportPreviewPlaceholder">选择历史报告，即可查看该轮整理的建议、确认结果和验证记录。</div>'
        '<div class="organization-preview-content" id="organizationReportPreviewContent" hidden><div class="organization-preview-head"><div><h2 id="organizationReportPreviewTitle"></h2><div class="organization-preview-meta" id="organizationReportPreviewMeta"></div></div><span class="badge" id="organizationReportPreviewStatus"></span></div>'
        '<div class="organization-preview-body article md" id="organizationReportPreviewBody"></div><div class="organization-preview-actions"><a class="button ghost" id="organizationReportPreviewDetail" href="/">查看整理任务卡</a>'
        f'{_finder(page, "organizationReportPreviewFinder", "在 Finder 打开报告文件夹")}</div></div></section>'
    )
    head = (
        f'<header class="review-page-head" id="taskOrganizationSection"><div class="review-page-heading"><h1>任务检视</h1><p>{int(stats.get("tasks", 0))} 项任务 · {int(stats.get("active", 0))} 项进行中 · {int(stats.get("focus", 0))} 项当前重点</p></div>'
        f'{page.get("head_html", "")}</header>'
    )
    return (
        f'{head}\n    <div class="primary-view-panel" data-weekly-panel="selected"><div class="organization-task-workspace">{organizer}{task_preview}</div></div>'
        f'\n    <section class="review-organization-section"><div class="organization-report-workspace">{report_list}{report_preview}</div></section>'
        '\n    <button class="review-drawer-backdrop" type="button" data-review-drawer-close aria-label="关闭预览" hidden></button>'
    )
