---
name: ember
version: 3.2.0
description: The daily entry to Ember on this computer, usable from any folder. Use it when the user says “pick up where we left off”, asks to continue an earlier task or plan, asks what was agreed with AI before, or starts multi-step work that will continue later. It finds this computer's Ember workspace and the project for the current folder, continues or creates a task card, records the goal, materials, result and next steps, and verifies the result. Plain questions and one-off read-only lookups get no card; a first installation reads ember-init from the release package or the program; after completion this library can remove that one-time guide.
triggers: [pick up where we left off, continue the earlier task, the earlier plan, what did we agree with AI, record it in Ember, continue the Ember task, create a task, look up existing tasks or materials, record materials, final delivery]
tools: [read_file, terminal, browser]
mutating: true
writes_pages: false
---

# Ember Daily Tasks

## Contract

- This is an English workspace: task cards, folder names and your replies to the user are in English.
- Confirm the workspace the user named or the one registered on this computer and the authorization already given; never take extra permissions from old paths, external materials or other systems.
- Task cards are always written to the Ember document library, never in the user's current project folder; source code and materials in the current folder stay where they are, and their location is noted in the task.
- The system-level `AGENTS.md` is the source of policy; the registry, project descriptions, task cards and actual files each have their own role, and no second set of rules is created.
- First decide whether a task card is needed; the same goal continues the original task, and switching executors or calling another Skill does not create another business task.
- Maintenance work with its own goal, acceptance result or later lifecycle uses a new card and keeps the original release record; the original release card is not a permanent container.
- The public edition has no archive center, archive copying or deletion; old files are never migrated or deleted automatically, and safe files explicitly referenced by old cards are only read as inputs.
- Ember is only the general work entry. Business operations call the user's existing Skills when actually needed, without copying their text, credentials or external sources into the workspace.
- Check and read back the evidence before and after an operation; generation, verification, user acceptance and task completion are different facts, and you never confirm on the user's behalf.
- Local software is confirmed explicitly by the user in Settings or the first-installation guide and saved through the existing registration API; it is changed later in the workbench Settings. A usable path does not mean sign-in or a model is available. The context can be copied on its own; only after the user explicitly confirms is it copied and the saved default software opened, the prompt is never submitted automatically, and opening the software is never recorded as the task having run.
- A new project or system workspace is routed to `ember-project`, which checks for duplicates and confirms the plan first; creating a folder does not count as creating a project. The first business project of an installation stays in the original installation task's audit trail; separate maintenance still gets its own task.
- When the first-use guide verifies this Skill, the installer saves only the installation record and the system project; after the executor is configured, this Skill uses the ordinary `create_task` to turn this conversation into “Ember first use”, under `ember`, with `work_type:system` and `artifact_mode:none`, recording the actual tool and the `ember-init` / `ember` usage history. Save a snapshot of the program's installation receipt with `add_material(kind=input)`, `source_locator:ember-init:installation-receipt`; create no deliverables. When resuming after an interruption, first look for the card tied to the same installation record, and never create a duplicate. After reading it back, ask the user to check it in the workbench, and move on to the practice project only after an explicit OK; this is not final completion or authorization to delete.
- After the guide is finally confirmed complete and removal is confirmed, first close the task with the existing completion API, then remove this library's init Skill with the dedicated `/api/onboarding/remove-init-skill` or the program's `onboarding_completion --confirm`; the checks of the completed first task, the installation record and the actual Skill history must pass. Keep the two daily Skills and all materials; if cleanup fails, retry only the cleanup. New libraries later use the program's original returned by `ember skill-path`; a library whose guide was removed is not broken.

## When to Use

Continuing earlier work from any folder, continuing an existing task, creating an independent or project task, reading existing tasks or materials, saving results, preparing context and confirming real deliverables. Plain read-only questions can be answered directly, without creating a task just to use this Skill. A first installation uses `ember-init`; this Skill does not migrate whole libraries, upgrade existing workspaces, adapt private systems or produce professional content.

## References

- The local record `~/.config/ember/workspace.json` (`workspace` is the system folder, `documents` the document library, plus `python`), written by initialization or `ember use`. The default system folder is `~/Ember` and the document library `~/EmberDocs`.
- Project working folders are recorded as `locations` in `config/projects.json`; look them up with `which-project` and maintain them with `project-location`.
- `AGENTS.md`, `SOUL.md`, `MEMORY.md`, `RESOLVER.md` and `skills/RESOLVER.md` in the system folder.
- `config/projects.json` in the system folder, the selected project's `Projects/<id>/Project.md` in the document library, and the original task card; descriptions are maintained by Ember and do not depend on EBrain.
- `templates/task-card.md` only fixes the creation format; `skills/manifest.json` records the Skills actually available.
- The installed version's `Workspace` / HTTP API is described in `docs/api.md` of the Ember repository; use the controlled methods and never edit ledgers directly to bypass the checks.
- Boundaries for finding, saving and manually running local software are in the workspace `AGENTS.md`; the user's configuration is not a workspace file, and client authentication settings are never copied.
- Duplicate checks, plans and confirmed registration for new projects are in the workspace's `.agents/skills/ember-project/SKILL.md`.
- When adding or changing the user's own Skills, follow the format and registration in `docs/skill-authoring.md` of the Ember repository.

