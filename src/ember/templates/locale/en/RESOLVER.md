# Ember Resolver

The folder holding this file is Ember's **system folder** on this computer (default `~/Ember`): it holds rules, Skills, configuration and the program (`app/`). Tasks and materials live only in the **document library** (default `~/EmberDocs`), whose absolute location is recorded as `documents` in `config/workspace.json`. The start command points to the system folder with `--workspace`.

| Item | Location |
| --- | --- |
| Project/system registry | system folder config/projects.json |
| Document library location, name and language | system folder config/workspace.json |
| First-installation Skill | system folder .agents/skills/ember-init/SKILL.md |
| Daily work entry Skill | system folder .agents/skills/ember/SKILL.md |
| Project/system creation Skill | system folder .agents/skills/ember-project/SKILL.md |
| Task review Skill | system folder .agents/skills/ember-review/SKILL.md |
| Skill authoring Skill | system folder .agents/skills/ember-skill-authoring/SKILL.md |
| Skill registry and routes | system folder skills/manifest.json, skills/RESOLVER.md |
| Task creation template | system folder templates/task-card.md |
| Program, installation receipt and report | system folder app/ |
| Project/system source description | document library Projects/<id>/Project.md |
| Active tasks | document library tasks/active/<task_id>.md |
| Completed tasks | document library tasks/completed/<task_id>.md |
| Task inputs | document library Inputs/<task_id>/ |
| User drafts | document library Deliverables/Drafts/<task_id>/ |
| Final deliverables | document library Deliverables/Final/<task_id>/ |
| Unsorted material | document library Inbox/ |
| Review reports | document library Admin/Reviews/ |
| Current-focus and Inbox label ledgers | document library Admin/Runtime/ |

Task cards, material IDs, `delivery.folder` and `inputs.folder` are all relative to the document library. Other folders are never scanned automatically, and unknown locations are never used as a data fallback. Rules are maintained only in AGENTS.md; the location table does not change any lifecycle.
