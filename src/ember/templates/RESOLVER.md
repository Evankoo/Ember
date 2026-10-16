# Ember Resolver

当前文件所在目录是本机余烬的**系统目录**（默认 `~/Ember`）：保存规则、Skill、配置与程序（`app/`）。任务与资料只放在**文档库**（默认 `~/Ember文档`），其绝对位置登记在 `config/workspace.json` 的 `documents`。启动命令通过 `--workspace` 指向系统目录。

| 对象 | 位置 |
| --- | --- |
| 项目/系统注册 | 系统目录 config/projects.json |
| 文档库位置与名称 | 系统目录 config/workspace.json |
| 首次安装 Skill | 系统目录 .agents/skills/ember-init/SKILL.md |
| 日常工作入口 Skill | 系统目录 .agents/skills/ember/SKILL.md |
| 项目/系统建项 Skill | 系统目录 .agents/skills/ember-project/SKILL.md |
| Skill 注册与路由 | 系统目录 skills/manifest.json、skills/RESOLVER.md |
| 任务创建模板 | 系统目录 templates/task-card.md |
| 程序、安装收据与报告 | 系统目录 app/ |
| 项目/系统说明正本 | 文档库 项目/<id>/项目看板.md |
| 活跃任务 | 文档库 tasks/active/<task_id>.md |
| 完成任务 | 文档库 tasks/completed/<task_id>.md |
| 任务输入 | 文档库 任务资料/<task_id>/ |
| 用户草稿 | 文档库 交付/草稿/<task_id>/ |
| 正式交付 | 文档库 交付/正式交付/<task_id>/ |
| 待分类资料 | 文档库 Inbox/ |
| 检视报告 | 文档库 管理中心/整理记录/ |
| 重要事项与 Inbox 标签台账 | 文档库 管理中心/运行状态/ |

任务卡、资料 ID 与 `delivery.folder`、`inputs.folder` 都是相对文档库的位置。不自动扫描其他目录，不把未知位置当作数据回退。规则只在 AGENTS.md 中维护，路径表不改变生命周期。
