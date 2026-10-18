"""Page presenters; data and action helpers supplied by the runtime."""
from __future__ import annotations
from .runtime.ember_compat import env as ember_env
from .. import ember_workbench as runtime

def _context_current_markdown(value: str, *, project: bool = False) -> str:
    """Return only EBrain 2.0's reader-facing current projection."""
    text = str(value or "").strip()
    managed = runtime._context_managed_block(
        text, "context-project-narrative" if project else "context-compiled"
    )
    if managed:
        text = managed
    text = runtime.re.sub(
        r"<!--\s*ebrain:context-(?:project-evidence|compiled-evidence):begin\s*-->.*?"
        r"<!--\s*ebrain:context-(?:project-evidence|compiled-evidence):end\s*-->",
        "", text, flags=runtime.re.DOTALL,
    )
    text = runtime.re.sub(r"<!--.*?-->", "", text, flags=runtime.re.DOTALL)
    return runtime.re.sub(r"\n{3,}", "\n\n", text).strip()


def _context_timeline_markdown(value: str) -> str:
    return runtime._context_managed_block(value, "context-timeline")


def _viewer_markdown_html(markdown: str, task_id: str, delivery_key: str, relative_path: str) -> str:
    """Render Markdown and turn safe local links into in-viewer navigation."""
    links: list[str] = []
    base = runtime.Path(relative_path).parent

    def replace_link(match: runtime.re.Match[str]) -> str:
        label, target = match.group(1), runtime.html.unescape(match.group(2)).strip().strip("<>")
        marker = f"GSTUDIOLINKTOKEN{len(links)}END"
        if runtime.re.match(r"^https?://", target, runtime.re.I):
            anchor = f'<a href="{runtime.html.escape(target, quote=True)}" target="_blank" rel="noreferrer">{runtime.html.escape(label)}</a>'
        else:
            local = (base / target).as_posix()
            resolved = runtime.library_delivery_path(task_id, delivery_key, local)
            if resolved:
                anchor = f'<button class="library-inline-link" type="button" data-library-relative="{runtime.html.escape(local, quote=True)}">{runtime.html.escape(label)}</button>'
            else:
                anchor = f'<span class="library-broken-link" title="目标不存在">{runtime.html.escape(label)}</span>'
        links.append(anchor)
        return marker

    tokenized = runtime.re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", replace_link, markdown)
    rendered = runtime.markdown_to_html(tokenized)
    for index, anchor in enumerate(links):
        rendered = rendered.replace(f"GSTUDIOLINKTOKEN{index}END", anchor)
    return rendered


def markdown_for_html(markdown: str) -> str:
    """Hide source-only navigation blocks without changing the Markdown file."""
    lines = markdown.splitlines()
    visible: list[str] = []
    hiding_navigation = False
    for line in lines:
        heading = runtime.re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            title = heading.group(2).strip().lower()
            if title in {"quick navigation", "快速导航"}:
                hiding_navigation = True
                continue
            if hiding_navigation and len(heading.group(1)) <= 2:
                hiding_navigation = False
        if hiding_navigation:
            continue
        if runtime.re.match(r"^\s*[-*]\s+\[任务文件夹\s*-\s*(?:MacBook Pro|Mac mini)\]", line, runtime.re.I):
            continue
        visible.append(line)
    return "\n".join(visible)


def render_status_page(title: str, heading: str, detail: str, token: str) -> str:
    """Render a shared-layout status page for 404/500 responses."""
    content = (
        '<section class="panel card status-page">'
        f"<h1>{runtime.html.escape(heading)}</h1>"
        f'<p class="subtitle">{runtime.html.escape(detail)}</p>'
        '<p><a class="button" href="/">返回任务台</a></p></section>'
    )
    return runtime._layout(title, content, token)


