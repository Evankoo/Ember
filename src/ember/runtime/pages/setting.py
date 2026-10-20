"""Page presenters; data and action helpers supplied by the runtime."""
from __future__ import annotations
from ..ember_compat import env as ember_env
from .. import ember_workbench as runtime

def _agent_catalog(token: str) -> tuple[str, int, int, int]:
    """Render registered Agents without running model checks on a page request."""
    escape = runtime.html.escape
    entries = runtime.ember_agent.registry().get("runtime_agents", {})
    if not isinstance(entries, dict):
        raise runtime.ember_agent.AgentError("Invalid runtime Agent registry")
    ledger = runtime.ember_agent.read_ledger()
    runs = [item for item in ledger.get("runs", []) if isinstance(item, dict)]
    cards = []
    ready = total = 0
    for agent_id, entry in entries.items():
        try:
            values, _ = runtime.ember_agent.agent_definition(agent_id)
        except runtime.ember_agent.AgentError:
            cards.append(f'<article class="settings-agent-card"><header><h3>{escape(agent_id)}</h3><span class="skill-status unavailable">定义不可读</span></header><p>登记仍在，请检查 Agent 正本；未将读取失败视作未登记。</p></article>')
            continue
        adapters = [part.strip() for part in values.get("adapters", "").split(",") if part.strip()]
        files = entry.get("adapter_files", {}) if isinstance(entry, dict) else {}
        if not isinstance(files, dict):
            files = {}
        registered = sum(bool(files.get(adapter)) and isinstance(files.get(adapter), list)
                         and all((runtime.ROOT / path).is_file() for path in files[adapter])
                         for adapter in adapters)
        ready += registered
        total += len(adapters)
        models = []
        for adapter in adapters:
            policy = runtime.ember_agent.executor_model_policy(values, adapter)
            primary = policy["primary_model"]
            fallback = policy.get("fallback_model", "none")
            label = "DeepSeek V4.1 Flash" if primary == "deepseek-flash" else primary
            order = f"{adapter.title() if adapter != 'opencode' else 'OpenCode'} · {label}"
            if fallback and fallback != "none":
                order += f" → {fallback}"
            models.append(f"<span>{escape(order)}</span>")
        own_runs = [item for item in runs if item.get("agent_id") == agent_id]
        latest = max((str(item.get("updated_at") or "") for item in own_runs), default="")
        recent = runtime.format_display_time(latest) if latest else "尚无记录"
        actions = ""
        if agent_id == "material-manager":
            if "hermes" in adapters:
                installed = (runtime.Path.home() / ".hermes" / "profiles" / agent_id / ".ember-agent.json").is_file()
                actions += runtime._form("/actions/agent-install", token, {"agent_id": agent_id, "return_to": "/settings#agents"}, "更新 Hermes 适配器" if installed else "安装 Hermes 适配器", "button")
            actions += runtime._form("/actions/agent-verify", token, {"agent_id": agent_id, "return_to": "/settings#agents"}, "验证 Agent", "button ghost")
        active = values.get("status") == "active"
        state = "已登记" if active and registered == len(adapters) and adapters else "适配待核对" if active else "未启用"
        css = "registered" if state == "已登记" else "needs-config"
        fallback_note = "无模型回退" if values.get("fallback_model") == "none" else "仅技术失败时允许模型回退"
        actions_html = f'<div class="settings-agent-actions">{actions}</div>' if actions else ""
        cards.append(f'''<article class="settings-agent-card" data-agent-id="{escape(agent_id, quote=True)}"><header><div><h3>{escape(values.get('display_name') or agent_id)}</h3></div><span class="skill-status {css}">{state}</span></header>
        <p>{escape(values.get('description') or '用途未登记')}</p><dl><div><dt>执行器与模型</dt><dd class="agent-model-order">{''.join(models) or '未声明'}</dd></div><div><dt>最近运行</dt><dd>{escape(recent)}</dd></div><div><dt>适配登记</dt><dd>{registered}/{len(adapters)} · {fallback_note}</dd></div></dl>
        {actions_html}<footer><details><summary>技术信息</summary><code>{escape(str(entry.get('manifest') or ''))}</code></details></footer></article>''')
    body = ''.join(cards) or '<p class="empty" style="display:block">尚无已登记 Agent。</p>'
    return body, len(entries), ready, total