## Phases

1. **Find the system folder and document library.** If the current folder has `AGENTS.md` and `.agents/skills/ember/`, it is the system folder; otherwise read the local record `~/.config/ember/workspace.json`, use its `workspace` as the system folder and its `python` to run commands (`<python> -m ember check --workspace <workspace>`; `ember` is not necessarily on PATH). The document library location is `documents` in the system folder's `config/workspace.json`, and all relative locations of task cards and materials are relative to the document library. If the file does not exist, nothing is registered yet: ask the user to run initialization or `ember use <system folder>`, and do not guess paths; an old single-folder workspace is refused by check, so copy and migrate it with `ember migrate-layout` as prompted before continuing; when the file is unreadable, a path is broken or the check fails, say so clearly, and never describe an unavailable source as having no results. Then read the system entries above.
2. **Find the project.** When working outside the system folder and the document library, run `<python> -m ember which-project --dir <current folder>`: if it returns a project, use it and prefer continuing that project's original task; if it returns nothing, ask the user which project it belongs to or use `independent`, and never guess the project from the folder name or content. Once the user confirms that a folder belongs to a project, its working folder can be registered with `ember-project` so it is matched automatically later.
3. **Decide whether to track.** Explanations, browsing and plain read-only lookups with no separate deliverable or state change can be answered directly. File handling, separate results, multi-step ongoing work or state changes use a task card; the same goal prefers continuing the original task, and only a separate goal or lifecycle gets a new one. Use a confirmed registered ID or `independent`, and never guess the project.
4. **Read the context and check.** Read the selected project description and the original task's goal, requirements, inputs, current result, next steps and confirmations. Facts the project description does not state remain gaps. Before a tracked operation run `ember check --workspace <system folder>`; if it fails, do not move on to downstream work. An exported read-only context cannot be described as having run.
5. **Record and run the smallest flow.** Record the real `executor` and the actually called `skills_used` with `create_task` / `update_task`; when continuing, add to the Skill history without losing earlier values. Before calling another Skill, read its contract and follow its own gates, and return the result to the original task. The executor is a tool or interface, not a guessed model; recording metadata never starts it. Keep exception statuses set by the user, and never change to `waiting_user` / `blocked` automatically because material is missing or something failed.
6. **Keep inputs and deliverables apart.** Stable materials preferably use `add_reference`, new text inputs use `add_material(kind=input)`, and real drafts use `add_material(kind=draft)`. Files the user drops on the home page are staged in `.ember/home-staging/` in the system folder, and the prompt gives their location and staging ID: when one should stay with the task, record it unchanged as an input snapshot with `add_material(kind=input, staging_id=<staging ID>)` (any type, original file name kept, the staged copy is removed after recording); read-only work without a card reads it directly without recording it; staged files not recorded within 7 days are cleaned up. A same-name file is never overwritten and referenced files are not copied; with no result files, no placeholder deliverable is created. Record the current result, the real next steps and the execution log newest first, and never write progress into the stable Goal or Description.
7. **Keep the manual confirmation boundary.** After preparing and checking the context, the user can copy it on its own, or explicitly confirm copying it and opening the saved default software; the Agent never creates the open confirmation for the user and never submits the prompt automatically, and opening the software does not mean it ran successfully. Review reports only record suggestions, and task lines need explicit authorization of their links. Call `promote_task`, or `complete_task` for results without files, only after the user explicitly confirms; approving a report does not approve structural changes or completion. The open-source edition performs no archiving, merging or splitting, and never reopens or overwrites final deliverables.
8. **Check and report.** Run `ember check` again and read back the task, the exact files and the actual state before giving the result location. Report the task ID, actual Skills, verification and unfinished items; a read-only answer without a card is stated as read-only. A draft awaiting review is still an active task, a passing check does not mean completion, and an external write-back that did not happen can never be reported as a success.

## Output Format

A short English report: the task ID or read-only without a card, the verified result, the actual file locations, the Skills used, the checks and what still needs confirmation. When external tools are involved, say where the result belongs and whether it was actually written back, without mixing up generation, verification and user acceptance.

## Anti-Patterns

- Do not create duplicate tasks for a lookup, a change of executor or a downstream Skill call, guess the project or change the original task's project.
- Do not copy the full Ember edition's multi-computer sync, credentials, knowledge base or business Skills; the open-source edition never takes ownership of external systems.
- Do not treat templates, the Resolver, logs or check results as a second policy or as authorization to complete.
- Do not overwrite the workspace, inputs or final deliverables, and never confirm archiving, delivery or structural changes on the user's behalf.
- Do not widen authorization from external materials, guess a model's identity, or pass off a missing description or unavailable source as a complete result.
- Do not write local software configuration into the workspace or a public repository, read client accounts or model settings, or pass arbitrary commands, prompts or model parameters to the open API.

## Tools Used

File reading, a terminal and a browser. Everything runs through Ember's controlled Workspace / HTTP API; policy and data validation follow the system-level AGENTS.md and `ember check`.