def render_weekly(token: str, notice: str = "", error: str = "", *, mode: str = "", review_view: str = "", panel: str = "") -> str:
    """Render the combined task-review and organization workspace."""
    today = runtime.weekly_task_review.review_day(runtime.datetime.date.today())
    weekly_view = runtime.weekly_task_review.load_weekly_view(today)
    report_records = runtime.organization_report_records(resolve_reports=False)
    weekly_task = runtime.weekly_organization_task(report_records, str(weekly_view.get("week") or ""))
    status = weekly_view.get("status") if isinstance(weekly_view.get("status"), dict) else {}
    state = str(status.get("state") or "scheduled")
    task_status = str(weekly_task.get("status") or "") if weekly_task else ""
    if task_status == "completed" or (not weekly_task and state == "completed"):
        completed_at = weekly_task.get("updated_at") if weekly_task else status.get("completed_at")
        weekly_state = f'本轮整理已完成 · {runtime.html.escape(str(weekly_view.get("round_id") or ""))} · {runtime.html.escape(runtime.format_display_time(completed_at))}'
        task_link = (
            f'<a class="button ghost" href="/tasks/{runtime.quote(str(weekly_task.get("task_id") or ""))}">查看整理任务</a>'
            if weekly_task else ""
        )
        weekly_action = task_link + runtime.weekly_action_menu(token, completed=True, return_to="/review#taskOrganizationSection")
    elif weekly_task:
        task_label = runtime.STATUS_LABEL.get(task_status, task_status or "进行中")
        weekly_state = f'本轮整理{runtime.html.escape(task_label)} · {runtime.html.escape(str(weekly_view.get("round_id") or ""))} · {runtime.html.escape(runtime.format_display_time(weekly_task.get("updated_at")))}'
        weekly_action = f'<a class="button ghost" href="/tasks/{runtime.quote(str(weekly_task.get("task_id") or ""))}">查看整理任务</a>'
    elif state == "scheduled":
        weekly_state = "等待周一 09:00 · 系统将生成上一完整自然周建议"
        weekly_action = ""
    else:
        weekly_state = f'等待整理 · 可开始整理 · {runtime.html.escape(str(weekly_view.get("round_id") or ""))} · 建议已生成'
        weekly_action = runtime._organization_form(token, "weekly")

    projects = runtime.project_items()
    view_state = runtime.review_view_state()
    records = runtime.launcher_task_records(runtime.collect_records())
    focus_ids = {str(value) for value in view_state.get("focus_task_ids", [])}
    tasks = []
    for record in records:
        task_id = str(record.get("task_id") or "")
        project = str(record.get("project") or "")
        work_type = str(record.get("work_type") or "")
        status_name = str(record.get("status") or "")
        tasks.append({
            "task_id": task_id, "title": str(record.get("task_name") or record.get("title") or task_id),
            "task_line": bool(runtime.task_group_tag(record)), "project": project,
            "project_label": str(record.get("project_title") or projects.get(project, {}).get("title") or project),
            "work_type": work_type, "type_label": runtime.TYPE_LABEL.get(work_type, work_type),
            "status": status_name, "status_label": runtime.STATUS_LABEL.get(status_name, status_name),
            "updated": runtime.format_display_time(record.get("updated_at")) or "未记录",
            "updated_sort": int(runtime.parse_sort_datetime(str(record.get("updated_at") or "")).timestamp()),
            "search": runtime.task_search_summary(record),
        })
    project_slugs = {str(record.get("project") or "") for record in records}
    ordered_slugs = [slug for slug in runtime.formal_project_slugs() if slug in project_slugs]
    ordered_slugs.extend(sorted(project_slugs - set(ordered_slugs)))
    reports = []
    for record in report_records:
        mode = str(record.get("organization_mode") or "")
        status_name = str(record.get("status") or "")
        reports.append({
            "task_id": str(record.get("task_id") or ""), "title": str(record.get("task_name") or record.get("title") or record.get("task_id") or ""),
            "mode": "weekly" if mode == "weekly" else "selected", "mode_label": "按周整理" if mode == "weekly" else "按任务整理",
            "status": status_name, "status_label": runtime.STATUS_LABEL.get(status_name, status_name),
            "updated": runtime.format_display_time(record.get("updated_at")) or "未记录", "missing_report": not record.get("report_path"),
        })
    index_link = runtime._form('/actions/open-organization-center', token, {'return_to':'/review?mode=weekly'}, '整理规则与索引', css='button ghost') if runtime.ember_organization.INDEX_PATH.exists() else '<span class="badge waiting_user">首次整理后生成索引</span>'
    page = {
        "stats": {"tasks": len(records), "active": sum(1 for record in records if str(record.get("status") or "") == "active"), "focus": len(focus_ids)},
        "head_html": f'<div class="review-weekly-summary"><span class="review-weekly-label">上周整理</span><div class="weekly-state">{weekly_state}</div>{weekly_action}</div>',
        "form": {"action": "/actions/organize-selected-tasks", "hidden": [("csrf", token), ("return_to", "/review")]},
        "projects": [(slug, runtime.task_scope_title(slug)) for slug in ordered_slugs if slug],
        "types": [(key, label) for key, label in runtime.TYPE_LABEL.items() if any(str(record.get("work_type") or "") == key for record in records)],
        "statuses": list(runtime.STATUS_LABEL.items()),
        "tasks": tasks,
        "group_action": {"action": "/actions/create-task-group-from-selection", "fixed_executor": "codex"},
        "finder": {"action": "/actions/open-folder", "hidden": [("csrf", token), ("task_id", ""), ("return_to", "/review")]},
        "reports": reports, "report_tools_html": index_link,
    }
    content = runtime.flash_message(notice, error) + runtime.review_page.render(page) + f'<script src="/assets/review.js?v={runtime.REVIEW_VERSION}"></script>'
    return runtime._layout("任务检视", content, token)


