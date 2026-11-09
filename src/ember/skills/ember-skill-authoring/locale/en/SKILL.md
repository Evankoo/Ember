---
name: ember-skill-authoring
version: 1.0.0
description: Create or change the user's own Skills for this computer's Ember. Use it when the user says “make a Skill”, “turn this way of working into a Skill” or wants to change their own Skill. It first checks whether an existing Skill already covers it, then writes SKILL.md in the standard structure, registers it in the manifest and Resolver, and verifies item by item. It never changes Ember's bundled Skills; a one-off operation goes into a task card, not a Skill.
triggers: [make a Skill, write a Skill, create a Skill, turn this way of working into a Skill, change my Skill, register a Skill]
tools: [read_file, write_file, terminal]
mutating: true
writes_pages: false
---

# Ember Skill Authoring

## Contract

- A Skill is an operating guide for AI tools that sets how one kind of recurring work is done; write only processes that will be used again.
- The user's own Skills live in the system folder's `.agents/skills/<name>/` and are registered in `skills/manifest.json` and `skills/RESOLVER.md`; with either missing, AI cannot find them.
- Never change Ember's bundled Skills (`ember-init`, `ember`, `ember-project`, `ember-review`, `ember-skill-authoring`). When a different way is needed, create the user's own Skill.
- The system folder's `AGENTS.md` holds the rules; a Skill points back to it and never rewrites a set of task rules.
- Show the plan to the user before writing; write files and change the registry only after the user confirms.

## When to Use

- The user wants to fix a way of working they repeat, for example “write an internal newsletter every week”.
- The user wants to change or rename a Skill they wrote.
- The user asks why AI does not use their Skill, and its writing and registration need checking.

A one-off operation belongs in a task card; for a request to change a bundled Skill, explain that it affects upgrades and suggest creating a new Skill instead.

## References

- The system folder's `skills/manifest.json` and `skills/RESOLVER.md`: registered Skills and routes.
- The bundled Skills under the system folder's `.agents/skills/`: examples of the structure.
- The system folder's `AGENTS.md`: task-card and confirmation rules.
- The full guide is the Ember repository's `docs/skill-authoring.md`.

## Phases

1. **Check for overlaps.** Read `skills/manifest.json` and `skills/RESOLVER.md`. When an existing Skill covers the work, change it instead of creating another Skill with overlapping triggers.
2. **Settle the plan.** Confirm with the user: the name (lowercase letters and hyphens, the same as the folder), what it solves, when to use it and when not, the triggers, and which steps write or publish anything. Show the plan and write only after the user confirms.
3. **Write SKILL.md.** The first line is `---`; the YAML header holds `name`, `version` (starting at `1.0.0` and changed with the content), `description` (one paragraph on what it does, when to use it and when not), `triggers` (what users really say), `tools` (the tool categories actually used), `mutating` (`true` when it writes) and `writes_pages: false`. The body has seven sections in order: `## Contract`, `## When to Use`, `## References`, `## Phases`, `## Output Format`, `## Anti-Patterns`, `## Tools Used`. Write paths relative to the system folder or `$HOME`, never `/Users/<name>/`; no accounts, tokens or machine configuration; steps that write, delete or publish say to ask the user first. Put long manuals in a `references/` folder beside it and link them from `## References`.
4. **Register.** Add an entry to the `skills` list in `skills/manifest.json`: `{"name": "<name>", "version": "<version>", "path": ".agents/skills/<name>/SKILL.md", "purpose": "<one-line purpose>"}`; add a route line to `skills/RESOLVER.md`: `- <when to use it>: read [<name>](../.agents/skills/<name>/SKILL.md).`. When changing an existing Skill, update its `version` in the manifest too.
5. **Verify.** Check each point: the first line is `---` and the YAML parses; `name` matches the folder; all seven sections are present in order; `manifest.json` is still valid JSON and the new Skill is in both the manifest and the Resolver; no `/Users/` personal path anywhere; `<python> -m ember check --workspace <system folder>` passes. Finally ask the user to say a trigger phrase in their AI tool and confirm the Skill is really read.
6. **Record.** When writing the Skill is ongoing maintenance, create or continue a task card under the Ember system project as `ember` describes, recording the files written and the verification.

## Output Format

```markdown
Skill: <name> <version> (new / changed)
- File: .agents/skills/<name>/SKILL.md
- Registered: manifest ✓, RESOLVER ✓
- Verification: <result per point>; ember check <passed / failed: reason>
- For you: say “<trigger phrase>” in your AI tool once to try it
```

## Anti-Patterns

- Never change bundled Skills or put the user's own Skill in the program folder `app/`.
- Never add files without registering them, or register without the files.
- Never write personal absolute paths, accounts, tokens or model settings.
- Never turn a one-off operation into a Skill or create a Skill whose triggers overlap an existing one.
- Never rewrite task-card rules in a Skill or let a Skill bypass the user's confirmation.

## Tools Used

File reading and writing and the terminal: read and write Skill files and the registry, and check the workspace with `ember check`.