def _render_skills_settings(token: str, notice: str = "", error: str = "") -> str:
    health = runtime.check_skill_health.read_snapshot()
    catalog = runtime.skill_catalog()
    usage_records, usage_cache = runtime.skill_usage_index()
    usage = runtime.skill_usage_stats(usage_records)
    usage_state = str(usage_cache.get("state") or "empty")
    usage_available = bool(usage_records) or usage_state in {"ready", "empty", "stale"}
    names = {str(item.get("name")): str(item.get("display_name") or item.get("name")) for item in catalog}
    category_labels = {
        "core-governance": "核心治理", "content-production": "内容生产", "social-data": "社媒数据",
        "video-processing": "视频处理", "voice-multimodal": "语音与多模态", "archive": "归档与入库",
        "research-knowledge": "研究与知识", "system-maintenance": "系统维护",
        "feishu-integration": "飞书集成", "other": "其他",
    }
    kind_labels = {
        "user-entry": "用户入口", "router": "总控路由", "pipeline-step": "流程组件",
        "provider-adapter": "服务适配", "backend-adapter": "后端适配", "foundation": "基础规范",
        "governance": "治理", "reporting": "报告", "intake-router": "需求路由",
    }
    visibility_labels = {"primary": "主入口", "secondary": "次级入口", "component": "组件", "disabled": "已停用", "system": "系统"}
    status_labels = {
        "available": "可用",
        "executor-provided": "随执行器提供",
        "needs-config": "需配置",
        "unavailable": "不可用",
        "unverified": "未检测",
    }
    category_order = list(category_labels)
    grouped: dict[str, list[dict[str, object]]] = {key: [] for key in category_order}
    for item in catalog:
        grouped.setdefault(str(item.get("category") or "system-maintenance"), []).append(item)

    counts = {key: 0 for key in status_labels}
    skill_sections: list[str] = []
    never_used_count = (
        sum(1 for item in catalog if int(usage.get(str(item.get("name") or ""), {}).get("total") or 0) == 0)
        if usage_available else None
    )
    pending_structure_count = sum(1 for item in catalog if not runtime.skill_is_standardized(item))
    for category in category_order:
        items = grouped.get(category, [])
        if not items:
            continue
        item_rows: list[str] = []
        for skill in sorted(items, key=lambda value: (bool(value.get("parent_skill")), str(value.get("display_name") or ""))):
            name = str(skill.get("name") or "")
            display_name = str(skill.get("display_name") or name)
            profile = str(skill.get("health_profile") or "always")
            state = runtime.snapshot_health_state(health, health_profile=profile, skill_name=name)
            presented = runtime.health_presentation(state, health_profile=profile)
            counts[presented["key"]] += 1
            note = str(state.get("note") or "").strip() if isinstance(state, dict) else ""
            dependency_detail = presented["detail"]
            if note and note not in dependency_detail:
                dependency_detail = f"{dependency_detail}；{note}"
            parent = str(skill.get("parent_skill") or "")
            parent_label = names.get(parent, parent)
            stat = usage.get(name, {})
            total, days_30 = int(stat.get("total") or 0), int(stat.get("days_30") or 0)
            last_used = stat.get("last_used")
            last_task = str(stat.get("last_task") or "")
            if usage_available:
                days_30_label = str(days_30)
                last_label = last_used.astimezone().strftime("%Y-%m-%d") if isinstance(last_used, runtime.datetime.datetime) else "从未登记"
                last_task_html = f'<a href="/tasks/{runtime.quote(last_task)}">{runtime.html.escape(last_task)}</a>' if last_task else "无关联任务"
                usage_detail = f"近 30 天关联 {days_30} 个任务；累计关联 {total} 个任务；最近任务 {last_task_html}"
                frequency = "never" if total == 0 else "low" if total <= 2 else "normal"
            else:
                days_30_label = "—"
                last_label = "—"
                usage_detail = "关联任务统计暂不可用；本地任务索引修复后会自动恢复。"
                frequency = "unknown"
            standardized = runtime.skill_is_standardized(skill)
            visibility = str(skill.get("visibility") or "secondary")
            kind = str(skill.get("kind") or "")
            description = str(skill.get("description") or "")
            context_label = f"所属：{parent_label} · {description}" if parent else description
            search_text = " ".join((name, display_name, category_labels.get(category, category), description, parent_label)).lower()
            relationship = f"{visibility_labels.get(visibility, visibility)} · {kind_labels.get(kind, kind)}"
            if parent:
                relationship += f" · 上级 Skill：{parent_label}"
            structure_label = "结构完整" if standardized else "待补结构"
            item_rows.append(
                f'''<details class="skill-row {'child' if parent else 'root'}" data-skill-card data-skill-status="{runtime.html.escape(presented['key'], quote=True)}" data-skill-category="{runtime.html.escape(category, quote=True)}" data-skill-frequency="{frequency}" data-skill-recent="{'1' if usage_available and days_30 else '0'}" data-skill-structure="{'complete' if standardized else 'pending'}" data-skill-search="{runtime.html.escape(search_text, quote=True)}">
                <summary><span class="skill-tree-mark">{'↳' if parent else '◆'}</span><span class="skill-identity"><strong>{runtime.html.escape(display_name)}</strong><small>{runtime.html.escape(context_label)}</small></span><span class="skill-status {runtime.html.escape(presented['key'], quote=True)}">{runtime.html.escape(presented['label'])}</span><span class="skill-usage"><b>{days_30_label}</b><small>近 30 天关联任务</small></span><span class="skill-last"><b>{runtime.html.escape(last_label)}</b><small>最近登记</small></span><span class="skill-disclosure">›</span></summary>
                <div class="skill-detail">
                  <div><span>能力关系</span><p>{runtime.html.escape(relationship)}</p></div>
                  <div><span>关联任务统计</span><p>{usage_detail}</p><small>统计口径：任务卡 <code>skills_used</code> 登记关系，不代表真实调用次数。</small></div>
                  <div><span>依赖与健康</span><p>{runtime.html.escape(dependency_detail)}</p><small>健康配置：<code>{runtime.html.escape(profile)}</code></small></div>
                  <div><span>维护信息</span><p>登记名 <code>{runtime.html.escape(name)}</code> · {structure_label}</p><small>登记文件：<code>{runtime.html.escape(str(skill.get('path') or ''))}</code></small></div>
                </div></details>'''
            )
        skill_sections.append(
            f'''<section class="skill-category" data-skill-category-section="{runtime.html.escape(category, quote=True)}"><div class="skill-category-head"><div><span class="skill-category-dot"></span><h2>{runtime.html.escape(category_labels.get(category, category))}</h2></div><span data-category-visible-count>{len(items)} 个</span></div><div class="skill-list">{''.join(item_rows)}</div></section>'''
        )

    checked_at = runtime.html.escape(runtime.format_display_time(str(health.get("checked_at") or "")) or "未记录")
    category_options = ''.join(
        f'<option value="{runtime.html.escape(key, quote=True)}">{runtime.html.escape(category_labels[key])}</option>'
        for key in category_order if grouped.get(key)
    )
    status_buttons = ''.join(
        f'<button class="skill-health-summary {key}" type="button" data-skill-summary-status="{key}" aria-pressed="false"><b>{counts[key]}</b><span>{label}</span></button>'
        for key, label in status_labels.items()
    )
    usage_filter_controls = (
        '<span>关联任务</span>'
        '<button class="chip active" type="button" data-skill-usage="all" aria-pressed="true">全部</button>'
        '<button class="chip" type="button" data-skill-usage="recent" aria-pressed="false">近 30 天有登记</button>'
        '<button class="chip" type="button" data-skill-usage="low" aria-pressed="false">低频登记</button>'
        '<button class="chip" type="button" data-skill-usage="never" aria-pressed="false">从未登记</button>'
        if usage_available else
        '<span>关联任务统计暂不可用</span>'
    )
    maintenance_summary = (
        f"{never_used_count} 项从未登记 · {pending_structure_count} 项待补结构"
        if never_used_count is not None else
        f"关联统计暂不可用 · {pending_structure_count} 项待补结构"
    )
    refresh_form = runtime._form(
        "/actions/refresh-settings-health",
        token,
        {"return_to": "/settings/skills"},
        "重新检测",
        "button",
    )
    usage_message = runtime.html.escape(str(usage_cache.get("message") or ""))
    cache_notice = (
        f'<div class="panel skill-cache-notice {runtime.html.escape(usage_state, quote=True)}" data-skill-cache-state="{runtime.html.escape(usage_state, quote=True)}"><strong>关联统计</strong><span>{usage_message}</span></div>'
        if usage_state != "ready" else ""
    )
    content = runtime.flash_message(notice, error) + f'''<section class="settings-page skill-settings" data-skill-usage-ready="{'1' if usage_available else '0'}">
    <header class="panel settings-overview skill-overview">
      <div class="settings-overview-copy"><span class="settings-kicker">SETTINGS · SKILLS</span><h1>Skills</h1><p>先看每项能力能做什么、现在能否使用，以及最近关联了多少任务。</p></div>
      <div class="skill-health-strip" role="group" aria-label="Skill 健康概览">{status_buttons}</div>
      <div class="settings-overview-actions">{refresh_form}<small>健康检查 {checked_at}</small><small title="{runtime.html.escape(str(runtime.check_skill_health.SNAPSHOT_PATH), quote=True)}">本机健康快照</small></div>
    </header>
    {cache_notice}
    <div class="panel skill-toolbar">
      <div class="skill-toolbar-main"><input id="skillSearch" type="search" aria-label="搜索 Skill 名称或用途" placeholder="搜索 Skill 名称或用途"><select id="skillCategory" aria-label="Skill 分类"><option value="all">全部分类</option>{category_options}</select><span class="skill-result-count" id="skillResultCount">{len(catalog)} 个结果</span></div>
      <div class="skill-status-filters" role="group" aria-label="可用状态"><button class="chip active" type="button" data-skill-filter="all" aria-pressed="true">全部状态</button><button class="chip" type="button" data-skill-filter="available" aria-pressed="false">可用</button><button class="chip" type="button" data-skill-filter="executor-provided" aria-pressed="false">随执行器提供</button><button class="chip" type="button" data-skill-filter="needs-config" aria-pressed="false">需配置</button><button class="chip" type="button" data-skill-filter="unavailable" aria-pressed="false">不可用</button><button class="chip" type="button" data-skill-filter="unverified" aria-pressed="false">未检测</button><button class="button ghost tiny" type="button" id="skillClearFilters">清除筛选</button></div>
      <details class="skill-maintenance-filters"><summary>维护筛选</summary><div role="group" aria-label="维护筛选">{usage_filter_controls}<button class="chip" type="button" data-skill-structure-toggle="pending" aria-pressed="false">待补结构</button><small>{maintenance_summary}</small></div></details>
    </div>
    <div class="skill-column-head"><span></span><span>能力</span><span>状态</span><span>近 30 天关联任务</span><span>最近登记</span><span></span></div>
    <div id="skillCatalog">{''.join(skill_sections)}</div>
    <div class="panel card skill-empty" id="skillEmpty" hidden>没有匹配的 Skill。可以清除筛选后重新查看。</div>
    </section>'''
    content += r'''
    <style>
    .skill-overview{grid-template-columns:minmax(280px,.9fr) minmax(440px,1.25fr) auto}.skill-health-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));overflow:hidden;border:1px solid var(--line);border-radius:8px}.skill-health-summary{display:flex;align-items:baseline;justify-content:center;gap:5px;min-width:0;padding:9px 8px;border:0;border-right:1px solid var(--line);background:var(--surface);cursor:pointer}.skill-health-summary:last-child{border-right:0}.skill-health-summary b{font-size:15px}.skill-health-summary span{font-size:9px;white-space:nowrap}.skill-health-summary:hover,.skill-health-summary.active{box-shadow:inset 0 -2px 0 currentColor}.skill-health-summary.available{color:#166534;background:#f0fdf4}.skill-health-summary.executor-provided{color:#1d4ed8;background:#eff6ff}.skill-health-summary.needs-config{color:#92400e;background:#fffbeb}.skill-health-summary.unavailable{color:#991b1b;background:#fef2f2}.skill-cache-notice{display:flex;align-items:center;gap:10px;padding:9px 12px;margin-top:-6px;color:var(--secondary);font-size:10px}.skill-cache-notice strong{color:var(--ink)}.skill-cache-notice.repairing,.skill-cache-notice.stale{border-color:#f59e0b;background:#fffbeb}.skill-cache-notice.unavailable{border-color:#ef4444;background:#fef2f2}.skill-toolbar{display:grid;gap:8px;padding:10px 12px}.skill-toolbar-main,.skill-status-filters{display:flex;align-items:center;gap:7px}.skill-toolbar-main input{width:min(420px,42vw);padding:7px 9px}.skill-toolbar-main select{width:150px;padding:7px 9px}.skill-result-count{margin-left:auto;color:var(--muted);font-size:10px}.skill-status-filters{padding-top:8px;border-top:1px solid var(--line-soft);flex-wrap:wrap}.skill-status-filters .button{margin-left:auto}.skill-maintenance-filters{border-top:1px solid var(--line-soft);padding-top:7px}.skill-maintenance-filters summary{width:max-content;color:var(--muted);font-size:9px;font-weight:750;cursor:pointer}.skill-maintenance-filters>div{display:flex;align-items:center;gap:5px;flex-wrap:wrap;padding-top:7px}.skill-maintenance-filters>div>span,.skill-maintenance-filters small{color:var(--muted);font-size:9px}.skill-maintenance-filters small{margin-left:auto}.skill-column-head,.skill-row>summary{display:grid;grid-template-columns:14px minmax(280px,1fr) 112px 130px 112px 16px;gap:10px;align-items:center}.skill-column-head{padding:1px 12px 5px 10px;color:var(--muted);font-size:8px}.skill-category{margin:0 0 10px}.skill-category-head{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;background:var(--line-soft);border:1px solid var(--line);border-bottom:0;border-radius:8px 8px 0 0}.skill-category-head>div{display:flex;align-items:center;gap:7px}.skill-category-head h2{margin:0;font-size:12px}.skill-category-head>span{color:var(--muted);font-size:9px}.skill-category-dot{width:6px;height:6px;border-radius:999px;background:var(--ink)}.skill-list{min-width:0;overflow:visible;border:1px solid var(--line);border-radius:0 0 8px 8px;background:var(--surface)}.skill-row{min-width:0;border-bottom:1px solid var(--line-soft)}.skill-row:last-child{border-bottom:0}.skill-row[open]{background:#fbfcfe}.skill-row>summary{min-width:0;min-height:58px;padding:7px 12px 7px 10px;cursor:pointer;list-style:none}.skill-row>summary::-webkit-details-marker{display:none}.skill-row>summary:hover{background:var(--line-soft)}.skill-row.child>summary{padding-left:24px}.skill-tree-mark{color:var(--muted);font-size:9px;text-align:center}.skill-row.root .skill-tree-mark{font-size:6px}.skill-identity{display:grid;min-width:0;gap:3px}.skill-identity strong{font-size:12px}.skill-identity small{overflow:hidden;color:var(--secondary);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.skill-usage,.skill-last{display:grid;gap:2px;min-width:0}.skill-usage b{font-size:14px}.skill-usage small,.skill-last b,.skill-last small{overflow:hidden;color:var(--muted);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.skill-last b{color:var(--secondary);font-size:9px}.skill-disclosure{color:var(--muted);font-size:14px;transition:transform .12s}.skill-row[open] .skill-disclosure{transform:rotate(90deg)}.skill-detail{display:grid;grid-template-columns:1fr 1.35fr 1.15fr 1.35fr;gap:14px;padding:11px 32px 13px 48px;border-top:1px solid var(--line-soft)}.skill-detail>div{min-width:0}.skill-detail span{display:block;margin-bottom:4px;color:var(--muted);font-size:8px;font-weight:750}.skill-detail p,.skill-detail small{margin:0;color:var(--secondary);font-size:9px;line-height:1.55;overflow-wrap:anywhere}.skill-detail small{display:block;margin-top:4px;color:var(--muted)}.skill-detail code{font-size:8px}.skill-detail a{font-weight:700}
    @media(max-width:1000px){.skill-overview{grid-template-columns:1fr 1fr}.skill-overview-copy{grid-column:1/-1}.skill-column-head{display:none}.skill-row>summary{grid-template-columns:14px minmax(220px,1fr) 112px 115px 16px}.skill-last{display:none}.skill-detail{grid-template-columns:1fr 1fr;padding-left:32px}}
    @media(max-width:650px){.skill-overview{grid-template-columns:1fr}.skill-overview-copy{grid-column:auto}.skill-health-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.skill-health-summary:nth-child(2){border-right:0}.skill-health-summary:nth-child(-n+2){border-bottom:1px solid var(--line)}.skill-toolbar-main{align-items:stretch;flex-direction:column}.skill-toolbar-main input,.skill-toolbar-main select{width:100%}.skill-result-count{margin-left:0}.skill-status-filters{gap:5px}.skill-status-filters .button{margin-left:0}.skill-maintenance-filters>div{align-items:flex-start}.skill-maintenance-filters small{width:100%;margin-left:0}.skill-row.child{box-shadow:inset 3px 0 0 var(--line)}.skill-row.child>summary{padding-left:10px}.skill-row>summary{grid-template-columns:minmax(0,1fr) auto 16px;grid-template-areas:"identity status disclosure" "identity usage disclosure";gap:4px 8px;min-height:70px;padding:9px 10px}.skill-tree-mark{display:none}.skill-identity{grid-area:identity}.skill-identity strong{font-size:13px}.skill-identity small{white-space:normal;line-height:1.4}.skill-row>summary>.skill-status{grid-area:status}.skill-usage{grid-area:usage;text-align:right}.skill-last{display:none}.skill-disclosure{grid-area:disclosure}.skill-detail{grid-template-columns:1fr;padding:10px 14px}.skill-cache-notice{align-items:flex-start;flex-direction:column}}
    </style>
    <script>
    (()=>{const root=document.querySelector('.skill-settings');if(root?.dataset.skillUsageReady==='0'){const next=new URL(location.href);if(next.searchParams.has('skill_usage')){next.searchParams.delete('skill_usage');history.replaceState(null,'',next.pathname+(next.searchParams.size?'?'+next.searchParams:''))}}})();
    </script>
    <script>
    (()=>{const params=new URLSearchParams(location.search),search=document.getElementById('skillSearch'),category=document.getElementById('skillCategory'),statusFilters=[...document.querySelectorAll('[data-skill-filter]')],summaryFilters=[...document.querySelectorAll('[data-skill-summary-status]')],usageFilters=[...document.querySelectorAll('[data-skill-usage]')],structureToggle=document.querySelector('[data-skill-structure-toggle]'),cards=[...document.querySelectorAll('[data-skill-card]')],empty=document.getElementById('skillEmpty'),resultCount=document.getElementById('skillResultCount'),clear=document.getElementById('skillClearFilters');const supported=['available','executor-provided','needs-config','unavailable','unverified'];let requestedStatus=params.get('skill_status');if(requestedStatus==='conditional')requestedStatus='needs-config';let status=supported.includes(requestedStatus)?requestedStatus:'all',usageMode=['recent','low','never'].includes(params.get('skill_usage'))?params.get('skill_usage'):'all',structure=params.get('skill_structure')==='pending'?'pending':'all';function filterSkills(){const query=(search?.value||'').trim().toLowerCase(),categoryValue=category?.value||'all';let visible=0;cards.forEach(card=>{const usageMatch=usageMode==='all'||usageMode==='recent'&&card.dataset.skillRecent==='1'||usageMode==='low'&&card.dataset.skillFrequency==='low'||usageMode==='never'&&card.dataset.skillFrequency==='never',show=(status==='all'||card.dataset.skillStatus===status)&&(categoryValue==='all'||card.dataset.skillCategory===categoryValue)&&(structure==='all'||card.dataset.skillStructure===structure)&&usageMatch&&(!query||card.dataset.skillSearch.includes(query));card.hidden=!show;if(show)visible++});document.querySelectorAll('[data-skill-category-section]').forEach(section=>{const sectionCards=[...section.querySelectorAll('[data-skill-card]')],sectionVisible=sectionCards.filter(card=>!card.hidden).length;section.hidden=sectionVisible===0;const count=section.querySelector('[data-category-visible-count]');if(count)count.textContent=sectionVisible+' 个'});statusFilters.forEach(button=>button.classList.toggle('active',button.dataset.skillFilter===status));summaryFilters.forEach(button=>button.classList.toggle('active',button.dataset.skillSummaryStatus===status));usageFilters.forEach(button=>button.classList.toggle('active',button.dataset.skillUsage===usageMode));structureToggle.classList.toggle('active',structure==='pending');structureToggle.setAttribute('aria-pressed',String(structure==='pending'));resultCount.textContent=visible+' 个结果';empty.hidden=visible>0;const next=new URLSearchParams(location.search);query?next.set('skill_q',query):next.delete('skill_q');status==='all'?next.delete('skill_status'):next.set('skill_status',status);usageMode==='all'?next.delete('skill_usage'):next.set('skill_usage',usageMode);structure==='all'?next.delete('skill_structure'):next.set('skill_structure',structure);categoryValue==='all'?next.delete('skill_category'):next.set('skill_category',categoryValue);history.replaceState(null,'',location.pathname+(next.size?'?'+next:''))}statusFilters.forEach(button=>button.addEventListener('click',()=>{status=button.dataset.skillFilter;filterSkills()}));summaryFilters.forEach(button=>button.addEventListener('click',()=>{status=status===button.dataset.skillSummaryStatus?'all':button.dataset.skillSummaryStatus;filterSkills()}));usageFilters.forEach(button=>button.addEventListener('click',()=>{usageMode=button.dataset.skillUsage;filterSkills()}));structureToggle.addEventListener('click',()=>{structure=structure==='pending'?'all':'pending';filterSkills()});search.value=params.get('skill_q')||'';search.addEventListener('input',filterSkills);category.value=params.get('skill_category')||'all';if(!category.value)category.value='all';category.addEventListener('change',filterSkills);clear.addEventListener('click',()=>{search.value='';category.value='all';status='all';usageMode='all';structure='all';filterSkills()});filterSkills()})();
    </script>
    <script>
    (()=>{const watched='[data-skill-filter],[data-skill-summary-status],[data-skill-usage],#skillClearFilters';const sync=()=>{document.querySelectorAll('[data-skill-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.classList.contains('active'))));document.querySelectorAll('[data-skill-summary-status],[data-skill-usage]').forEach(button=>button.setAttribute('aria-pressed',String(button.classList.contains('active'))))};document.addEventListener('click',event=>{if(event.target.closest(watched))requestAnimationFrame(sync)});sync()})();
    </script>'''
    return runtime._layout("Skills", content, token)