def render_executors(
    token: str,
    section: str = "executors",
    notice: str = "",
    error: str = "",
) -> str:
    if section == "skills":
        return runtime._render_skills_settings(token, notice, error)
    if section != "executors":
        raise ValueError("不支持的设置页面。")

    executor_items = runtime.executor_status()
    executor_cards: list[str] = []
    ready_executors = 0
    for key, item in executor_items.items():
        available = bool(item.get("configured"))
        ready_executors += int(available)
        capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), list) else []
        labels = [runtime.NEW_TASK_LABEL.get(str(value), "资料归档" if value == "archive" else str(value)) for value in capabilities]
        executor_cards.append(
            f'''<article class="panel executor-card" data-executor-state="{'available' if available else 'unavailable'}">
            <div class="executor-card-head"><div><h2>{runtime.html.escape(str(item.get('label') or key))}</h2><p>{runtime.html.escape(str(item.get('description') or ''))}</p></div><span class="skill-status {'available' if available else 'unavailable'}">{'可用' if available else '不可用'}</span></div>
            <div class="executor-card-facts"><span><small>模型</small>{runtime.html.escape(str(item.get('model_label') or '') or '在执行器内选择')}</span><span><small>可处理入口</small>{runtime.html.escape('、'.join(labels) or '通用任务')}</span></div>
            <details class="settings-maintenance"><summary>检测详情</summary><p><code>{runtime.html.escape(str(item.get('resolved') or '未检测到程序'))}</code></p></details>
            </article>'''
        )

    catalog = runtime.skill_catalog()
    catalog_names = {
        str(item.get("name")): str(item.get("display_name") or item.get("name"))
        for item in catalog
    }
    catalog_profiles = {
        str(item.get("name")): str(item.get("health_profile") or "always")
        for item in catalog
    }
    snapshot = runtime.check_skill_health.read_snapshot()
    registry = runtime.native_execution_registry()
    integration_rows: list[str] = []
    integration_ready = 0
    integration_issues = 0
    for registry_key, kind_label in (("mcp_integrations", "MCP"), ("tool_integrations", "工具")):
        for item in registry.get(registry_key, []):
            profile = str(item.get("health_profile") or "always")
            owner = str(item.get("owner_skill") or "gstudio")
            state = runtime.snapshot_health_state(
                snapshot,
                health_profile=profile,
                skill_name=owner if catalog_profiles.get(owner) == profile else "",
            )
            presented = runtime.health_presentation(state, health_profile=profile)
            is_issue = presented["key"] in {"needs-config", "unavailable"}
            integration_issues += int(is_issue)
            integration_ready += int(not is_issue)
            owner_label = catalog_names.get(owner, owner)
            descriptor = str(item.get("descriptor") or "")
            source = f"config/mcp-integrations/{descriptor}" if descriptor else "余烬 · Ember 原生注册"
            integration_rows.append(
                f'''<article class="integration-row" data-integration-row data-integration-issue="{'1' if is_issue else '0'}">
                <span class="integration-kind">{kind_label}</span>
                <div class="integration-identity"><strong>{runtime.html.escape(str(item.get('display_name') or item.get('id')))}</strong><small>{runtime.html.escape(str(item.get('description') or ''))}</small></div>
                <span class="skill-status {runtime.html.escape(presented['key'], quote=True)}">{runtime.html.escape(presented['label'])}</span>
                <a class="integration-owner" href="/settings/skills?skill_q={runtime.quote(owner)}" title="登记名：{runtime.html.escape(owner, quote=True)}">{runtime.html.escape(owner_label)}</a>
                <div class="integration-detail">{runtime.html.escape(presented['detail'])}</div>
                <details class="integration-source"><summary aria-label="查看登记来源">›</summary><div><span>健康配置</span><code>{runtime.html.escape(profile)}</code><span>登记来源</span><code>{runtime.html.escape(source)}</code></div></details>
                </article>'''
            )

    checked_at = runtime.html.escape(runtime.format_display_time(str(snapshot.get("checked_at") or "")) or "未记录")
    config_path = runtime.Path(runtime.ember_env("EMBER_EXECUTOR_CONFIG") or runtime.local_config_root() / "executors.json")
    total_integrations = len(integration_rows)
    total_components = len(executor_items) + total_integrations
    total_ready = ready_executors + integration_ready
    total_issues = total_components - total_ready
    executor_hint = (
        "中央工作台默认复制完整提示词；选择在线 Mac 后才通过远程执行桥派发。"
        if runtime.ember_env("EMBER_CENTRAL_MODE") == "1"
        else "执行器负责承接任务，MCP 与工具为具体 Skill 提供外部能力。"
    )
    refresh_form = runtime._form(
        "/actions/refresh-settings-health",
        token,
        {"return_to": "/settings/executors"},
        "重新检测",
        "button",
    )
    content = runtime.flash_message(notice, error) + f'''<section class="settings-page execution-settings">
    <header class="panel settings-overview">
      <div class="settings-overview-copy"><span class="settings-kicker">SETTINGS · EXECUTION</span><h1>执行环境</h1><p>查看 余烬 · Ember 自己登记的执行器、MCP 与工具是否就绪，以及异常会影响哪个 Skill。</p></div>
      <div class="settings-metrics" aria-label="执行环境概览"><span><b>{total_ready}</b><small>可用组件</small></span><span><b>{total_issues}</b><small>需要处理</small></span><span><b>{total_components}</b><small>登记总数</small></span></div>
      <div class="settings-overview-actions">{refresh_form}<small>最近检测 {checked_at}</small></div>
    </header>
    <section class="settings-section">
      <div class="settings-section-head"><div><h2>执行器</h2><p>{runtime.html.escape(executor_hint)}</p></div><span>{ready_executors}/{len(executor_items)} 可用</span></div>
      <div class="executor-card-grid">{''.join(executor_cards)}</div>
    </section>
    <section class="settings-section">
      <div class="settings-section-head"><div><h2>集成能力</h2><p>MCP 与工具统一展示；配置来源留在详情中。</p></div><div class="settings-section-tools"><button class="chip" type="button" id="integrationIssueFilter" aria-pressed="false">只看异常 {integration_issues}</button><span id="integrationResultCount">{total_integrations} 项</span></div></div>
      <div class="integration-table">
        <div class="integration-table-head"><span>类型</span><span>能力</span><span>状态</span><span>归属 Skill</span><span>当前判断</span><span></span></div>
        <div class="integration-table-body">{''.join(integration_rows)}</div>
      </div>
    </section>
    <details class="panel settings-config-detail"><summary>本机配置与范围说明</summary><div><p>这里只显示 余烬 · Ember 注册表中的能力，不导入 Codex 或 OpenCode 内部自带的 MCP、插件和工具。</p><span>执行器配置</span><code>{runtime.html.escape(str(config_path))}</code></div></details>
    </section>'''
    content += r'''
    <style>
    .settings-page{display:grid;gap:16px;max-width:1480px;margin:0 auto}.settings-overview{display:grid;grid-template-columns:minmax(280px,1fr) auto auto;align-items:center;gap:22px;padding:18px 20px}.settings-kicker{color:var(--muted);font-size:9px;font-weight:800;letter-spacing:.12em}.settings-overview h1{margin:3px 0 5px;font-size:26px;letter-spacing:-.025em}.settings-overview p,.settings-section-head p{margin:0;color:var(--muted);font-size:11px;line-height:1.55}.settings-metrics{display:grid;grid-template-columns:repeat(3,minmax(84px,1fr));overflow:hidden;border:1px solid var(--line);border-radius:8px}.settings-metrics span{display:grid;gap:2px;padding:9px 13px;border-right:1px solid var(--line);text-align:center}.settings-metrics span:last-child{border-right:0}.settings-metrics b{font-size:18px}.settings-metrics small,.settings-overview-actions small{color:var(--muted);font-size:9px}.settings-overview-actions{display:grid;justify-items:end;gap:5px}.settings-overview-actions .button{min-width:92px}.settings-section{display:grid;gap:8px}.settings-section-head{display:flex;align-items:end;justify-content:space-between;gap:16px;padding:0 2px}.settings-section-head h2{margin:0 0 2px;font-size:15px}.settings-section-head>span,.settings-section-tools{color:var(--muted);font-size:10px}.settings-section-tools{display:flex;align-items:center;gap:8px}.executor-card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.executor-card{min-width:0;padding:14px 16px}.executor-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.executor-card h2{margin:0;font-size:15px}.executor-card-head p{margin:3px 0 0;color:var(--muted);font-size:10px}.executor-card-facts{display:grid;grid-template-columns:1fr 1.35fr;gap:12px;margin-top:13px;padding-top:11px;border-top:1px solid var(--line-soft)}.executor-card-facts span{min-width:0;color:var(--secondary);font-size:10px;overflow-wrap:anywhere}.executor-card-facts small{display:block;margin-bottom:3px;color:var(--muted);font-size:8px;font-weight:750}.settings-maintenance{margin-top:9px}.settings-maintenance summary,.settings-config-detail>summary{color:var(--muted);font-size:9px;cursor:pointer}.settings-maintenance p{margin:6px 0 0}.settings-maintenance code{font-size:8px;overflow-wrap:anywhere}.integration-table{overflow:hidden;border:1px solid var(--line);border-radius:9px;background:var(--surface)}.integration-table-head,.integration-row{display:grid;grid-template-columns:54px minmax(220px,1.3fr) 100px minmax(130px,.65fr) minmax(220px,1fr) 24px;gap:12px;align-items:center}.integration-table-head{padding:7px 12px;border-bottom:1px solid var(--line);background:var(--line-soft);color:var(--muted);font-size:8px;font-weight:750}.integration-row{min-height:58px;padding:8px 12px;border-bottom:1px solid var(--line-soft)}.integration-row:last-child{border-bottom:0}.integration-kind{color:var(--muted);font-size:8px;font-weight:800;letter-spacing:.08em}.integration-identity{display:grid;min-width:0;gap:3px}.integration-identity strong{font-size:11px}.integration-identity small{overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.integration-owner{font-size:10px;font-weight:700}.integration-detail{color:var(--secondary);font-size:9px;line-height:1.45;overflow-wrap:anywhere}.integration-source{position:relative}.integration-source summary{display:grid;width:22px;height:22px;place-items:center;color:var(--muted);font-size:15px;cursor:pointer;list-style:none}.integration-source summary::-webkit-details-marker{display:none}.integration-source[open] summary{transform:rotate(90deg)}.integration-source>div{position:absolute;z-index:8;right:0;top:27px;display:grid;width:260px;gap:4px;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--surface);box-shadow:0 10px 24px rgba(15,23,42,.14)}.integration-source span{color:var(--muted);font-size:8px}.integration-source code{font-size:8px;overflow-wrap:anywhere}.settings-config-detail{padding:11px 14px}.settings-config-detail>div{display:grid;gap:5px;margin-top:9px;color:var(--secondary);font-size:9px}.settings-config-detail p{margin:0}.settings-config-detail span{color:var(--muted);font-weight:750}.settings-config-detail code{overflow-wrap:anywhere}.skill-status{display:inline-flex;align-items:center;justify-content:center;padding:3px 7px;border-radius:999px;font-size:8px;font-weight:750;white-space:nowrap}.skill-status.available{color:#166534;background:#dcfce7}.skill-status.executor-provided{color:#1d4ed8;background:#dbeafe}.skill-status.needs-config{color:#92400e;background:#fef3c7}.skill-status.unavailable{color:#991b1b;background:#fee2e2}
    .integration-table{overflow:visible}
    @media(max-width:900px){.settings-overview{grid-template-columns:1fr 1fr}.settings-overview-copy{grid-column:1/-1}.settings-overview-actions{justify-items:start}.integration-table-head{display:none}.integration-row{grid-template-columns:44px minmax(0,1fr) auto 22px;grid-template-areas:"kind identity status source" "kind owner detail source";gap:5px 9px;padding:10px 11px}.integration-kind{grid-area:kind}.integration-identity{grid-area:identity}.integration-row>.skill-status{grid-area:status}.integration-owner{grid-area:owner}.integration-detail{grid-area:detail}.integration-source{grid-area:source}.integration-source>div{right:0}.executor-card-grid{grid-template-columns:1fr}}
    @media(max-width:600px){.settings-page{gap:13px}.settings-overview{grid-template-columns:1fr;padding:14px}.settings-overview-copy{grid-column:auto}.settings-metrics{width:100%}.settings-overview-actions{display:flex;align-items:center;justify-content:space-between}.settings-section-head{align-items:flex-start;flex-direction:column}.settings-section-tools{width:100%;justify-content:space-between}.executor-card-facts{grid-template-columns:1fr}.integration-row{grid-template-columns:minmax(0,1fr) auto 20px;grid-template-areas:"identity status source" "owner owner source" "detail detail source"}.integration-kind{display:none}.integration-identity small{white-space:normal}.integration-source>div{position:fixed;inset:auto 14px 72px 14px;width:auto}.settings-metrics span{padding:8px 6px}}
    </style>
    <script>
    (()=>{const filter=document.getElementById('integrationIssueFilter'),rows=[...document.querySelectorAll('[data-integration-row]')],count=document.getElementById('integrationResultCount');if(!filter)return;let issuesOnly=false;const render=()=>{let visible=0;rows.forEach(row=>{const show=!issuesOnly||row.dataset.integrationIssue==='1';row.hidden=!show;if(show)visible++});filter.classList.toggle('active',issuesOnly);filter.setAttribute('aria-pressed',String(issuesOnly));filter.textContent=issuesOnly?'显示全部':'只看异常 '+rows.filter(row=>row.dataset.integrationIssue==='1').length;count.textContent=visible+' 项'};filter.addEventListener('click',()=>{issuesOnly=!issuesOnly;render()});render()})();
    </script>'''
    return runtime._layout("执行环境", content, token)


