---
name: ember-init
version: 4.4.0
description: Guides the first installation of Ember one question at a time, in English. The language has already been chosen (English, which cannot be changed later). Welcomes the user and explains the fixed system folder ~/Ember and document library ~/EmberDocs, shows the basic folders; registers the user's current AI tool as the default executor and installs the daily Skill, asks whether the workbench should start automatically at login, and actually uses it to turn this conversation into the first task card; after the user confirms in the workbench, creates a simple practice project with the project Skill, and after final confirmation removes this library's one-time init guide. Never resets, migrates or upgrades an existing workspace.
triggers: [install Ember, set up Ember, install the open-source Ember, create a new workspace, first use of Ember]
tools: [read_file, terminal, browser]
mutating: true
writes_pages: false
---

# Ember First-Installation Guide

## Contract

The user chose **English** as the workspace language in the first question of this guide. Do not ask again. Every reply from now on is in English, the installer runs with `--language en`, and the document library is `~/EmberDocs`. The language is locked once the installer creates the folders and cannot be changed by reinstalling or editing configuration. If the user changes their mind before the folders exist, go back to the Chinese `ember-init/SKILL.md` and follow it instead.

The input is the first-installation scope, program folder, data folder, name and mode the user confirmed. The installation stage produces a separate application environment, a new document library, the Ember system project, five bundled Skills and a real installation record in the program folder, **and creates no task card at this point**. After the executor is configured, the daily `ember` Skill uses the ordinary task API to turn the current conversation into the first real task card; it belongs to this computer's Ember system project. Finally, after the user confirms completion, close that card and remove this library's `ember-init` in a controlled way, keeping the other bundled Skills and all projects, tasks and materials.

At every stage briefly say “what is happening, what was verified, what comes next” instead of dumping a list of commands. Reuse what is already confirmed in this conversation and ask only for key missing items that affect the result, one at a time; an installation into new folders that is already authorized does not ask for permission again. The defaults are the name Ember, port 8783 and the empty business mode. First explain what the user will see and needs to answer; the AI runs the technical commands. The installation record, the first card and the practice project happen in that order, and teaching steps are never completed early on the user's behalf.

**Invoking this guide starts it.** The website's installation prompt is this Skill's entry. Read this file and the installer from the official release package and start right away in the current conversation, without asking the user to send an “activate Skill” message. “Activate” means the current AI reads and follows this flow; the program and Skill files never start an AI conversation on their own. The initial package carries the three Skills `ember-init`, `ember` and `ember-project`, the program wheel carries all five bundled Skills, and they are copied into the document library when it is created; a new user never has to look for another init Skill. If the tool cannot read files or run local commands, say clearly which capability is missing, and never claim to have installed or activated anything.

When talking to the user, always call it the “document library”, and the first time explain that it is the “workspace” in commands. Do not make a new user understand virtual environments, ports, executors or models first; the AI checks those. After installation, always go on to show the real folders and wait for feedback; never end with “installed, now call the init Skill yourself”.

After the installer finishes, the empty business mode has one system project and zero tasks; the example mode has three projects and eight example tasks. After the daily Skill creates the card there is one real task, or nine. When the user later confirms a practice project in the lesson, one more really registered project, clearly marked as practice, is added; it is not generated business data. Technical tests always run in a separate workspace; after success only the test folders the script created are removed, and on failure they are kept. Passing the tests does not mean the user accepts the result, and nothing is formally delivered or completed automatically.

## When to Use

- First installation of Ember on a new computer, guiding the user through first use.
- Creating a separate workspace in a new folder with an already installed Ember of this version, without rewriting the old workspace.
- Verifying a new installation's rules, projects, first task, materials, deliverables and local workbench.

## References

