#!/usr/bin/env python3
"""Render a self-contained local HTML dashboard from GStudio task records."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import html
import json
from datetime import datetime
from pathlib import Path

from .time_format import format_display_time, parse_sort_datetime

def public_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    keys = (
        "task_id", "task_name", "description", "project", "project_title",
        "subproject", "status", "work_type", "state", "updated_at",
        "delivery_folder", "record_type",
    )
    # Default sort: newest updated_at first
    sorted_records = sorted(records, key=lambda r: parse_sort_datetime(str(r.get("updated_at") or "")), reverse=True)
    return [
        {key: (format_display_time(record.get(key)) if key == "updated_at" else record.get(key, "")) for key in keys}
        for record in sorted_records
    ]


def render_task_dashboard(
    records: list[dict[str, object]],
    generated_at: str | None = None,
    *,
    project_order: list[str] | None = None,
    project_boards: dict[str, str] | None = None,
) -> str:
    generated_at = format_display_time(generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    project_order = project_order or list(dict.fromkeys(str(item.get("project") or "") for item in records if item.get("project")))
    project_boards = project_boards or {}
    data = json.dumps(public_records(records), ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>余烬 · Ember 任务看板</title>
  <style>
    :root {{ --ink:#18212f; --muted:#687386; --paper:#f5f2eb; --card:#fffdf8; --line:#ddd7ca; --navy:#18324d; --orange:#e87532; --red:#b8473f; --green:#3f7259; --shadow:0 12px 32px rgba(24,33,47,.08); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--paper); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; }}
    a {{ color:inherit; }}
    .shell {{ max-width:1500px; margin:auto; padding:34px 28px 60px; }}
    header {{ display:flex; justify-content:space-between; align-items:flex-end; gap:24px; margin-bottom:24px; }}
    .eyebrow {{ color:var(--orange); font-size:12px; font-weight:800; letter-spacing:.16em; text-transform:uppercase; }}
    h1 {{ margin:7px 0 6px; font-size:clamp(28px,4vw,48px); letter-spacing:-.045em; }}
    .subtitle {{ color:var(--muted); font-size:14px; }}
    .header-links {{ display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; }}
    .header-links a {{ padding:9px 12px; border:1px solid var(--line); border-radius:999px; background:rgba(255,253,248,.8); text-decoration:none; font-size:13px; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:18px; }}
    .stat {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:17px 18px; box-shadow:var(--shadow); }}
    .stat b {{ display:block; font-size:28px; margin-top:4px; }}
    .stat span {{ color:var(--muted); font-size:12px; }}
    .toolbar {{ position:sticky; top:0; z-index:5; display:grid; grid-template-columns:minmax(240px,1.5fr) repeat(2,minmax(150px,.55fr)); gap:10px; padding:12px; margin-bottom:12px; background:rgba(245,242,235,.92); backdrop-filter:blur(14px); border:1px solid var(--line); border-radius:16px; }}
    input,select {{ width:100%; border:1px solid var(--line); border-radius:11px; background:var(--card); padding:12px 13px; color:var(--ink); font:inherit; outline:none; }}
    input:focus,select:focus {{ border-color:var(--orange); box-shadow:0 0 0 3px rgba(232,117,50,.13); }}
    .status-bar {{ display:flex; gap:8px; flex-wrap:wrap; margin:14px 0; }}
    .chip {{ border:1px solid var(--line); background:var(--card); color:var(--ink); border-radius:999px; padding:8px 13px; cursor:pointer; }}
    .chip.active {{ background:var(--navy); border-color:var(--navy); color:white; }}
    .result-line {{ display:flex; justify-content:space-between; color:var(--muted); font-size:13px; margin:10px 2px; }}
    .table-wrap {{ overflow:auto; background:var(--card); border:1px solid var(--line); border-radius:18px; box-shadow:var(--shadow); }}
    table {{ border-collapse:collapse; width:100%; min-width:980px; }}
    th {{ position:sticky; top:0; z-index:2; background:#efeade; color:#5b6473; text-align:left; font-size:12px; padding:12px 14px; border-bottom:1px solid var(--line); }}
    td {{ padding:14px; border-bottom:1px solid #ebe6dc; vertical-align:top; font-size:14px; }}
    tr:last-child td {{ border-bottom:0; }}
    tr:hover td {{ background:#fffbf3; }}
    .task-link {{ font-weight:750; color:var(--navy); text-decoration:none; }}
    .task-link:hover {{ color:var(--orange); text-decoration:underline; }}
    .desc {{ color:#4c5666; line-height:1.55; max-width:600px; }}
    .badge {{ display:inline-flex; align-items:center; white-space:nowrap; padding:2px 7px; border-radius:999px; font-size:11px; font-weight:600; background:#ece8df; }}
    .badge.waiting_user {{ color:#8d4d10; background:#fff0d7; }}
    .badge.blocked {{ color:#8e2d29; background:#fde5e2; }}
    .badge.active {{ color:#20533c; background:#e2f1e8; }}
    .badge.completed {{ color:#596170; background:#e8e9ec; }}
    .meta {{ color:var(--muted); font-size:12px; margin-top:5px; }}
    .actions {{ display:flex; gap:7px; flex-wrap:wrap; }}
    .actions a {{ text-decoration:none; border:1px solid var(--line); border-radius:8px; padding:6px 8px; font-size:12px; background:white; }}
    .empty {{ padding:60px 20px; text-align:center; color:var(--muted); display:none; }}
    footer {{ color:var(--muted); font-size:12px; margin-top:16px; text-align:right; }}
    #projectBoards {{ display:contents; }}
    @media (max-width:850px) {{ .shell{{padding:22px 14px 44px}} header{{align-items:flex-start;flex-direction:column}} .header-links{{justify-content:flex-start}} .stats{{grid-template-columns:repeat(2,1fr)}} .toolbar{{position:static;grid-template-columns:1fr}} }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div><div class="eyebrow">Local command center</div><h1>余烬 · Ember 任务看板</h1><div class="subtitle">任务卡是真源 · 看板随索引即时刷新 · 周一全量校准</div></div>
      <nav class="header-links"><a href="http://127.0.0.1:8765/">打开增强工作台</a><span id="projectBoards"></span></nav>
    </header>
    <section class="stats">
      <div class="stat"><span>全部任务</span><b id="statAll">0</b></div>
      <div class="stat"><span>进行中</span><b id="statActive">0</b></div>
      <div class="stat"><span>已完成</span><b id="statCompleted">0</b></div>
    </section>
    <section class="toolbar" aria-label="任务筛选">
      <input id="search" type="search" placeholder="搜索任务名称、描述或小项目…" aria-label="搜索任务">
      <select id="project" aria-label="按项目筛选"><option value="">全部项目</option></select>
      <select id="workType" aria-label="按类型筛选"><option value="">全部类型</option></select>
    </section>
    <div class="status-bar" id="statusBar" aria-label="按状态筛选"></div>
    <div class="result-line"><span id="resultCount"></span><span>任务名称可直接打开任务卡</span></div>
    <section class="table-wrap">
      <table><thead><tr><th>任务名称</th><th>任务描述</th><th>项目</th><th>状态</th><th>类型</th><th>更新时间</th><th>快捷入口</th></tr></thead><tbody id="rows"></tbody></table>
      <div class="empty" id="empty">没有符合条件的任务</div>
    </section>
    <footer>生成于 {html.escape(generated_at)} · 本地文件，不上传任务内容</footer>
  </main>
  <script>
    const TASKS={data};
    const PROJECT_ORDER={json.dumps(project_order, ensure_ascii=False)};
    const PROJECT_BOARD={json.dumps(project_boards, ensure_ascii=False)};
    const TYPE_LABEL={{text:'文字',image:'图片',video:'视频',audio:'音频',data:'数据',system:'系统',organize:'整理',archive:'归档',mixed:'混合'}};
    const STATUS_LABEL={{all:'全部',active:'进行中',completed:'已完成',waiting_user:'待确认',blocked:'阻塞'}};
    let status='all';
    const $=id=>document.getElementById(id);
    const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    const taskHref=t=>`../tasks/${{t.state||'active'}}/${{encodeURIComponent(t.task_id)}}.md`;
    const workbenchTaskHref=t=>`http://127.0.0.1:8765/tasks/${{encodeURIComponent(t.task_id)}}`;
    const deliveryHref=t=>t.delivery_folder?`../${{t.delivery_folder.replace(/^\/+/, '')}}`:'';
    const priority={{active:0,completed:1,waiting_user:2,blocked:3}};
    const subseq=(q,s)=>{{let i=0,j=0;q=q.toLowerCase();s=s.toLowerCase();while(i<q.length&&j<s.length){{if(q[i]===s[j])i++;j++;}}return i===q.length;}};
    function init(){{
      const projects=[...new Map(TASKS.map(t=>[t.project,t.project_title||t.project])).entries()].sort((a,b)=>PROJECT_ORDER.indexOf(a[0])-PROJECT_ORDER.indexOf(b[0]));
      projects.forEach(([v,label])=>$('project').insertAdjacentHTML('beforeend',`<option value="${{esc(v)}}">${{esc(label)}}</option>`));
      Object.entries(TYPE_LABEL).forEach(([v,label])=>$('workType').insertAdjacentHTML('beforeend',`<option value="${{v}}">${{label}}</option>`));
      $('statusBar').innerHTML=['all','active','completed'].map(v=>`<button class="chip ${{v==='all'?'active':''}}" data-status="${{v}}">${{STATUS_LABEL[v]}}</button>`).join('');
      $('statusBar').addEventListener('click',e=>{{if(!e.target.dataset.status)return;status=e.target.dataset.status;document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('active',x===e.target));render();}});
      ['search','project','workType'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',render));
      $('projectBoards').innerHTML=projects.filter(([v])=>PROJECT_BOARD[v]).map(([v,label])=>`<a href="${{PROJECT_BOARD[v]}}">${{esc(label)}}文案</a>`).join('');
      $('statAll').textContent=TASKS.length;$('statActive').textContent=TASKS.filter(t=>t.status==='active').length;$('statCompleted').textContent=TASKS.filter(t=>t.status==='completed').length;
      render();
    }}
    function render(){{
      const q=$('search').value.trim().toLowerCase(), project=$('project').value, type=$('workType').value;
      const filtered=TASKS.filter(t=>(status==='all'||t.status===status)&&(!project||t.project===project)&&(!type||t.work_type===type)&&(!q||subseq(q,[t.task_name,t.description,t.subproject,t.project_title].join(' ')))).sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))||(priority[a.status]??9)-(priority[b.status]??9));
      $('rows').innerHTML=filtered.map(t=>{{const delivery=deliveryHref(t);return `<tr><td><a class="task-link" href="${{workbenchTaskHref(t)}}">${{esc(t.task_name)}}</a>${{t.subproject?`<div class="meta">${{esc(t.subproject)}}</div>`:''}}</td><td class="desc">${{esc(t.description)}}</td><td>${{esc(t.project_title)}}</td><td><span class="badge ${{esc(t.status)}}">${{STATUS_LABEL[t.status]||esc(t.status)}}</span></td><td>${{TYPE_LABEL[t.work_type]||esc(t.work_type)}}</td><td>${{esc(t.updated_at)}}</td><td><div class="actions"><a href="${{workbenchTaskHref(t)}}">详情</a><a href="${{taskHref(t)}}">原始MD</a>${{delivery?`<a href="${{delivery}}">交付文件夹</a>`:''}}</div></td></tr>`}}).join('');
      $('resultCount').textContent=`显示 ${{filtered.length}} / ${{TASKS.length}} 条`;$('empty').style.display=filtered.length?'none':'block';
    }}
    init();
  </script>
</body>
</html>"""


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.index).read_text(encoding="utf-8"))
    records = payload.get("records", payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_task_dashboard(records), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
