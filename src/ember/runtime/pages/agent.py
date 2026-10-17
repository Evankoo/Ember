"""Page presenters; data and action helpers supplied by the runtime."""
from __future__ import annotations
from .. import gstudio_workbench as runtime

def render_agents(token: str, notice: str = "", error: str = "") -> str:
    agent_id = "material-manager"
    values, _ = runtime.gstudio_agent.agent_definition(agent_id)
    statuses = runtime.gstudio_agent.executor_status(agent_id)
    ledger = runtime.gstudio_agent.read_ledger()
    runs = [
        item for item in ledger.get("runs", [])
        if isinstance(item, dict) and item.get("agent_id") == agent_id
    ]
    recent = list(reversed(runs[-8:]))
    state_labels = {
        "available": ("可用", "available"),
        "degraded": ("降级可用", "needs-config"),
        "needs_configuration": ("需配置", "needs-config"),
        "unavailable": ("不可用", "unavailable"),
    }
    executor_labels = {"codex": "Codex", "opencode": "OpenCode", "hermes": "Hermes"}
    executor_rows: list[str] = []
    for executor, status in statuses.items():
        label, css = state_labels.get(str(status.get("state") or ""), ("未验证", "needs-config"))
        policy = runtime.gstudio_agent.executor_model_policy(values, executor)
        model = policy["primary_model"] if status.get("primary_ready") else policy["fallback_model"] if status.get("fallback_ready") else "未配置"
        executor_rows.append(
            f'''<article class="integration-row"><span class="integration-kind">Agent</span>
            <div class="integration-identity"><strong>{runtime.html.escape(executor_labels.get(executor, executor))}</strong><small>{runtime.html.escape(str(status.get('resolved') or ''))}</small></div>
            <span class="skill-status {css}">{label}</span><span class="integration-owner">{runtime.html.escape(model)}</span>
            <div class="integration-detail">{'主模型 · 按模式推理' if status.get('primary_ready') else '备用模型 · 按模式推理' if status.get('fallback_ready') else '需要配置声明模型'}</div></article>'''
        )
    run_rows = ''.join(
        f'''<div class="model-row"><strong>{runtime.html.escape(str(item.get('state') or ''))}</strong><span>{runtime.html.escape(str(item.get('mode') or ''))} · {runtime.html.escape(str(item.get('executor') or ''))} · {runtime.html.escape(str(item.get('model') or ''))}</span><small>{runtime.html.escape(runtime.format_display_time(str(item.get('updated_at') or '')))}</small></div>'''
        for item in recent
    ) or '<div class="empty" style="display:block">尚无资料管理员运行记录。</div>'
    installed = bool(statuses.get("hermes", {}).get("installed"))
    install_label = "更新 Hermes 适配器" if installed else "安装 Hermes 适配器"
    mode_reasoning = runtime.html.escape(str(values.get("mode_reasoning") or "未配置"))
    model_order = "；".join(
        f"{executor_labels[executor]}: {runtime.gstudio_agent.executor_model_policy(values, executor)['primary_model']} → {values['fallback_model']}"
        for executor in executor_labels
    )
    content = runtime.flash_message(notice, error) + f'''<section class="settings-page execution-settings">
    <header class="panel settings-overview"><div class="settings-overview-copy"><span class="settings-kicker">SETTINGS · AGENTS</span><h1>Agents</h1><p>Agent 是执行层，不改变项目与任务层级；所有执行器读取同一份 余烬 · Ember canonical 定义。</p></div><div class="settings-metrics"><span><b>1</b><small>已登记 Agent</small></span><span><b>{sum(1 for item in statuses.values() if item.get('state') in {'available','degraded'})}</b><small>可运行适配器</small></span><span><b>{len(runs)}</b><small>累计运行</small></span></div></header>
    <section class="settings-section"><div class="settings-section-head"><div><h2>资料管理员</h2><p>{runtime.html.escape(values['description'])}</p><p>它是受治理流程的后台执行 Agent，不在任务与资料页面提供独立入口；只有归档、来源入库或已确认整理真正进入执行阶段时，系统才会调用。</p></div><span>由流程调用</span></div>
      <article class="panel executor-card"><div class="executor-card-head"><div><h2>material-manager</h2><p>文件管理、项目归档、EBrain 来源原始入库与已确认任务整理</p></div><span class="skill-status available">已启用</span></div>
       <div class="executor-card-facts"><span><small>模型顺序</small>{runtime.html.escape(model_order)}</span><span><small>模式推理</small>{mode_reasoning}</span><span><small>canonical</small>agents/material-manager/AGENT.md</span></div>
      <div class="model-list"><div class="model-row">普通文件管理 · 余烬 · Ember <code>gstudio</code></div><div class="model-row">项目归档 · 余烬 · Ember <code>project-intake</code></div><div class="model-row">来源入库 · EBrain <code>ebrain-in</code>（外部引用）</div><div class="model-row">已确认任务整理 · 余烬 · Ember <code>gstudio-organization</code></div></div>
       <div class="settings-overview-actions"><form method="post" action="/actions/agent-install"><input type="hidden" name="csrf" value="{runtime.html.escape(token, quote=True)}"><input type="hidden" name="agent_id" value="material-manager"><input type="hidden" name="return_to" value="/settings/agents"><button class="button" type="submit">{install_label}</button></form><form method="post" action="/actions/agent-verify"><input type="hidden" name="csrf" value="{runtime.html.escape(token, quote=True)}"><input type="hidden" name="agent_id" value="material-manager"><input type="hidden" name="return_to" value="/settings/agents"><button class="button ghost" type="submit">验证 Agent</button></form><form method="post" action="/actions/agent-expire-runs"><input type="hidden" name="csrf" value="{runtime.html.escape(token, quote=True)}"><input type="hidden" name="return_to" value="/settings/agents"><button class="button ghost" type="submit">收口过期运行</button></form></div></article>
    </section>
    <section class="settings-section"><div class="settings-section-head"><div><h2>执行器适配</h2><p>缺少对应执行器的主模型时只允许显式降级到 DeepSeek，不使用执行器默认模型。</p></div></div><div class="integration-table">{''.join(executor_rows)}</div></section>
    <section class="settings-section"><div class="settings-section-head"><div><h2>最近运行</h2><p>共享台账 revision {int(ledger.get('revision') or 0)}，不保存提示词、凭据或文件正文。</p></div></div><div class="model-list">{run_rows}</div></section>
    </section>'''
    content += '''<style>
    .execution-settings{display:grid;max-width:1480px;margin:0 auto;gap:16px}.execution-settings .settings-overview{display:grid;grid-template-columns:minmax(320px,1fr) auto;align-items:center;gap:22px;padding:18px 20px}.execution-settings .settings-kicker{color:var(--muted);font-size:9px;font-weight:800;letter-spacing:.12em}.execution-settings .settings-overview h1{margin:3px 0 5px;font-size:26px}.execution-settings .settings-overview p,.execution-settings .settings-section-head p{margin:0;color:var(--muted);font-size:11px;line-height:1.55}.execution-settings .settings-metrics{display:grid;grid-template-columns:repeat(3,minmax(92px,1fr));overflow:hidden;border:1px solid var(--line);border-radius:8px}.execution-settings .settings-metrics span{display:grid;gap:2px;padding:9px 13px;border-right:1px solid var(--line);text-align:center}.execution-settings .settings-metrics span:last-child{border-right:0}.execution-settings .settings-metrics b{font-size:18px}.execution-settings .settings-metrics small{color:var(--muted);font-size:9px}.execution-settings .settings-section{display:grid;gap:8px}.execution-settings .settings-section-head{display:flex;align-items:end;justify-content:space-between;gap:16px;padding:0 2px}.execution-settings .settings-section-head h2{margin:0 0 2px;font-size:15px}.execution-settings .settings-section-head>span{color:var(--muted);font-size:10px}.execution-settings .executor-card{min-width:0;padding:14px 16px}.execution-settings .executor-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.execution-settings .executor-card h2{margin:0;font-size:15px}.execution-settings .executor-card-head p{margin:3px 0 0;color:var(--muted);font-size:10px}.execution-settings .executor-card-facts{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:13px;padding-top:11px;border-top:1px solid var(--line-soft)}.execution-settings .executor-card-facts span{min-width:0;color:var(--secondary);font-size:10px;overflow-wrap:anywhere}.execution-settings .executor-card-facts small{display:block;margin-bottom:3px;color:var(--muted);font-size:8px;font-weight:750}.execution-settings .executor-card>.model-list{margin-top:12px}.execution-settings .executor-card>.settings-overview-actions{display:flex;justify-content:flex-end;gap:7px;margin-top:12px}.execution-settings .executor-card>.settings-overview-actions form{margin:0}.execution-settings .integration-table{overflow:hidden;border:1px solid var(--line);border-radius:9px;background:var(--surface)}.execution-settings .integration-row{display:grid;grid-template-columns:54px minmax(220px,1fr) 90px minmax(160px,.7fr) minmax(130px,.6fr);gap:12px;align-items:center;min-height:58px;padding:8px 12px;border-bottom:1px solid var(--line-soft)}.execution-settings .integration-row:last-child{border-bottom:0}.execution-settings .integration-kind{color:var(--muted);font-size:8px;font-weight:800;letter-spacing:.08em}.execution-settings .integration-identity{display:grid;min-width:0;gap:3px}.execution-settings .integration-identity strong{font-size:11px}.execution-settings .integration-identity small{overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.execution-settings .integration-owner{font-size:10px;font-weight:700}.execution-settings .integration-detail{color:var(--secondary);font-size:9px;line-height:1.45}.execution-settings .skill-status{display:inline-flex;align-items:center;justify-content:center;padding:3px 7px;border-radius:999px;font-size:8px;font-weight:750;white-space:nowrap}.execution-settings .skill-status.available{color:#166534;background:#dcfce7}.execution-settings .skill-status.needs-config{color:#92400e;background:#fef3c7}.execution-settings .skill-status.unavailable{color:#991b1b;background:#fee2e2}
    @media(max-width:900px){.execution-settings .settings-overview{grid-template-columns:1fr}.execution-settings .integration-row{grid-template-columns:44px minmax(0,1fr) auto;grid-template-areas:"kind identity status" "kind owner detail";gap:5px 9px}.execution-settings .integration-kind{grid-area:kind}.execution-settings .integration-identity{grid-area:identity}.execution-settings .integration-row>.skill-status{grid-area:status}.execution-settings .integration-owner{grid-area:owner}.execution-settings .integration-detail{grid-area:detail}}
    @media(max-width:600px){.execution-settings{gap:13px}.execution-settings .settings-overview{padding:14px}.execution-settings .settings-metrics{width:100%}.execution-settings .settings-section-head{align-items:flex-start;flex-direction:column}.execution-settings .executor-card-facts{grid-template-columns:1fr}.execution-settings .executor-card>.settings-overview-actions{justify-content:stretch;flex-direction:column}.execution-settings .executor-card>.settings-overview-actions .button{width:100%}.execution-settings .integration-row{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"identity status" "owner owner" "detail detail"}.execution-settings .integration-kind{display:none}.execution-settings .integration-identity small{white-space:normal}.execution-settings .settings-metrics span{padding:8px 6px}}
    </style>'''
    return runtime._layout("Agents", content, token)
