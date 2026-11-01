# Skill 写法

Skill 是一份给 AI 工具读的操作说明，规定一类工作怎么做。这份文档说明怎么给本机余烬新增或修改自己的 Skill。自带的三个 Skill（`ember-init`、`ember`、`ember-project`）就是按这里的写法写的，可以直接当例子看。

## 动手之前

1. 读 `skills/manifest.json` 和 `skills/RESOLVER.md`，看有没有 Skill 已经覆盖这件事。有就改它，不要再建一个触发词重叠的新 Skill。
2. 不要改自带的三个 Skill。升级时 `ember install-skill` 遇到被改过的副本会停止，不覆盖，你的副本也就不再更新。需要不同的做法时，新建自己的 Skill。
3. 一次性的操作不用写 Skill，写进任务卡就够了。

## 放在哪里

每个 Skill 一个文件夹，放在系统目录（默认 `~/Ember`）：

```text
.agents/skills/<skill-name>/
├── SKILL.md            # 必需：主流程
├── references/         # 可选：长规则、边界情况、原始手册
└── scripts/            # 可选：配套脚本
```

文件夹名用小写字母和连字符，与 `name` 一致。

## SKILL.md 开头

文件第一行就是 `---`，前面不留空行，内容是合法的 YAML：

```yaml
---
name: weekly-newsletter
version: 1.0.0
description: 把本周任务整理成一封内部周报。用户说“写周报”时使用；普通任务汇报不用。
triggers: [写周报, 整理本周周报]
tools: [read_file, write_file, terminal]
mutating: true
writes_pages: false
---
```

| 字段 | 写什么 |
| --- | --- |
| `name` | Skill 名称，与文件夹一致 |
| `version` | 版本号，内容改动时一起改 |
| `description` | 一段话写清做什么、什么时候用、什么时候不用，AI 工具靠它判断要不要调用 |
| `triggers` | 用户真实会说的话，要具体 |
| `tools` | 实际用到的工具类别 |
| `mutating` | 会改文件或数据写 `true`，只读写 `false` |
| `writes_pages` | 是否直接写知识库页面；开源版没有知识库，写 `false` |

## 正文结构

按这个顺序写这七节：

```markdown
# 标题

## Contract
这个 Skill 保证什么，3 到 7 条。

## When to Use
什么情况用，什么情况不用。

## References
用到的参考文件、模板、脚本或其他 Skill。

## Phases
带编号的步骤，写清前置检查、写到哪里、怎么验证。

## Output Format
最终回复或产物应该是什么样。

## Anti-Patterns
不要做什么，写真实会犯的错。

## Tools Used
用到哪些工具，为什么用。
```

## 写的时候注意

- **路径可移植。** 用相对系统目录的路径或 `$HOME`，不写 `/Users/<名字>/` 这样的个人路径。
- **保持简短。** `SKILL.md` 只放能走完流程的主线。长手册、边界情况和详细规则放进 `references/`，再从 `## References` 链接过去。
- **不重复写规则。** 任务卡规则以系统目录的 `AGENTS.md` 为准，Skill 里回指即可。
- **不写密钥。** 账号、令牌和本机配置不进 Skill。
- **遵守确认边界。** 会写入、删除或对外发布的步骤，要写明什么时候先问用户。

## 登记

Skill 写好后，登记两处，让 AI 工具找得到：

1. `skills/manifest.json` 的 `skills` 列表加一项：

   ```json
   {"name": "weekly-newsletter", "version": "1.0.0", "path": ".agents/skills/weekly-newsletter/SKILL.md", "purpose": "整理内部周报"}
   ```

2. `skills/RESOLVER.md` 加一行路由：

   ```markdown
   - 整理内部周报：读取 [weekly-newsletter](../.agents/skills/weekly-newsletter/SKILL.md)。
   ```

设置页只显示自带的基础 Skill，你自己的 Skill 不会出现在那里，这是正常的。要在其他目录也能调用，把它放进所用 AI 工具的 Skill 目录，位置以该工具的文档为准。

## 验证

开源版没有自动检查 Skill 写法的工具，`ember check` 只检查工作区本身，所以改完要自己走一遍：

1. 第一行是 `---`，开头的 YAML 能正常解析。
2. `name` 与文件夹一致，七节齐全且顺序正确。
3. `manifest.json` 仍是合法 JSON，新 Skill 在 `manifest.json` 和 `RESOLVER.md` 里都有。
4. 全文搜一下 `/Users/`，确认没有个人路径。
5. 运行 `ember check`，确认工作区没有被改坏。
6. 在 AI 工具里说一句触发词，确认它真的读取了这个 Skill，并走完一遍流程。
