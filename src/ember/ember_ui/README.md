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
- `static/system.css`, `static/system.js`: the system workspace layout and its
  task search (`window.EmberSystem.mount`).
- `static/review.js`: 任务检视 search, filters, selection and previews
  (`window.EmberReview.mount`).
- `markdown.py`, `marks.py`: the Markdown subset and the flame mark both
  editions render.
- `pages/task_detail.py`, `pages/home.py`, `pages/project.py`, `pages/system.py`,
  `pages/review.py`: the task detail, home, project workspace, system workspace and
  任务检视 page templates. It takes one page
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