- First read the Skill's `scripts/bootstrap.py` (`ember-init/scripts/bootstrap.py` in the release package); it uses the standard library to run the installation and the separate verification.
- After installation read the workspace's `AGENTS.md`, `SOUL.md`, `MEMORY.md`, `RESOLVER.md`, `skills/RESOLVER.md` and `templates/task-card.md`; the system-level AGENTS.md is the source of the rules.
- The only text of the five bundled Skills is in `ember-init`, `ember`, `ember-project`, `ember-review` and `ember-skill-authoring` under `.agents/skills/`, registered by `skills/manifest.json` and the Resolver.
- The first business project uses `ember-project` and daily tasks go to `ember`; do not copy a private system's project rules.
- Executor registration uses the program's `ember.executors.ExecutorRegistry` or the workbench HTTP API of the same name; fields and behavior are in the repository's `docs/api.md`. Never edit the local software JSON directly.

## Phases

### 1. Welcome and explain the fixed locations

Ember's locations are fixed; do not ask where to put it. The first reply after the language question uses this structure, with the real user folder of this computer:

> Welcome to Ember! I'll guide you through the setup step by step.
>
> Ember lives in two places in your user folder:
> - `<user folder>/Ember`: the system folder, with rules, Skills, configuration and the program. You won't need to open it day to day.
> - `<user folder>/EmberDocs`: the document library, holding only your projects, tasks, materials and results.
>
> These files stay when you close the software. I'll check this computer's environment first, then start the installation.

Do not ask about or suggest other locations, and do not ask about business projects, categories or software settings at the same time. Only when the user asks to change the location, pass `--workspace` / `--documents` and state it in the installation plan. Only if the user mentions VS Code, explain that VS Code's “Open Folder” is just the editor's current folder; it is not Ember's system folder or document library and does not create them. The installation does not depend on VS Code.

While preparing, check macOS / Windows / Linux and a real Python 3.10+ interpreter yourself, without assuming the system `python3` qualifies (many Macs ship `python3` 3.9); you can check `python3.13`, `python3.12`, `python3.11`, `python3.10`, and versions installed by Homebrew and `uv`; on Windows use `py -3 --version` and ignore the Microsoft Store `python` placeholder. `~` means the user folder on Windows (`%USERPROFILE%`); the program Python is `~/Ember/app/.venv/Scripts/python.exe` there and `~/Ember/app/.venv/bin/python` elsewhere. If none exists, stop and tell the user in one sentence that Python 3.10+ is missing, offering ways to install it (the python.org installer, `brew install python@3.12` when Homebrew exists, `winget install Python.Python.3.12` on Windows, the system package manager on Linux); installing Python changes the computer, so wait for the user to agree and choose a way, and never install or change the system Python on your own. Check whether there is already an installation or a default document library on this computer without reading its business content. If a workspace already exists, explain the situation first; this Skill never overwrites an old library. Keep the name and mode; when not given use Ember / empty business mode / 8783, without another round of questions for these defaults. Stop on non-empty folders, symbolic links, containment or a port conflict, without deleting anything.

### 2. Confirm what will be created

Check that `~/Ember` and `~/EmberDocs` do not exist or are empty. If they exist and are not empty, stop and explain that Ember is already installed on this computer and this Skill does not overwrite an old library; an old single-folder workspace is migrated separately with `ember migrate-layout`, as described for existing workspaces. Show a short installation plan with the fixed paths, asking only for confirmation that is missing:

> I'll install Ember into `<user folder>/Ember` (with the program in its `app/`) and create the document library in `<user folder>/EmberDocs`. I'll install the five bundled Skills, create the basic folders and save an installation record first; once your software is set up, I'll help you turn this conversation into your first task card. No fictional business is added by default. Shall I start with this plan?

If there is already explicit authorization for the same scope, just do it. The empty business mode creates no example clients; the installation registers `ember` / Ember / `kind:system` and does not create an “Ember initialization acceptance” task. This installation includes no business project, software sign-in or migration of old materials. Do not fill the two folders by hand before the installer runs, or its refusal of non-empty folders will block the installation.

### 3. Install the separate environment