def _context_section_html(value: object, body: str) -> str:
    markdown = str(value or "").strip()
    if not markdown:
        return ""
    rendered = runtime.markdown_to_html(markdown)
    for key, citation in runtime.extract_citations(body).items():
        rendered = rendered.replace(f"[^{key}]", runtime._citation_badge(key, citation))
    return rendered


def context_overview_data(intro: dict[str, object] | None, *, system: bool = False, project: str = "", token: str = "") -> dict[str, object]:
    if not intro:
        return {"state": "message", "message": "概览正本暂不可读，当前仅显示 余烬 · Ember 登记信息。"}
    if not intro.get("supported"):
        return {"state": "message", "message": f"项目说明格式 {intro.get('layout_id') or '未标记'} 暂不可映射，请核对 余烬 · Ember 共享正本。"}
    body = str(intro.get("body") or "")
    primary = runtime._context_section_html(intro.get("current_state"), body)
    if not primary:
        return {"state": "message", "message": "余烬 · Ember 共享正本尚无已确认的概览内容。"}
    sections: list[dict[str, object]] = []
    if intro.get("entries"):
        sections.append({"title": str(intro.get("entry_heading") or "工作位置与入口"), "entries": runtime.project_entry_parts_data(str(intro["entries"]), project, token)})
    for key, title in (("scope", "范围与要求"), ("stage", "当前阶段")):
        value = runtime._context_section_html(intro.get(key), body)
        if value:
            sections.append({"title": title, "html": value})
    return {
        "state": "ok", "layout_id": str(intro.get("layout_id") or "context"),
        "primary_label": str(intro.get("current_heading") or ("当前概况" if system else "项目总览")),
        "primary_html": primary, "sections": sections, "timeline_html": runtime._context_section_html(intro.get("timeline"), body),
    }


