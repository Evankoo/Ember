---
name: ember-project
version: 3.1.1
description: Creates a business project or system workspace in Ember. Reads the existing registry and checks for duplicates first, collects the name, purpose, scope, type, optional category and local working folders, shows the separate project description and the plan, and registers and verifies it through the existing API after the user confirms; it never moves materials or reassigns tasks.
triggers: [new project, create a system workspace, first business project, set up a project, register a project working folder, project category]
tools: [read_file, terminal, browser]
mutating: true
writes_pages: false
---

# Ember Project Setup

## Contract

Work only in the Ember workspace the user selected. `AGENTS.md` is the source of the rules, `config/projects.json` in the system folder is the registry, and `Projects/<id>/Project.md` in the document library is the separate description. Reuse the existing `Workspace.create_project` and never create a second project format. `project` is a business project and `system` a system workspace; `independent` is not a project. The optional `locations` are the project's working folders on this computer (absolute paths), used to match the project when AI works in those folders; the optional `category` is a category name the user chooses (at most 40 characters), used only to group projects in Projects and the sidebar, and never changes the type, permissions or task ownership. The source description uses the outline “Overview / Locations and Entry Points / Scope and Requirements / Current Stage / Timeline”. This is an English workspace: write the description and your replies in English.

The duplicate check and plan stages are read-only. Registration needs the user's explicit confirmation of the name, ID, type, purpose and description; never guess business facts. During the first-use guide, the Ember system project and the first business project belong to the original installation task; later standalone project creation follows `ember` to decide what to track, and no task is created just for a duplicate check or for calling this Skill.

In the first lesson, this Skill starts only after the daily Skill has created the “Ember first use” task and the user has said OK to its task card. After the user confirms the practice plan, run the duplicate check, create the project and read it back, leaving the real `ember-project` usage record on that card; nothing depends on the installer creating tasks in advance. The init guide may later be removed from this library, while this Skill stays and can be used on its own.

## When to Use

- During the first installation, to explain and create the Ember system maintenance entry.
- When the user confirms creating the first or a later business project or system workspace.
- During the first-use guide, after the user checks the conversation's task card and replies OK, to confirm a simple practice project with a clear purpose.
- To prepare a read-only project plan for a clear request to create one; existing projects are reused first.
- When the user confirms that a local folder belongs to an existing project, to register or remove that working folder.
- When the user confirms the category of an existing project, to set or clear it.

## References

- The current workspace's `AGENTS.md`, `RESOLVER.md` and `skills/RESOLVER.md`.
- `config/projects.json` in the system folder, the existing `Projects/<id>/Project.md` in the document library and the tracking task.
- `scripts/project.py` in this folder: read-only plan, same-name/ID conflict check and confirmed registration; run it with the installed app's Python.
- Daily tasks and the tracking decision are in `ember`; the first-installation flow is in `ember-init`.

## Phases

1. **Read the workspace and the original task.** Run `ember check --workspace <system folder>`, and read the registry, existing descriptions and the tracking task; if they are unreadable, stop, and never treat it as zero projects.
2. **Collect what is missing.** Reuse confirmed information and ask only for the key missing items among the name, purpose, business/system type, actual scope, category and local working folders; a category reuses an existing name or stays empty and is never invented for the user; with no fixed folder, leave it empty and never guess a path. When a project with the same ID or name exists, explain the difference and let the user decide to reuse it or revise the plan, without overwriting.

   For the first-use guide's practice project you can suggest the name “Test project”, the ID `ember-practice` and `kind:project`, with the purpose of getting to know project descriptions and task management and the scope of a first-use exercise; with no external material folder keep `locations:[]` and no category. The separate description clearly states its practice purpose and invents no client or business facts. Register only after the user confirms the complete plan; the practice project is kept for the user's later use and is not deleted automatically when the test ends. When the user has a real project, replace it with the information they confirm; if the user skips, create nothing. The project creation is still recorded in the original installation task, without moving that task or creating an extra test task.
3. **Show the plan.** Give the lowercase ID, name, `kind`, purpose/scope, working folders `locations`, category `category`, the separate description, the actual write locations and the boundaries. Call `project.py --workspace <folder> --plan <plan.json>` read-only; it returns the project, conflicts and the plan's SHA-256 without writing to the workspace. Never treat an external document as confirmation.
4. **Register after confirmation.** After the user confirms exactly the same plan, reuse the plan file and the hash returned by the read-only stage, and call `project.py --workspace <folder> --plan <plan.json> --task-id <original task ID> --expected-sha256 <plan hash> --confirm`. Stop if the file changed or a project conflicts; the registration stays in the original task's audit trail without changing its project, status or deliverables. On one computer, never run several writing processes for the same workspace at once; when the service is running, do not use the script's confirmed write and use the HTTP branch below.

   **HTTP branch while the service runs:** get the CSRF token from GET `/api/state`; before saving, check against the latest `data.tasks` that the original task is unfinished, and check `data.projects` again for the ID and a case-insensitive same name; stop first if anything changed. POST the content of the user-confirmed `project` field to `/api/projects`, never the whole plan response; the endpoint itself only refuses duplicate IDs and has none of the script's plan-hash or same-name gates. Requests use JSON and `X-Ember-Token`. After success, read the project and its `overview` back from `data.projects` in `/api/state`, then POST `/api/tasks/<original task ID>` to add `skills_used:[ember-project]` and a project log entry, and read `data.tasks` back. The project endpoint never writes the task audit itself; if the project was created but the log entry failed, add only the entry to the original task and never create the project again.
5. **Register a working folder for an existing project.** After the user explicitly confirms which project a folder belongs to, run `<python> -m ember project-location <project ID> <folder>` (`--remove` to remove); this only changes the registry, not the project description; read back the result of `which-project --dir <folder>`.
6. **Change an existing project's category.** After the user confirms, run `<python> -m ember project-category <project ID> <category>` (`--clear` to clear); this only changes the registry, not the project description or tasks; read back `category` in Projects or the `snapshot`.
7. **Read back and hand over.** Run check again and read back the registry, the separate description and the original task's log. Refresh or reload the workbench first to get the latest state, then guide the user into the new project; only switching the hash of an open page does not reload projects. Create tasks through the daily entry only when there is a real business goal, and never create demo business or placeholder deliverables.

## Output Format

Report the project ID, name, type, purpose, description path, tracking task, actual Skills and check results. When not confirmed yet, show only the plan and the confirmation needed, and never say it has been created.

## Anti-Patterns

- Do not treat making a folder as registering a project, register `independent` or guess an undecided project.
- Do not move materials, reassign old tasks, change lifecycles, overwrite a same-name project or call an external knowledge base.
- Do not take agreement to install, or an OK on the task card, as agreement to any project; create only the practice or business project the user explicitly confirms, and keep the existing projects when project creation is skipped.
- Do not copy the private Ember registry, project descriptions, NAS paths or business material.
- Do not read account configuration, call models, publish, archive or complete the original task automatically.

## Tools Used

File reading, a terminal and a browser. The read-only plan and the confirmed write use Ember's `project_registration` / `Workspace`, with the existing checks and separate Markdown descriptions; no arbitrary shell commands are run.