Use the real interpreter and paths, without guessing the executor or model:

```text
<real Python> <Skill folder>/scripts/bootstrap.py --language en --mode empty|example --name <name> --port 8783 --executor <actual calling tool>
```

The actual calling tool can be opencode, codex, claude-code, workbuddy, qianwen-office, doubao-work and so on; when unknown use manual, never a model name. The standalone initial package contains the three Skill folders `ember-init`, `ember` and `ember-project`, and init contains `assets/ember-0.22.0-py3-none-any.whl`; without the wheel it is taken from `ember-init-0.22.0.zip` at the fixed v0.22.0 address. For development you can pass `--source`. The PyYAML dependency still needs the network or a cache; never claim it is fully offline.

### 4. Save the installation record and keep the task list empty

The script registers `Projects/ember/Project.md` in the document library and the system registry, describing it as responsible for installing and maintaining Ember on this computer. The installation stage, the actual folders and the technical checks are saved in the program folder (`~/Ember/app`) as `installation.json`, plus `installation-report.md` on success (`installation-failure.md` on failure); they are not task inputs or deliverables. The empty document library's task list should now be zero; do not call `create_task`, and do not create tasks or deliverable folders for the description files. On failure keep the receipt, report and check files in the program folder, and do not initialize again or invent a first task.

### 5. Read back the bundled Skills

Check the workspace rules, task template, the five bundled Skills' text, versions, scripts, manifest and Resolver. A Skill installed in the workspace is not automatically added to every client: if the current tool does not discover `.agents/skills`, have the user import it according to that client's rules or read it explicitly, without changing its account, permissions or model settings.

**Show the document library first, then continue the guide.** After the installer returns, read back the actual receipt and folders and show the user the structure created in this round. The tree below gives the reading order and explanations; it is not evidence of execution. Show only folders that actually exist, with the root replaced by the real absolute path:

```text
<user folder>/EmberDocs/
  Projects/              project and system descriptions
  tasks/active/          tasks in progress
  tasks/completed/       completed tasks
  Inputs/                task input materials
  Deliverables/Drafts/   drafts awaiting confirmation
  Deliverables/Final/    confirmed final results
  Inbox/                 materials collected for now
  Admin/                 review reports and workbench state
```

Also explain that the system rules, the bundled Skills (`.agents/skills/`), version routes (`skills/`) and the program (`app/`) are all in `<user folder>/Ember`, and the document library holds only the folders above. Give a clickable document library path; when the current tool can browse files, show that folder, without starting VS Code or other software automatically. Explain that empty basic folders are normal and task subfolders are created only when real materials or results appear.

End this round with only:

> The document library and its basic folders are set up in `<actual path>`. From now on projects, tasks, materials and results are kept in these places. Does this look right?

After the user replies, go on in order with “current AI tool and daily Skill → whether the workbench starts automatically → the conversation's task card → the user confirms in the workbench → a simple practice project”; never list all the later questions at once. The locations are fixed; if the user insists on another location, do not initialize again or move the existing library, first explain that an installation record now exists, then confirm the separate adjustment. This confirmation accepts only the folder stage; it is not acceptance of the whole installation, a final delivery or task completion. Report the separate verification the installer already ran truthfully, and never claim it has not run yet.

### 6. Read back the installation record and technical checks

The installer has already checked the real document library, then tested projects, tasks, inputs, deliverables, references and local HTTP in its own temporary document library. No test data stays in the user's document library. Read back the status, stage, checks and report path in `installation.json` in the program folder, then read the actual success / failure report at the receipt's `report_path`, and run check. On success say “the system is installed; next, let's set up the AI tool you are using”; on failure say which step failed and fix it first, without starting the hands-on guide. Passing the technical checks is not user acceptance, and the script did not create a task for the daily Skill.

### 7. Set up the current AI tool and install the daily Skill