def _render_system_workspace(
    project: str,
    item: dict[str, object],
    records: list[dict[str, object]],
    token: str,
) -> str:
    """Render an AI system as an operating surface, not a content project."""
    title = str(item.get("title") or project)
    source = runtime.project_intro_source(project)
    description = "暂无系统说明。"
    intro = None
    if source:
        try:
            intro = runtime.parse_project_intro(source)
            if intro.get("supported"):
                description = ""
        except OSError:
            pass
    active = [record for record in records if str(record.get("status") or "") in {"active", "waiting_user", "blocked"}]
    current_focus = str(item.get("current_focus") or "").strip()
    lines = [record for record in records if record.get("task_kind") == "task_group" and record not in active]
    recent = [record for record in records if str(record.get("status") or "") == "completed" and record not in lines][:8]
    visible_records = (active + lines + recent)[:10]
    return_to = f"/projects/{runtime.quote(project)}"
    workbench = runtime.project_entry_target(project, "workbench")
    if project == "gstudio":
        index_status = runtime.task_index_sync_status()
        index_state = str(index_status.get("state") or "unknown") if index_status else "unknown"
        shared_ready = runtime.shared_workspace_root().is_dir()
        health_ready = shared_ready and index_state in {"ok", "ready"}
        health = {"label": "正常" if health_ready else "需要关注",
                  "detail": "共享工作区与任务索引就绪" if health_ready else "共享工作区或任务索引未就绪"}
    else:
        health = {"label": "未接入", "detail": "尚无可验证的注册健康源"}
    page = {
        "title": title, "eyebrow": "AI SYSTEM", "description_html": runtime.markdown_to_html(description), "focus": current_focus,
        "actions": [{"href": str(workbench[1]), "label": "打开工作台"}] if workbench and workbench[0] == "url" else [],
        "launcher": {"confirm_label": "开始系统任务并确认执行器", "form": {
            "action": "/actions/new-task",
            "attrs": [("data-execution-confirm", None), ("data-execution-label", "开始系统任务并确认执行器")],
            "hidden": [("csrf", token), ("task_type", "generic"), ("project", project), ("return_to", return_to)]}},
        "health": health, "stats": {"active": len(active), "lines": len(lines), "records": len(records)},
        "overview": runtime.context_overview_data(intro, system=True, project=project, token=token),
        "strip": runtime.project_location_strip(project, include_actions=False, described_entries=runtime.project_described_entries(intro)),
        "rows": runtime.project_task_row_data(visible_records, project),
        "all_tasks": {"href": f"/review?project={runtime.quote(project)}"},
    }
    content = runtime.system_page.render(page) + f'<style>{runtime.SYSTEM_STYLE}</style><script src="/assets/system.js?v={runtime.SYSTEM_VERSION}"></script>'
    return runtime._layout(f"{title}系统工作区", content, token, project, page_kind="system-workspace")


def render_copy_board_markdown(markdown: str) -> str:
    pattern = runtime.re.compile(r"^###\s+版本历史\s*$\n?(.*?)(?=^##\s+|\Z)", runtime.re.MULTILINE | runtime.re.DOTALL)
    out: list[str] = []
    cursor = 0
    for match in pattern.finditer(markdown):
        out.append(runtime.markdown_to_html(markdown[cursor:match.start()]))
        out.append(f'<details class="history"><summary>版本历史</summary>{runtime.markdown_to_html(match.group(1))}</details>')
        cursor = match.end()
    out.append(runtime.markdown_to_html(markdown[cursor:]))
    return "".join(out)
