"""Page presenters; data and action helpers supplied by the runtime."""
from __future__ import annotations
from .. import ember_workbench as runtime

def render_projects(token: str) -> str:
    projects = runtime.project_items()
    records = runtime.collect_records()
    work_categories = runtime.load_work_categories()
    now = runtime.datetime.datetime.now(runtime.datetime.timezone.utc)
    cards: dict[str, dict[str, object]] = {}
    priorities = runtime.project_priorities()
    display_slugs = [slug for slug in runtime.project_display_order() if slug in projects]
    total_active = 0
    attention_count = 0
    newest_first = lambda record: runtime._parse_record_datetime(record) or runtime.datetime.datetime.min  # noqa: E731

    def recent_completed(matching, days):
        return [
            record for record in matching
            if record.get("status") == "completed"
            and (updated := runtime._parse_record_datetime(record))
            and now - updated <= runtime.datetime.timedelta(days=days)
        ]

    def board(scope, matching):
        by_id = {str(record.get("task_id") or ""): record for record in matching}
        important = [by_id[task_id] for task_id in priorities.get(scope, []) if task_id in by_id]
        important_ids = {str(record.get("task_id") or "") for record in important}
        active = sorted((record for record in matching if record.get("status") == "active"), key=newest_first, reverse=True)
        completed = sorted(recent_completed(matching, 30), key=newest_first, reverse=True)
        return runtime._project_board_columns(
            important,
            [record for record in active if str(record.get("task_id") or "") not in important_ids],
            [record for record in completed if str(record.get("task_id") or "") not in important_ids],
        )

    for slug in display_slugs:
        item = projects.get(slug)
        if not item:
            continue
        matching = runtime._project_task_records(slug, records)
        active_count = sum(record.get("status") == "active" for record in matching)
        status_key, reason = runtime._project_status_and_reason(records, slug)
        total_active += active_count
        attention_count += int(status_key == "attention")
        week_ago = now - runtime.datetime.timedelta(days=7)
        completed_7d = [record for record in matching if record.get("status") == "completed" and (updated := runtime._parse_record_datetime(record)) and updated >= week_ago]
        project_url = f"/projects/{runtime.quote(slug)}"
        cards[slug] = {
            "slug": slug, "title": str(item.get("title") or slug), "href": project_url,
            "category": str(item.get("work_category") or "other"),
            "status_key": status_key, "status_label": runtime.STATUS_LABEL_PROJECT.get(status_key, status_key),
            "focus": str(item.get("current_focus") or "未指定当前主线").strip() or "未指定当前主线",
            "stats": [(active_count, "进行中"), (len(completed_7d), "近 7 天完成")],
            "lines": [f'主线更新于 {runtime.format_display_time(str(item.get("focus_updated_at") or "")) or "未记录"}'],
            "note": f"状态说明：{reason}",
            "actions": [{"label": "进入项目", "href": project_url, "primary": True},
                        {"label": "任务整理", "href": runtime._organize_url_for_project(slug)}],
            "columns": board(slug, matching),
        }

    independent_records = runtime._project_task_records("independent", records)
    mainlines = sorted(
        (record for record in independent_records if record.get("status") == "active" and record.get("task_kind") == "task_group"),
        key=newest_first, reverse=True,
    )
    independent = {
        "slug": "independent", "title": "独立任务", "href": "/review?project=independent", "category": "independent", "independent": True,
        "focus": "尚未形成任务主线",
        "stats": [(sum(record.get("status") == "active" for record in independent_records), "进行中"),
                  (len(recent_completed(independent_records, 30)), "近 30 天完成")],
        "note": "独立任务可整理、排序并逐步形成项目，但不进入项目归档。",
        "actions": [{"label": "查看独立任务", "href": "/review?project=independent", "primary": True},
                    {"label": "任务整理", "href": "/weekly?project=independent"}],
        "board_label": "独立任务看板", "columns": board("independent", independent_records),
    }
    if mainlines:
        mainline_id = str(mainlines[0].get("task_id") or "")
        independent.update(focus=str(mainlines[0].get("task_name") or mainlines[0].get("title") or mainline_id), focus_href=f"/tasks/{runtime.quote(mainline_id)}")
    cards["independent"] = independent

    card_order = [slug for slug in runtime.project_display_order() if slug == "independent" or slug in display_slugs]
    category_counts = {category: sum(item.get("work_category") == category for item in projects.values()) for category in work_categories}
    filters = [("all", "全部", len(display_slugs) + 1)]
    filters += [(category, str(rule["title"]), category_counts[category]) for category, rule in work_categories.items()]
    other_count = sum(item.get("work_category") not in work_categories for item in projects.values())
    if other_count:
        filters.append(("other", "其他项目", other_count))
    filters.append(("independent", "独立任务", 1))
    content = runtime.projects_page.render({
        "counts": {"projects": len(display_slugs), "active": total_active, "attention": attention_count},
        "filters": filters, "csrf": token,
        "empty_html": '该分类尚未登记项目。<a href="/review?project=independent">从独立任务继续现有工作</a>，不会自动新建项目或迁移任务。',
        "cards": [cards[slug] for slug in card_order if slug in cards],
    }) + f'<style>{runtime.PROJECTS_STYLE}</style><script src="/assets/projects.js?v={runtime.PROJECTS_VERSION}"></script>'
    return runtime._layout("项目视图", content, token)


def render_project_entries(markdown: str, project: str, token: str = "", return_to: str = "") -> str:
    """Render compact entry rows with exact copy values and bounded local actions."""
    return runtime.project_page.entries(runtime.project_entry_parts_data(markdown, project, token, return_to))


