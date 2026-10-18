"""Page presenters; data and action helpers supplied by the runtime."""
from __future__ import annotations
from .runtime.ember_compat import env as ember_env
from .. import ember_workbench as runtime

def task_overview_data(records: list[dict[str, object]]) -> dict[str, object]:
    """Rows and filter choices for the homepage's read-only, cross-project task browser."""
    cards = [record for record in records if record.get("record_type") == "task_card"]
    cards.sort(key=lambda r: runtime.parse_sort_datetime(str(r.get("updated_at") or "")), reverse=True)
    project_options: dict[str, str] = {}
    rows = []
    for record in cards:
        task_id = str(record.get("task_id") or "")
        project_slug = str(record.get("project") or "")
        project_label = runtime.task_scope_title(project_slug, str(record.get("project_title") or ""))
        project_options.setdefault(project_slug, project_label)
        status = str(record.get("status") or "")
        work_type = str(record.get("work_type") or "")
        rows.append({
            "task_id": task_id, "title": str(record.get("task_name") or record.get("title") or task_id),
            "href": f"/tasks/{runtime.quote(task_id)}", "task_line": bool(runtime.task_group_tag(record)),
            "description": str(record.get("description") or ""),
            "project_slug": project_slug, "project_label": project_label,
            "status": status, "status_label": runtime.STATUS_LABEL.get(status, status),
            "work_type": work_type, "type_label": runtime.TYPE_LABEL.get(work_type, work_type),
            "updated": runtime.format_display_time(record.get("updated_at")),
            "search": " ".join(
                str(record.get(key) or "")
                for key in ("task_name", "title", "description", "project_title", "project", "task_id", "work_type", "status")
            ).lower(),
        })
    return {
        "rows": rows,
        "projects": [(slug, label) for slug, label in sorted(project_options.items(), key=lambda item: item[1]) if slug],
        "types": [(key, label) for key, label in runtime.TYPE_LABEL.items() if any(str(card.get("work_type") or "") == key for card in cards)],
    }


def _render_task_body(body: str, name: str) -> tuple[str, str]:
    """Keep the task narrative visible and render the execution log last."""
    reading_html, entries = runtime._task_body(body, name)
    return reading_html, runtime.task_detail.execution_log(entries, runtime.TASK_LOG_MACHINE_PREFIXES) if entries is not None else ""


