"""Projects view (项目视图): one card per project plus the independent-task card, each with its
current mainline, recent counts and a three-column task board, filtered by work category.

ember_ui/static/projects.js drives the page once rendered (category filter, task drag between board
columns, card reordering); projects.css holds its styles. render(page) takes one dictionary and
returns markup only (no inline script, style or event attribute). Keys (optional ones may be omitted):

  counts             {projects, active, attention} shown under the heading
  head_actions_html  markup after the heading's summary (for example a 新建项目 button)
  filters            [(key, label, count)]; the first is selected. A card shows under a filter when
                     its category equals the key; "all" shows every card
  empty_html         inner markup of the notice shown when a filter matches no card
  csrf               token the default save actions send
  cards              [card]; a card is
                     {slug, title, href, title_attrs, category, independent, status_key, status_label,
                      focus, focus_href, stats: [(count, label)], lines: [text], note,
                      actions: [{label, href, primary, attrs}], board_label,
                      columns: [{key, label, empty, rows: [row]}]}
                     and a row is {task_id, title, href, task_line, return_column}. `attrs` and
                     `title_attrs` are [(name, value)] added to the link. A row in the "important"
                     column shows which column it returns to.
"""
from __future__ import annotations

import html

RETURN_LABELS = {"completed": "近30天完成", "active": "进行中"}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _attrs(pairs) -> str:
    return "".join(f' {_esc(name)}="{_esc(value)}"' for name, value in pairs or ())


def column(spec: dict, project: str) -> str:
    key, rows = spec["key"], spec.get("rows") or []
    if not rows:
        body = f'<span class="project-view-task empty">{html.escape(spec.get("empty", ""))}</span>'
    else:
        items = []
        for row in rows:
            task_id, title = _esc(row["task_id"]), html.escape(row.get("title") or row["task_id"])
            back = row.get("return_column") or ""
            tag = '<span class="task-group-tag">任务主线</span>' if row.get("task_line") else ""
            state = f'<span class="project-task-state {_esc(back)}">{html.escape(RETURN_LABELS.get(back, "原状态"))}</span>' if key == "important" else ""
            important = "true" if key == "important" else "false"
            items.append(f'<div class="project-view-task-wrap"><a class="project-view-task" draggable="true" data-task-id="{task_id}" data-return-column="{_esc(back)}" data-important="{important}" href="{_esc(row["href"])}" title="{_esc(row.get("title") or row["task_id"])}"><span class="project-task-name">{title}{tag}</span>{state}</a></div>')
        body = "".join(items)
    return f'<div class="project-view-column" data-board-column="{_esc(key)}" data-project="{_esc(project)}"><div class="project-view-column-head">{html.escape(spec["label"])} ({len(rows)})</div><div class="project-view-column-body">{body}</div></div>'


def card(spec: dict) -> str:
    slug, title, independent = spec["slug"], spec["title"], spec.get("independent")
    focus = html.escape(spec.get("focus") or "")
    if spec.get("focus_href"):
        focus = f'<a href="{_esc(spec["focus_href"])}">{focus}</a>'
    stats = " · ".join(f"<b>{count}</b> {html.escape(label)}" for count, label in spec.get("stats", ()))
    lines = "".join(f"<div>{html.escape(line)}</div>" for line in spec.get("lines", ()))
    actions = "".join(
        f'<a class="button {"primary" if action.get("primary") else "ghost"}" href="{_esc(action["href"])}"{_attrs(action.get("attrs"))}>{html.escape(action["label"])}</a>'
        for action in spec.get("actions", ())
    )
    board = "".join(column(item, slug) for item in spec.get("columns", ()))
    link = f'<a href="{_esc(spec["href"])}"{_attrs(spec.get("title_attrs"))}>{html.escape(title)}</a>'
    if independent:
        extra, heading = ' independent-task-overview', f'<h2 id="independentTaskTitle">{link}</h2><span class="independent-scope-badge">非项目</span>'
        tail = ' data-independent-task-overview aria-labelledby="independentTaskTitle"'
    else:
        extra, heading, tail = "", f'<h2>{link}</h2><span class="project-status {_esc(spec.get("status_key", ""))}">{html.escape(spec.get("status_label", ""))}</span>', ""
    return (f'<article class="project-view-card{extra}" draggable="false" data-project-card="{_esc(slug)}" data-project-title="{_esc(title)}" data-work-category="{_esc(spec.get("category", ""))}"{tail}>'
            f'<div class="project-info"><div class="card-head">{heading}</div>'
            f'<div class="project-focus"><div class="focus-label">当前主线</div><div class="focus-text">{focus}</div></div>'
            f'<div class="project-metrics"><div class="project-recent-stats"><div>{stats}</div>{lines}</div><div class="project-center-meta"><span>{html.escape(spec.get("note", ""))}</span></div></div>'
            f'<div class="card-actions">{actions}</div></div>'
            f'<div class="project-view-board" aria-label="{_esc(spec.get("board_label", "项目任务看板"))}">{board}</div></article>')


def render(page: dict) -> str:
    counts = page.get("counts") or {}
    filters = "".join(
        f'<button type="button" class="chip{" active" if index == 0 else ""}" data-project-category-filter="{_esc(key)}" aria-pressed="{"true" if index == 0 else "false"}">{html.escape(label)} <small>{count}</small></button>'
        for index, (key, label, count) in enumerate(page.get("filters", ()))
    )
    cards = "".join(card(item) for item in page.get("cards", ())) or '<div class="project-view-empty">暂无项目或独立任务数据</div>'
    csrf = f' data-csrf="{_esc(page["csrf"])}"' if page.get("csrf") else ""
    return f'''<header class="project-view-page-head">
      <h1>项目视图</h1><p>{counts.get("projects", 0)} 个项目 · {counts.get("active", 0)} 项进行中 · {counts.get("attention", 0)} 个需要关注</p>{page.get("head_actions_html", "")}
    </header><nav class="chips project-category-filters" aria-label="工作分类">{filters}</nav>
    <p class="library-empty" id="projectCategoryEmpty" role="status" aria-live="polite" hidden>{page.get("empty_html", "该分类尚未登记项目。")}</p>
    <section class="project-view-grid" aria-label="项目概览"{csrf}>
      {cards}
    </section>'''