Prefer the AI tool already used in this session. The executor is the AI software the user chooses; it is already holding this conversation, so it usually needs no installation. Keep three things apart: the installer's `--executor` only records the tool name; the default executor registration decides which software the workbench opens later; the global daily Skill lets that tool find the document library and work on tasks. None of them replaces another.

Identify the current tool from the host context or the user's confirmed choice, and check its real app / command path with read-only discovery. Never guess the current tool from a model name, the first PATH entry or “some software was found”; desktop apps, CLIs and editor extensions are different things. When the identity or path is unclear, ask for one missing item at a time. If the current tool is unavailable or does not support global Skills, say so truthfully and offer to continue by reading the Skill in the document library explicitly, without silently installing other software.

Show the user the tool name and software path you found and where the daily Skill will be installed, and say:

> Next, I suggest making `<AI tool>`, which you are using now, Ember's default executor, and installing the daily task Skill it uses. To switch tools later, go to “Settings → Execution environment → Change configuration” in the workbench. Shall I set it up this way?

This confirmation covers the software registration and Skill installation shown; with authorization for the same scope already given, just do it. Do not ask the user to run commands by hand. Keep the existing software list; if a different default exists, explain the difference between the old and new default first and save as the user chooses.

Order of work:

1. **Register the default software.** With the program Python call `ExecutorRegistry.snapshot()` and continue only if the configuration is readable; read-only `discover()` returns candidates. Keep the existing `executors` entries and reuse or add the current tool by its resolved real path, each entry having only `id`, `label`, `kind` and `path`, with `kind` either `app` or `command`. The payload uses `executors`, the selected `default_executor` and the current `expected_revision`; call `validate()` first, then `save()`. You can also use the workbench's `/api/executors/discover`, `check` and `save`, POSTing with the CSRF token from `/api/state`. After saving, read back the default, `registry_readable` and `ready`; never write the JSON directly, drop other software or bypass a version conflict. The configuration is kept in `~/.config/ember/executors.json` on this computer, not in the document library. Only the path is checked; the software is not started, and `ready` is not a model / sign-in check.
2. **Register the default document library.** Read back `default_workspace` in the installation receipt and `~/.config/ember/workspace.json`. The installer already ran `ember use`; do not overwrite it again. If it is `kept-existing`, show the old and new libraries, and only after the user explicitly chooses run `<program Python> -m ember use <new system folder> --replace`.
3. **Install the global daily Skill.** Confirm the user-level Skills folder by the current tool's real discovery rules (for example Claude Code `~/.claude/skills`, Codex `~/.agents/skills`, OpenCode `~/.config/opencode/skills`) and run `<program Python> -m ember install-skill --target <folder>`. Read back `SKILL.md` under the returned `path` (that is `<folder>/ember/SKILL.md`) and its version; in this English workspace it is the English daily Skill. `unchanged` means the same version and `upgraded` an upgrade from an official earlier version; a locally changed copy stops and is not overwritten. The installation folder is remembered, so after upgrading the program, running `install-skill` without arguments updates these targets. The init and project Skills are already in the document library and the daily Skill routes to them, so they need no global installation. Continue once the current AI has explicitly read the new daily Skill; never claim the client hot-loaded it just because copying succeeded.
4. **Verify the lookup.** Outside the document library, run `-m ember where` and `-m ember check` with the program Python to confirm the default library is this one. If the user chose to keep another default library, name this library explicitly from now on and say truthfully that automatic lookup still points to the old one.

The Settings entry you mention only changes the default executor; the Skills section in Settings currently shows registration and versions, so never claim it has a button to install global client Skills. The installation needs no MCP and does not change software accounts, permissions or model settings.

### 8. Ask whether the workbench should start automatically at login

By default the workbench is only a process started for now; it stops when the computer restarts, the user logs out or the terminal that started it is closed. The bundled background service (`ember service`) can run it automatically after the user logs in and restart it if it exits unexpectedly, without administrator rights. This leaves a login item on the computer, so ask once and install only after the user explicitly agrees:

