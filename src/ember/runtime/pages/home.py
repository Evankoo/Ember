"""Page presenters; data and action helpers supplied by the runtime."""
from __future__ import annotations
from .. import ember_workbench as runtime

def _legacy_render_home(token: str, notice: str = "", error: str = "") -> str:
    records = runtime.collect_records()
    records.sort(key=lambda r: runtime.parse_sort_datetime(str(r.get("updated_at") or "")), reverse=True)
    projects = runtime.project_items()
    options = []
    for slug in runtime.formal_project_slugs():
        matching = next((r for r in records if r.get("project") == slug), None)
        if matching:
            options.append(f'<option value="{slug}">{runtime.html.escape(str(matching.get("project_title") or projects.get(slug, {}).get("title") or slug))}</option>')
    rows, cards = [], []
    for record in records:
        task_id = str(record.get("task_id", "")); name = runtime.html.escape(str(record.get("task_name") or task_id)); desc = runtime.html.escape(str(record.get("description") or "")); project = runtime.html.escape(str(record.get("project_title") or record.get("project") or "")); status = str(record.get("status") or ""); work_type = str(record.get("work_type") or ""); updated = runtime.html.escape(runtime.format_display_time(record.get("updated_at"))); sub = runtime.html.escape(str(record.get("subproject") or ""))
        search_value = " ".join(str(record.get(key) or "") for key in ("task_name", "description", "project_title", "subproject")).lower()
        project_slug = runtime.html.escape(str(record.get("project") or ""), quote=True)
        attrs = f'data-search="{runtime.html.escape(search_value, quote=True)}" data-project="{project_slug}" data-type="{runtime.html.escape(work_type, quote=True)}" data-status="{runtime.html.escape(status, quote=True)}"'
        detail = f'/tasks/{runtime.quote(task_id)}'
        delivery = runtime.resolve_delivery_folder(record)
        folder_form = runtime._form('/actions/open-folder', token, {'task_id': task_id, 'return_to': '/'}, 'Finder') if delivery else ''
        rows.append(f'<tr {attrs} data-href="{detail}" tabindex="0"><td class="name"><a class="task-name" href="{detail}">{name}</a>{f"<div class=meta>{sub}</div>" if sub else ""}</td><td class="desc" title="{desc}">{desc}</td><td>{project}</td><td><span class="badge {status}">{runtime.STATUS_LABEL.get(status,status)}</span></td><td>{runtime.TYPE_LABEL.get(work_type,work_type)}</td><td>{updated}</td><td><div class="actions">{folder_form}</div></td></tr>')
        cards.append(f'<article class="mobile-task" {attrs}><div class="row"><a class="task-name" href="{detail}">{name}</a><span class="badge {status}">{runtime.STATUS_LABEL.get(status,status)}</span></div><div class="desc" title="{desc}">{desc}</div><div class="meta">{project} · {runtime.TYPE_LABEL.get(work_type,work_type)} · {updated}</div></article>')
    stats = {key: sum(1 for r in records if r.get("status") == key) for key in ("active", "completed")}
    message = runtime.flash_message(notice, error)
    today = __import__("datetime").date.today()
    weekly_view = runtime.weekly_task_review.load_weekly_view(today)
    weekly_status = weekly_view.get("status") if isinstance(weekly_view.get("status"), dict) else {}
    weekly_task = runtime.weekly_organization_task(runtime.organization_report_records(resolve_reports=False), str(weekly_view.get("week") or ""))
    weekly_completed = str(weekly_task.get("status") or "") == "completed" if weekly_task else weekly_status.get("state") == "completed"
    weekly_label = "已完成" if weekly_completed else ("进行中" if weekly_task else "等待整理")
    content = f"""
    <section class="hero"><div><div class="eyebrow">余烬 · Ember task system</div><h1>任务系统总览</h1><div class="subtitle">从这里查看和管理你的任务、项目与归档。</div></div></section>{message}
    <section class="stats"><div class="stat"><span>进行中</span><b>{stats['active']}</b></div><div class="stat"><span>已完成</span><b>{stats['completed']}</b></div><div class="stat weekly-stat"><div><span>本周整理</span><b>{weekly_label}</b></div><a class="button" href="/weekly">查看详情</a></div></section>
    <section class="panel new-task"><div class="new-task-head"><div><h2 class="power-title">开始一项工作</h2><div class="subtitle power-subtitle">选择类型，开始创作</div></div></div>{runtime.new_task_entry_grid(token)}</section>
    <section class="section" id="projects"><div class="section-head"><div><div class="eyebrow">PROJECT STATUS</div><h2>项目状态</h2></div><a class="button primary" href="/projects">进入项目视图</a></div><div class="overview-grid">{runtime.project_overview_cards(records)}</div></section>
    <div class="section-head"><div><div class="eyebrow">TASK WORKSPACE</div><h2>任务工作区</h2></div><span class="meta">共 {len(records)} 条</span></div>
    <section class="toolbar"><div class="search-wrap"><span class="search-icon" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg></span><input id="search" type="search" placeholder="搜索任务名称、描述或小项目…" aria-label="搜索任务"></div><select id="project" aria-label="按项目筛选"><option value="">全部项目</option>{''.join(options)}</select><select id="workType" aria-label="按类型筛选"><option value="">全部类型</option>{''.join(f'<option value="{k}">{v}</option>' for k,v in runtime.TYPE_LABEL.items())}</select><div class="chips" id="chips" aria-label="按状态筛选">{''.join(f'<button class="chip{ " active" if k=="active" else ""}" type="button" data-status="{k}">{v}</button>' for k,v in [('active','进行中'),('all','全部'),('completed','已完成')])}</div><button id="clearFilters" class="button ghost clear-filters" type="button">清除筛选</button></section>
    <div class="result-line"><span id="count">正在筛选任务…</span><span>默认聚焦进行中；人工标注的待确认与阻塞可在“全部”中查看</span></div>
    <section class="panel table-wrap desktop-table"><table class="task-table"><thead><tr><th>任务名称</th><th>任务描述</th><th>项目</th><th>状态</th><th>类型</th><th>更新时间</th><th>快捷入口</th></tr></thead><tbody id="desktopRows">{''.join(rows)}</tbody></table><div class="empty">没有符合条件的任务</div></section>
    <section class="panel mobile-list" id="mobileRows">{''.join(cards)}</section>
    <script>(()=>{{const params=new URLSearchParams(location.search);let status=params.get('status')||'active';const search=document.getElementById('search'),project=document.getElementById('project'),workType=document.getElementById('workType'),clear=document.getElementById('clearFilters');search.value=params.get('q')||'';project.value=params.get('project')||'';workType.value=params.get('type')||'';if(!['active','all','completed'].includes(status))status='active';const subseq=(q,s)=>{{let i=0,j=0;q=q.toLowerCase();s=s.toLowerCase();while(i<q.length&&j<s.length){{if(q[i]===s[j])i++;j++;}}return i===q.length;}};const all=[...document.querySelectorAll('[data-search]')];function syncUrl(){{const next=new URLSearchParams();if(search.value.trim())next.set('q',search.value.trim());if(project.value)next.set('project',project.value);if(workType.value)next.set('type',workType.value);if(status!=='active')next.set('status',status);history.replaceState(null,'',location.pathname+(next.size?'?'+next:''));}}function render(){{const q=search.value.trim().toLowerCase(),p=project.value,t=workType.value;let visible=0;all.forEach(el=>{{const show=(!q||subseq(q,el.dataset.search))&&(!p||el.dataset.project===p)&&(!t||el.dataset.type===t)&&(status==='all'||el.dataset.status===status);el.style.display=show?'':'none';if(show&&el.tagName==='TR')visible++}});document.getElementById('count').textContent=`显示 ${{visible}} / {len(records)} 条`;document.querySelectorAll('.empty').forEach(x=>{{x.style.display=visible?'none':'block';if(!visible)x.innerHTML='没有符合条件的任务<br><button type="button" class="button" id="emptyClear">清除筛选</button>'}});document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('active',x.dataset.status===status));clear.classList.toggle('dimmed',!(q||p||t||status!=='active'));syncUrl();}}function reset(){{search.value='';project.value='';workType.value='';status='active';render();}}search.addEventListener('input',render);[project,workType].forEach(el=>el.addEventListener('change',render));document.getElementById('chips').addEventListener('click',e=>{{if(!e.target.dataset.status)return;status=e.target.dataset.status;render();}});clear.addEventListener('click',reset);document.addEventListener('click',e=>{{if(e.target.id==='emptyClear')reset();const row=e.target.closest('tr[data-href]');if(row&&!e.target.closest('a,button,form'))location.href=row.dataset.href;}});document.addEventListener('keydown',e=>{{const row=e.target.closest('tr[data-href]');if(row&&(e.key==='Enter'||e.key===' ')){{e.preventDefault();location.href=row.dataset.href;}}}});render();}})();</script>"""
    return runtime._layout("任务总览", content, token)


def render_home(token: str, notice: str = "", error: str = "") -> str:
    """Render the homepage as one task/context routing input."""
    records = runtime.launcher_task_records(runtime.collect_records())
    page = {
        "attention": runtime.home_attention_items(),
        "form": {"action": "/actions/route-task", "hidden": [("csrf", token), ("return_to", "/")]},
        "task_meta": runtime.home_task_metadata(records),
        "intents": list(runtime.HOME_INTENTS),
        "configure_href": "/settings#execution", "task_href_base": "/tasks/", "review_href": "/review",
        "overview": runtime.task_overview_data(records),
    }
    content = (
        runtime.flash_message(notice, error) + runtime.home_page.render(page)
        + f'<script src="/assets/home.js?v={runtime.HOME_VERSION}"></script><script src="/assets/task-overview.js?v={runtime.TASK_OVERVIEW_VERSION}"></script>'
    )
    return runtime._layout("任务台", content, token)