def project_entry_parts_data(markdown: str, project: str, token: str = "", return_to: str = "") -> list[dict[str, object]]:
    """Entry table parts for the template; registered local directories get an 打开目录 form."""
    registered = runtime._registered_project_entry_values(project)
    open_keys = {value: key for key, value in registered.items() if runtime.project_entry_locator_kind(value) == "path"}
    available: dict[str, bool] = {}
    parts: list[dict[str, object]] = []
    for part in runtime._project_entry_parts(markdown):
        if isinstance(part, str):
            parts.append({"html": runtime.markdown_to_html(part)})
            continue
        rows = []
        for label, environment, value, description in part:
            kind = runtime.project_entry_locator_kind(value)
            actions = ""
            key = open_keys.get(value)
            if token and kind == "path" and key:
                if key not in available:
                    target = runtime.project_entry_target(project, key)
                    available[key] = bool(target and target[0] == "path")
                if available[key]:
                    actions = runtime._form("/actions/open-project-entry", token, {"project": project, "entry": key, "return_to": return_to or f"/projects/{runtime.quote(project)}"}, "打开目录", "button ghost")
            rows.append({"label": label, "environment": environment, "value": value, "kind": kind, "note": description, "actions_html": actions})
        parts.append({"rows": rows})
    return parts


def project_hero_data(project: str, token: str, records: list[dict[str, object]] | None = None) -> dict[str, object]:
    item = runtime.project_items().get(project)
    source = runtime.project_intro_source(project)
    intro = None
    if source:
        try:
            intro = runtime.parse_project_intro(source)
        except OSError:
            intro = None
    return_to = f"/projects/{runtime.quote(project)}"
    task_records = records or []
    return {
        "title": str(item.get("title") or project) if item else project, "eyebrow": "PROJECT",
        "launcher": {"confirm_label": "开始项目任务并确认执行器", "form": {
            "action": "/actions/new-task",
            "attrs": [("data-execution-confirm", None), ("data-execution-label", "开始项目任务并确认执行器")],
            "hidden": [("csrf", token), ("task_type", "generic"), ("project", project), ("return_to", return_to)]}},
        "focus": str((item or {}).get("current_focus") or "").strip(),
        "stats": {
            "active": sum(str(record.get("status") or "") in {"active", "waiting_user", "blocked"} for record in task_records),
            "groups": sum(record.get("task_kind") == "task_group" for record in task_records),
            "completed": sum(str(record.get("status") or "") == "completed" for record in task_records),
        },
        "overview": runtime.context_overview_data(intro, project=project, token=token),
        "strip": runtime.project_location_strip(project, described_entries=runtime.project_described_entries(intro)),
    }


def render_project(project: str, token: str, notice: str = "", error: str = "") -> str | None:
    if project not in runtime.project_items():
        return None
    source = runtime.project_intro_source(project)
    item = runtime.project_items().get(project)
    if not source or not item:
        return None
    text = source.read_text(encoding="utf-8", errors="replace")
    _, body = runtime.tasks.frontmatter(text)
    title = str(item.get("title") or project)
    return_to = f"/projects/{runtime.quote(project)}/copy"
    work_entry = runtime.project_work_entry(project, token, return_to)
    message = runtime.flash_message(notice, error)
    back = f'<a class="button" href="/projects/{runtime.quote(project)}">返回项目工作区</a>'
    content = f"""{message}<section class="project-identity"><h1>{runtime.html.escape(title)}</h1><div class="project-identity-actions">{back}{work_entry}</div></section><article class="article md project-description-full">{runtime.render_project_intro_markdown(body, project, token=token)}</article>"""
    return runtime._layout(f"{title}项目介绍", content, token, project)


def render_project_intro_markdown(markdown: str, project: str, *, token: str = "") -> str:
    """Render project intro Markdown without exposing internal maintenance state."""
    citations = runtime.extract_citations(markdown)

    # Split off the "整理记录" section; render the rest with citation badges.
    pattern = runtime.re.compile(r"^##[ \t]+(整理记录|工作位置与入口|系统入口)[ \t]*$\n?(.*?)(?=^##\s+|\Z)", runtime.re.MULTILINE | runtime.re.DOTALL)
    out: list[str] = []
    cursor = 0
    for match in pattern.finditer(markdown):
        body_part = markdown[cursor:match.start()]
        body_html = runtime.markdown_to_html(body_part)
        for key, citation in citations.items():
            body_html = body_html.replace(f"[^{key}]", runtime._citation_badge(key, citation))
        out.append(body_html)
        if match.group(1) != "整理记录":
            out.append(f'<section class="project-description-section"><h3>{runtime.html.escape(match.group(1))}</h3>')
            out.append(runtime.render_project_entries(match.group(2), project, token, f"/projects/{runtime.quote(project)}/copy"))
            out.append('</section>')
        # The maintenance task card owns user-visible history. The Markdown
        # section is ignored for compatibility with older project sources.
        cursor = match.end()
    body_part = markdown[cursor:]
    body_html = runtime.markdown_to_html(body_part)
    for key, citation in citations.items():
        body_html = body_html.replace(f"[^{key}]", runtime._citation_badge(key, citation))
    out.append(body_html)

    # Append machine-readable organization history sidecar.
    history = runtime.load_project_intro_history(project)
    if history:
        history_lines = []
        for entry in history:
            ts = str(entry.get("timestamp") or "")
            rnd = entry.get("round", 0)
            src = ", ".join(str(t) for t in entry.get("source_tasks", []) or [])
            summary = str(entry.get("summary") or "")
            history_lines.append(f"<li>R{rnd:02d} · {runtime.html.escape(ts)} · 来源：{runtime.html.escape(src)} · {runtime.html.escape(summary)}</li>")
        out.append(f'<details class="history"><summary>整理流程记录（{len(history)} 条）</summary><ul>{"".join(history_lines)}</ul></details>')
    return "".join(out)
