"use strict";

/* Ember open-source workbench. Page markup follows the Ember workbench and is styled by
   ember_ui/ (copied verbatim from the workbench, including its shared scripts); data comes only from this
   local workspace through /api. */
const app = (() => {
  const main = document.getElementById("main-content");
  const sidebar = document.getElementById("sidebar");
  const dialog = document.getElementById("workbench-dialog");
  const dialogBody = document.getElementById("dialog-body");
  const state = { data: null, route: "home", id: "", dialogReturn: null, taskMaterials: null, home: null, overview: null, review: null, library: null, preview: null, settings: null, settingsRequest: 0, contextRequest: 0 };
  const ui = { projectCategory: "" };
  const software = { entries: [], default: "", editing: false, manual: { label: "", kind: "app", path: "" }, epoch: 0, saving: false };
  const statusNames = { active: "进行中", waiting_user: "待确认", blocked: "受阻", completed: "已完成" };
  const workNames = { text: "文字", image: "图片", video: "视频", audio: "音频", data: "数据", mixed: "混合", system: "系统" };
  const categoryClasses = ["account_operations", "course_teaching", "novel_writing", "system_building"];
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
  const actionMark = brandMark.replace('class="brand-mark"', 'class="gstudio-mark"');
  const actionKey = (action, label, attrs = "", extra = "") => `<button class="gstudio-action-trigger ${extra}" type="button" data-action="${action}" title="${esc(label)}" aria-label="${esc(label)}" ${attrs}>${actionMark}</button>`;
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
        out.push(`<div class="md-table"><table><thead><tr>${head.map(cell => `<th>${inline(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(r => `<tr>${r.map(cell => `<td>${inline(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
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

  /* One toast for the whole page, from ember_ui/ember-ui.js as in the full workbench. */
  function notice(message, error = false) {
    window.GStudioUI.toast(message, error ? "error" : "info", error ? 9000 : 4500);
  }

  /* The small-screen toggle and saved section/scroll state are ember_ui/sidebar.js. */
  function setMenu(open) { sidebar.setMobileOpen(open); }

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
    document.getElementById("workspace-nav").innerHTML = `${section("收藏项目", favoriteItems, "data-sidebar-favorites").replace('class="sidebar-section"', 'class="sidebar-section sidebar-favorites"').replace(`<div class="sidebar-empty">暂无项目</div>`, `<div class="sidebar-empty">点击项目旁的星标收藏</div>`)}${groups.filter(([, items]) => items.length).map(([name, items]) => section(name, items, `data-work-category-section="${esc(name)}"`)).join("")}`;
    sidebar.restoreNavigation();
    document.getElementById("workspace-state").textContent = data().workspace_name || "本地工作区";
    document.getElementById("workspace-version").textContent = `版本 ${data().version || ""}`;
    for (const link of document.querySelectorAll("[data-nav]")) {
      // As in the workbench: a project page highlights only the project; a task page highlights 任务台 and its project.
      const active = link.dataset.nav === state.route || (state.route === "task" && link.dataset.nav === "home");
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    }
    const navMain = document.querySelector(".sidebar-nav-main");
    navMain.querySelector(".back-link")?.remove();
    if (state.route === "task") navMain.insertAdjacentHTML("afterbegin", `<a class="back-link" href="#projects">← 返回项目视图</a>`);
    for (const link of document.querySelectorAll("[data-project-nav]")) {
      const active = (state.route === "project" && link.dataset.projectNav === state.id) || (state.route === "task" && link.dataset.projectNav === task(state.id)?.project);
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
    const executionDialog = document.getElementById("executionConfirmDialog");
    if (executionDialog.open) executionDialog.close();
    if (data()) { renderNav(); renderRoute(); main.focus({ preventScroll: true }); window.scrollTo(0, 0); }
  }
  function go(hash) { if (location.hash === `#${hash}`) route(); else location.hash = hash; }




  /* ---------- 任务台 ---------- */
  /* Rendered on the server with the full workbench's template (ember_ui/pages/home.py) and driven by
     its scripts (ember_ui/home.js, task-overview.js). This page supplies search, previews, attached
     text files, the prompt preview and what happens after confirmation, from the local workspace. */
  const homeAttachments = new Map();
  const homeHooks = {
    search: query => api(`api/home/search?q=${encodeURIComponent(query)}`),
    taskPreview: id => api(`api/home/task-preview?id=${encodeURIComponent(id)}`),
    materialPreview: item => api(item.preview_url),
    // Only text files are attached, as text inside the prompt; nothing is uploaded or stored.
    async stageFile(file) {
      if (!TEXT_FILE.test(file.name)) throw new Error("只接收 Markdown、TXT、CSV、JSON 文字文件");
      if (file.size > 1048576) throw new Error("超过 1 MB，未加入");
      const text = await file.text(), used = [...homeAttachments.values()].reduce((sum, item) => sum + item.text.length, 0);
      if (used + text.length > ATTACHMENT_LIMIT) throw new Error("附带的文字已接近上下文上限");
      const id = `local-${crypto.randomUUID()}`;
      homeAttachments.set(id, { name: file.name, text });
      return { staging_id: id, name: file.name, size: file.size };
    },
    async previewPrompt(form) {
      const fields = new FormData(form), taskId = String(fields.get("task_id") || ""), mode = String(fields.get("route_mode") || "new");
      const relation = taskId ? { continue: "continue", derive: "based" }[mode] || "new" : "new";
      const fileIds = fields.getAll("material_selection").map(value => { try { return JSON.parse(value).file_id; } catch { return undefined; } }).filter(Boolean);
      const attachments = fields.getAll("staged_file_id").map(id => homeAttachments.get(String(id))).filter(Boolean);
      const payload = { request: String(fields.get("request_text") || "").trim(), relation, file_ids: fileIds, attachments, page: "home" };
      if (relation !== "new") payload.task_id = taskId;
      return executionPreview(form, payload);
    },
    dispatch: (form, prompt) => openWithPrompt(prompt, executionPrompts.get(form)?.environment),
  };

  async function renderHome() {
    main.className = "shell app-main home-page";
    let page;
    try { page = await api("api/pages/home"); }
    catch (error) { if (state.route === "home") main.innerHTML = `<section class="panel load-error"><h1>任务台读取失败</h1><p class="form-error">${esc(error.message)}</p></section>`; return; }
    if (state.route !== "home") return;
    state.home?.destroy(); state.overview?.destroy();
    main.innerHTML = page.html;
    state.home = window.EmberHome.mount(document.getElementById("homeCommandForm"), homeHooks);
    state.overview = window.EmberTaskOverview.mount(document.getElementById("homeAllTasks"));
  }

  /* ---------- 检查更新 ---------- */
  /* Asks GitHub only when clicked. Installing is left to the user's AI tool with the prompt below. */
  const updateState = { result: null, environment: null };
  async function checkUpdate() {
    openDialog("检查更新", `<div class="update-panel" aria-live="polite"><p class="muted">正在查询 GitHub 上的最新发行版…</p></div>`);
    let result, failure = "";
    try { result = await api("api/update"); } catch (error) { failure = error.message; }
    try { updateState.environment = (await api("api/settings")).execution_environment; } catch { updateState.environment = null; }
    updateState.result = result || null;
    const panel = dialogBody.querySelector(".update-panel");
    if (!panel) return;
    const releases = "https://github.com/Evankoo/Ember/releases";
    if (failure) { panel.innerHTML = `<div class="update-summary"><strong>没能检查更新</strong><p class="form-error">${esc(failure)}</p></div><div class="form-actions"><a class="button ghost" href="${releases}" target="_blank" rel="noopener noreferrer">打开发行页</a></div>`; return; }
    const link = `<a class="button ghost" href="${esc(result.url)}" target="_blank" rel="noopener noreferrer">查看发行页</a>`;
    if (!result.newer) { panel.innerHTML = `<div class="update-summary is-current"><strong>已是最新版本 ${esc(result.current)}</strong><p class="muted">GitHub 上最新的发行版是 ${esc(result.latest)}${result.published_at ? `（${esc(result.published_at)} 发布）` : ""}。</p></div><div class="form-actions">${link}</div>`; return; }
    const environment = updateState.environment, selected = environment?.executors?.find(entry => entry.id === environment.default_executor);
    panel.innerHTML = `<div class="update-summary is-new"><strong>发现新版本 ${esc(result.latest)}</strong><p class="muted">当前 ${esc(result.current)}${result.published_at ? ` · ${esc(result.published_at)} 发布` : ""}。更新由你的 AI 工具执行：复制下面的提示词交给它，它会先备份、校验官方程序包，再更新并检查。</p></div>${result.notes.trim() ? `<details class="update-notes" open><summary>更新说明</summary><div class="article md">${markdown(result.notes)}</div></details>` : ""}<section class="home-prompt-review update-prompt"><header><span class="home-prompt-state ready">更新提示词</span><small>${new Intl.NumberFormat("zh-CN").format(result.prompt.text.length)} 字 · 只读</small></header><div class="home-prompt-body article md" id="update-prompt-body" tabindex="0">${markdown(result.prompt.text)}</div></section><p class="execution-confirm-feedback" id="update-feedback" role="status" aria-live="polite"></p><div class="form-actions">${link}<button class="button ghost" type="button" data-action="copy-update">复制更新提示词</button><button class="button primary" type="button" data-action="copy-open-update"${environment?.ready ? "" : " disabled"}>${environment?.ready ? `复制并用 ${esc(selected.label)} 打开` : "未配置执行软件"}</button></div>${environment?.ready ? "" : `<p class="muted">也可以先到 <a href="#settings" data-action="open-settings">设置 → 执行环境</a> 配置常用的 AI 工具。</p>`}`;
  }

  function updateFeedback(message, error = false) {
    const node = document.getElementById("update-feedback");
    if (node) { node.textContent = message; node.classList.toggle("error", error); }
  }

  async function copyUpdatePrompt() {
    const text = updateState.result?.prompt?.text;
    if (!text) throw new Error("没有可复制的更新提示词。");
    try { await navigator.clipboard.writeText(text); return true; }
    catch {
      const area = Object.assign(document.createElement("textarea"), { value: text, readOnly: true, className: "home-prompt-manual-copy" });
      document.getElementById("update-prompt-body").replaceChildren(area); area.focus(); area.select();
      return false;
    }
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
    const column = (key, title, rows) => `<div class="project-view-column" data-board-column="${key}"><div class="project-view-column-head">${title} (${rows.length})</div><div class="project-view-column-body">${rows.map(entry).join("") || `<span class="project-view-task empty">暂无</span>`}</div></div>`;
    const board = `<div class="project-view-board">${column("important", "当前重要事项", important)}${column("active", "进行中", active)}${column("completed", "近 30 天完成", recent)}</div>`;
    const review = `<a class="button ghost" href="#review" data-action="review-project" data-id="${esc(id)}">任务整理</a>`;
    if (id === "independent") return `<article class="project-view-card independent-task-overview" data-project-card="independent" aria-labelledby="independent-task-title"><div class="project-info"><div class="card-head"><h2 id="independent-task-title"><a href="#review" data-action="review-project" data-id="independent">独立任务</a></h2><span class="independent-scope-badge">非项目</span></div><div class="project-focus"><div class="focus-label">当前主线</div><div class="focus-text">尚未形成任务主线</div></div><div class="project-metrics"><div class="project-recent-stats"><div><b>${items.filter(t => t.status === "active").length}</b> 进行中 · <b>${recentCompleted(items).length}</b> 近 30 天完成</div></div><div class="project-center-meta"><span>独立任务可整理，并逐步形成项目。</span></div></div><div class="card-actions"><a class="button primary" href="#review" data-action="review-project" data-id="independent">查看独立任务</a>${review}</div></div>${board}</article>`;
    return `<article class="project-view-card" data-project-card="${esc(id)}"><div class="project-info"><div class="card-head"><h2><a href="#project/${encodeURIComponent(id)}">${esc(p.name)}</a></h2><span class="project-status ${cls}">${label}</span></div><div class="project-focus"><div class="focus-label">当前主线</div><div class="focus-text">${esc(p.focus || "暂无明确推进主线")}</div></div><div class="project-metrics"><div class="project-recent-stats"><div><b>${items.filter(t => t.status === "active").length}</b> 进行中 · <b>${recentCompleted(items, 7).length}</b> 近 7 天完成</div><div>最近更新 ${esc(latest)}</div></div><div class="project-center-meta"><span>状态说明：${esc(reason)}</span></div></div><div class="card-actions"><a class="button primary" href="#project/${encodeURIComponent(id)}">进入项目</a>${review}</div></div>${board}</article>`;
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

  /* ---------- 项目页 ---------- */
  /* Rendered on the server with the full workbench's template (ember_ui/pages/project.py); the tabs and
     task filters are ember_ui/project.js. The 交付文件 / 输入资料 tabs hand over to this page's own file
     browser through the same hook the full workbench uses. */
  async function renderProject() {
    const p = project(state.id), id = state.id;
    main.className = `shell app-main project-workspace-page paper-management-page`;
    if (!p) { main.innerHTML = `<section class="panel project-intro-card"><h1>找不到项目</h1><p>该项目不在当前工作区。</p><a href="#projects">返回项目视图</a></section>`; return; }
    let page;
    try { page = await api(`api/pages/project?id=${encodeURIComponent(id)}`); }
    catch (error) { if (state.route === "project" && state.id === id) main.innerHTML = `<section class="panel load-error"><h1>项目页读取失败</h1><p class="form-error">${esc(error.message)}</p></section>`; return; }
    if (state.route !== "project" || state.id !== id) return;
    pageStyle(page.kind);
    main.className = `shell app-main ${page.kind === "system" ? "system-workspace-page" : "project-workspace-page"} paper-management-page`;
    main.innerHTML = page.html;
    document.title = `${p.name} · 余烬`;
    const files = main.querySelector("[data-library-browser]");
    if (files) state.library = window.EmberLibrary.mount(files, libraryHooks);
    (page.kind === "system" ? window.EmberSystem : window.EmberProject).mount(main);
  }

  /* ---------- 文件预览 ---------- */
  /* Files in the shape the shared preview renderer (ember_ui/ember-ui.js) takes, so the task page and
     资料浏览 show previews exactly as the full workbench does. */
  function previewData(item) {
    const base = { name: item.name, mime: item.media_type || kindName(item.kind), size: item.bytes, updated_at: item.updated_at || "",
                   relative_path: item.relative_path, raw_url: `api/preview?id=${encodeURIComponent(item.id)}` };
    if (typeof item.text === "string") return { ...base, kind: "markdown", body_html: /\.(md|markdown)$/i.test(item.name) ? markdown(item.text) : `<pre class="library-text-preview">${esc(item.text)}</pre>` };
    return { ...base, kind: item.preview || "file" };
  }

  /* ---------- 任务详情 ---------- */
  /* The server renders this page with the full workbench's template; ember_ui/task-detail.js runs the
     materials (file list, divider, preview, drawer) and this page supplies files, previews and file
     actions from the local workspace. */
  const folderOf = f => f.id.slice(f.id.indexOf(`/${f.taskId}/`) + f.taskId.length + 2);
  const outputsOf = t => t ? data().files.filter(f => (t.outputs || []).includes(f.id)) : [];
  const deliveryOf = t => outputsOf(t)[0]?.kind || (t?.artifact_mode === "delivery" ? "draft" : "");
  const outputAt = (taskId, path) => outputsOf(task(taskId)).find(f => folderOf(f) === path);
  const fileActions = (item, input) => `<button class="button" type="button" data-action="reveal" data-id="${esc(item.id)}" data-mode="reveal">Finder 中显示</button><button class="button" type="button" data-action="reveal" data-id="${esc(item.id)}" data-mode="open">系统应用打开</button>${input ? "" : `<button class="button" type="button" data-action="download" data-id="${esc(item.id)}">下载到本机</button>`}`;
  const taskMaterials = {
    // One directory level of a task's delivery files, or all of them when flat.
    async directory({ task: taskId, path = "", flat }) {
      const own = outputsOf(task(taskId)), prefix = path ? `${path}/` : "";
      const entry = f => ({ name: f.name, relative_path: folderOf(f), is_dir: false, suffix: (f.name.match(/\.[^./]+$/) || [""])[0], updated_at: f.updated_at });
      if (flat) return { entries: own.map(entry) };
      const folders = new Set(), files = [];
      for (const f of own) {
        const rest = folderOf(f).startsWith(prefix) ? folderOf(f).slice(prefix.length) : null;
        if (rest === null) continue;
        if (rest.includes("/")) folders.add(rest.slice(0, rest.indexOf("/"))); else files.push(entry(f));
      }
      return { entries: [...[...folders].sort().map(name => ({ name, relative_path: prefix + name, is_dir: true })), ...files.sort((a, b) => a.name.localeCompare(b.name))] };
    },
    // Input rows carry the file ID as their path.
    async preview({ task: taskId, path, input }) {
      const item = input ? file(path) : outputAt(taskId, path);
      if (!item) throw new Error("该文件已不在当前工作区，请刷新页面。");
      return { ...previewData({ ...item, ...(await api(`api/file?id=${encodeURIComponent(item.id)}`)) }), id: item.id };
    },
    actions: (data, input) => fileActions(data, input),
    taskHref: id => `#task/${encodeURIComponent(id)}`,
  };

  async function renderTask() {
    const item = task(state.id), id = state.id;
    main.className = "shell app-main task-detail-page paper-management-page";
    if (!item) { main.innerHTML = `<section class="panel task-current-pane"><h1>找不到任务</h1><p>该任务不在当前工作区。</p><a href="#home">返回任务台</a></section>`; return; }
    // The page itself is rendered on the server with the shared template (ember_ui/pages/task_detail.py).
    let page;
    try { page = await api(`api/pages/task?id=${encodeURIComponent(id)}`); }
    catch (error) { if (state.route === "task" && state.id === id) main.innerHTML = `<section class="panel load-error"><h1>任务页读取失败</h1><p class="form-error">${esc(error.message)}</p></section>`; return; }
    if (state.route !== "task" || state.id !== id) return;
    state.taskMaterials?.destroy();
    main.innerHTML = page.html;
    document.title = `${item.title} · 余烬`;
    const related = item.kind === "task_line" ? (item.related || []).map(task).filter(Boolean) : [];
    const workspace = document.getElementById("taskDeliveryWorkspace");
    state.taskMaterials = workspace ? window.EmberTaskDetail.mount(workspace, {
      ...taskMaterials,
      relatedDeliveries: related.map(t => ({ task_id: t.id, title: t.title, delivery: outputsOf(t).length ? deliveryOf(t) : "", delivery_label: kindName(deliveryOf(t)), status: statusNames[t.status] || t.status })),
    }) : null;
  }

  /* ---------- 确认执行 ---------- */
  /* The full workbench's confirmation dialogs (ember_ui/execution-confirm.js on the task, project and
     library pages; ember_ui/home.js on the home page) ask this page for the prompt. After the user
     confirms, the prompt is copied and then the saved software is opened; nothing calls a model. */
  const executionPrompts = new WeakMap();
  async function executionPreview(form, payload, title = "", scope = "") {
    const [prompt, settings] = await Promise.all([payload.review ? api("api/review/context", { task_ids: payload.task_ids }) : api("api/context", payload), api("api/settings")]);
    const environment = settings.execution_environment, software = environment.executors.find(entry => entry.id === environment.default_executor);
    executionPrompts.set(form, { prompt, environment });
    return { fixed_prompt_html: markdown(prompt.fixed), fixed_prompt: prompt.fixed, task: prompt.task, prompt_prefix: prompt.prefix, prompt_suffix: prompt.suffix,
             title, scope, executor_ready: Boolean(environment.ready && software), executor: environment.default_executor || "",
             executor_label: software?.label || "", executor_path: software?.path || "", executor_error: environment.error || "" };
  }
  // Two separate results, reported in turn: copying, then opening.
  async function openWithPrompt(text, environment) {
    if (!environment?.ready || !text.trim()) { notice("提示词还没有生成，或还没有可用的执行软件。", true); return; }
    if (!(await window.GStudioUI.copyPrompt(text))) { notice("复制失败：浏览器没能写入剪贴板，因此没有打开软件。请重新打开确认弹窗，用“复制提示词”手动复制。", true); return; }
    try {
      const opened = await api("api/executors/open", { executor_id: environment.default_executor, expected_revision: environment.revision, confirmation: true });
      notice(`已复制并打开 ${opened.label}。请手工粘贴、发送；没有调用模型。`);
    } catch (error) { notice(`已复制提示词；打开失败：${error.message}`, true); }
  }
  // What a confirmation form asks for: continue a task, start in a project, or work on selected files.
  function executionRequest(form) {
    const fields = new FormData(form);
    const taskId = String(fields.get("task_id") || ""), projectId = String(fields.get("project_id") || "");
    if (taskId) {
      const t = task(taskId);
      if (!t) throw new Error("该任务已不在当前工作区，请刷新页面。");
      const fileIds = fields.getAll("selection").map(value => { try { const item = JSON.parse(value); return outputAt(item.task_id, item.path)?.id; } catch { return undefined; } }).filter(Boolean);
      const based = t.status === "completed" || fields.has("create_new_task");
      return { payload: { request: based ? `基于${t.status === "completed" ? "已完成任务" : "所选文件"}准备新工作：${t.title}` : t.next || `继续推进：${t.title}`,
                          relation: based ? "based" : "continue", task_id: t.id, file_ids: fileIds, page: "task" },
               title: `${based ? "基于" : "继续"} · ${t.title}`, scope: `任务 ${t.id} · 所选文件 ${fileIds.length} 个` };
    }
    if (projectId) {
      const p = project(projectId);
      return { payload: { request: `在「${projectName(projectId)}」中开始一项新工作：先读取${p?.kind === "system" ? "系统" : "项目"}说明，等待我补充具体要求。`, relation: "new", project_id: projectId, file_ids: [], page: "project" },
               title: `新任务 · ${projectName(projectId)}`, scope: `${p?.kind === "system" ? "系统" : "项目"} ${projectId}` };
    }
    const reviewIds = fields.getAll("selected_task_id").map(String);
    if (reviewIds.length) return { payload: { task_ids: reviewIds, review: true }, title: "整理所选任务", scope: `所选任务 ${reviewIds.length} 项` };
    const fileIds = fields.getAll("selection").map(value => { try { return JSON.parse(value).file_id; } catch { return undefined; } }).filter(Boolean);
    return { payload: { request: "请先核对所选资料，再按我的要求处理：", relation: "new", file_ids: fileIds, page: "library" },
             title: "基于所选资料新建", scope: `所选资料 ${fileIds.length} 项` };
  }
  window.GStudioRunner.preview = async form => { const request = executionRequest(form); return executionPreview(form, request.payload, request.title, request.scope); };
  function dispatchExecution(form) {
    const saved = executionPrompts.get(form), edited = form.elements.task_override?.value.trim() || "";
    openWithPrompt(saved && edited ? saved.prompt.prefix + edited + saved.prompt.suffix : "", saved?.environment);
  }

  /* ---------- 资料浏览 ---------- */
  /* Rendered on the server with the full workbench's template (ember_ui/pages/library.py) and driven by
     ember_ui/library.js, here and in the project page's file tabs. Files open and preview from this workspace. */
  const libraryHooks = {
    taskHref: id => `#task/${encodeURIComponent(id)}`,
    preview: item => api(`api/home/file-preview?id=${encodeURIComponent(item.selection.file_id)}`),
    action: (item, mode, label) => `<button class="button ghost" type="button" data-action="reveal" data-id="${esc(item.selection.file_id)}" data-mode="${mode === "open" ? "open" : "reveal"}">${esc(label)}</button>`,
  };
  async function renderLibrary() {
    main.className = "shell app-main library-page paper-management-page";
    let page;
    try { page = await api("api/pages/library"); }
    catch (error) { if (state.route === "library") main.innerHTML = `<section class="panel load-error"><h1>资料浏览读取失败</h1><p class="form-error">${esc(error.message)}</p></section>`; return; }
    if (state.route !== "library") return;
    state.library?.destroy();
    main.innerHTML = page.html;
    state.library = window.EmberLibrary.mount(main.querySelector("[data-library-browser]"), libraryHooks);
  }

  /* ---------- 任务检视 ---------- */
  /* Rendered on the server with the full workbench's template (ember_ui/pages/review.py) and driven by
     ember_ui/review.js; this page supplies search and the two previews from the local workspace. */
  const reviewHooks = {
    search: ({ query, project, type, status }) => api(`api/review/search?${new URLSearchParams({ q: query, project, type, status })}`),
    taskPreview: id => api(`api/home/task-preview?id=${encodeURIComponent(id)}`),
    reportPreview: id => api(`api/review/report-preview?id=${encodeURIComponent(id)}`),
  };
  async function renderReview() {
    main.className = "shell app-main organization-page paper-management-page";
    let page;
    try { page = await api("api/pages/review"); }
    catch (error) { if (state.route === "review") main.innerHTML = `<section class="panel load-error"><h1>任务检视读取失败</h1><p class="form-error">${esc(error.message)}</p></section>`; return; }
    if (state.route !== "review") return;
    state.review?.destroy();
    main.innerHTML = page.html;
    state.review = window.EmberReview.mount(main, reviewHooks);
  }
  const reviewSelection = () => [...main.querySelectorAll('[name="selected_task_id"]:checked')].map(input => input.value);


  /* ---------- 设置 ---------- */
  function renderSettings() {
    main.className = "shell app-main settings-page paper-management-page";
    main.innerHTML = `<section class="settings-hub paper-management-page"><header class="settings-hub-head"><div><h1>设置</h1><p>本机执行环境与当前文档库的基础 Skill，在这里查看和管理。</p></div><div class="settings-hub-actions"><button class="button" type="button" data-action="check-update">检查更新</button><button id="health-check-button" class="button" type="button" data-action="health-check">检查服务状态</button></div></header><nav class="settings-section-nav" aria-label="设置分区"><a href="#settings" data-action="scroll-to" data-id="execution-environment">执行环境</a><a href="#settings" data-action="scroll-to" data-id="settings-skills-section">Skills</a></nav><section id="execution-environment" class="settings-execution-strip"><div class="settings-section-head"><div><h2>执行环境</h2><p>先看当前生效的环境，需要时再修改配置。</p></div><span>仅对这台电脑生效</span></div><div id="software-content" aria-live="polite">正在读取本机已保存的软件清单…</div></section><section id="health-result" class="settings-health-summary"><div class="settings-health-main"><span class="settings-health-state">服务状态</span><small>只在点击“检查服务状态”后检查；不会验证软件登录或调用模型。</small></div></section><section id="settings-skills-section" class="settings-skills-module"><div class="settings-skills-head"><div><h2>Skills</h2><p>这里显示当前文档库保留的基础 Skill。首次引导完成并确认移除后，日常任务入口和项目建立继续保留。登记不代表模型已登录或能够执行；专业业务 Skill 由你另行准备。</p></div></div><div id="settings-skills" class="compact-skill-list">正在读取当前工作区的登记…</div></section></section>`;
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
      document.getElementById("settings-skills").innerHTML = result.skills.map(item => `<details class="compact-skill-row"><summary><span class="setting-identity"><strong>${esc(item.name)}</strong><small>${esc(item.purpose || "已登记基础 Skill")}</small></span><span class="setting-category">基础</span><span class="skill-status available">${esc(item.version)}</span><span class="skill-detail-toggle" aria-hidden="true"></span></summary><div class="compact-skill-detail"><code>${esc(item.path || item.name)}</code></div></details>`).join("") || `<p class="form-error">登记结果为空；请检查工作区契约，不要把它当作能力已验证。</p>`;
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

  // As in the full workbench, a page's own stylesheet applies only on that page.
  function pageStyle(name = "") {
    document.querySelectorAll("link[data-page-style]").forEach(link => { link.disabled = link.dataset.pageStyle !== name; });
  }

  function renderRoute() {
    pageStyle(state.route === "task" ? "task" : "");
    for (const key of ["taskMaterials", "home", "overview", "review", "library"]) { state[key]?.destroy(); state[key] = null; }
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
    openDialog("保存整理报告", `<form id="report-form" class="stack dialog-form" data-form="report"><label>报告名称<input id="report-title" name="title" required></label><label>报告范围<select name="mode"><option value="selected">所选任务</option><option value="weekly">按周整理</option></select></label><p class="muted">当前选择 ${reviewSelection().length} 项任务。保存的是你填写的报告，不会调整任务结构或生命周期。</p><label>报告内容<textarea id="report-content" name="content" required rows="14"></textarea></label><p class="form-error" role="alert"></p><div class="form-actions"><button id="report-submit" class="button primary" type="submit">保存报告</button><button class="button ghost" type="button" data-action="close-dialog">取消</button></div></form>`);
  }

  async function mutate(path, payload) {
    const result = await api(path, payload);
    try { await loadState(); }
    catch (error) { const failure = new Error(`操作已保存，但刷新失败：${error.message}。请重新加载页面核对，避免重复提交。`); failure.saved = true; throw failure; }
    return result;
  }

  async function submit(form) {
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
        case "report": await mutate("api/reports", { ...payload, task_ids: reviewSelection() }); closeDialog(); notice("整理报告已保存。"); break;
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
      case "project-category": ui.projectCategory = id; renderProjects(); return;
      // The full workbench opens 任务检视 filtered by ?project=; review.js reads it from the address.
      case "review-project": history.pushState(null, "", `${location.pathname}?project=${encodeURIComponent(id)}#review`); route(); return;
      case "new-report": newReport(); return;
      case "download": { const link = Object.assign(document.createElement("a"), { href: `api/raw?id=${encodeURIComponent(id)}`, download: "" }); link.click(); return; }
      case "check-update": setMenu(false); await checkUpdate(); return;
      case "copy-update": {
        const copied = await copyUpdatePrompt();
        updateFeedback(copied ? "更新提示词已复制。请在 AI 工具里粘贴并确认发送。" : "浏览器没能写入剪贴板，已选中完整提示词，请按 ⌘C 手动复制。", !copied);
        return;
      }
    }
    button.dataset.busy = "true"; button.disabled = true; button.setAttribute("aria-busy", "true");
    try {
      switch (button.dataset.action) {
        case "reveal": { const opened = await api("api/reveal", { id, mode: button.dataset.mode }); notice(button.dataset.mode === "open" ? `已用系统应用打开 ${opened.opened}。` : `已在 Finder 中显示 ${opened.opened}。`); break; }
        case "reveal-folder": await api("api/reveal", { task_id: id, folder: button.dataset.folder }); notice("已打开文件夹。"); break;
        case "reveal-location": await api("api/reveal", { project: id, location: button.dataset.location }); notice("已打开目录。"); break;
        case "important": await mutate(`api/tasks/${encodeURIComponent(id)}/important`, { important: !task(id).important, revision: data().revision }); notice("重点状态已保存。任务内容与生命周期未改变。"); break;
        case "health-check": {
          const health = await api("api/health");
          document.getElementById("health-result").innerHTML = `<div class="settings-health-main"><span class="settings-health-state">${health.status === "ready" ? "服务正常" : esc(health.status)}</span><small>检查时间 ${esc(new Date().toLocaleString())}</small></div><div class="settings-health-metrics"><span><b>${esc(health.tasks ?? "—")}</b> 项任务</span><span><b>${esc(health.contract?.skills?.length ?? "—")}</b> 项基础 Skill</span><span>版本 <b>${esc(health.version || "—")}</b></span></div>`;
          break;
        }
        case "discover-software": await softwareRequest("discover"); break;
        case "check-software": await softwareRequest("check"); break;
        case "save-software": await softwareRequest("save"); break;
        case "copy-open-update": {
          const environment = updateState.environment;
          if (!(await copyUpdatePrompt())) { updateFeedback("① 复制失败：浏览器没能写入剪贴板，因此没有打开软件。已选中完整提示词，请手动复制。", true); break; }
          updateFeedback("① 已复制更新提示词；② 正在打开软件…");
          try {
            const opened = await api("api/executors/open", { executor_id: environment.default_executor, expected_revision: environment.revision, confirmation: true });
            updateFeedback(`① 已复制更新提示词；② 已打开 ${opened.label}。请在软件里粘贴并确认发送。`);
          } catch (error) { updateFeedback(`① 已复制更新提示词；② 打开失败：${error.message}`, true); }
          break;
        }
      }
    } finally {
      delete button.dataset.busy; button.removeAttribute("aria-busy");
      if (button.isConnected) button.disabled = false;
    }
  }

  document.addEventListener("submit", event => {
    const form = event.target.closest("[data-form]");
    if (form) { event.preventDefault(); submit(form); return; }
    // Reached only after the shared confirmation dialog: it intercepts the first submit.
    const folder = event.target.closest("[data-task-folder-reveal]");
    if (folder) { event.preventDefault(); api("api/reveal", { task_id: folder.elements.task_id.value, folder: "delivery" }).then(() => notice("已打开文件夹。"), error => notice(error.message, true)); return; }
    const confirmed = event.target.closest("[data-execution-confirm]");
    if (confirmed) { event.preventDefault(); dispatchExecution(confirmed); }
  });
  document.addEventListener("click", event => {
    const navigation = event.target.closest('.app-sidebar a[href^="#"]');
    if (navigation) { setMenu(false); if (navigation.hash === location.hash) { main.focus({ preventScroll: true }); window.scrollTo(0, 0); } }
    const control = event.target.closest("[data-action]");
    main.querySelectorAll("details.task-manage-menu[open]").forEach(menu => { if (!menu.contains(event.target) || control) menu.open = false; });
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
  });
  document.addEventListener("change", event => {
    const control = event.target;
    if (control.id === "default-software") { document.getElementById("software-default-field")?.classList.remove("needs-choice"); software.default = control.value; softwareChanged(); return; }
    if (control.id === "software-kind") { software.manual.kind = control.value; softwareChanged(); return; }
    if (control.dataset.softwareField === "kind") {
      software.entries.find(entry => entry.id === control.closest("[data-software-id]").dataset.softwareId).kind = control.value;
      softwareChanged(); return;
    }
    if (control.id === "material-kind") {
      const reference = control.value === "reference";
      document.getElementById("material-text-fields").disabled = reference;
      document.getElementById("material-text-fields").hidden = reference;
      document.getElementById("material-reference-fields").disabled = !reference;
      document.getElementById("material-reference-fields").hidden = !reference;
      document.getElementById("material-reference-path").required = reference;
      document.getElementById("material-purpose").required = reference;
    }
  });
  document.addEventListener("keydown", event => {
  });
  document.querySelector(".skip-link").addEventListener("click", event => { event.preventDefault(); main.focus(); });
  document.getElementById("dialog-close").addEventListener("click", closeDialog);
  // A project or home page keeps its filters in the address bar; another page starts without them.
  window.addEventListener("hashchange", () => { if (location.search) history.replaceState(null, "", location.pathname + location.hash); route(); });
  document.addEventListener("click", async event => {
    const button = event.target.closest("[data-project-entry-copy]");
    if (!button) return;
    const copied = await window.GStudioUI.copyPrompt(button.dataset.projectEntryCopy);
    notice(copied ? "入口已复制" : "复制失败，请选择路径或网址手动复制", !copied);
  });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && event.target.closest?.("#software-candidates")) { event.preventDefault(); closeFoundSoftware(); document.getElementById("find-software")?.focus(); } });
  // The task header clips overflow, so the actions menu is placed against the viewport.
  document.addEventListener("toggle", event => {
    const menu = event.target;
    if (!menu.classList?.contains("task-manage-menu") || !menu.open) return;
    const rect = menu.querySelector("summary").getBoundingClientRect(), list = menu.querySelector(".task-manage-list");
    Object.assign(list.style, { position: "fixed", top: `${rect.bottom + 6}px`, right: `${Math.max(8, innerWidth - rect.right)}px` });
    list.querySelector("button")?.focus();
  }, true);
  window.addEventListener("keydown", event => { if (event.key === "Escape") main.querySelectorAll("details.task-manage-menu[open]").forEach(menu => { menu.open = false; menu.querySelector("summary").focus(); }); });
  window.addEventListener("scroll", () => main.querySelectorAll("details.task-manage-menu[open]").forEach(menu => { menu.open = false; }), true);

  route();
  loadState().catch(error => {
    main.className = "shell app-main";
    main.innerHTML = `<section class="panel load-error"><h1>工作区读取失败</h1><p class="form-error">${esc(error.message)}</p><p class="muted">确认本地服务已启动后，重新加载此页面。之前保存的数据不会被覆盖。</p></section>`;
    document.getElementById("workspace-state").textContent = "工作区不可用";
  });
  return { refresh: loadState };
})();