> One more optional setting: should the workbench run in the background every time you log in? Then you can always open `http://127.0.0.1:<port>/` in your browser without asking me to start it. It runs only on this computer, needs no administrator rights, and you can turn it off any time. I recommend turning it on. Turn it on?

Ask only on macOS and Windows. Linux does not support this command; just explain that `ember serve` can be run with the system's own service manager, without configuring it, and move on.

After the user agrees:

1. First run `-m ember service status` with the program Python. If it is installed and its `workspace` is this system folder, reuse it without installing again; if it is installed but points to another workspace, show the old and new workspaces, explain that only one can run in the background at a time, and continue only after the user explicitly chooses to replace it; otherwise keep the old service and treat it as “not turned on”.
2. The background service and the temporary workbench use the same port and cannot run together. If this conversation started the workbench with `startup_argv`, first stop that process started here, then GET `/api/health` to confirm the port is free; if the port is held by a process of unknown origin, stop and explain, without ending it.
3. Run `<program Python> -m ember service install --workspace <system folder> --port <port>`. Read back the result and `service status`: `installed` and `running` are true, `workspace` is this system folder and `url` is reachable; then GET `/api/health` and `/api/state` to confirm the workbench reads this document library.
4. If installation fails or the read-back does not match, say so truthfully with the returned log path, never write a LaunchAgent, scheduled task or registry entry yourself, and do not retry repeatedly; continue the guide with a temporary start from `startup_argv`, and tell the user they can turn it on later with `ember service install`.

When the user does not turn it on, continue as usual and tell the user: after a restart the workbench stops, so ask the AI to start it or run `ember serve` when needed, and run `ember service install` any time to turn it on. Whatever the choice, record it and the actual state in the next stage's task card; stopping or uninstalling the background service later needs a separate request from the user, using `ember service stop` / `uninstall`.

### 9. Create the first task card with the daily Skill and ask the user to check it

Say to the user:

> Your software is set up. Now let's try it for real: I'll turn this installation and setup conversation into your first task card. In a later conversation you can pick up from this card.

Actually read the newly installed `ember/SKILL.md` and follow its lookup, check and ordinary task creation flow. First check this library, the system project and the installation receipt; in a normal first installation there is no real installation task yet. When resuming after an interruption, first look by the known ID or for the system task that recorded the `ember-init:installation-receipt` input; continue only if it matches this same installation, check first when ambiguous, and never guess from the title alone or create a duplicate. Never take an example task as the user's first card.

First check whether this document library's service is running; if not, use `ember service start` when the background service is installed, otherwise start it from the receipt's `startup_argv`; if it is running, reuse it and check its workspace without starting another. While the service runs, write through the HTTP API with the CSRF token; when it does not, wrap `Workspace` writes in `workspace_lock(workspace)`. The daily Skill performs these ordinary operations; never let the installer create the card:

1. `create_task` / POST `/api/tasks`: title “Ember first use”, `project:ember`, `work_type:system`, `task_kind:task`, `artifact_mode:none`, the real `executor` and the actual `skills_used:[ember-init,ember]`. The goal is to finish this installation and first use; the description states the choices and requirements the user confirmed, without inventing chat or business. There are no files to deliver here; the installation report is installation evidence, and no draft is created just to complete the task.
2. With `update_task` / POST `/api/tasks/<id>`, record the actual installation result, software registration, daily Skill usage, whether the workbench starts automatically and its actual state, and the next steps. Save the full text of the current `installation.json` in the program folder as an input snapshot with `add_material(kind=input,name=installation-record.json,source_locator=ember-init:installation-receipt,purpose=Read-only record of this installation and its technical checks)`; if the same name exists, read it back and compare without overwriting. The report can be saved as another text input naming its actual report path as the source; do not copy accounts, keys or unrelated conversation.
3. If the card was created but recording the input failed, keep and continue the ID just returned, add the input, and never create the card again. The recorded ID is the only tracking card for the rest of this flow.
4. Read back the body, tool, Skills and inputs by ID from `data.tasks` of GET `/api/state`; there is no GET `/api/tasks/<id>`. Check health and the Task desk, Projects, Review, Library and Settings entries. Refresh or reload the workbench, then open `#task/<id>` at the real URL; only switching the hash does not reload the data. Confirm the card really appears in the `ember` system project. If the service cannot be kept running, say so truthfully and never promise “it opens now”.

