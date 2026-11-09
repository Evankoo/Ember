---
name: ember-skill-authoring
version: 1.0.0
description: 为本机余烬新建或修改用户自己的 Skill。用户说“做一个 Skill”“把这套做法写成 Skill”或要改自己的 Skill 时使用：先查有没有已覆盖的 Skill，再按统一结构写 SKILL.md、登记到 manifest 与 Resolver，并逐项验证。不改余烬自带的 Skill；一次性的操作写进任务卡，不写 Skill。
triggers: [做一个 Skill, 写一个 Skill, 新建 Skill, 把这套做法写成 Skill, 修改我的 Skill, 登记 Skill]
tools: [read_file, write_file, terminal]
mutating: true
writes_pages: false
---

# 余烬 Skill 写法

## Contract

- Skill 是给 AI 工具读的操作说明，规定一类重复工作怎么做；只写会反复用到的流程。
- 用户自己的 Skill 放在系统目录 `.agents/skills/<name>/`，并登记到 `skills/manifest.json` 与 `skills/RESOLVER.md`，两处缺一处 AI 就找不到。
- 不改余烬自带的 Skill（`ember-init`、`ember`、`ember-project`、`ember-review`、`ember-skill-authoring`）。需要不同做法时新建自己的 Skill。
- 规则以系统目录 `AGENTS.md` 为准，Skill 里回指即可，不重写一套任务规则。
- 写入前把方案给用户看；用户确认后才写文件和改登记。

## When to Use

- 用户要把一套反复使用的做法固定下来，例如“每周写一封内部周报”。
- 用户要修改或改名自己写过的 Skill。
- 用户问自己的 Skill 为什么没被 AI 调用，需要检查写法和登记。

一次性的操作写进任务卡即可；改余烬自带 Skill 的需求，说明会影响升级，建议改为新建。

## References

- 系统目录 `skills/manifest.json`、`skills/RESOLVER.md`：已登记的 Skill 和路由。
- 系统目录 `.agents/skills/` 下的自带 Skill：写法示例。
- 系统目录 `AGENTS.md`：任务卡与确认规则。
- 完整说明见余烬仓库 `docs/skill-authoring.md`。

## Phases

1. **查重。** 读 `skills/manifest.json` 和 `skills/RESOLVER.md`。已有 Skill 覆盖这件事就改它，不再建一个触发词重叠的新 Skill。
2. **定方案。** 和用户确认：名称（小写字母和连字符，与文件夹同名）、要解决的事、什么时候用和不用、触发词、步骤里哪些会写入或对外发布。把方案给用户看，确认后再写。
3. **写 SKILL.md。** 文件第一行就是 `---`，开头 YAML 含 `name`、`version`（从 `1.0.0` 起，内容改动时一起改）、`description`（一段话写清做什么、何时用、何时不用）、`triggers`（用户真实会说的话）、`tools`（实际用到的工具类别）、`mutating`（会写入为 `true`）、`writes_pages: false`。正文依次写七节：`## Contract`、`## When to Use`、`## References`、`## Phases`、`## Output Format`、`## Anti-Patterns`、`## Tools Used`。路径写相对系统目录或 `$HOME`，不写 `/Users/<名字>/`；不写账号、令牌和本机配置；会写入、删除或发布的步骤写明先问用户。长手册放进同目录 `references/`，从 `## References` 链接。
4. **登记。** 在 `skills/manifest.json` 的 `skills` 列表加一项：`{"name": "<name>", "version": "<version>", "path": ".agents/skills/<name>/SKILL.md", "purpose": "<一句话用途>"}`；在 `skills/RESOLVER.md` 加一行路由：`- <什么时候用>：读取 [<name>](../.agents/skills/<name>/SKILL.md)。`。修改已有 Skill 时同步更新 manifest 里的 `version`。
5. **验证。** 逐项核对：第一行是 `---` 且 YAML 能解析；`name` 与文件夹一致；七节齐全且顺序正确；`manifest.json` 仍是合法 JSON，新 Skill 在 manifest 和 Resolver 里都有；全文没有 `/Users/` 个人路径；运行 `<python> -m ember check --workspace <系统目录>` 通过。最后请用户在 AI 工具里说一句触发词，确认真的读取了这个 Skill。
6. **记录。** 这次写 Skill 属于持续维护时，按 `ember` 在余烬系统项目下建立或续接任务卡，记录写入的文件和验证结果。

## Output Format

```markdown
Skill：<name> <version>（新建 / 修改）
- 文件：.agents/skills/<name>/SKILL.md
- 登记：manifest ✓，RESOLVER ✓
- 验证：<逐项结果>；ember check <通过 / 失败：原因>
- 待你做：在 AI 工具里说“<触发词>”试一次
```

## Anti-Patterns

- 不改自带 Skill，不把自己的 Skill 放进程序目录 `app/`。
- 不只放文件不登记，也不只登记不放文件。
- 不写个人绝对路径、账号、令牌或模型配置。
- 不把一次性操作写成 Skill，不建触发词和已有 Skill 重叠的新 Skill。
- 不在 Skill 里重写任务卡规则，不让 Skill 绕过用户确认。

## Tools Used

文件读写与终端：读写 Skill 文件和登记，用 `ember check` 校验工作区。