def render_settings(token: str, notice: str = "", error: str = "") -> str:
    """Render the single compact settings surface for runtime capabilities."""
    executors = runtime.executor_status()
    ready_executors = 0
    for item in executors.values():
        available = bool(item.get("configured"))
        ready_executors += int(available)

    catalog = runtime.skill_catalog()
    health = runtime.check_skill_health.read_snapshot()
    snapshot_state = str(health.get("snapshot_state") or ("stale" if health.get("checked_at") else "missing"))
    if snapshot_state not in {"fresh", "stale", "missing"}:
        snapshot_state = "missing"
    checked_at = runtime.html.escape(runtime.format_display_time(str(health.get("checked_at") or "")) or "未记录")
    snapshot_copy = {
        "fresh": f"上次能力检测 {checked_at} · 结果在 15 分钟有效期内",
        "stale": f"上次能力检测 {checked_at} · 结果已过期，请重新检测",
        "missing": "尚无能力检测结果，请运行健康检查",
    }[snapshot_state]

    def capability_presentation(state: dict[str, object] | None, profile: str) -> dict[str, str]:
        presented = runtime.health_presentation(state if snapshot_state != "missing" else None, health_profile=profile)
        if snapshot_state == "stale" and presented["key"] != "unverified":
            presented = {**presented, "label": f"上次{presented['label']}", "detail": f"上次检测结果：{presented['detail']}；结果已过期，需重新检测"}
        return presented

    catalog_profiles = {str(item.get("name")): str(item.get("health_profile") or "always") for item in catalog}
    category_labels = {
        "core-governance": "核心治理", "content-production": "内容生产", "social-data": "社媒数据",
        "video-processing": "视频处理", "voice-multimodal": "语音与多模态", "archive": "归档与入库",
        "research-knowledge": "研究与知识", "system-maintenance": "系统维护",
        "feishu-integration": "飞书集成", "other": "其他",
    }
    skill_counts = {"available": 0, "executor-provided": 0, "needs-config": 0, "unavailable": 0, "unverified": 0}
    category_counts: dict[str, int] = {}
    category_issues: dict[str, int] = {}
    dependency_groups: dict[str, dict[str, object]] = {}
    skill_rows: list[dict[str, object]] = []
    for item in catalog:
        name = str(item.get("name") or "")
        display_name = str(item.get("display_name") or name)
        registered_category = str(item.get("category") or "system-maintenance")
        category = registered_category if registered_category in category_labels else "other"
        category_label = category_labels[category]
        category_counts[category] = category_counts.get(category, 0) + 1
        profile = str(item.get("health_profile") or "always")
        state = runtime.snapshot_health_state(health, health_profile=profile, skill_name=name)
        presented = capability_presentation(state, profile)
        skill_counts[presented["key"]] = skill_counts.get(presented["key"], 0) + 1
        if presented["key"] in {"needs-config", "unavailable", "unverified"}:
            category_issues[category] = category_issues.get(category, 0) + 1
        if presented["key"] in {"needs-config", "unavailable"}:
            group = dependency_groups.setdefault(profile, {"count": 0, "details": []})
            group["count"] = int(group["count"]) + 1
            if presented["detail"] not in group["details"]:
                group["details"].append(presented["detail"])
        description = str(item.get("description") or "")
        search_text = " ".join((name, display_name, category_label, description)).lower()
        skill_rows.append({
            "name": name, "display_name": display_name, "description": description, "category": category, "category_label": category_label,
            "profile": profile, "state": presented["key"], "state_label": presented["label"],
            "details": [("登记名", name), ("", presented["detail"]), ("健康配置", profile), ("登记文件", str(item.get("path") or ""))],
        })

    integration_cards: list[str] = []
    integration_issues = 0
    integration_total = 0
    registry = runtime.native_execution_registry()
    for registry_key, kind_label in (("mcp_integrations", "MCP"), ("tool_integrations", "本机工具")):
        for item in registry.get(registry_key, []):
            integration_total += 1
            owner = str(item.get("owner_skill") or "gstudio")
            profile = str(item.get("health_profile") or "always")
            state = runtime.snapshot_health_state(
                health,
                health_profile=profile,
                skill_name=owner if catalog_profiles.get(owner) == profile else "",
            )
            presented = capability_presentation(state, profile)
            issue = presented["key"] in {"needs-config", "unavailable", "unverified"}
            integration_issues += int(issue)
            integration_cards.append(
                f'''<article class="integration-card" data-integration data-integration-kind="{runtime.html.escape(kind_label, quote=True)}" data-setting-state="{runtime.html.escape(presented['key'], quote=True)}">
                <div class="integration-card-head"><span>{runtime.html.escape(kind_label)}</span><span class="skill-status {runtime.html.escape(presented['key'], quote=True)}">{runtime.html.escape(presented['label'])}</span></div>
                <strong>{runtime.html.escape(str(item.get('display_name') or item.get('id')))}</strong><p>{runtime.html.escape(str(item.get('description') or '用途未登记'))}</p>{f'<p class="integration-issue">{runtime.html.escape(presented["detail"])}</p>' if issue else ''}<small>归属 {runtime.html.escape(owner)}</small></article>'''
            )

    agent_cards, agent_count, agent_ready, adapter_count = _agent_catalog(token)
    ledger = runtime.ember_agent.read_ledger()
    stale_run_count = 0
    now = runtime.datetime.datetime.now(runtime.datetime.timezone.utc)
    for run in ledger.get("runs", []):
        if not isinstance(run, dict) or run.get("state") != "running":
            continue
        try:
            started_at = runtime.datetime.datetime.fromisoformat(str(run.get("started_at") or ""))
        except ValueError:
            continue
        if started_at.tzinfo is not None and now - started_at.astimezone(runtime.datetime.timezone.utc) > runtime.ember_agent.RUN_AUTHORIZATION_MAX_AGE:
            stale_run_count += 1
    categories = [
        {"key": category, "label": label, "count": category_counts[category],
         "note": f"{category_issues[category]} 待核对" if category_issues.get(category) else ""}
        for category, label in category_labels.items() if category_counts.get(category, 0)
    ]
    refresh_form = runtime._form("/actions/refresh-settings-health", token, {"return_to": "/settings"}, "运行健康检查", "button")
    config_path = runtime.Path(runtime.ember_env("EMBER_EXECUTOR_CONFIG") or runtime.local_config_root() / "executors.json")
    saved_settings = runtime.executor_settings.read_settings()
    local_executors = list(saved_settings.get("executors") or [])
    executors = {item["id"]: executors.get(item["id"], {}) for item in local_executors}
    ready_executors = sum(bool(item.get("configured")) for item in executors.values())
    registry_readable = bool(saved_settings.get("registry_readable", True))
    environment_metric = f"{ready_executors}/{len(executors)}" if registry_readable else "未知"
    execution_html = runtime.settings_page.execution({
        "environment": saved_settings, "config_path": config_path,
        "form": {"action": "/actions/save-executor-settings", "check_action": "/actions/check-executor-settings",
                 "hidden": [("csrf", token), ("return_to", "/settings#execution")]},
    })
    skill_issue_count = sum(skill_counts.get(key, 0) for key in ("needs-config", "unavailable", "unverified"))
    capability_summary = " · ".join(
        f"{skill_counts[key]} 项{label}"
        for key, label in (("needs-config", "待配置"), ("unavailable", "依赖待核对"), ("unverified", "待检测"))
        if skill_counts[key]
    ) or ("尚无能力检测结果" if snapshot_state == "missing" else "上次能力检测无异常 · 结果已过期" if snapshot_state == "stale" else "能力检测无异常")
    issue_status = (
        f'<a class="settings-attention-link" href="#skills" data-skill-issues-link>{"上次检测：" if snapshot_state == "stale" else ""}{capability_summary}</a>'
        if skill_issue_count else f'<span class="settings-ready-label">{capability_summary}</span>'
    )
    dependency_copy = {
        "lark-cli": ("飞书能力 · 共用飞书登录", "共用 lark-cli 登录配置，按需核对用户授权。"),
        "alist-rclone": ("归档连接 · AList / rclone", "共用归档连接，使用相关归档流程前核对依赖。"),
    }
    dependency_groups_data = []
    for profile, group in dependency_groups.items():
        title, guidance = dependency_copy.get(profile, (f"共用依赖 · {profile}", "同一健康配置关联多项能力，先核对共同依赖。"))
        dependency_groups_data.append({"profile": profile, "title": title, "guidance": guidance, "detail": "；".join(group["details"]), "count": group["count"]})
    skills_data = {
        "snapshot": snapshot_state, "summary": capability_summary, "categories": categories, "rows": skill_rows,
        "dependencies": {"note": "上次检测已过期，需重新检测。" if snapshot_state == "stale" else "按共同依赖归类。",
                         "groups": dependency_groups_data},
    }
    head_page = {
        "actions_html": f'{refresh_form}<small data-capability-snapshot="{snapshot_state}">{snapshot_copy}</small>',
        "nav": [{"href": "#execution", "label": "执行环境"}, {"href": "#skills", "label": "Skills"}, {"href": "#agents", "label": "Agents"}, {"href": "#integrations", "label": "集成能力"}],
    }

    content = runtime.flash_message(notice, error) + f'''<section class="settings-hub paper-management-page">
    {runtime.settings_page.head(head_page)}

    {execution_html}

    <section class="settings-health-summary" data-settings-health aria-live="polite"><div class="settings-health-main"><span class="settings-health-state" id="settingsHealthState">正在读取系统状态</span><small id="settingsHealthDetail">检查共享空间、索引、运行源码与核心页面。</small></div><div class="settings-health-metrics"><span><b>{environment_metric}</b> 执行器已安装</span><span><b>{agent_ready}/{adapter_count}</b> Agent 适配器已登记</span>{issue_status}</div></section>

    {runtime.settings_page.skills(skills_data)}

    <section class="settings-catalog-section" id="agents"><div class="settings-section-head"><div><h2>Agents</h2></div><span>{agent_count} 个 Agent · {agent_ready}/{adapter_count} 适配器已登记</span></div><div class="settings-agent-grid">{agent_cards}</div>{runtime._form('/actions/agent-expire-runs', token, {'return_to': '/settings#agents'}, f'关闭过期运行记录（{stale_run_count}）', 'button ghost') if stale_run_count else ''}</section>

    <section class="settings-catalog-section" id="integrations" data-capability-snapshot="{snapshot_state}"><div class="settings-section-head"><div><h2>集成能力</h2></div><span>{integration_total} 项已登记 · {integration_issues} 项待核对</span></div><div class="settings-integration-grid">{''.join(integration_cards)}</div></section>


    </section>'''
    content += f'<style>{runtime.SETTINGS_STYLE}</style><script src="/assets/settings.js?v={runtime.SETTINGS_VERSION}"></script>'
    content += r'''<script>(()=>{
      const summary=document.querySelector('[data-settings-health]'),state=document.getElementById('settingsHealthState'),detail=document.getElementById('settingsHealthDetail');
      if(!summary||!state||!detail)return;
      const maxReads=6,retryDelay=2000;let reads=0;
      const label=(ready,ok,bad)=>ready?ok:bad,indexUpdating=item=>['stale','refreshing'].includes(item.state)||item.refreshing===true;
      async function readHealth(){
        if(!summary.isConnected)return;
        reads++;
        try{
          const response=await fetch('/health',{headers:{Accept:'application/json'},signal:AbortSignal.timeout(5000)});
          if(!response.ok)throw new Error('health request failed');
          const payload=await response.json(),readiness=payload.readiness||{},checks=readiness.checks||{},ready=readiness.status==='ready';
          const root=checks.shared_root||{},task=checks.task_index||{},search=checks.home_search_index||{},source=checks.runtime_source||{},routes=checks.page_routes||{};
          const updating=indexUpdating(task)||indexUpdating(search),otherIssue=!root.available||source.state!=='ready'||(!indexUpdating(task)&&!['ok','ready'].includes(task.state))||(!indexUpdating(search)&&search.state!=='ready')||['stalled','error'].includes(routes.state)||checks.pdf_preview&&checks.pdf_preview.state!=='ready';
          summary.dataset.healthState=ready?'ready':updating&&!otherIssue?'updating':'degraded';
          state.textContent=ready?'系统运行正常':updating&&!otherIssue?'索引更新中':'系统部分能力异常';
          detail.textContent=[label(root.available,'共享空间正常','共享空间不可用'),indexUpdating(task)?'任务索引更新中':label(['ok','ready'].includes(task.state),'任务索引正常','任务索引异常'),indexUpdating(search)?'搜索索引更新中':label(search.state==='ready','搜索索引正常','搜索索引异常'),label(source.state==='ready','运行源码一致','运行源码需重载'),label(!['stalled','error'].includes(routes.state),'核心页面正常','核心页面异常')].join(' · ');
          if(updating&&reads<maxReads)setTimeout(readHealth,retryDelay);
          else if(updating)detail.textContent+=' · 稍后刷新查看最新状态';
        }catch(error){summary.dataset.healthState='unknown';state.textContent='系统状态暂时无法读取';detail.textContent='能力检测仍可单独运行，请稍后重试。'}
      }
      readHealth();
    })();</script>'''

    content += f'<style>{runtime.EXECUTOR_SETTINGS_STYLE}</style><script src="/assets/executor-settings.js?v={runtime.EXECUTOR_SETTINGS_VERSION}"></script>'
    return runtime._layout("设置", content, token)
