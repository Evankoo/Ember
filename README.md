# 余烬 · Ember

English · [中文](README.zh-CN.md)

**When the tokens burn out, what is left?**

**Every conversation rekindles from the last one's embers.**

**People and AI move work forward on the same record.**

Ember is an AI task system. Each piece of work becomes a task record that holds its goal, progress, materials and results, stored on your own computer. You can read, edit and search it at any time; when AI starts work it reads the record directly for precise context, and writes back when it is done.

The name comes from the *Zhuangzi*: “The fingers fail in feeding the fuel, but the fire passes on, and no one knows where it ends.” Every AI conversation is a piece of firewood that burns out; the task record is the fire. Between two conversations the embers stay warm, and the next one starts from there.

It was shaped by real work and is used every day for courses, content and system building. This repository is the complete open-source (single-computer) edition of Ember, MIT licensed, for macOS / Windows / Linux.

[About](https://ai.evan-manual.com/ember/) · [Live demo](https://ai.evan-manual.com/ember/demo/) · [Latest release](https://github.com/Evankoo/Ember/releases/latest) · [Changelog (Chinese)](CHANGELOG.md)

## Why

The more you use AI, the more scattered the context becomes:

- in a new conversation you worry the AI does not know the situation;
- so you explain the background again, hunt for materials and write long instructions;
- and something still gets missed, the AI goes off track and the work has to be redone.

Ember turns each piece of work into a task record, so whoever picks it up next, you or the AI, continues from the same place.

## Languages

Ember comes in Chinese and English. **The language is chosen once, when a workspace is created, and cannot be changed afterwards.** An English workspace is English throughout: folder names (`~/EmberDocs`, `Deliverables/Drafts`, `Inputs`, `Projects`, `Admin`…), task-card headings, execution logs, project descriptions, the rule files, the three Skills, the prompts given to AI and the workbench interface. There is one installation package for both languages.

## Install

### Let AI install it (recommended)

You need macOS, Windows 11 or Linux, and Python 3.10 or newer (many Macs ship only 3.9). If there is no suitable Python, the AI tells you first and installs one only after you agree.

Send this to an AI tool that can read and write files on your computer, such as Codex, Claude Code or OpenCode:

```text
Please install the complete open-source edition of Ember with its official init Skill:
https://github.com/Evankoo/Ember
Read and follow ember-init directly, one question at a time. After installing, show me the basic folders and keep guiding me.
```

The AI downloads `ember-init-*.zip` from the [latest release](https://github.com/Evankoo/Ember/releases/latest), unpacks the three Skills, and the init Skill then guides you step by step:

0. It first asks you, in Chinese and English, to choose a language: 中文 or English. Choose English. Your choice cannot be changed after installation;
1. it explains the fixed locations: the system folder `~/Ember` (rules, Skills, configuration and the program) and the document library `~/EmberDocs` (projects, tasks, materials and results);
2. it installs the program, the basic folders and the three bundled Skills, creates the Ember system project and saves an installation record, without creating tasks in advance;
3. it shows the real document library; after you confirm, it sets up the AI tool you are using and installs the daily Skill (you can switch tools later in “Settings → Execution environment → Change configuration”), and asks whether the workbench should start automatically at login (macOS and Windows);
4. it uses the daily Skill to turn this conversation into your first task card, “Ember first use”, and asks you to check it in the workbench; it continues only after you say OK;
5. it walks you through creating a simple practice project with the project Skill;
6. finally it asks whether to confirm completion and remove the one-time installation guide. Your tasks, projects and materials stay, and the daily and project Skills remain.

### Manual install

Python 3.10 or newer is required. In the repository folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
ember init ~/Ember --language en --example     # also creates ~/EmberDocs
ember use ~/Ember
ember serve
```

Open **http://127.0.0.1:8783/** in a browser and press `Ctrl+C` to stop. `--language` sets the workspace language and cannot be changed later; without it, `ember init` asks in the terminal. `--example` adds a completely fictional example with clients, projects and tasks; leave it out for an empty document library. The document library defaults to “<system folder name>Docs” next to the system folder, or set it with `--documents`.

## How to use it

1. **Work with AI as usual.** In an AI tool that can read and write local files, ask as you normally would.
2. **AI writes into the task record.** The daily Skill `ember` lets AI create or continue a card as it works, writing back the goal, materials, result and next steps. Task records are always written into the Ember workspace; the project folder you are working in gets no extra files.
3. **Pick up any time.** Next time, say “continue the autumn plan from last time” and the AI reads from that task card; if you forgot an earlier conclusion, search for it in the workbench.

Once a project has its local working folder registered, AI working in that folder matches it to the project automatically:

```bash
ember project-location autumn-site ~/code/autumn-site
ember which-project --dir ~/code/autumn-site/src
ember project-category autumn-site "Content operations"
```

The daily Skill can also be installed globally by hand, for example `ember install-skill --target ~/.claude/skills`. In an English workspace it installs the English Skill. No MCP is needed.

## Design principles

- **People can work with it.** Task records can be read, edited and searched at any time, and every material and result can be found again.
- **AI can use it.** AI reads the record for precise context and writes results and next steps back.
- **Everything is local.** Projects, tasks, materials and results are ordinary files: task cards are Markdown and results keep their original formats.
- **Open source.** MIT licensed; the service only listens locally, never calls a model or sends prompts automatically, and asks you before opening AI software.

## What is included

| Part | Description |
| --- | --- |
| Workbench | Task desk, Projects, Review, Library and Settings, plus project and task details |
| Task records | One task card per piece of work: Goal, Description, Current Result, Next Steps and Execution Log |
| Materials and deliverables | Inputs, drafts and final deliverables are kept apart; same-name files are never overwritten |
| Three Skills | `ember-init` for the first installation, `ember` for daily work, `ember-project` for creating projects after confirmation |
| Command line | `init`, `use`, `where`, `check`, `serve`, `install-skill`, `which-project`, `project-location`, `project-category` |

The open-source edition is the single-computer base edition. It does not include the full edition's archive center, multi-computer sync, knowledge base, runtime Agents, model authentication or automatic publishing, and offers no permanent deletion, automatic task merging or automatic backups. Back up your workspace yourself. The service only listens on the local loopback address; do not expose a workspace to the internet through a reverse proxy.

The other documents in `docs/` and the changelog are currently in Chinese.

Original code, examples and Skills are [MIT](LICENSE) licensed; the heading font follows the SIL Open Font License 1.1, see `src/ember/web/fonts/OFL.txt`.