def render_task(task_id: str, token: str, notice: str = "", error: str = "", *, back_path: str = "/projects", back_label: str = "项目视图") -> str | None:
    records = runtime.record_map()
    record = records.get(task_id)
    source = runtime.task_source(task_id)
    if not record or not source:
        return None
    text = source.read_text(encoding="utf-8", errors="replace")
    _, body = runtime.tasks.frontmatter(text)
    name = str(record.get("task_name") or record.get("title") or task_id)
    status = str(record.get("status") or "")
    return_to = f"/tasks/{runtime.quote(task_id)}"
    delivery = runtime.library_task_delivery(record) or {}
    delivery_key = str(delivery.get("key") or "")
    is_central = runtime.ember_env("EMBER_CENTRAL_MODE") == "1"
    skills = record.get("skills_used") if isinstance(record.get("skills_used"), list) else []
    skill_display = "、".join(str(item) for item in skills if str(item)) or "未记录"
    model_families = record.get("model_families") if isinstance(record.get("model_families"), list) else []
    model_display = " / ".join(str(item) for item in model_families if str(item)) or "未报告"
    updated_label = runtime.format_display_time(record.get("updated_at")) or "未记录"
    body_html, log_entries = runtime._task_body(body, name)

    related_delivery_items: list[dict[str, str]] = []
    related: list[dict[str, object]] | None = None
    parent: dict[str, str] | None = None
    if record.get("task_kind") == "task_group":
        related = []
        for related_id in [str(value) for value in record.get("related_task_ids") or []]:
            member = records.get(related_id)
            if not member:
                related.append({"task_id": related_id, "missing": True})
                continue
            related_state = str(member.get("status") or "")
            related_name = str(member.get("task_name") or member.get("title") or related_id)
            related_delivery = runtime.library_task_delivery(member) or {}
            related_delivery_items.append({
                "task_id": related_id,
                "title": related_name,
                "delivery": str(related_delivery.get("key") or ""),
                "delivery_label": str(related_delivery.get("name") or "暂无交付"),
                "status": runtime.STATUS_LABEL.get(related_state, related_state),
            })
            related.append({"task_id": related_id, "title": related_name, "href": f"/tasks/{runtime.quote(related_id)}",
                            "status": related_state, "status_label": runtime.STATUS_LABEL.get(related_state, related_state)})
    else:
        parent_groups = [
            group for group in records.values()
            if group.get("record_type") == "task_card"
            and group.get("task_kind") == "task_group"
            and task_id in [str(value) for value in group.get("related_task_ids") or []]
        ]
        if parent_groups:
            group = max(parent_groups, key=lambda item: str(item.get("updated_at") or ""))
            parent_id = str(group.get("task_id") or "")
            parent = {"title": str(group.get("task_name") or group.get("title") or parent_id or "任务主线"), "href": f"/tasks/{runtime.quote(parent_id)}"}

    try:
        parsed_inputs = runtime.parse_inputs(text)
    except ValueError:
        parsed_inputs = {"items": []}
    input_items = parsed_inputs.get("items") if isinstance(parsed_inputs, dict) else []
    input_items = input_items if isinstance(input_items, list) else []
    hidden = [("csrf", token), ("task_id", task_id), ("return_to", return_to)]
    input_folder_control = {"label": "回到输入目录" if is_central else "打开输入目录", "disabled": not runtime.task_input_root(task_id),
                            "form": {"action": "/actions/open-task-input-folder", "attrs": [("data-task-folder-action", "input")], "hidden": hidden}}
    task_folder_control = {"label": "打开交付文件夹", "disabled": not delivery,
                           "disabled_reason": "尚无交付文件夹",
                           "form": {"action": "/actions/open-folder", "attrs": [("data-task-folder-action", "delivery")], "hidden": hidden}}
    continue_control = {"confirm_label": "核对提示词并继续任务", "form": {
        "action": "/actions/continue-task", "hidden": hidden,
        "attrs": [("data-task-continue-form", None), ("data-execution-confirm", None), ("data-execution-label", "继续当前任务")]}}
    related_deliveries_json = runtime.json.dumps(related_delivery_items, ensure_ascii=False).replace("</", "<\\/")
    has_materials = bool(delivery_key or input_items or related_delivery_items)
    controller = (runtime.TASK_DETAIL_CONTROLLER_START.replace("__TASK_DETAIL_VERSION__", runtime.TASK_DETAIL_VERSION) + related_deliveries_json + runtime.TASK_DETAIL_CONTROLLER_END) if has_materials else ""
    project = str(record.get("project") or "independent")
    project_item = runtime.project_items().get(project) or {}
    page = {
        "task_id": task_id, "title": name, "status": status, "status_label": runtime.STATUS_LABEL.get(status, status),
        "project_title": str(project_item.get("title") or ("独立任务" if project == "independent" else project)),
        "project_href": f'/projects/{runtime.quote(project)}' if project in runtime.project_items() else "/review",
        "updated_label": updated_label, "parent": parent,
        "body_html": body_html, "after_body_html": runtime.external_results_markup(text),
        "technical": [f"Skill {skill_display}", f"执行器 {runtime.TASK_EXECUTOR_LABEL.get(str(record.get('executor') or ''), str(record.get('executor') or '未记录'))}", f"模型 {model_display}"],
        "log": {"entries": log_entries, "machine_prefixes": runtime.TASK_LOG_MACHINE_PREFIXES} if log_entries is not None else None,
        "related": related,
        "continue": continue_control,
        "folder_control": task_folder_control,
        "materials": {
            "delivery": delivery_key,
            "attrs": [("data-central-mode", "1" if is_central else "0"), ("data-csrf", token)],
            "input_count": len(input_items),
            "folder_controls": [input_folder_control, task_folder_control],
            "inputs": runtime._task_input_rows(task_id, text, token, return_to),
        } if has_materials else None,
    }
    message = runtime.flash_message(notice, error)
    content = f'''{message}<style data-task-detail-style="single">{runtime.TASK_DETAIL_STYLE}</style>
    {runtime.task_detail.render(page)}{controller}'''
    safe_back_path = runtime.html.escape(back_path, quote=True)
    safe_back_label = runtime.html.escape(back_label)
    return runtime._layout(name, content, token, active_project=project if project in runtime.project_items() else "", nav_prefix=f'<a class="back-link" href="{safe_back_path}">← 返回{safe_back_label}</a>', page_kind="task-detail")