This round asks only:

> Your first task card is ready. Open “Ember first use” in the workbench and check whether its goal and installation result are accurate. Anything to add? If not, reply “OK” and we'll practice creating a project.

Wait for the user's reply. If something is missing, update the same card with the daily Skill and ask again; only after an explicit OK move on to the practice project, adding the actual reply to the task log. This OK only confirms the task content; it does not complete the whole guide or authorize deleting the init Skill.

### 10. Last exercise: create a simple project with the project Skill

After the user's OK on the task card, read `ember-project/SKILL.md` in the document library and create a clear practice project through its duplicate check, complete plan confirmation and controlled registration. Give the user one simple suggestion and ask only this:

> Finally, let's practice creating a project. I suggest calling it “Test project”, used only to get to know project descriptions and task management, with no external material folder for now. Is that name and purpose OK?

The AI prepares the technical plan and shows it as an easy summary: the suggested ID `ember-practice`, `kind:project`, the practice purpose and scope, empty `locations` and no `category`, the separate project description and the actual write locations. The description must say clearly that it is the user's own first-use practice and does not stand for a real client or business; it stays in the document library and is not deleted automatically after the check. If the user has a real simple project, use the name and purpose they confirm instead, without inventing business facts. If the user skips, record the skip and create nothing.

Check for duplicates read-only and show the plan first, then get the user's confirmation of that same plan; once every field is confirmed, do not ask again. If the user changes the name or purpose, revise the plan accordingly; on a same name / ID, let them choose to reuse or change it first, and never create a duplicate. Follow `ember-project`, either through the existing `project.py` plan-hash confirmation or, while the service runs, through that Skill's HTTP branch, checking for duplicates again and submitting the confirmed project fields, then separately record the actual Skill and the project log entry on the original installation task; the API never completes the task audit itself. After creating it, read back the project and its `overview` by ID from `data.projects` of `/api/state`, check `Projects/<id>/Project.md` in the document library read-only, run check, refresh or reload the workbench, then give the `#project/<id>` link and show the project name, purpose and description; never just switch the hash on an old open page. The installation task stays in the `ember` system project, is not moved to the practice project, and no tasks or deliverable files are created for demonstration.

### 11. The user confirms completion; remove the one-time guide

First read back the task card, the practice project and the actual software configuration, and confirm nothing is unresolved. Show the three things actually done this time: the current AI tool is set up, the first task card is saved and the practice project is created, and say whether the workbench starts automatically at login; if the user explicitly skipped the project or something failed, say so truthfully and never claim everything is done. Tell the user that tools are switched later in “Settings → Execution environment → Change configuration”, daily work uses `ember`, and creating projects uses `ember-project`.

Finally ask only one clear question:

> The first-use guide is finished. Your task card and practice project are kept, and the daily task and project features stay available. Once you confirm, I'll remove this one-time installation guide from the document library, so it no longer appears in the Skill list here. Confirm completion and remove the installation guide now?

You must wait for this final confirmation. Earlier confirmations of the folders, the task card OK or the project confirmation cannot replace it. If the user asks to keep the guide, keep it; when paused, not clearly answered or with unresolved problems, do not clean up. If the user explicitly skipped the project, record the skip and keep the guide; this round must not claim the full hands-on practice and automatic removal are done.

After the confirmation to “complete and remove”:

