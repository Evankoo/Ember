"use strict";

/* Ember open-source workbench. Page markup follows the Ember workbench and is styled by
   assets/workbench.css; data comes only from this local workspace through /api. */
const app = (() => {
  const main = document.getElementById("main-content");
  const sidebar = document.getElementById("sidebar");
  const dialog = document.getElementById("workbench-dialog");
  const dialogBody = document.getElementById("dialog-body");
  const state = { data: null, route: "home", id: "", dialogReturn: null, toastTimer: null, preview: null, settings: null, settingsRequest: 0, contextRequest: 0 };
  const filters = {
    home: { query: "", project: "", type: "", status: "" },
    review: { query: "", project: "", type: "", status: "", sort: "updated" },
    library: { query: "", project: "", kind: "delivery", subtype: "" },
    project: { query: "", kind: "tasks", task: "all", subtype: "" }
  };
  const ui = { review: new Set(), library: new Set(), reviewTask: "", reviewReport: "", reportFilter: "", file: "", projectId: "", projectCategory: "", reviewFilters: false, taskFiles: "delivery" };
  const composer = { task: "", files: [], attachments: [] };
  const confirm = { request: "", relation: "new", taskId: "", fileIds: [], attachments: [] };
  const software = { entries: [], default: "", editing: false, manual: { label: "", kind: "app", path: "" }, epoch: 0, saving: false };
  const statusNames = { active: "进行中", waiting_user: "待确认", blocked: "受阻", completed: "已完成" };
  const workNames = { text: "文字", image: "图片", video: "视频", audio: "音频", data: "数据", mixed: "混合", system: "系统" };
  const categoryClasses = ["account_operations", "course_teaching", "novel_writing", "system_building"];
  const routeNames = { new: ["新建任务", "建立独立任务上下文"], continue: ["继续任务", "沿用原任务的目标与记录"], based: ["基于任务新建", "参考已有任务开启新工作"] };
  const brandMark = `<svg class="brand-mark" viewBox="0 0 256 256" fill="none" aria-hidden="true" focusable="false"><path d="M68 146H194C197 106 186 68 162 36C154 58 128 68 100 86C76 102 62 124 62 150C62 194 94 222 134 222C160 222 180 212 194 196" stroke="currentColor" stroke-width="27" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  const TEXT_FILE = /\.(md|markdown|txt|csv|json)$/i;
  const ATTACHMENT_LIMIT = 16000;

  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const data = () => state.data;
  const task = id => data().tasks.find(item => item.id === id);
  const project = id => data().projects.find(item => item.id === id);
  const file = id => data().files.find(item => item.id === id);
  const projectName = id => id === "independent" ? "独立任务" : project(id)?.name || id || "独立任务";
  const badge = item => `<span class="badge ${esc(item.status)}">${esc(statusNames[item.status] || item.status)}</span>`;
  const actionKey = (action, label, attrs = "", extra = "") => `<button class="gstudio-action-trigger ${extra}" type="button" data-action="${action}" title="${esc(label)}" aria-label="${esc(label)}" ${attrs}>${brandMark}</button>`;
  const option = (value, name, current) => `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(name)}</option>`;
  const projectOptions = (current = "", all = true) => `${all ? option("", "全部项目", current) : ""}${data().projects.map(p => option(p.id, p.name, current)).join("")}${option("independent", "独立任务", current)}`;
  const kindName = kind => ({ input: "输入资料", draft: "草稿交付", formal: "正式交付", inbox: "收件箱" }[kind] || kind);
  const taskLink = item => `#task/${encodeURIComponent(item.id)}`;
  const formError = form => form.querySelector(".form-error");
  const bytes = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n || 0} B`;
  const stamp = item => String(item.updated_at || item.date || "").slice(0, 16);
  const days = value => (Date.now() - Date.parse(String(value || "").replace(" ", "T").replace(/\+08:00$/, "+08:00"))) / 86400000;
  const workType = item => item.kind === "task_line" ? "任务线" : workNames[item.work_type] || item.work_type;
  const categories = () => [...new Set(data().projects.map(p => p.category).filter(Boolean))];
  const categoryClass = name => categoryClasses[Math.max(0, categories().indexOf(name)) % categoryClasses.length];
  const fileIcon = item => /\.md$/i.test(item.name) ? "M" : /\.(png|jpe?g|webp|gif)$/i.test(item.name) ? "◇" : /\.(mp4|mov|webm)$/i.test(item.name) ? "▶" : /\.pdf$/i.test(item.name) ? "P" : "·";
  const fileKind = item => `<span class="task-file-kind">${esc((String(item.name).match(/\.([a-z0-9]{1,8})$/i) || [, "文件"])[1].toUpperCase().slice(0, 4))}</span>`;
  const executorNames = { codex: "Codex", opencode: "OpenCode", "claude-code": "Claude Code", workbuddy: "WorkBuddy", "qianwen-office": "千问办公", "doubao-work": "豆包工作", external: "外部", manual: "人工" };
  /* Entries the program writes itself; consecutive ones of the same kind fold into one row. */
  const machineLogKinds = ["添加输入快照", "添加草稿交付", "登记输入引用"];
  function logRows(logs) {
    const entries = logs.map(log => {
      const legacy = !log.date && String(log.text).match(/^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})(?::\d{2})?(?:[+-]\d{2}:?\d{2})?\s*[：｜|:]\s*(.*)$/);
      const date = legacy ? legacy[1] : String(log.date || "");
      const text = legacy ? legacy[2] : String(log.text || "");
      return { time: date.replace("T", " ").slice(0, 16), text, kind: machineLogKinds.find(kind => text.startsWith(kind)) || "" };
    });
    const rows = [];
    for (let i = 0; i < entries.length;) {
      let end = i + 1;
      while (entries[i].kind && end < entries.length && entries[end].kind === entries[i].kind) end++;
      const time = `<time>${esc(entries[i].time)}</time>`;
      rows.push(end - i > 1
        ? `<li class="task-log-entry task-log-machine">${time}<details><summary>${esc(entries[i].kind)} · ${end - i} 条</summary><ul>${entries.slice(i, end).map(e => `<li>${inline(e.text)}</li>`).join("")}</ul></details></li>`
        : `<li class="task-log-entry${entries[i].kind ? " task-log-machine" : ""}">${time}<div>${inline(entries[i].text)}</div></li>`);
      i = end;
    }
    return rows.join("");
  }

  function inline(text) {
    return esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|#)[^\s)]+)\)/g, (_, label, url) => `<a href="${url}" rel="noreferrer">${label}</a>`);
  }

  /* Small, escape-first Markdown reader for task and project cards; no raw HTML is ever trusted. */
  function markdown(source) {
    const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (/^```/.test(line)) {
        const code = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
        i++; out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); continue;
      }
      const heading = line.match(/^(#{1,4})\s+(.*)$/);
      if (heading) { const level = Math.min(heading[1].length + 1, 4); out.push(`<h${level}>${inline(heading[2])}</h${level}>`); i++; continue; }
      if (/^\|.*\|\s*$/.test(line) && /^\|?\s*:?-{2,}/.test(lines[i + 1] || "")) {
        const cells = row => row.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
        const head = cells(line); i += 2;
        const body = [];
        while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) body.push(cells(lines[i++]));
        out.push(`<div class="table-scroll"><table><thead><tr>${head.map(cell => `<th>${inline(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(r => `<tr>${r.map(cell => `<td>${inline(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line), items = [];
        while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        out.push(`<${ordered ? "ol" : "ul"}>${items.map(item => `<li>${inline(item)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`); continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
        out.push(`<blockquote>${quote.map(inline).join("<br>")}</blockquote>`); continue;
      }
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*]|\d+\.)\s|>|\|)/.test(lines[i])) paragraph.push(lines[i++]);
      if (!paragraph.length) paragraph.push(lines[i++]);
      out.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
    }
    return out.join("");
  }

  async function api(path, payload) {
    const options = payload === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Ember-Token": data()?.csrf_token || "" }, body: JSON.stringify(payload) };
    const response = await fetch(path, options);
    let result;
    try { result = await response.json(); } catch { throw new Error("服务未返回有效数据，请检查工作台是否仍在运行。"); }
    if (!response.ok || !result.ok) throw new Error(result.error || `请求失败（${response.status}）`);
    return result.data;
  }

  function notice(message, error = false) {
    const node = document.getElementById("notice");
    clearTimeout(state.toastTimer);
    node.textContent = message;
    node.classList.toggle("error", error);
    node.hidden = false;
    requestAnimationFrame(() => node.classList.add("show"));
    state.toastTimer = setTimeout(() => { node.classList.remove("show"); node.hidden = true; }, error ? 9000 : 4500);
  }

  function setMenu(open) {
    sidebar.classList.toggle("mobile-open", open);
    const toggle = document.getElementById("menu-toggle");
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "收起" : "菜单";
  }

  function openDialog(title, html, variant = "") {
    if (!dialog.open) state.dialogReturn = document.activeElement;
    document.getElementById("dialog-title").textContent = title;
    dialogBody.innerHTML = html;
    dialog.className = `paper-dialog workbench-dialog ${variant}`.trim();
    if (!dialog.open) dialog.showModal();
    requestAnimationFrame(() => {
      const first = dialogBody.querySelector("input:not([type=checkbox]):not([type=radio]):not([type=hidden]),textarea,select");
      (first || document.getElementById("dialog-close")).focus();
    });
  }

  function closeDialog() { dialog.close(); }
  dialog.addEventListener("close", () => {
    const previous = state.dialogReturn;
    const replacement = previous?.id && document.getElementById(previous.id);
    if (previous?.isConnected) previous.focus();
    else if (replacement) replacement.focus();
    else main.focus({ preventScroll: true });
    state.dialogReturn = null;
  });
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeDialog();
  });
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll("button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex='0']")].filter(node => node.getClientRects().length);
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  /* Favorites are a per-browser presentation preference; they never change the workspace. */
  const favoriteKey = () => `ember.favorites.${data()?.workspace_name || "workspace"}`;
  function favorites() { try { return new Set(JSON.parse(localStorage.getItem(favoriteKey()) || "[]")); } catch { return new Set(); } }
  function toggleFavorite(id) {
    const values = favorites();
    values.has(id) ? values.delete(id) : values.add(id);
    try { localStorage.setItem(favoriteKey(), JSON.stringify([...values])); } catch { notice("浏览器不允许保存收藏，本次刷新后会恢复。", true); }
    renderNav();
  }

  async function loadState(render = true) {
    state.data = await api("api/state");
    data().tasks ||= []; data().projects ||= []; data().files ||= []; data().reports ||= [];
    for (const id of [...ui.review]) if (!task(id)) ui.review.delete(id);
    for (const id of [...ui.library]) if (!file(id)) ui.library.delete(id);
    renderNav();
    if (render) renderRoute();
  }

  function renderNav() {
    const saved = favorites();
    const row = p => `<div class="sidebar-project-row" data-sidebar-project="${esc(p.id)}"><a href="#project/${encodeURIComponent(p.id)}" data-project-nav="${esc(p.id)}" aria-label="${p.kind === "system" ? "系统" : "项目"}：${esc(p.name)}"><span class="sidebar-dot ${categoryClass(p.category)}"></span><span class="sidebar-project-title">${esc(p.name)}</span></a><button type="button" class="sidebar-favorite-button${saved.has(p.id) ? " saved" : ""}" data-action="favorite" data-id="${esc(p.id)}" aria-label="${saved.has(p.id) ? "取消收藏" : "收藏置顶"} · ${esc(p.name)}" aria-pressed="${saved.has(p.id)}">${saved.has(p.id) ? "★" : "☆"}</button></div>`;
    const section = (title, items, attrs = "") => `<details class="sidebar-section" ${attrs} open><summary>${esc(title)}</summary><div class="sidebar-children">${items.map(row).join("") || `<div class="sidebar-empty">暂无项目</div>`}</div></details>`;
    const groups = categories().length
      ? [...categories().map(name => [name, data().projects.filter(p => p.category === name)]), ["未分类", data().projects.filter(p => !p.category)]]
      : [["项目", data().projects.filter(p => p.kind !== "system")], ["系统", data().projects.filter(p => p.kind === "system")]];
    const favoriteItems = data().projects.filter(p => saved.has(p.id));
    document.getElementById("workspace-nav").innerHTML = `${section("收藏项目", favoriteItems, "data-sidebar-favorites").replace(`<div class="sidebar-empty">暂无项目</div>`, `<div class="sidebar-empty">点击项目旁的星标收藏</div>`)}${groups.filter(([, items]) => items.length).map(([name, items]) => section(name, items, `data-work-category-section="${esc(name)}"`)).join("")}`;
    document.getElementById("workspace-state").textContent = data().workspace_name || "本地工作区";
    document.getElementById("workspace-version").textContent = `版本 ${data().version || ""}`;
    for (const link of document.querySelectorAll("[data-nav]")) {
      const active = link.dataset.nav === state.route || (state.route === "project" && link.dataset.nav === "projects");
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
    for (const link of document.querySelectorAll("[data-project-nav]")) {
      const active = state.route === "project" && link.dataset.projectNav === state.id;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
  }

  function route() {
    const hash = location.hash.replace(/^#/, "") || "home";
    const [name, id] = hash.split("/");
    state.route = name; state.id = id ? decodeURIComponent(id) : "";
    setMenu(false);
    if (dialog.open) closeDialog();
    if (data()) { renderNav(); renderRoute(); main.focus({ preventScroll: true }); window.scrollTo(0, 0); }
  }
  function go(hash) { if (location.hash === `#${hash}`) route(); else location.hash = hash; }

  function matchingTasks(key, supplied = data().tasks) {
    const f = filters[key], query = f.query.trim().toLowerCase();
    const rows = supplied.filter(t => (!f.project || t.project === f.project) && (!f.type || t.work_type === f.type) && (!f.status || t.status === f.status) && (!query || [t.title, t.goal, t.description, t.current, t.next, t.id, ...(t.logs || []).map(log => log.text)].join(" ").toLowerCase().includes(query)));
    const order = f.sort === "title" ? (a, b) => a.title.localeCompare(b.title, "zh") : (a, b) => String(b.updated_at || b.date).localeCompare(String(a.updated_at || a.date));
    return rows.sort(order);
  }

  const taskRow = t => `<tr data-task-id="${esc(t.id)}"><td class="name"><a class="task-name" href="${taskLink(t)}">${esc(t.title)}</a>${t.kind === "task_line" ? `<span class="task-group-tag">任务线</span>` : ""}</td><td class="desc">${esc(t.goal || t.description || "")}</td><td class="overview-project">${esc(projectName(t.project))}</td><td class="overview-status">${badge(t)}</td><td class="overview-type">${esc(workType(t))}</td><td class="overview-updated">${esc(stamp(t))}</td></tr>`;
  const taskTable = (id, rows, emptyText) => `<div class="task-overview-scroll"><table class="task-table project-overview-table"><colgroup><col class="overview-name-col"><col class="overview-desc-col"><col class="overview-project-col"><col class="overview-status-col"><col class="overview-type-col"><col class="overview-updated-col"></colgroup><thead><tr><th>任务名称</th><th>任务描述</th><th>项目</th><th>状态</th><th class="overview-type">类型</th><th>更新时间</th></tr></thead><tbody id="${id}">${rows.map(taskRow).join("") || `<tr><td class="empty" colspan="6">${esc(emptyText)}</td></tr>`}</tbody></table></div>`;

  function statusChips(key) {
    const current = filters[key].status;
    return `<div class="chips" role="group" aria-label="任务状态">${[["", "全部"], ["active", "进行中"], ["completed", "已完成"], ["waiting_user", "待确认"], ["blocked", "受阻"]].map(([value, name]) => `<button class="chip${current === value ? " active" : ""}" type="button" data-action="status-filter" data-filter="${key}" data-id="${value}" aria-pressed="${current === value}">${name}</button>`).join("")}</div>`;
  }

  /* ---------- 任务台 ---------- */
  function renderHome() {
    const types = [...new Set(data().tasks.map(t => t.work_type))];
    main.className = "shell app-main home-page";
    main.innerHTML = `<section class="home-command-shell" aria-labelledby="home-title"><div class="home-command-heading"><h1 id="home-title">想让 <span class="home-command-ai">AI</span> 帮你做什么</h1></div><form id="context-form" class="action-form home-command-form" data-form="home-command"><div class="home-entry-row"><div class="home-entry-main"><div class="home-composer"><textarea id="context-request" name="request" rows="4" aria-label="本次要求" placeholder="输入要求，或用 fd 检索任务与资料…"></textarea><div class="home-composer-foot"><div id="home-contexts" class="home-input-contexts"></div><div id="home-materials" class="home-material-chips"></div><span class="home-drop-hint">可粘贴或拖入文字文件 · fd 检索任务与资料 · Shift+Enter 换行</span></div></div><div id="home-results" class="home-results" hidden></div></div><button id="context-prepare" class="home-confirm-open gstudio-action-trigger" type="submit" aria-label="确认执行" title="确认执行">${brandMark}</button></div></form></section><section class="home-all-tasks" aria-labelledby="home-tasks-title"><div class="task-overview-sticky"><div class="section-head"><div class="task-overview-heading"><h2 id="home-tasks-title">全部任务</h2></div><span class="meta">显示 <span id="home-count">0</span> / ${data().tasks.length} 条</span></div><div class="task-overview-filters"><div class="search-wrap"><span class="search-icon" aria-hidden="true">⌕</span><input id="home-search" type="search" data-filter="home" data-field="query" aria-label="搜索任务" placeholder="搜索任务…" value="${esc(filters.home.query)}"></div><select id="home-project" data-filter="home" data-field="project" aria-label="项目">${projectOptions(filters.home.project)}</select><select id="home-type" data-filter="home" data-field="type" aria-label="类型">${option("", "全部类型", filters.home.type)}${types.map(type => option(type, workNames[type] || type, filters.home.type)).join("")}</select></div><div class="task-overview-status-bar">${statusChips("home")}<button class="button ghost clear-filters" type="button" data-action="reset-filter" data-id="home">清除筛选</button></div></div><div id="home-table">${taskTable("home-task-list", [], "")}</div></section>`;
    renderComposer();
    renderTaskResults("home");
  }

  function renderTaskResults(key) {
    const items = matchingTasks(key);
    if (key === "home") {
      document.getElementById("home-table").innerHTML = taskTable("home-task-list", items, data().tasks.length ? "没有匹配任务，请调整搜索或筛选。" : "工作区还没有任务。在上方描述要做的事，或让 AI 用余烬 Skill 记录工作。");
      document.getElementById("home-count").textContent = String(items.length);
      main.querySelector('[data-action="reset-filter"][data-id="home"]').classList.toggle("dimmed", !Object.values(filters.home).some(Boolean));
    } else if (key === "review") renderReviewList();
  }

  function renderComposer() {
    const contexts = document.getElementById("home-contexts"), materials = document.getElementById("home-materials");
    if (!contexts) return;
    const target = task(composer.task);
    contexts.innerHTML = (target ? [`<div class="home-context-chip"><span class="home-context-dot"></span><span class="home-context-kind">任务</span><b>${esc(target.title)}</b><button type="button" data-action="composer-remove-task" aria-label="移除关联任务">×</button></div>`] : []).concat(composer.files.map(id => file(id)).filter(Boolean).map(f => `<div class="home-context-chip"><span class="home-context-dot"></span><span class="home-context-kind">资料</span><b>${esc(f.name)}</b><button type="button" data-action="composer-remove-file" data-id="${esc(f.id)}" aria-label="移除资料 ${esc(f.name)}">×</button></div>`)).join("");
    materials.innerHTML = composer.attachments.map((item, index) => `<div class="home-context-chip"><span class="home-context-dot"></span><span class="home-context-kind">文件</span><b>${esc(item.name)}</b><button type="button" data-action="composer-remove-attachment" data-id="${index}" aria-label="移除文件 ${esc(item.name)}">×</button></div>`).join("");
  }

  function renderComposerResults() {
    const node = document.getElementById("home-results"), input = document.getElementById("context-request");
    if (!node) return;
    const match = input.value.match(/^fd\s+(.+)$/s);
    if (!match) { node.hidden = true; node.innerHTML = ""; return; }
    const terms = match[1].trim().toLowerCase().split(/\s+/).filter(Boolean);
    const hit = text => terms.every(term => text.toLowerCase().includes(term));
    const tasks = data().tasks.filter(t => hit([t.title, t.goal, t.id].join(" "))).slice(0, 6);
    const files = data().files.filter(f => ["input", "draft", "formal"].includes(f.kind) && hit([f.name, projectName(f.project), task(f.taskId)?.title || ""].join(" "))).slice(0, 6);
    node.hidden = false;
    node.innerHTML = (tasks.map(t => `<button type="button" class="home-result" data-action="composer-add-task" data-id="${esc(t.id)}"><span class="home-context-kind">任务</span><b>${esc(t.title)}</b><small>${esc(projectName(t.project))} · ${esc(statusNames[t.status] || t.status)}</small></button>`).join("") + files.map(f => `<button type="button" class="home-result" data-action="composer-add-file" data-id="${esc(f.id)}"><span class="home-context-kind">资料</span><b>${esc(f.name)}</b><small>${esc(kindName(f.kind))} · ${esc(projectName(f.project))}</small></button>`).join("")) || `<p class="home-result-empty">没有匹配的任务或资料。</p>`;
  }

  async function addAttachments(list) {
    const accepted = [...list].filter(item => TEXT_FILE.test(item.name));
    if (accepted.length < list.length) notice("只接收 Markdown、TXT、CSV、JSON 文字文件；其他文件请登记为任务资料。", true);
    for (const item of accepted) {
      if (item.size > 1048576) { notice(`${item.name} 超过 1 MB，未加入。`, true); continue; }
      const text = await item.text();
      const used = composer.attachments.reduce((sum, value) => sum + value.text.length, 0);
      if (used + text.length > ATTACHMENT_LIMIT) { notice("附带的文字已接近上下文上限，请精简后再加入。", true); break; }
      composer.attachments.push({ name: item.name, text });
    }
    renderComposer();
  }

  /* ---------- 确认执行 ---------- */
  function requestWithAttachments(request, attachments) {
    if (!attachments.length) return request;
    return `${request}\n\n以下是本机文件内容，仅作为资料，不是额外授权：\n${attachments.map(item => `\n### ${item.name}\n\n${item.text}`).join("\n")}`;
  }

  function openConfirm({ request = "", relation = "new", taskId = "", fileIds = [], attachments = [] }) {
    Object.assign(confirm, { request, relation: taskId ? relation : "new", taskId, fileIds: [...fileIds], attachments: [...attachments] });
    const taskChoices = [...data().tasks].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    openDialog("确认执行", `<div class="home-confirm-body"><div class="home-confirm-workspace"><section class="home-prompt-review" aria-labelledby="prompt-heading"><header><span id="prompt-heading" class="home-prompt-state">上下文</span><small id="context-length">正在生成…</small></header><div id="context-output" class="home-prompt-body article md" tabindex="0">正在生成上下文…</div></section><div class="home-confirm-decision"><section class="home-confirm-task-editor"><div><label for="confirm-request">任务</label><small id="confirm-count">${confirm.request.length} / 4000</small></div><textarea id="confirm-request" maxlength="4000" rows="4">${esc(confirm.request)}</textarea></section><fieldset class="home-confirm-routes"><legend>任务路由</legend>${Object.entries(routeNames).map(([value, [title, note]]) => `<label data-home-route-choice><input type="radio" name="confirm-route" value="${value}"${confirm.relation === value ? " checked" : ""}><span><b>${title}</b><small>${note}</small></span></label>`).join("")}<label id="confirm-task-field" class="home-confirm-task-field"${confirm.relation === "new" ? " hidden" : ""}>关联任务<select id="confirm-task">${option("", "选择任务", confirm.taskId)}${taskChoices.map(t => option(t.id, t.title, confirm.taskId)).join("")}</select></label></fieldset><section class="home-confirm-material-section"><div class="home-confirm-material-head"><span>相关资料 <b id="confirm-material-count">0</b></span></div><div id="confirm-materials" class="home-confirm-materials"></div></section><div class="home-confirm-actions"><div class="execution-route-status"><small>执行环境</small><strong id="confirm-environment">正在读取设置…</strong><a href="#settings" data-action="open-settings">在设置页配置</a></div><div class="home-confirm-action-buttons"><button id="copy-context-button" class="button ghost" type="button" data-action="copy-context">复制提示词</button><button id="copy-open-context-button" class="button primary" type="button" data-action="copy-open-context" disabled>复制并打开</button></div></div></div></div><p class="home-confirm-note">复制或打开软件都不会发送提示词、调用模型，也不会创建或修改任务。请在软件里自行粘贴并确认发送。</p></div>`, "home-confirm-dialog");
    renderConfirmMaterials();
    readEnvironment();
    refreshContext();
  }

  function renderConfirmMaterials() {
    const items = confirm.fileIds.map(id => file(id)).filter(Boolean).map(f => `<span class="home-context-chip"><span class="home-context-kind">资料</span><b>${esc(f.name)}</b></span>`)
      .concat(confirm.attachments.map(item => `<span class="home-context-chip"><span class="home-context-kind">文件</span><b>${esc(item.name)}</b></span>`));
    document.getElementById("confirm-material-count").textContent = String(items.length);
    document.getElementById("confirm-materials").innerHTML = items.join("") || `<small class="muted">未附带资料。</small>`;
  }

  async function readEnvironment() {
    let environment = null, failure = "";
    try { environment = (await api("api/settings")).execution_environment; } catch (error) { failure = error.message; }
    state.preview = { ...(state.preview || {}), environment };
    const selected = environment?.executors.find(entry => entry.id === environment.default_executor);
    const label = document.getElementById("confirm-environment"), button = document.getElementById("copy-open-context-button");
    if (!label) return;
    label.textContent = environment?.ready ? selected.label : failure || environment?.error || "未配置可用的默认软件";
    button.disabled = !environment?.ready || !state.preview?.text;
    button.textContent = environment?.ready ? `复制并打开 · ${selected.label}` : "复制并打开";
  }

  function refreshContext() {
    state.contextPromise = generateContext();
    return state.contextPromise;
  }

  async function generateContext() {
    const request = ++state.contextRequest;
    const output = document.getElementById("context-output");
    if (!output) return;
    if (!confirm.request.trim()) { output.innerHTML = `<p class="muted">先写下这次要做的事。</p>`; state.preview = { ...(state.preview || {}), text: "" }; document.getElementById("copy-open-context-button").disabled = true; return; }
    if (confirm.relation !== "new" && !confirm.taskId) { output.innerHTML = `<p class="muted">选择要关联的任务后生成上下文。</p>`; state.preview = { ...(state.preview || {}), text: "" }; return; }
    try {
      const payload = { request: requestWithAttachments(confirm.request, confirm.attachments), relation: confirm.relation, file_ids: confirm.fileIds };
      if (confirm.relation !== "new") payload.task_id = confirm.taskId;
      const result = await api("api/context", payload);
      if (request !== state.contextRequest || !document.getElementById("context-output")) return;
      state.preview = { ...(state.preview || {}), text: result.text };
      output.innerHTML = markdown(result.text);
      document.getElementById("context-length").textContent = `${result.text.length} 字 · 只读`;
      const button = document.getElementById("copy-open-context-button");
      button.disabled = !state.preview.environment?.ready;
    } catch (error) {
      if (request === state.contextRequest) output.innerHTML = `<p class="form-error">${esc(error.message)}</p>`;
    }
  }
  let contextTimer = null;
  const scheduleContext = () => { clearTimeout(contextTimer); contextTimer = setTimeout(refreshContext, 300); };

  function selectOutput() {
    const output = document.getElementById("context-output");
    if (!output) return;
    output.focus();
    const range = document.createRange(); range.selectNodeContents(output);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
  }

  /* ---------- 项目视图 ---------- */
  const recentCompleted = (items, limit = 30) => items.filter(t => t.status === "completed" && days(t.updated_at || t.date) <= limit);

  function projectHealth(items) {
    const active = items.filter(t => t.status === "active");
    if (items.some(t => t.status === "blocked")) return ["attention", "需要关注", "有受阻任务"];
    if (items.some(t => t.status === "waiting_user")) return ["waiting", "等待确认", "有任务等待确认"];
    if (active.length && active.filter(t => days(t.updated_at || t.date) > 21).length * 2 > active.length) return ["stalled", "推进放缓", "过半进行中任务超过 21 天未更新"];
    if (active.length) return ["normal", "正常推进", "有近期更新"];
    return ["normal", "暂无进行中", "当前没有进行中的任务"];
  }

  function projectCard(p) {
    const id = p.id, items = data().tasks.filter(t => (t.project || "independent") === id);
    const important = items.filter(t => t.important), importantIds = new Set(important.map(t => t.id));
    const active = items.filter(t => t.status === "active" && !importantIds.has(t.id));
    const recent = recentCompleted(items).filter(t => !importantIds.has(t.id));
    const [cls, label, reason] = projectHealth(items);
    const latest = items.map(t => stamp(t)).sort().pop() || "暂无";
    const entry = t => `<div class="project-view-task-wrap"><a class="project-view-task" href="${taskLink(t)}" data-task-id="${esc(t.id)}"><span class="project-task-name">${esc(t.title)}${t.kind === "task_line" ? `<span class="task-group-tag">任务线</span>` : ""}</span><span class="project-task-state ${t.status === "completed" ? "completed" : "active"}">${t.status === "completed" ? "近30天完成" : esc(statusNames[t.status] || t.status)}</span></a></div>`;
    const column = (key, title, rows) => `<div class="project-view-column" data-board-column="${key}"><div class="project-view-column-head">${title} (${rows.length})</div><div class="project-view-column-body">${rows.map(entry).join("") || `<div class="project-view-empty">暂无</div>`}</div></div>`;
    const title = id === "independent" ? esc(p.name) : `<a href="#project/${encodeURIComponent(id)}">${esc(p.name)}</a>`;
    return `<article class="project-view-card" data-project-card="${esc(id)}"><div class="project-info"><div class="card-head"><h2>${title}</h2><span class="project-status ${cls}">${label}</span></div><div class="project-focus"><div class="focus-label">当前主线</div><div class="focus-text">${esc(p.focus || (id === "independent" ? "无需项目归属的独立工作" : "暂无明确推进主线"))}</div></div><div class="project-metrics"><div class="project-recent-stats"><div><b>${items.filter(t => t.status === "active").length}</b> 进行中 · <b>${recentCompleted(items, 7).length}</b> 近 7 天完成</div><div>最近更新 ${esc(latest)}</div></div><div class="project-center-meta"><span>状态说明：${esc(reason)}</span></div></div><div class="card-actions">${id !== "independent" ? `<a class="button primary" href="#project/${encodeURIComponent(id)}">进入项目</a>` : ""}<button class="button ghost" type="button" data-action="review-project" data-id="${esc(id)}">任务整理</button></div></div><div class="project-view-board">${column("important", "当前重要事项", important)}${column("active", "进行中", active)}${column("completed", "近 30 天完成", recent)}</div></article>`;
  }

  function renderProjects() {
    const independent = { id: "independent", name: "独立任务", focus: "" };
    const cats = categories(), uncategorized = data().projects.filter(p => !p.category);
    const tabs = [["", "全部", data().projects.length + 1], ...cats.map(name => [name, name, data().projects.filter(p => p.category === name).length]), ...(cats.length && uncategorized.length ? [["__none", "未分类", uncategorized.length]] : []), ["__independent", "独立任务", 1]];
    if (!tabs.some(([value]) => value === ui.projectCategory)) ui.projectCategory = "";
    const selected = ui.projectCategory;
    const visible = selected === "__independent" ? [] : data().projects.filter(p => !selected || (selected === "__none" ? !p.category : p.category === selected));
    const showIndependent = !selected || selected === "__independent";
    const activeCount = data().tasks.filter(t => t.status === "active").length;
    const attention = data().projects.filter(p => projectHealth(data().tasks.filter(t => t.project === p.id))[0] !== "normal").length;
    main.className = "shell app-main project-view-page paper-management-page";
    main.innerHTML = `<header class="project-view-page-head"><h1>项目视图</h1><p>${data().projects.length} 个项目 · ${activeCount} 项进行中 · ${attention} 个需要关注</p><button id="new-project-button" class="button ghost" type="button" data-action="new-project">新建项目</button></header><nav class="chips project-category-filters" aria-label="项目分类">${tabs.map(([value, name, count]) => `<button class="chip${selected === value ? " active" : ""}" type="button" data-action="project-category" data-id="${esc(value)}" aria-pressed="${selected === value}">${esc(name)}<small>${count}</small></button>`).join("")}</nav><section class="project-view-grid">${visible.map(projectCard).join("")}${showIndependent ? projectCard(independent) : ""}${!visible.length && !showIndependent ? `<p class="library-empty">该分类尚未登记项目。</p>` : ""}</section>`;
  }

  function cardBody(p) {
    const overview = String(p.overview || p.description || "");
    return overview.replace(/^#\s+.*\n?/, "").replace(/^##\s+(?:项目|系统)总览\s*\n/m, "").trim();
  }

  function renderProject() {
    const p = project(state.id);
    main.className = "shell app-main project-workspace-page paper-management-page";
    if (!p) { main.innerHTML = `<section class="panel project-intro-card"><h1>找不到项目</h1><p>该项目不在当前工作区。</p><a href="#projects">返回项目视图</a></section>`; return; }
    if (ui.projectId !== p.id) { ui.projectId = p.id; filters.project = { query: "", kind: "tasks", task: "all", subtype: "" }; ui.file = ""; }
    const entity = p.kind === "system" ? "系统" : "项目";
    const tasks = data().tasks.filter(t => t.project === p.id);
    const deliveries = data().files.filter(f => f.project === p.id && ["draft", "formal"].includes(f.kind));
    const inputs = data().files.filter(f => f.project === p.id && f.kind === "input");
    const timeline = (p.timeline || []).map(item => `<li><b>${esc(item.date)}</b> ${esc(item.title)}${item.text ? `：${esc(item.text)}` : ""}</li>`).join("");
    const locations = (p.locations || []).length ? `<div class="project-location-strip"><div class="project-location-items">${p.locations.map(path => `<span class="project-location-item"><small>本机工作目录</small><code>${esc(path)}</code></span>`).join("")}</div></div>` : "";
    const tabs = [["tasks", "任务", tasks.length], ["delivery", "交付文件", deliveries.length], ["input", "输入资料", inputs.length]];
    main.innerHTML = `<section class="panel project-intro-card project-workspace-hero"><div class="intro-head"><div><span class="eyebrow">${p.kind === "system" ? "SYSTEM" : "PROJECT"}${p.category ? ` · ${esc(p.category)}` : ""}</span><h1>${esc(p.name)}</h1></div><div class="project-hero-actions"><button class="button ghost" type="button" data-action="new-task" data-project="${esc(p.id)}">新建任务</button><div class="project-task-launcher">${actionKey("project-context", `从该${entity}准备上下文`, `data-id="${esc(p.id)}"`)}</div></div></div><div class="intro-desc">${esc(p.description || "")}</div><div class="project-hero-summary"><div class="project-current-focus"><small>当前重点</small><strong>${esc(p.focus || "暂无明确推进主线")}</strong></div><div class="project-hero-stats"><span><b>${tasks.length}</b> 项任务 · <b>${tasks.filter(t => t.status === "active").length}</b> 项进行中 · <b>${deliveries.length}</b> 个交付文件</span></div></div><section class="context-overview-panel"><section class="context-overview-primary"><h2>${entity}总览</h2><div class="context-overview-copy">${markdown(cardBody(p)) || `<p>暂无${entity}说明。</p>`}</div></section>${timeline ? `<hr><section class="context-reader-timeline"><h3>时间线</h3><div class="context-overview-copy"><ul>${timeline}</ul></div></section>` : ""}</section>${locations}</section><nav class="project-workspace-tabs" role="tablist" aria-label="${entity}内容">${tabs.map(([id, label, count]) => `<button class="${filters.project.kind === id ? "active" : ""}" role="tab" type="button" data-action="project-tab" data-id="${id}" aria-selected="${filters.project.kind === id}">${label}<span>${count}</span></button>`).join("")}</nav><div id="project-scene" class="project-scene"></div>`;
    renderProjectScene();
  }

  const projectTaskFilters = [["all", "全部"], ["important", "当前重点"], ["groups", "任务主线"], ["active", "进行中"], ["completed", "已完成"]];

  function renderProjectScene() {
    const f = filters.project, scene = document.getElementById("project-scene");
    if (f.kind === "tasks") {
      const entity = project(state.id)?.kind === "system" ? "系统" : "项目";
      const count = data().tasks.filter(t => t.project === state.id).length;
      const chip = ([id, label]) => `<button type="button" class="chip${f.task === id ? " active" : ""}" data-action="project-task-filter" data-id="${id}" aria-pressed="${f.task === id}">${label}</button>`;
      scene.innerHTML = `<section class="panel project-workspace"><div class="project-workspace-layout"><div class="project-task-pane" data-project-panel="tasks"><div class="project-pane-head"><div class="project-pane-title"><h2>${entity}任务</h2><span>${count}</span></div><div class="project-pane-tools"><input id="project-search" class="project-pane-search" type="search" data-filter="project" data-field="query" placeholder="搜索${entity}任务" aria-label="搜索${entity}任务" value="${esc(f.query)}"></div></div><div class="project-task-filters" aria-label="任务筛选">${projectTaskFilters.map(chip).join("")}<span class="filter-separator" aria-hidden="true"></span>${chip(["delivery", "有交付文件"])}</div><div class="project-task-list" id="project-task-list"></div></div></div></section>`;
      renderProjectTasks();
    } else {
      scene.innerHTML = `<section class="panel project-workspace"><div class="project-workspace-layout"><div class="project-material-pane library-material-page" data-project-panel="materials">${libraryLayout("project")}</div></div></section>`;
      renderFiles("project");
    }
  }

  function renderProjectTasks() {
    const f = filters.project, q = f.query.trim().toLowerCase();
    const keep = { all: () => true, important: t => t.important, groups: t => t.kind === "task_line", active: t => t.status !== "completed", completed: t => t.status === "completed", delivery: t => (t.outputs || []).length > 0 }[f.task] || (() => true);
    const rows = data().tasks.filter(t => t.project === state.id && keep(t) && (!q || [t.title, t.goal, t.description, t.id].join(" ").toLowerCase().includes(q)))
      .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    document.getElementById("project-task-list").innerHTML = rows.map(t => {
      const delivered = (t.outputs || []).length > 0;
      return `<article class="project-task-row" data-task-id="${esc(t.id)}" data-status="${esc(t.status)}"><div class="project-task-row-main"><a href="#task/${encodeURIComponent(t.id)}">${esc(t.title)}</a><div class="subtitle">${esc(t.goal)}</div></div><div class="project-task-row-meta"><span class="badge ${esc(t.status)}">${esc(statusNames[t.status] || t.status)}</span><span class="delivery-label${delivered ? " has-delivery" : ""}">${delivered ? "有交付文件" : "无独立交付文件"}</span></div></article>`;
    }).join("") || `<p class="muted project-task-empty">没有匹配的任务。</p>`;
  }

  /* ---------- 任务详情 ---------- */
  function renderTask() {
    const item = task(state.id);
    main.className = "shell app-main task-detail-page paper-management-page";
    if (!item) { main.innerHTML = `<section class="panel task-current-pane"><h1>找不到任务</h1><p>该任务不在当前工作区。</p><a href="#home">返回任务台</a></section>`; return; }
    const inputIds = new Set(item.inputs || []);
    const inputs = data().files.filter(f => inputIds.has(f.id));
    const deliveries = data().files.filter(f => (item.outputs || []).includes(f.id));
    const hasMaterials = inputs.length + deliveries.length > 0;
    const open = item.status !== "completed";
    const completion = item.artifact_mode === "delivery" ? `<button id="promote-task-button" class="button ghost" type="button" data-action="promote" data-id="${esc(item.id)}">正式交付并完成</button>` : `<button id="complete-task-button" class="button ghost" type="button" data-action="complete" data-id="${esc(item.id)}">完成任务</button>`;
    const actions = `${open ? `<button id="edit-task-button" class="button ghost" type="button" data-action="edit-task" data-id="${esc(item.id)}">更新任务记录</button><button id="add-material-button" class="button ghost" type="button" data-action="add-material" data-id="${esc(item.id)}">添加资料</button>${completion}` : ""}<button class="button ghost" type="button" data-action="important" data-id="${esc(item.id)}" aria-pressed="${Boolean(item.important)}">${item.important ? "移出重点" : "设为重点"}</button>`;
    const tools = actionKey("task-context", open ? "继续该任务" : "基于已完成任务新建", `data-id="${esc(item.id)}"`);
    const section = (title, text, fallback) => `<h3>${title}</h3>${text ? markdown(text) : `<p class="muted">${fallback}</p>`}`;
    const related = (item.related || []).length ? `<h3>关联任务</h3><ul>${item.related.map(id => task(id) ? `<li><a href="${taskLink(task(id))}">${esc(task(id).title)}</a></li>` : `<li>${esc(id)}</li>`).join("")}</ul>` : "";
    const technical = item.executor || (item.skills_used || []).length ? `<section class="task-technical-info"><h3>技术信息</h3><p class="task-technical-summary"><span>执行工具 ${esc(executorNames[item.executor] || item.executor || "未记录")} · Skill ${esc((item.skills_used || []).join("、") || "未记录")}</span></p></section>` : "";
    const logs = logRows(item.logs || []);
    const pane = hasMaterials ? `<section class="panel task-delivery-workspace" aria-label="任务资料"><section class="task-delivery-shelf"><header class="task-delivery-head"><div class="task-file-tabs" role="tablist">${[["delivery", "交付文件", deliveries.length], ["input", "输入资料", inputs.length]].map(([id, label, count]) => `<button class="${ui.taskFiles === id ? "active" : ""}" type="button" role="tab" data-action="task-files" data-id="${id}" aria-selected="${ui.taskFiles === id}">${label}<span>${count}</span></button>`).join("")}</div></header><div class="task-input-panel task-file-pane"><div class="task-input-list">${(ui.taskFiles === "input" ? inputs : deliveries).map(f => `<div class="task-input-row" data-file-id="${esc(f.id)}"${inputIds.has(f.id) && (f.taskId !== item.id || f.kind !== "input") ? ' data-input-reference="true"' : ""}><span class="task-input-icon" aria-hidden="true">${fileKind(f)}</span><div class="task-input-copy"><button type="button" class="task-input-name" data-action="file-read" data-id="${esc(f.id)}">${esc(f.name)}</button><span>${esc(kindName(f.kind))} · ${bytes(f.bytes)}${f.purpose ? ` · ${esc(f.purpose)}` : ""}</span></div></div>`).join("") || `<div class="task-preview-empty">暂无${ui.taskFiles === "input" ? "输入资料" : "交付文件"}。</div>`}</div></div></section></section>` : "";
    main.innerHTML = `<div class="task-detail-workspace ${hasMaterials ? "has-materials" : "no-materials"}"><section class="panel task-current-pane"><header class="task-current-head"><div class="task-current-title-row">${badge(item)}<h1>${esc(item.title)}</h1><div class="task-current-heading-tools">${tools}</div></div><div class="task-current-meta">${item.project === "independent" ? `<span>独立任务</span>` : `<a href="#project/${encodeURIComponent(item.project)}">${esc(projectName(item.project))}</a>`}<span class="task-current-meta-separator">·</span><span>${item.kind === "task_line" ? "任务线" : esc(workType(item))}</span><span class="task-current-meta-separator">·</span><code class="task-current-id">ID ${esc(item.id)}</code><span class="task-current-updated">最近更新 ${esc(stamp(item))}</span></div></header><div class="task-current-actions">${actions}</div><article class="task-current-body article md">${section("任务目标", item.goal, "暂无目标。")}${section("任务描述", item.description, "暂无描述。")}${section("当前结果", item.current, "尚无结果记录。")}${item.next ? section("下一步", item.next, "") : ""}${related}${technical}<section class="task-execution-log"><h3>执行日志</h3>${logs ? `<ol class="task-log-list">${logs}</ol>` : `<p class="muted">暂无执行日志。</p>`}</section>${open ? "" : `<p class="muted">已完成任务只读。</p>`}</article></section>${pane}</div>`;
  }

  /* ---------- 资料浏览 ---------- */
  function libraryLayout(key) {
    const f = filters[key], isLibrary = key === "library";
    const subtypes = f.kind === "input" ? [["", "全部输入类型"], ["snapshot", "快照"], ["reference", "引用"]] : [["", "全部交付状态"], ["draft", "草稿交付"], ["formal", "正式交付"]];
    return `<section class="library-file-controls${isLibrary ? "" : " project-material-controls"}"><div class="search-wrap"><span class="search-icon" aria-hidden="true">⌕</span><input id="${key}-search" type="search" data-filter="${key}" data-field="query" aria-label="搜索资料" placeholder="搜索文件名、任务或用途" value="${esc(f.query)}"></div>${isLibrary ? `<select id="library-project" data-filter="library" data-field="project" aria-label="项目">${projectOptions(f.project)}</select>` : ""}<select id="${key}-subtype" data-filter="${key}" data-field="subtype" aria-label="资料类型">${subtypes.map(([value, name]) => option(value, name, f.subtype)).join("")}</select></section><div class="library-file-first-layout"><section class="panel library-material-index"><header class="library-column-head"><div><h2>${f.kind === "input" ? "输入资料" : "交付文件"}</h2><span id="${key}-file-count" class="meta"></span></div>${isLibrary ? `<button class="button ghost" type="button" data-action="clear-files" id="library-clear"${ui.library.size ? "" : " hidden"}>清空选择</button>` : ""}</header><div id="${key}-file-list" class="library-material-list"></div>${isLibrary ? `<footer id="library-selection" class="library-selection-bar"${ui.library.size ? "" : " hidden"}></footer>` : ""}</section><section id="${key}-file-preview" class="panel library-material-preview"><header class="library-column-head"><div class="library-preview-title-block"><h2>内容预览</h2><span class="meta">选择文件后查看内容</span></div></header><div class="library-source-strip"><span>尚未选择资料。</span></div><div class="library-preview-body library-full-preview"><div class="library-preview-placeholder">从左侧选择文件或输入资料。</div></div></section></div>`;
  }

  function renderLibrary() {
    const f = filters.library;
    const count = kind => data().files.filter(item => kind === "input" ? item.kind === "input" : ["draft", "formal"].includes(item.kind)).length;
    main.className = "shell app-main library-page paper-management-page";
    main.innerHTML = `<div class="library-material-page"><header class="library-page-head"><div><h1>资料浏览</h1><p>以文件为主浏览交付与输入资料；项目和任务仅作为来源关系。</p></div><div class="library-kind-tabs" role="tablist" aria-label="资料类型">${[["delivery", "交付文件"], ["input", "输入资料"]].map(([id, title]) => `<button class="${f.kind === id ? "active" : ""}" type="button" role="tab" data-action="library-tab" data-id="${id}" aria-selected="${f.kind === id}">${title}<span>${count(id)}</span></button>`).join("")}</div></header>${libraryLayout("library")}</div>`;
    renderFiles("library"); renderFileSelection();
  }

  function matchingFiles(key) {
    const f = filters[key], q = f.query.trim().toLowerCase();
    return data().files.filter(item => (key !== "project" || item.project === state.id) && (f.kind === "input" ? item.kind === "input" : ["draft", "formal"].includes(item.kind)) && (!f.project || item.project === f.project) && (!f.subtype || (f.subtype === "snapshot" ? item.storage !== "reference" : f.subtype === "reference" ? item.storage === "reference" : item.kind === f.subtype)) && (!q || [item.name, projectName(item.project), task(item.taskId)?.title || "", item.purpose || ""].join(" ").toLowerCase().includes(q)));
  }

  function fileRow(item, selectable) {
    const checked = ui.library.has(item.id), source = task(item.taskId);
    return `<article class="library-material-row${checked ? " selected" : ""}${ui.file === item.id ? " previewing" : ""}" data-file-id="${esc(item.id)}">${selectable ? `<input type="checkbox" data-select-file="${esc(item.id)}" aria-label="选择 ${esc(item.name)}"${checked ? " checked" : ""}>` : ""}<span class="library-node-icon" aria-hidden="true">${fileIcon(item)}</span><button type="button" data-action="file-read" data-id="${esc(item.id)}"><strong>${esc(item.name)}</strong><small>${esc(kindName(item.kind))} · ${bytes(item.bytes)}${item.purpose ? ` · ${esc(item.purpose)}` : ""}</small><small>${esc(projectName(item.project))}${source ? ` · 关联任务：${esc(source.title)}` : ""}</small></button>${source ? `<a href="${taskLink(source)}" title="查看关联任务">任务</a>` : ""}</article>`;
  }

  function renderFiles(key) {
    const items = matchingFiles(key);
    document.getElementById(`${key}-file-list`).innerHTML = items.map(item => fileRow(item, key === "library")).join("") || `<div class="library-empty">没有符合当前条件的资料。</div>`;
    document.getElementById(`${key}-file-count`).textContent = `${items.length} 项`;
    if (state.preview?.id && ui.file && items.some(item => item.id === ui.file)) showPreview(key, state.preview);
  }

  function renderFileSelection() {
    const bar = document.getElementById("library-selection");
    if (!bar) return;
    bar.hidden = !ui.library.size;
    document.getElementById("library-clear").hidden = !ui.library.size;
    bar.innerHTML = ui.library.size ? `<div><strong>已选 ${ui.library.size} 项</strong><span>原资料保持只读</span></div>${actionKey("files-context", "基于所选资料准备上下文")}` : "";
  }

  function filePreviewHtml(item) {
    const source = task(item.taskId);
    const body = typeof item.text === "string" ? (/\.(md|markdown)$/i.test(item.name) ? `<article class="article md">${markdown(item.text)}</article>` : `<pre class="library-text-preview">${esc(item.text)}</pre>`) : `<div class="library-file-info"><h3>${esc(item.name)}</h3><div class="library-file-meta"><span>类型</span><span>${esc(kindName(item.kind))}</span><span>大小</span><span>${bytes(item.bytes)}</span></div><p class="muted">此文件不提供文本预览，请下载后使用对应应用打开。</p></div>`;
    return `<div class="library-source-strip"><span><strong>${esc(kindName(item.kind))}</strong> ／ ${esc(projectName(item.project))}${source ? ` ／ 关联任务：${esc(source.title)}` : ""}</span>${source ? `<a class="button ghost" href="${taskLink(source)}">查看任务</a>` : ""}</div><div class="library-preview-body library-full-preview">${body}<div class="library-file-actions"><a class="button ghost" href="api/raw?id=${encodeURIComponent(item.id)}" download>下载</a></div></div>`;
  }

  function showPreview(key, item) {
    const panel = document.getElementById(`${key}-file-preview`);
    if (!panel) return;
    panel.innerHTML = `<header class="library-column-head"><div class="library-preview-title-block"><h2>${esc(item.name)}</h2><span class="meta">${esc(kindName(item.kind))} · ${bytes(item.bytes)}</span></div></header>${filePreviewHtml(item)}`;
  }

  async function readFile(id) {
    const item = file(id);
    if (!item) throw new Error("该文件已不在当前工作区，请刷新页面。");
    const result = await api(`api/file?id=${encodeURIComponent(id)}`);
    ui.file = id; state.preview = { ...item, ...result };
    const key = state.route === "project" ? "project" : "library";
    const panel = document.getElementById(`${key}-file-preview`);
    main.querySelectorAll(".library-material-row").forEach(row => row.classList.toggle("previewing", row.dataset.fileId === id));
    if (panel && window.innerWidth > 1180) showPreview(key, state.preview);
    else openDialog(item.name, filePreviewHtml(state.preview), "drawer");
  }

  /* ---------- 任务检视 ---------- */
  function renderReview() {
    const f = filters.review, types = [...new Set(data().tasks.map(t => t.work_type))];
    const activeFilters = [f.project, f.type, f.status].filter(Boolean).length;
    main.className = "shell app-main organization-page paper-management-page";
    main.innerHTML = `<header class="review-page-head"><div class="review-page-heading"><h1>任务检视</h1><p>${data().tasks.length} 项任务 · ${data().tasks.filter(t => t.status === "active").length} 项进行中 · ${data().tasks.filter(t => t.important).length} 项当前重点</p></div><button id="save-report-button" class="button ghost" type="button" data-action="new-report">保存整理报告</button></header><div class="primary-view-panel"><div class="organization-task-workspace"><section class="panel selected-task-organizer"><div class="review-task-head"><div><h2>任务列表</h2><span id="review-count">0 项</span></div></div><div class="organize-task-form"><div class="organize-task-search"><div class="search-wrap"><span class="search-icon" aria-hidden="true">⌕</span><input id="review-search" type="search" data-filter="review" data-field="query" aria-label="搜索任务" placeholder="搜索任务名称、目标或日志" value="${esc(f.query)}"></div></div><div class="organize-task-filters"><button class="button ghost review-filter-toggle" type="button" data-action="review-filters" aria-expanded="${ui.reviewFilters}">筛选<span>${activeFilters}</span></button><div class="review-filter-fields"${ui.reviewFilters ? "" : " hidden"}><select data-filter="review" data-field="project" aria-label="项目">${projectOptions(f.project)}</select><select data-filter="review" data-field="type" aria-label="任务类型">${option("", "全部任务类型", f.type)}${types.map(type => option(type, workNames[type] || type, f.type)).join("")}</select><select data-filter="review" data-field="status" aria-label="任务状态">${option("", "全部任务状态", f.status)}${Object.entries(statusNames).map(([value, name]) => option(value, name, f.status)).join("")}</select><button class="button ghost review-filter-reset" type="button" data-action="reset-filter" data-id="review">重置筛选</button></div><select class="review-sort-control" data-filter="review" data-field="sort" aria-label="排序">${option("updated", "最近更新优先", f.sort)}${option("title", "按名称", f.sort)}</select></div><div id="review-task-list" class="organize-task-list"></div><div class="organize-task-footer"><span id="review-selection-count" class="organize-task-count">未选择任务</span><div class="organize-task-footer-actions"><button class="button ghost" type="button" data-action="clear-review">清空选择</button>${actionKey("review-context", "准备所选任务整理上下文", 'id="review-context-button"')}</div></div></div></section><section class="panel organization-task-preview review-inspector"><div class="review-inspector-tabs"><strong>任务卡</strong></div><div id="review-task-preview"></div></section></div></div><section class="review-organization-section"><div class="organization-report-workspace"><section class="panel organization-report-list-panel"><div class="organization-card-head"><div><h2>历史整理报告</h2><p>查看历次建议、确认结果与记录。</p></div><div class="organization-report-tools"><span class="mode-mark">${data().reports.length} 份</span></div></div><div class="organization-report-filters">${[["", "全部"], ["weekly", "按周"], ["selected", "按任务"]].map(([value, name]) => `<button class="organization-report-filter${ui.reportFilter === value ? " active" : ""}" type="button" data-action="report-filter" data-id="${value}">${name}</button>`).join("")}</div><div class="organization-report-list">${data().reports.filter(r => !ui.reportFilter || r.mode === ui.reportFilter).map(r => `<button class="organization-report-item${ui.reviewReport === r.id ? " active" : ""}" type="button" data-action="report-read" data-id="${esc(r.id)}"><span><span class="organization-report-title">${esc(r.title)}</span><span class="organization-report-meta">${r.mode === "weekly" ? "按周整理" : "按任务整理"} · ${esc(r.date)}</span></span></button>`).join("") || `<div class="library-empty">还没有保存的整理报告。</div>`}</div></section><section class="panel organization-report-preview"><div class="review-inspector-tabs"><strong>整理报告</strong></div><div id="review-report-preview"></div></section></div></section>`;
    renderReviewList();
    renderReviewPreview();
    renderReportPreview();
  }

  function renderReviewList() {
    const items = matchingTasks("review");
    document.getElementById("review-task-list").innerHTML = items.map(t => `<div class="organize-task-item${ui.reviewTask === t.id ? " active" : ""}" data-task-id="${esc(t.id)}"><input type="checkbox" data-select-task="${esc(t.id)}" aria-label="选择 ${esc(t.title)}"${ui.review.has(t.id) ? " checked" : ""}><button type="button" class="organize-task-main" data-action="review-read" data-id="${esc(t.id)}"><span class="organize-task-title-row"><span class="organize-task-title">${esc(t.title)}</span>${t.kind === "task_line" ? `<span class="task-group-tag">任务线</span>` : ""}</span><span class="organize-task-meta">${esc(projectName(t.project))} · ${esc(workType(t))} · 最近修改 ${esc(stamp(t))}</span></button>${badge(t)}</div>`).join("") || `<div class="review-task-empty"><strong>没有匹配任务</strong><span>可以调整搜索词或筛选条件。</span></div>`;
    document.getElementById("review-count").textContent = `${items.length} 项`;
    renderReviewSelection();
  }

  function renderReviewSelection() {
    const visible = new Set(matchingTasks("review").map(t => t.id));
    const hidden = [...ui.review].filter(id => !visible.has(id)).length;
    document.getElementById("review-selection-count").textContent = ui.review.size ? `已选 ${ui.review.size} 项${hidden ? `（${hidden} 项在当前筛选外）` : ""}` : "未选择任务";
    document.getElementById("review-context-button").disabled = !ui.review.size;
  }

  function taskPreview(item) {
    return `<div class="organization-preview-content"><div class="organization-preview-head"><div><h2>${esc(item.title)}</h2><div class="organization-preview-meta">${esc(projectName(item.project))} · ${esc(statusNames[item.status] || item.status)} · 最近更新 ${esc(stamp(item))}</div></div></div><div class="organization-preview-body article md"><h3>任务目标</h3>${markdown(item.goal) || "<p>暂无目标。</p>"}<h3>当前结果</h3>${markdown(item.current) || "<p>尚无结果记录。</p>"}${item.next ? `<h3>下一步</h3>${markdown(item.next)}` : ""}<h3>执行日志</h3>${(item.logs || []).length ? `<ul>${item.logs.slice(0, 8).map(log => `<li>${log.date ? `<b>${esc(log.date)}</b> ` : ""}${inline(log.text)}</li>`).join("")}</ul>` : "<p>暂无执行日志。</p>"}</div><div class="organization-preview-actions"><a class="button ghost" href="${taskLink(item)}">查看完整任务详情</a></div></div>`;
  }

  function renderReviewPreview() {
    const node = document.getElementById("review-task-preview"), item = task(ui.reviewTask);
    node.innerHTML = item ? taskPreview(item) : `<div class="organization-preview-placeholder">点击任务，核对目标、当前结果、执行日志和交付情况。勾选框只用于选择整理范围。</div>`;
  }

  function renderReportPreview() {
    const node = document.getElementById("review-report-preview"), report = data().reports.find(r => r.id === ui.reviewReport);
    node.innerHTML = report ? `<div class="organization-preview-content"><div class="organization-preview-head"><div><h2>${esc(report.title)}</h2><div class="organization-preview-meta">${report.mode === "weekly" ? "按周整理" : "按任务整理"} · ${esc(report.date)}</div></div></div><div class="organization-preview-body article md">${markdown(report.content)}</div></div>` : `<div class="organization-preview-placeholder">选择历史报告，即可查看该轮整理的建议和确认结果。</div>`;
  }

  /* ---------- 设置 ---------- */
  function renderSettings() {
    main.className = "shell app-main settings-page paper-management-page";
    main.innerHTML = `<section class="settings-hub paper-management-page"><header class="settings-hub-head"><div><h1>设置</h1><p>本机执行环境与当前文档库的基础 Skill，在这里查看和管理。</p></div><div class="settings-hub-actions"><button id="health-check-button" class="button" type="button" data-action="health-check">检查服务状态</button></div></header><nav class="settings-section-nav" aria-label="设置分区"><a href="#settings" data-action="scroll-to" data-id="execution-environment">执行环境</a><a href="#settings" data-action="scroll-to" data-id="settings-skills-section">Skills</a></nav><section id="execution-environment" class="settings-execution-strip"><div class="settings-section-head"><div><h2>执行环境</h2><p>先看当前生效的环境，需要时再修改配置。</p></div><span>仅对这台电脑生效</span></div><div id="software-content" aria-live="polite">正在读取本机已保存的软件清单…</div></section><section id="health-result" class="settings-health-summary"><div class="settings-health-main"><span class="settings-health-state">服务状态</span><small>只在点击“检查服务状态”后检查；不会验证软件登录或调用模型。</small></div></section><section id="settings-skills-section" class="settings-skills-module"><div class="settings-skills-head"><div><h2>Skills</h2><p>这里显示当前文档库保留的基础 Skill。首次引导完成并确认移除后，日常任务入口和项目建立继续保留。登记不代表模型已登录或能够执行；专业业务 Skill 由你另行准备。</p></div></div><div id="settings-skills" class="compact-skill-list">正在读取当前工作区的登记…</div></section></section>`;
    readSettings();
  }

  const cloneEntries = entries => entries.map(entry => ({ ...entry }));
  const softwareSignature = () => JSON.stringify([software.entries, software.default, software.manual]);
  const softwarePayload = () => ({ executors: software.entries, default_executor: software.default, expected_revision: state.settings.execution_environment.revision });

  async function readSettings() {
    const request = ++state.settingsRequest;
    try {
      const result = await api("api/settings");
      if (request !== state.settingsRequest || state.route !== "settings") return;
      state.settings = result;
      resetSoftware();
      renderSoftware();
      document.getElementById("settings-skills").innerHTML = result.skills.map(item => `<details class="compact-skill-row core-skill"><summary><span class="setting-identity"><strong>${esc(item.name)}</strong><small>${esc(item.purpose || "已登记基础 Skill")}</small></span><span class="setting-category">基础</span><span class="skill-status available">${esc(item.version)}</span><span class="skill-detail-toggle" aria-hidden="true"></span></summary><div class="compact-skill-detail"><code>${esc(item.path || item.name)}</code></div></details>`).join("") || `<p class="form-error">登记结果为空；请检查工作区契约，不要把它当作能力已验证。</p>`;
    } catch (error) {
      if (request !== state.settingsRequest || state.route !== "settings") return;
      document.getElementById("software-content").innerHTML = `<p class="form-error">${esc(error.message)} · 原配置保留，未当作空清单。</p><button class="button" type="button" data-action="settings-reload">重新读取</button>`;
      document.getElementById("settings-skills").textContent = "登记暂不可读，不能确定已安装能力。";
    }
  }

  function resetSoftware() {
    const saved = state.settings.execution_environment;
    software.epoch++;
    software.entries = cloneEntries(saved.executors);
    software.default = saved.default_executor;
    software.editing = !saved.ready;
    software.manual = { label: "", kind: "app", path: "" };
  }

  function renderSoftware() {
    const saved = state.settings.execution_environment;
    const current = saved.executors.find(entry => entry.id === saved.default_executor);
    const status = saved.ready ? "saved" : !saved.registry_readable || saved.default_executor ? "unavailable" : "empty";
    const heading = saved.ready ? "已配置 · 软件路径可用" : !saved.registry_readable ? "配置暂不可读" : current ? "软件路径需要修复" : "尚未配置本机环境";
    const rows = software.entries.map(entry => `<div class="executor-local-row software-registered-row" data-software-id="${esc(entry.id)}"><input data-software-field="label" value="${esc(entry.label)}" maxlength="80" aria-label="软件名称"><select data-software-field="kind" aria-label="软件类型">${option("app", "桌面应用", entry.kind)}${option("command", "命令行程序", entry.kind)}</select><input data-software-field="path" value="${esc(entry.path)}" maxlength="4096" spellcheck="false" aria-label="软件路径"><button class="button ghost" type="button" data-action="remove-software" data-id="${esc(entry.id)}">移除</button></div>`).join("");
    document.getElementById("software-content").innerHTML = `<div id="software-summary" class="executor-current-environment" data-environment-state="${status}"><div class="executor-current-main"><div class="executor-current-heading"><small>当前生效 · 本机配置</small><span class="skill-status ${saved.ready ? "registered" : "unavailable"}">${esc(heading)}</span></div><h3 id="current-software-name">${esc(current?.label || "未选择默认软件")}</h3>${current ? `<div class="executor-current-path"><span>${current.kind === "app" ? "桌面应用" : "命令行程序"}</span><code>${esc(current.path)}</code></div>` : ""}<p>${esc(saved.error || (saved.ready ? "确认执行时可复制提示词并打开这个软件；请在软件中手工粘贴、发送。" : "添加本机软件、选择默认项，检查后明确保存。"))}</p></div><div class="executor-current-actions"><button id="edit-software" class="button" type="button" data-action="edit-software" aria-controls="software-editor" aria-expanded="${software.editing}">${saved.ready ? "修改配置" : "配置 / 修复"}</button><small>${saved.registry_readable ? `已登记 ${saved.executors.length} 个软件` : "本机清单未知"}<br>模型和登录由软件管理</small></div></div><div id="software-editor" class="executor-settings-editor"${software.editing ? "" : " hidden"}><div class="action-form executor-settings-form"><div class="executor-editor-heading"><h3>修改本机执行环境</h3><p>1 添加本机软件 · 2 选择默认软件 · 3 检查并保存</p></div><div class="executor-editor-section-head"><strong>1 · 本机软件清单</strong><button id="find-software" class="button ghost" type="button" data-action="discover-software" aria-controls="software-candidates" aria-expanded="false">自动查找软件</button></div><div id="software-candidates" class="executor-discovery" hidden></div><div id="software-registered-list" class="executor-local-list">${rows || '<div class="executor-local-empty">清单为空。先查找，或手工添加有效的本机应用 / 命令行程序。</div>'}</div><small class="executor-editor-hint">可以编辑或移除已有软件，也可以查找或手工添加。这里只更改草稿，不会启动软件。</small><div class="executor-add-fields software-manual"><label>软件名称<input id="software-name" maxlength="80" placeholder="例如：我的 AI 助手" value="${esc(software.manual.label)}"></label><label>软件类型<select id="software-kind">${option("app", "桌面应用（.app）", software.manual.kind)}${option("command", "命令行程序", software.manual.kind)}</select></label><label>软件路径<input id="software-path" maxlength="4096" spellcheck="false" value="${esc(software.manual.path)}" placeholder="/Applications/软件.app 或可执行文件路径"></label><button id="add-software" class="button ghost" type="button" data-action="add-software">手工添加</button></div><label id="software-default-field" class="executor-default-field">2 · 选择默认软件<select id="default-software">${softwareOptions()}</select><small>确认执行时“复制并打开”会使用这里保存的软件。</small></label><small id="software-editor-state" class="executor-settings-state" data-state="unchanged" role="status" aria-live="polite">与已保存配置一致；修改后请检查并保存。</small><div class="executor-settings-actions"><button id="check-software" class="button ghost" type="button" data-action="check-software">检查软件路径</button><button id="save-software" class="button primary" type="button" data-action="save-software">保存配置</button><button id="cancel-software" class="button ghost" type="button" data-action="cancel-software">取消修改</button></div><p class="executor-editor-hint">保存才会更新本机余烬配置；不读取或修改软件的模型、登录和权限。</p></div></div><span class="settings-source-line executor-config-source">配置位置 <code>${esc(saved.config_path)}</code></span>`;
  }

  function softwareOptions() {
    return option("", "请选择本机软件", software.default) + software.entries.map(entry => option(entry.id, entry.label, software.default)).join("");
  }

  function softwareStatus(kind, message) {
    const node = document.getElementById("software-editor-state");
    if (node) { node.dataset.state = kind; node.textContent = message; }
  }

  function softwareChanged() {
    software.epoch++;
    softwareStatus("dirty", "修改尚未保存。当前生效环境仍是上方已保存的配置。");
    const select = document.getElementById("default-software");
    if (select) select.innerHTML = softwareOptions();
  }

  function addSoftware(entry, manual = false) {
    if (!entry.label.trim() || !entry.path.trim()) throw new Error("请填写软件名称和路径，再添加到清单。");
    if (software.entries.some(item => item.kind === entry.kind && item.path === entry.path)) throw new Error("这个路径已经在清单中，请修改现有条目。");
    if (software.entries.length >= 32) throw new Error("本机清单最多登记 32 项软件。");
    software.entries.push({ id: entry.id, label: entry.label, kind: entry.kind, path: entry.path });
    if (manual) software.manual = { label: "", kind: "app", path: "" };
    software.epoch++;
    if (!software.default && software.entries.length === 1) {
      software.default = entry.id;
      renderSoftware();
      softwareStatus("dirty", "已添加并设为默认软件，尚未保存；请检查后保存。");
      highlightDefault();
      return;
    }
    renderSoftware();
    softwareStatus("dirty", "已添加到编辑清单，尚未保存；请选择默认软件，检查后保存。");
    document.querySelector(`[data-software-id="${entry.id}"] [data-software-field="path"]`).focus();
  }

  // Choosing a found program adds it when needed and makes it the default in one step.
  function chooseFoundSoftware(entry) {
    const existing = software.entries.find(item => item.kind === entry.kind && item.path === entry.path);
    if (!existing) {
      if (software.entries.length >= 32) throw new Error("本机清单最多登记 32 项软件。");
      software.entries.push({ id: entry.id, label: entry.label, kind: entry.kind, path: entry.path });
    }
    software.default = (existing || entry).id;
    software.epoch++;
    renderSoftware();
    softwareStatus("dirty", `已选用 ${entry.label} 作为默认软件；尚未保存，请检查后保存。`);
    highlightDefault();
  }

  function highlightDefault() {
    const field = document.getElementById("software-default-field");
    field?.classList.remove("needs-choice");
    field?.classList.add("is-chosen");
    setTimeout(() => field?.classList.remove("is-chosen"), 1600);
    document.getElementById("default-software")?.focus();
  }

  function closeFoundSoftware() {
    software.epoch++;
    const node = document.getElementById("software-candidates");
    if (node) { node.hidden = true; node.innerHTML = ""; }
    document.getElementById("find-software")?.setAttribute("aria-expanded", "false");
  }

  async function softwareRequest(kind) {
    if (software.saving) return;
    if (kind !== "discover" && (software.manual.label.trim() || software.manual.path.trim())) throw new Error("手工填写的软件还未添加，请先点“手工添加”，或清空未添加的草稿。");
    if (kind !== "discover" && software.entries.length && !software.default) {
      const message = "请先在「2 · 选择默认软件」里选一个软件，再检查或保存。";
      softwareStatus("error", message);
      document.getElementById("software-default-field")?.classList.add("needs-choice");
      document.getElementById("default-software")?.focus();
      throw new Error(message);
    }
    const epoch = software.epoch, signature = softwareSignature();
    if (kind === "save") {
      software.saving = true;
      document.querySelectorAll("#software-editor input,#software-editor select,#software-editor button,#edit-software").forEach(node => { node.disabled = true; });
    }
    try {
      if (kind === "discover") {
        const result = await api("api/executors/discover", {});
        if (epoch !== software.epoch || state.route !== "settings") return;
        const node = document.getElementById("software-candidates");
        node.hidden = false;
        document.getElementById("find-software")?.setAttribute("aria-expanded", "true");
        const candidates = result.candidates.filter(entry => /^[a-z0-9][a-z0-9_-]{0,63}$/.test(entry.id) && ["app", "command"].includes(entry.kind) && typeof entry.path === "string" && typeof entry.label === "string");
        ui.foundSoftware = candidates;
        const known = entry => software.entries.some(item => item.kind === entry.kind && item.path === entry.path);
        node.innerHTML = `<div class="executor-discovery-head"><small>${candidates.length ? `找到 ${candidates.length} 个候选。点「选用」即加入清单并设为默认；尚未保存。` : esc(result.scope)}${result.limited ? " · 查找范围受限，结果可能不完整。" : ""}${result.warnings.map(item => " · " + esc(item)).join("")}</small><button class="button ghost" type="button" data-action="close-found-software">收起</button></div><div class="software-candidate-list">${candidates.map((entry, index) => `<div class="software-candidate${known(entry) ? " is-added" : ""}"><div><strong>${esc(entry.label)}</strong><code>${esc(entry.path)}</code></div><button class="button ghost" type="button" data-action="choose-found-software" data-id="${index}" aria-label="${known(entry) ? "设为默认" : "选用"} ${esc(entry.label)}">${known(entry) ? "设为默认" : "选用"}</button></div>`).join("") || `<p>${result.warnings.length || result.limited ? "未得到完整结果；可重试或手工添加。" : "在常见安装目录未找到支持的软件；可手工添加，不会自动安装。"}</p>`}</div>`;
        return;
      }
      softwareStatus(kind === "save" ? "saving" : "checking", kind === "save" ? "正在保存本机清单…" : "正在检查路径；不会启动软件或保存…");
      const result = await api(`api/executors/${kind}`, softwarePayload());
      if (kind === "check") {
        if (epoch === software.epoch && signature === softwareSignature() && state.route === "settings") softwareStatus("checked", "路径检查通过，但尚未保存；模型和登录没有验证。");
      } else {
        state.settings.execution_environment = result;
        resetSoftware();
        if (state.route === "settings") renderSoftware();
        notice("本机环境已保存。客户端模型、账号、会话与任务记录均未修改。");
      }
    } catch (error) {
      if (epoch === software.epoch && state.route === "settings") {
        softwareStatus("error", error.message);
        throw error;
      }
    } finally {
      if (kind === "save") {
        software.saving = false;
        document.querySelectorAll("#software-editor input,#software-editor select,#software-editor button,#edit-software").forEach(node => { node.disabled = false; });
      }
    }
  }

  function renderRoute() {
    document.body.classList.toggle("paper-management-shell", state.route !== "home");
    const renders = { home: renderHome, projects: renderProjects, project: renderProject, task: renderTask, library: renderLibrary, review: renderReview, settings: renderSettings };
    const render = renders[state.route];
    if (render) render();
    else { main.className = "shell app-main"; main.innerHTML = `<section class="panel not-found"><h1>页面不存在</h1><p>这个地址不在开源版工作台中。</p><a href="#home">返回任务台</a></section>`; }
    const heading = state.route === "home" ? "任务台" : main.querySelector("h1")?.textContent || "工作台";
    document.title = `${heading} · 余烬`;
  }

  /* ---------- 弹窗表单 ---------- */
  function newTask(projectId = "independent") {
    openDialog("新建任务", `<form id="new-task-form" class="stack dialog-form" data-form="new-task"><label>任务名称<input id="task-title" name="title" required maxlength="20" placeholder="20字内的完整名称"></label><div class="field-grid"><label>归属项目 / 系统<select id="task-project" name="project">${projectOptions(projectId, false)}</select></label><label>工作类型<select name="work_type">${Object.entries(workNames).map(([id, name]) => option(id, name, "mixed")).join("")}</select></label></div><label>任务目标<textarea id="task-goal" name="goal" required placeholder="明确要得到什么结果"></textarea></label><label>任务描述<textarea name="description" placeholder="背景、范围与约束"></textarea></label><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary" id="create-task-submit" type="submit">保存任务</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  function newProject() {
    openDialog("新建项目", `<form id="new-project-form" class="stack dialog-form" data-form="new-project"><div class="field-grid"><label>类型<select id="project-kind" name="kind"><option value="project">项目</option><option value="system">系统</option></select></label><label>分类<input id="project-category" name="category" maxlength="20" list="project-category-options" placeholder="可选，例如 内容运营"><datalist id="project-category-options">${categories().map(name => option(name, name, "")).join("")}</datalist></label></div><div class="field-grid"><label>名称<input id="project-name" name="name" required maxlength="60"></label><label>标识<input id="project-id" name="id" required pattern="[a-z0-9][a-z0-9_-]*" placeholder="例如 community-notes"></label></div><label>简短说明<textarea name="description" required></textarea></label><label>当前重点<input name="focus"></label><label>本机工作目录<input name="location" placeholder="可选，绝对路径；AI 在这个目录协作时会对应本项目"></label><p class="form-error" role="alert"></p><div class="form-actions"><button id="create-project-submit" type="submit" class="button primary">保存到工作区</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  function editTask(id) {
    const t = task(id);
    openDialog("更新任务记录", `<form id="edit-task-form" class="stack dialog-form" data-form="edit-task" data-id="${esc(id)}"><label>当前结果<textarea id="task-current" name="current">${esc(t.current)}</textarea></label><label>下一步<textarea id="task-next" name="next">${esc(t.next)}</textarea></label><label>新增执行日志<textarea id="task-log-entry" name="log_entry" placeholder="写下本次行动和已验证的结果"></textarea></label><label>任务状态<select name="status">${Object.entries(statusNames).filter(([value]) => value !== "completed" || t.status === "completed").map(([value, name]) => option(value, name, t.status)).join("")}</select></label><small>完成与正式交付使用独立的确认操作。</small><p class="form-error" role="alert"></p><div class="form-actions"><button id="update-task-submit" class="button primary" type="submit">保存记录</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  function addMaterial(id) {
    openDialog("添加资料", `<form id="material-form" class="stack dialog-form" data-form="material" data-id="${esc(id)}"><label>资料用途<select id="material-kind" name="kind"><option value="input">输入资料</option><option value="draft">草稿交付</option><option value="reference">引用已有资料</option></select></label><fieldset id="material-text-fields" class="stack"><label>文件名称<input id="material-name" name="name" required placeholder="例如 方案.md"></label><label>文本内容<textarea id="material-content" name="content" required rows="12"></textarea></label><small>按所选用途写入独立目录。已有同名文件不会被覆盖。</small></fieldset><fieldset id="material-reference-fields" class="stack" disabled hidden><label>来源资料<select id="material-reference-path" name="reference_path"><option value="">选择当前工作区内的文件</option>${data().files.map(f => option(f.id, `${f.name} · ${kindName(f.kind)} · ${task(f.taskId)?.title || projectName(f.project)}`, "")).join("")}</select></label><small>登记现有资料的位置和用途，保留来源归属，不复制文件。</small></fieldset><label>资料用途说明<input id="material-purpose" name="purpose" placeholder="例如：作为本次方案的表达参考"></label><p class="form-error" role="alert"></p><div class="form-actions"><button id="material-submit" class="button primary" type="submit">保存资料</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  function completeTask(id) {
    const t = task(id);
    openDialog("完成任务", `<form id="complete-form" class="stack dialog-form" data-form="complete" data-id="${esc(id)}"><p>完成“${esc(t.title)}”。本任务不采用文件交付；确认后保存完成状态，保留任务记录、输入资料与引用。</p><small>此操作不会生成正式交付文件。已完成任务随后只读。</small><label class="check-label"><input id="complete-confirmation" name="confirmation" type="checkbox" required><span>我已核对当前结果，确认任务目标已经达成。</span></label><p class="form-error" role="alert"></p><div class="form-actions"><button id="complete-submit" class="button primary" type="submit">确认完成任务</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  function promote(id) {
    const t = task(id), drafts = data().files.filter(f => f.taskId === id && f.kind === "draft");
    openDialog("正式交付并完成", `<form id="promote-form" class="stack dialog-form" data-form="promote" data-id="${esc(id)}"><p>完成“${esc(t.title)}”，将${drafts.length ? ` ${drafts.length} 个草稿文件` : "现有草稿目录"}复制并校验为正式交付，保留草稿与输入，再保存任务完成状态。</p><div>${drafts.map(f => `<p class="muted">${esc(f.name)}</p>`).join("")}</div><label class="check-label"><input id="promote-confirmation" name="confirmation" type="checkbox" required><span>我已核对当前结果与交付内容，确认正式交付并完成这个任务。</span></label><p class="form-error" role="alert"></p><div class="form-actions"><button id="promote-submit" class="button primary" type="submit">确认正式交付并完成</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  function newReport() {
    openDialog("保存整理报告", `<form id="report-form" class="stack dialog-form" data-form="report"><label>报告名称<input id="report-title" name="title" required></label><label>报告范围<select name="mode"><option value="selected">所选任务</option><option value="weekly">按周整理</option></select></label><p class="muted">当前选择 ${ui.review.size} 项任务。保存的是你填写的报告，不会调整任务结构或生命周期。</p><label>报告内容<textarea id="report-content" name="content" required rows="14"></textarea></label><p class="form-error" role="alert"></p><div class="form-actions"><button id="report-submit" class="button primary" type="submit">保存报告</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  async function mutate(path, payload) {
    const result = await api(path, payload);
    try { await loadState(); }
    catch (error) { const failure = new Error(`操作已保存，但刷新失败：${error.message}。请重新加载页面核对，避免重复提交。`); failure.saved = true; throw failure; }
    return result;
  }

  async function submit(form) {
    if (form.dataset.form === "home-command") {
      const request = document.getElementById("context-request").value.trim();
      if (/^fd\s/.test(request)) { notice("fd 用于检索：从下方结果选择任务或资料，然后写下这次的要求。"); return; }
      openConfirm({ request, relation: composer.task ? (task(composer.task)?.status === "completed" ? "based" : "continue") : "new", taskId: composer.task, fileIds: composer.files, attachments: composer.attachments });
      return;
    }
    if (form.dataset.busy || form.dataset.committed) return;
    const error = formError(form); if (error) error.textContent = "";
    const fields = new FormData(form), payload = Object.fromEntries(fields.entries());
    const controls = [...form.querySelectorAll("button[type=submit]")];
    form.dataset.busy = "true"; controls.forEach(button => { button.disabled = true; button.setAttribute("aria-busy", "true"); });
    try {
      switch (form.dataset.form) {
        case "new-task": {
          const created = await mutate("api/tasks", payload);
          closeDialog(); go(`task/${encodeURIComponent(created.id || created.task_id)}`); notice("任务已保存到当前工作区。"); break;
        }
        case "new-project": {
          const { location: place, ...fields } = payload;
          if (place?.trim()) fields.locations = [place.trim()];
          const created = await mutate("api/projects", fields);
          closeDialog(); go(`project/${encodeURIComponent(created.id || payload.id)}`); notice(`${payload.kind === "system" ? "系统" : "项目"}已保存到工作区。`); break;
        }
        case "edit-task": await mutate(`api/tasks/${encodeURIComponent(form.dataset.id)}`, payload); closeDialog(); notice("任务记录已保存。"); break;
        case "material": {
          const isReference = payload.kind === "reference";
          const path = `api/tasks/${encodeURIComponent(form.dataset.id)}/${isReference ? "references" : "materials"}`;
          const material = isReference ? { path: payload.reference_path, purpose: payload.purpose } : { kind: payload.kind, name: payload.name, content: payload.content, ...(payload.purpose ? { purpose: payload.purpose } : {}) };
          await mutate(path, material); closeDialog(); notice(isReference ? "资料引用已登记，来源文件保持原位。" : "文本资料已保存，原有文件保留。"); break;
        }
        case "complete": await mutate(`api/tasks/${encodeURIComponent(form.dataset.id)}/complete`, { confirmation: fields.has("confirmation") }); closeDialog(); notice("任务已完成，任务记录与资料已保留。"); break;
        case "promote": await mutate(`api/tasks/${encodeURIComponent(form.dataset.id)}/promote`, { confirmation: fields.has("confirmation") }); closeDialog(); notice("正式交付已保存，任务已完成。"); break;
        case "report": await mutate("api/reports", { ...payload, task_ids: [...ui.review] }); closeDialog(); notice("整理报告已保存。"); break;
      }
    } catch (failure) { if (failure.saved) form.dataset.committed = "true"; if (error) error.textContent = failure.message; else notice(failure.message, true); }
    finally { delete form.dataset.busy; controls.forEach(button => { button.disabled = Boolean(form.dataset.committed); button.removeAttribute("aria-busy"); }); }
  }

  async function action(button) {
    if (button.dataset.busy) return;
    const id = button.dataset.id;
    switch (button.dataset.action) {
      case "close-dialog": closeDialog(); return;
      case "open-settings": closeDialog(); go("settings"); return;
      case "settings-reload": await readSettings(); return;
      case "scroll-to": document.getElementById(id)?.scrollIntoView({ block: "start" }); return;
      case "favorite": toggleFavorite(id); return;
      case "edit-software":
        software.editing = true; renderSoftware();
        (document.querySelector("[data-software-field=label]") || document.getElementById("software-name")).focus(); return;
      case "cancel-software":
        if (software.saving) return;
        resetSoftware(); renderSoftware();
        (state.settings.execution_environment.ready ? document.getElementById("edit-software") : document.getElementById("default-software")).focus(); return;
      case "add-software": addSoftware({ ...software.manual, id: "local-" + crypto.randomUUID().replaceAll("-", "") }, true); return;
      case "choose-found-software": chooseFoundSoftware(ui.foundSoftware[Number(id)]); return;
      case "close-found-software": closeFoundSoftware(); document.getElementById("find-software")?.focus(); return;
      case "remove-software":
        software.entries = software.entries.filter(entry => entry.id !== id);
        if (software.default === id) software.default = "";
        software.epoch++; renderSoftware(); softwareStatus("dirty", "已从编辑清单移除，尚未保存。"); return;
      case "new-task": newTask(button.dataset.project); return;
      case "new-project": newProject(); return;
      case "edit-task": editTask(id); return;
      case "add-material": addMaterial(id); return;
      case "promote": promote(id); return;
      case "complete": completeTask(id); return;
      case "status-filter": filters[button.dataset.filter].status = id; renderRoute(); return;
      case "project-category": ui.projectCategory = id; renderProjects(); return;
      case "project-tab": filters.project.kind = id; filters.project.query = ""; filters.project.subtype = ""; ui.file = ""; renderProject(); return;
      case "project-task-filter": filters.project.task = id; renderProjectScene(); return;
      case "task-files": ui.taskFiles = id; renderTask(); return;
      case "library-tab": filters.library.kind = id; filters.library.subtype = ""; ui.file = ""; renderLibrary(); return;
      case "reset-filter": filters[id] = { ...filters[id], query: "", project: "", type: "", status: "" }; renderRoute(); return;
      case "review-filters": ui.reviewFilters = !ui.reviewFilters; renderReview(); return;
      case "report-filter": ui.reportFilter = id; renderReview(); return;
      case "clear-review": ui.review.clear(); renderReviewList(); return;
      case "clear-files": ui.library.clear(); renderLibrary(); return;
      case "review-project": filters.review = { query: "", project: id, type: "", status: "", sort: "updated" }; ui.reviewFilters = true; go("review"); return;
      case "review-read": {
        ui.reviewTask = id;
        main.querySelectorAll(".organize-task-item").forEach(row => row.classList.toggle("active", row.dataset.taskId === id));
        if (window.innerWidth > 1180) renderReviewPreview(); else openDialog(task(id).title, taskPreview(task(id)), "drawer");
        return;
      }
      case "report-read": {
        ui.reviewReport = id; const report = data().reports.find(r => r.id === id);
        main.querySelectorAll(".organization-report-item").forEach(item => item.classList.toggle("active", item.dataset.id === id));
        if (window.innerWidth > 1180) renderReportPreview(); else openDialog(report.title, `<div class="article md">${markdown(report.content)}</div>`, "drawer");
        return;
      }
      case "composer-add-task": composer.task = id; document.getElementById("context-request").value = ""; renderComposerResults(); renderComposer(); document.getElementById("context-request").focus(); return;
      case "composer-add-file": if (!composer.files.includes(id)) composer.files.push(id); document.getElementById("context-request").value = ""; renderComposerResults(); renderComposer(); document.getElementById("context-request").focus(); return;
      case "composer-remove-task": composer.task = ""; renderComposer(); return;
      case "composer-remove-file": composer.files = composer.files.filter(value => value !== id); renderComposer(); return;
      case "composer-remove-attachment": composer.attachments.splice(Number(id), 1); renderComposer(); return;
      case "task-context": {
        const t = task(id), done = t.status === "completed";
        openConfirm({ relation: done ? "based" : "continue", taskId: id, request: done ? `基于已完成任务准备新工作：${t.title}` : t.next || `继续推进：${t.title}` }); return;
      }
      case "project-context": openConfirm({ request: `${project(id).kind === "system" ? "系统" : "项目"}：${projectName(id)}\n当前重点：${project(id).focus || "暂无"}\n\n本次要求：` }); return;
      case "files-context": openConfirm({ fileIds: [...ui.library], request: "请基于所选资料完成：" }); return;
      case "new-report": newReport(); return;
      case "copy-context": {
        await state.contextPromise;
        const text = state.preview?.text;
        if (!text) { notice("上下文还没有生成，请先写下要求并选择任务路由。", true); return; }
        try { await navigator.clipboard.writeText(text); notice("提示词已复制。请在外部工具中粘贴并确认发送。"); }
        catch { selectOutput(); notice("浏览器无法写入剪贴板，已选中提示词，请手动复制。", true); }
        return;
      }
    }
    button.dataset.busy = "true"; button.disabled = true; button.setAttribute("aria-busy", "true");
    try {
      switch (button.dataset.action) {
        case "file-read": await readFile(id); break;
        case "review-context": {
          const result = await api("api/review/context", { task_ids: [...ui.review] });
          openDialog("整理上下文", `<div class="home-prompt-review"><div id="context-output" class="home-prompt-body article md" tabindex="0">${markdown(result.text)}</div></div><div class="form-actions"><button id="copy-context-button" class="button" type="button" data-action="copy-context">复制提示词</button></div>`, "home-confirm-dialog");
          state.preview = { ...(state.preview || {}), text: result.text };
          break;
        }
        case "important": await mutate(`api/tasks/${encodeURIComponent(id)}/important`, { important: !task(id).important, revision: data().revision }); notice("重点状态已保存。任务内容与生命周期未改变。"); break;
        case "health-check": {
          const health = await api("api/health");
          document.getElementById("health-result").innerHTML = `<div class="settings-health-main"><span class="settings-health-state">${health.status === "ready" ? "服务正常" : esc(health.status)}</span><small>检查时间 ${esc(new Date().toLocaleString())}</small></div><div class="settings-health-metrics"><span><b>${esc(health.tasks ?? "—")}</b> 项任务</span><span><b>${esc(health.contract?.skills?.length ?? "—")}</b> 项基础 Skill</span><span>版本 <b>${esc(health.version || "—")}</b></span></div>`;
          break;
        }
        case "discover-software": await softwareRequest("discover"); break;
        case "check-software": await softwareRequest("check"); break;
        case "save-software": await softwareRequest("save"); break;
        case "copy-open-context": {
          await state.contextPromise;
          const preview = state.preview;
          if (!preview?.environment?.ready) throw new Error("请先在设置页保存有效的本机环境。");
          if (!preview.text) throw new Error("上下文还没有生成。");
          try { await navigator.clipboard.writeText(preview.text); }
          catch { selectOutput(); notice("无法复制，因此没有打开软件。请手工复制并打开客户端。", true); break; }
          try {
            const opened = await api("api/executors/open", { executor_id: preview.environment.default_executor, expected_revision: preview.environment.revision, confirmation: true });
            notice(`已复制并打开 ${opened.label}。请手工粘贴、发送；没有调用模型。`);
          } catch (error) { notice(`提示词已复制，但软件没有打开：${error.message}`, true); }
          break;
        }
      }
    } finally {
      delete button.dataset.busy; button.removeAttribute("aria-busy");
      if (button.isConnected) button.disabled = button.id === "copy-open-context-button" ? !state.preview?.environment?.ready || !state.preview?.text : false;
    }
  }

  document.addEventListener("submit", event => { const form = event.target.closest("[data-form]"); if (form) { event.preventDefault(); submit(form); } });
  document.addEventListener("click", event => {
    const navigation = event.target.closest('.app-sidebar a[href^="#"]');
    if (navigation) { setMenu(false); if (navigation.hash === location.hash) { main.focus({ preventScroll: true }); window.scrollTo(0, 0); } }
    const control = event.target.closest("[data-action]");
    if (control && (control.tagName === "BUTTON" || control.tagName === "A")) {
      if (control.tagName === "A") event.preventDefault();
      action(control).catch(error => notice(error.message, true));
    }
  });
  document.addEventListener("input", event => {
    const control = event.target;
    if (control.closest("#software-editor")) {
      if (control.tagName === "SELECT") return;
      const row = control.closest("[data-software-id]");
      if (row && control.dataset.softwareField) software.entries.find(entry => entry.id === row.dataset.softwareId)[control.dataset.softwareField] = control.value;
      if (control.id === "software-name") software.manual.label = control.value;
      if (control.id === "software-path") software.manual.path = control.value;
      softwareChanged(); return;
    }
    if (control.id === "context-request") { renderComposerResults(); return; }
    if (control.id === "confirm-request") { confirm.request = control.value; document.getElementById("confirm-count").textContent = `${control.value.length} / 4000`; scheduleContext(); return; }
    if (control.dataset.filter) {
      const key = control.dataset.filter; filters[key][control.dataset.field] = control.value;
      if (key === "home" || key === "review") renderTaskResults(key);
      else if (key === "project") filters.project.kind === "tasks" ? renderProjectTasks() : renderFiles("project");
      else if (key === "library") renderFiles("library");
    }
  });
  document.addEventListener("change", event => {
    const control = event.target;
    if (control.id === "default-software") { document.getElementById("software-default-field")?.classList.remove("needs-choice"); software.default = control.value; softwareChanged(); return; }
    if (control.id === "software-kind") { software.manual.kind = control.value; softwareChanged(); return; }
    if (control.dataset.softwareField === "kind") {
      software.entries.find(entry => entry.id === control.closest("[data-software-id]").dataset.softwareId).kind = control.value;
      softwareChanged(); return;
    }
    if (control.name === "confirm-route") { confirm.relation = control.value; document.getElementById("confirm-task-field").hidden = control.value === "new"; refreshContext(); return; }
    if (control.id === "confirm-task") { confirm.taskId = control.value; refreshContext(); return; }
    if (control.id === "material-kind") {
      const reference = control.value === "reference";
      document.getElementById("material-text-fields").disabled = reference;
      document.getElementById("material-text-fields").hidden = reference;
      document.getElementById("material-reference-fields").disabled = !reference;
      document.getElementById("material-reference-fields").hidden = !reference;
      document.getElementById("material-reference-path").required = reference;
      document.getElementById("material-purpose").required = reference;
    }
    if (control.dataset.selectTask) { control.checked ? ui.review.add(control.dataset.selectTask) : ui.review.delete(control.dataset.selectTask); renderReviewSelection(); }
    else if (control.dataset.selectFile) { control.checked ? ui.library.add(control.dataset.selectFile) : ui.library.delete(control.dataset.selectFile); control.closest(".library-material-row")?.classList.toggle("selected", control.checked); renderFileSelection(); }
  });
  document.addEventListener("keydown", event => {
    if (event.target.id === "context-request" && event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      document.getElementById("context-form").requestSubmit();
    }
  });
  document.addEventListener("paste", event => {
    if (event.target.id !== "context-request" || !event.clipboardData?.files.length) return;
    event.preventDefault(); addAttachments(event.clipboardData.files).catch(error => notice(error.message, true));
  });
  document.addEventListener("dragover", event => { if (event.target.closest?.(".home-composer")) event.preventDefault(); });
  document.addEventListener("drop", event => {
    if (!event.target.closest?.(".home-composer")) return;
    event.preventDefault(); addAttachments(event.dataTransfer.files).catch(error => notice(error.message, true));
  });
  document.querySelector(".skip-link").addEventListener("click", event => { event.preventDefault(); main.focus(); });
  document.getElementById("dialog-close").addEventListener("click", closeDialog);
  document.getElementById("menu-toggle").addEventListener("click", () => setMenu(!sidebar.classList.contains("mobile-open")));
  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", event => { if (event.key === "Escape" && event.target.closest?.("#software-candidates")) { event.preventDefault(); closeFoundSoftware(); document.getElementById("find-software")?.focus(); } });
  window.addEventListener("keydown", event => { if (event.key === "Escape" && !dialog.open && sidebar.classList.contains("mobile-open")) { setMenu(false); document.getElementById("menu-toggle").focus(); } });

  route();
  loadState().catch(error => {
    main.className = "shell app-main";
    main.innerHTML = `<section class="panel load-error"><h1>工作区读取失败</h1><p class="form-error">${esc(error.message)}</p><p class="muted">确认本地服务已启动后，重新加载此页面。之前保存的数据不会被覆盖。</p></section>`;
    document.getElementById("workspace-state").textContent = "工作区不可用";
  });
  return { refresh: loadState };
})();