def _legacy_render_project_tasks(project: str, token: str) -> str | None:
    if project not in runtime.project_items():
        return None
    item = runtime.project_items().get(project)
    if not item:
        return None
    records = [record for record in runtime.collect_records() if record.get("project") == project and record.get("record_type") == "task_card"]
    records.sort(key=lambda record: runtime.parse_sort_datetime(str(record.get("updated_at") or "")), reverse=True)
    ledgers = [record for record in runtime.collect_records() if record.get("project") == project and record.get("record_type") == "ledger_row"]
    ledgers.sort(key=lambda record: runtime.parse_sort_datetime(str(record.get("updated_at") or "")), reverse=True)

    title = str(item.get("title") or project)
    return_to = f"/projects/{runtime.quote(project)}"
    intro_card = runtime.project_intro_card(project, token)

    # Build task table rows (no project column).
    rows, mobile_cards = [], []
    for record in records:
        task_id = str(record.get("task_id", ""))
        name = runtime.html.escape(str(record.get("task_name") or task_id))
        group_tag = runtime.task_group_tag(record)
        desc = runtime.html.escape(str(record.get("description") or ""))
        status = str(record.get("status") or "")
        work_type = str(record.get("work_type") or "")
        updated = runtime.html.escape(runtime.format_display_time(record.get("updated_at")))
        updated_iso = runtime.html.escape(str(record.get("updated_at") or ""))
        sub = runtime.html.escape(str(record.get("subproject") or ""))
        search_value = " ".join(str(record.get(key) or "") for key in ("task_name", "description", "subproject")).lower()
        delivery = runtime.resolve_delivery_folder(record)
        has_delivery = "1" if delivery else "0"
        delivery_label = runtime.html.escape(delivery.name if delivery else "")
        folder_form = runtime._form("/actions/open-folder", token, {"task_id": task_id, "return_to": return_to}, "Finder") if delivery else ""
        attrs = f'data-search="{runtime.html.escape(search_value, quote=True)}" data-type="{runtime.html.escape(work_type, quote=True)}" data-status="{runtime.html.escape(status, quote=True)}" data-updated-at="{runtime.html.escape(updated_iso, quote=True)}" data-has-delivery="{has_delivery}"'
        detail = f"/tasks/{runtime.quote(task_id)}"
        rows.append(f'<tr {attrs} data-href="{detail}" tabindex="0"><td class="name"><a class="task-name" href="{detail}">{name}{group_tag}</a>{f"<div class=meta>{sub}</div>" if sub else ""}</td><td class="desc" title="{desc}">{desc}</td><td><span class="badge {status}">{runtime.STATUS_LABEL.get(status, status)}</span></td><td>{runtime.TYPE_LABEL.get(work_type, work_type)}</td><td>{updated}</td><td><div class="actions">{folder_form}</div></td></tr>')
        mobile_cards.append(f'<article class="mobile-task" {attrs}><div class="row"><a class="task-name" href="{detail}">{name}{group_tag}</a><span class="badge {status}">{runtime.STATUS_LABEL.get(status, status)}</span></div><div class="desc" title="{desc}">{desc}</div><div class="meta">{runtime.TYPE_LABEL.get(work_type, work_type)} · {updated}{f" · 交付：{delivery_label}" if delivery else ""}</div></article>')

    def record_links(items: list[dict[str, object]], empty: str) -> str:
        if not items:
            return f'<div class="subtitle">{empty}</div>'
        lines = []
        for record in items:
            label = runtime.html.escape(str(record.get("task_name") or record.get("title") or record.get("task_id") or ""))
            if record.get("record_type") == "ledger_row":
                name = f"<span>{label}</span>"
            else:
                name = f'<a href="/tasks/{runtime.quote(str(record.get("task_id") or ""))}">{label}</a>'
            lines.append(f'<li>{name} <span class="meta">{runtime.html.escape(runtime.format_display_time(record.get("updated_at")))}</span></li>')
        return "<ul>" + "".join(lines) + "</ul>"

    time_options = "".join(f'<option value="{k}">{v}</option>' for k, v in [("", "全部时间"), ("7d", "最近 7 天"), ("30d", "最近 30 天"), ("month", "本月"), ("quarter", "本季度")])
    type_options = "".join(f'<option value="{k}">{v}</option>' for k, v in [("", "全部类型")] + list(runtime.TYPE_LABEL.items()))
    delivery_options = "".join(f'<option value="{k}">{v}</option>' for k, v in [("", "全部任务"), ("1", "有交付物"), ("0", "无交付物")])
    now = runtime.datetime.datetime.now(runtime.datetime.timezone.utc)
    recent_completed = sum(
        1
        for record in records
        if record.get("status") == "completed"
        and now - runtime.parse_sort_datetime(str(record.get("updated_at") or "")) <= runtime.datetime.timedelta(days=30)
    )

    content = f'''<div class="breadcrumb"><a href="/">任务台</a> / <a href="/projects">视图</a> / {runtime.html.escape(title)}</div>
    <section class="panel new-task"><div class="new-task-head"><div><h2 class="power-title">从该项目开始</h2><div class="subtitle power-subtitle">选择任务类型与执行工具</div></div></div>{runtime.project_task_entry_grid(project, token, return_to)}</section>
    {intro_card}
    <section class="stats project-stats" aria-label="项目全量统计"><div class="stat"><span>全部进行中</span><b>{sum(1 for r in records if r.get('status') == 'active')}</b></div><div class="stat"><span>近 30 天完成</span><b>{recent_completed}</b></div><div class="stat"><span>全部有交付物</span><b>{sum(1 for r in records if runtime.resolve_delivery_folder(r))}</b></div><div class="stat"><span>全部发布记录</span><b>{len(ledgers)}</b></div></section>
    <section class="toolbar project-toolbar"><div class="search-wrap"><span class="search-icon" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg></span><input id="search" type="search" placeholder="搜索任务名称、描述…" aria-label="搜索任务"></div><select id="timeRange" aria-label="按时间筛选">{time_options}</select><select id="workType" aria-label="按类型筛选">{type_options}</select><select id="hasDelivery" aria-label="按交付物筛选">{delivery_options}</select><div class="chips" id="chips" aria-label="按状态筛选">{''.join(f'<button class="chip{" active" if k=="active" else ""}" type="button" data-status="{k}">{v}</button>' for k,v in [('active','进行中'),('all','全部'),('completed','已完成')])}</div><button id="clearFilters" class="button ghost clear-filters" type="button">清除筛选</button></section>
    <div class="result-line"><span id="count">正在筛选任务…</span><span>上方为项目全量统计 · 列表默认聚焦进行中</span></div>
    <section class="panel table-wrap desktop-table"><table class="task-table"><thead><tr><th>任务</th><th>说明</th><th>状态</th><th>类型</th><th>最近更新</th><th>交付</th></tr></thead><tbody id="desktopRows">{''.join(rows)}</tbody></table><div class="empty">没有符合条件的任务</div></section>
    <section class="panel mobile-list" id="mobileRows">{''.join(mobile_cards)}</section>
    <script>(()=>{{const params=new URLSearchParams(location.search);let status=params.get('status')||'active';const search=document.getElementById('search'),timeRange=document.getElementById('timeRange'),workType=document.getElementById('workType'),hasDelivery=document.getElementById('hasDelivery'),clear=document.getElementById('clearFilters');search.value=params.get('q')||'';timeRange.value=params.get('time')||'';workType.value=params.get('type')||'';hasDelivery.value=params.get('delivery')||'';if(!['active','all','completed'].includes(status))status='active';const subseq=(q,s)=>{{let i=0,j=0;q=q.toLowerCase();s=s.toLowerCase();while(i<q.length&&j<s.length){{if(q[i]===s[j])i++;j++;}}return i===q.length;}};const inTime=(iso,range)=>{{if(!range||!iso)return true;const d=new Date(iso.replace(' ','T'));if(isNaN(d))return true;const now=new Date();if(range==='7d')return now-d<=7*86400000;if(range==='30d')return now-d<=30*86400000;if(range==='month')return d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth();if(range==='quarter')return d.getFullYear()===now.getFullYear()&&Math.floor(d.getMonth()/3)===Math.floor(now.getMonth()/3);return true;}};const all=[...document.querySelectorAll('[data-search]')];function syncUrl(){{const next=new URLSearchParams();if(search.value.trim())next.set('q',search.value.trim());if(timeRange.value)next.set('time',timeRange.value);if(workType.value)next.set('type',workType.value);if(hasDelivery.value)next.set('delivery',hasDelivery.value);if(status!=='active')next.set('status',status);history.replaceState(null,'',location.pathname+(next.size?'?'+next:''));}}function render(){{const q=search.value.trim().toLowerCase(),t=timeRange.value,w=workType.value,d=hasDelivery.value;let visible=0;all.forEach(el=>{{const show=(!q||subseq(q,el.dataset.search))&&(!t||inTime(el.dataset.updatedAt,t))&&(!w||el.dataset.type===w)&&(!d||el.dataset.hasDelivery===d)&&(status==='all'||el.dataset.status===status);el.style.display=show?'':'none';if(show&&el.tagName==='TR')visible++;}});document.getElementById('count').textContent=`显示 ${{visible}} / {len(records)} 条`;document.querySelectorAll('.empty').forEach(x=>{{x.style.display=visible?'none':'block';if(!visible)x.innerHTML='没有符合条件的任务<br><button type="button" class="button" id="emptyClear">清除筛选</button>'}});document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('active',x.dataset.status===status));clear.classList.toggle('dimmed',!(q||t||w||d||status!=='active'));syncUrl();}}function reset(){{search.value='';timeRange.value='';workType.value='';hasDelivery.value='';status='active';render();}}search.addEventListener('input',render);[timeRange,workType,hasDelivery].forEach(el=>el.addEventListener('change',render));document.getElementById('chips').addEventListener('click',e=>{{if(!e.target.dataset.status)return;status=e.target.dataset.status;render();}});clear.addEventListener('click',reset);document.addEventListener('click',e=>{{if(e.target.id==='emptyClear')reset();const row=e.target.closest('tr[data-href]');if(row&&!e.target.closest('a,button,form'))location.href=row.dataset.href;}});document.addEventListener('keydown',e=>{{const row=e.target.closest('tr[data-href]');if(row&&(e.key==='Enter'||e.key===' ')){{e.preventDefault();location.href=row.dataset.href;}}}});render();}})();</script>'''
    return runtime._layout(f"{title}任务视图", content, token, project)


