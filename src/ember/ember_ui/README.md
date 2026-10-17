# ember_ui — shared interface layer

The interface code both editions of 余烬 · Ember use. This repository holds the
canonical copy; the open-source edition copies this folder verbatim with its
own export tool and never edits it there.

- `static/workbench.css`, `static/task-detail.css`: the workbench stylesheet and
  the task detail layout.
- `static/ember-ui.js`: toast, clipboard copy and file preview rendering
  (`window.GStudioUI`, `window.GStudioPreview`).
- `static/sidebar-state.js`, `static/sidebar.js`: sidebar section/scroll state
  and the small-screen toggle.
- `static/execution-confirm.js`: the execution confirmation dialog.
- `static/task-detail.js`: task materials list, divider and drawer
  (`window.EmberTaskDetail.mount`).
- `static/home.js`, `static/task-overview.js`: the home request input, search,
  preview and home execution confirmation (`window.EmberHome.mount`), and the
  全部任务 browser (`window.EmberTaskOverview.mount`).
- `static/project.css`, `static/project.js`: the project workspace layout, its
  tabs and task filters (`window.EmberProject.mount`).
- `static/projects.css`, `static/projects.js`: the 项目视图 category filter, task
  drag into and out of 当前重要事项, and card reordering (`window.EmberProjects.mount`).
- `static/system.css`, `static/system.js`: the system workspace layout and its
  task search (`window.EmberSystem.mount`).
- `static/review.js`: 任务检视 search, filters, selection and previews
  (`window.EmberReview.mount`).
- `static/library.js`: the file-first material browser of 资料浏览 and the
  project file tabs (`window.EmberLibrary.mount`).
- `static/settings.css`, `static/settings.js`: the settings page layout and its
  Skills filters (`window.EmberSettings.mount`).
- `static/executor-settings.css`, `static/executor-settings.js`: the 执行环境 editor
  (local programs, default, path check and save; `window.EmberExecutorSettings.mount`).
- `pages/shell.py`: the document around every page, the sidebar (page links,
  workspace projects by category with favorites, bottom status) and the execution
  confirmation dialog; edition modules go in its `*_html` slots.
- `markdown.py`, `marks.py`: the Markdown subset and the flame mark both
  editions render.
- `pages/task_detail.py`, `pages/home.py`, `pages/projects.py`, `pages/project.py`,
  `pages/system.py`, `pages/review.py`, `pages/library.py`, `pages/settings.py`: the
  task detail, home, 项目视图, project workspace, system workspace, 任务检视, 资料浏览
  and 设置 (shell, Skills and 执行环境) page templates. It takes one page
  dictionary (documented in the module) and returns markup only; each edition
  builds the dictionary from its own data and wraps the result.

Rules, enforced by the workbench test suite:

1. Python modules use only the standard library and relative imports, read
   no files and make no requests.
2. No machine paths, network addresses, storage or internal system names,
   registered project names, or references to the workbench's Python modules.
   Edition-specific data access and actions are passed in by the page (for
   example the `actions` option of `EmberTaskDetail.mount`).
3. Static files are served byte-for-byte at `/assets/<name>`; change a file here and
   the version query changes with it.