1. On the still active original task, add the final real result, the practice project's ID / purpose, the user's final confirmation and the intended removal scope; do not invent follow-up items when there are none. Complete this `artifact_mode:none` task through the existing `complete_task(id,{confirmation:true})` or POST `/api/tasks/<id>/complete`. Never bypass the completion gate with an ordinary status update, and never create final deliverable files.
2. While the service runs, POST `/api/onboarding/remove-init-skill` with only `{task_id:<completed first task ID>,confirmation:true}`, using the current service's CSRF token. When the service is not running, run `-m ember.onboarding_completion --workspace <system folder> --task-id <ID> --confirm` with the program Python. The cleanup checks this installation record, the completed task and the actual Skill history, handles only the fixed `.agents/skills/ember-init`, and updates the manifest / Resolver and the completion record. Never use `rm -rf` yourself or pass arbitrary paths; if it detects a guide the user changed, keep it and explain.
3. If cleanup fails, the original task stays completed; retry only the same cleanup, without creating another card, completing the task again or claiming it was deleted. After success run check and read back `/api/health`, `/api/settings` and the completed task / project. Refresh the workbench and confirm it still works and that the current Skills are `ember`, `ember-project`, `ember-review` and `ember-skill-authoring` before giving the user the result.

Removal applies only to the init Skill in the current document library; the original in the program package, the original downloaded package and any other global copies the user installed are outside this action. They do not affect this library's other bundled Skills; a new document library later can still read the program's bundled init guide through `ember skill-path`. Upgrading the program or updating the global daily Skill never reinstalls a guide already removed from the document library.

When the same program version only creates a new library, a separate installation record for this installation must still be kept, never overwriting another library's receipt in the original application folder; first confirm where the separate record goes and that the existing installation supports the flow, and never fake a ready state with an old receipt. Existing workspaces are outside this Skill's upgrade or cleanup scope.

## Output Format

A short English summary per stage: the actual program / document library folders, the default executor and where to change it later, the installation and actual use of the global daily Skill, whether the workbench starts automatically at login and its actual state, the link to the first real task card and the user's feedback, the practice project link or the fact that it was skipped, the installation record, the technical checks and the running service, and the final confirmation and whether the guide was actually removed. When the task is not accepted yet, say so, and never equate a successful program installation with completing the whole first use.

## Anti-Patterns

- Do not overwrite, reset or migrate an existing workspace, and never delete failure evidence or user files.
- Do not leave simulated test tasks in the real empty business workspace, and do not create fictional business projects automatically.
- Do not use a private Ember, NAS, real historical tasks or authentication configuration as a template.
- Do not reinstall AI software already in use, guess the default executor or silently switch to other software; register and install the daily Skill only as explicitly chosen this time. Do not configure plugins, MCP, credentials, mail or public listening; starting automatically at login is installed only with `ember service install` after the user explicitly agrees, never with a login item you write yourself; never run AI automatically or overwrite a changed Skill.
- Do not replace manual acceptance with passing tests, and never create placeholder deliverables or deliver or complete tasks on the user's behalf.
- Do not restore the retired archive module, and never treat authorization to install as authorization for any project creation or material migration.
- Do not call copying Skill files starting an AI conversation automatically; never make a new user send an activation command again, fire a series of questions at once, or skip showing the document library before creating business projects.
- Do not create the first card before configuring the executor, and never present a card created in advance by a script as the daily Skill's first card test.
- Do not remove the guide before the final explicit confirmation, and never delete the program source, global Skills, the practice project, tasks, inputs or installation records; never describe a failed cleanup as a success.
- Do not take an existing file, a usable path or passing program tests as the daily Skill having actually run; never skip the user's check of the task card, or treat the practice project as default fictional business or delete it automatically after verification.
- Do not change the workspace language after the folders exist, or answer in Chinese in this English installation.

## Tools Used

File reading, a terminal and a browser. The installation starts child processes with argument arrays; the installation record uses `onboarding`, the first task is created by the daily Skill through the existing `Workspace` / HTTP API, and project creation uses `ember-project`'s existing controlled API; no arbitrary shell commands are assembled.