def project_task_row_data(records: list[dict[str, object]], project: str) -> list[dict[str, object]]:
    important_ids = set(runtime.project_priorities().get(project, []))
    rows = []
    for record in records:
        task_id = str(record.get("task_id") or "")
        status = str(record.get("status") or "")
        is_group = record.get("task_kind") == "task_group"
        rows.append({
            "task_id": task_id, "title": str(record.get("task_name") or record.get("title") or task_id),
            "href": f"/tasks/{runtime.quote(task_id)}", "task_line": bool(runtime.task_group_tag(record)),
            "description": str(record.get("description") or ""), "status": status, "status_label": runtime.STATUS_LABEL.get(status, status),
            "important": task_id in important_ids, "group": is_group,
            "has_delivery": bool(record.get("delivery_folder") or record.get("paths")),
            "search": " ".join(str(record.get(key) or "") for key in ("task_name", "description", "subproject")).casefold() + " " + task_id.casefold(),
        })
    return rows


def render_project_tasks(project: str, token: str) -> str | None:
    if project not in runtime.project_items():
        return None
    item = runtime.project_items().get(project)
    if not item:
        return None
    records = [
        record for record in runtime.collect_records()
        if record.get("project") == project and record.get("record_type") == "task_card"
    ]
    records.sort(key=lambda record: runtime.parse_sort_datetime(str(record.get("updated_at") or "")), reverse=True)
    title = str(item.get("title") or project)
    if str(item.get("project_type") or "") == "ai_system":
        return runtime._render_system_workspace(project, item, records, token)
    capabilities = set(map(str, item.get("capabilities") or []))
    has_delivery = "ember_delivery" in capabilities
    return_to = f"/projects/{runtime.quote(project)}"
    if has_delivery:
        material_pane, delivery_count, input_count = runtime.project_material_browser(project, token, return_to)
    else:
        material_pane = ""
        delivery_count = 0
        input_count = 0
    page = runtime.project_hero_data(project, token, records)
    page.update({
        "counts": {"tasks": len(records), "delivery": delivery_count, "input": input_count},
        "task_search_label": "搜索项目任务" if has_delivery else "搜索系统任务",
        "has_delivery": has_delivery, "rows": runtime.project_task_row_data(records, project), "materials_html": material_pane,
    })
    content = (
        runtime.project_page.render(page)
        + f'<style>{runtime.PROJECT_STYLE}</style><script src="/assets/project.js?v={runtime.PROJECT_VERSION}"></script>'
    )
    return runtime._layout(f"{title}任务视图", content, token, project, page_kind="project-workspace")
