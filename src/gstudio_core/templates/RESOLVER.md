# GStudio Core Resolver

当前文件所在目录就是本地数据工作区。安装代码与虚拟环境在初始化时选择的安装目录；启动命令通过 `--workspace` 明确本目录。

| 对象 | 相对位置 |
| --- | --- |
| 项目/系统注册 | config/projects.json |
| 项目/系统说明正本 | projects/<id>.md |
| 活跃任务 | tasks/active/<task_id>.md |
| 完成任务 | tasks/completed/<task_id>.md |
| 任务输入 | inputs/<task_id>/ |
| 用户草稿 | delivery/draft/<task_id>/ |
| 正式交付 | delivery/formal/<task_id>/ |
| 待分类资料 | inbox/ |
| 检视报告 | reports/ |
| 呈现与 Inbox 标签台账 | .gstudio/ |
| 首次安装 Skill | .agents/skills/gstudio-init/SKILL.md |
| 日常工作入口 Skill | .agents/skills/gstudio-core/SKILL.md |
| Skill 注册与路由 | skills/manifest.json、skills/RESOLVER.md |
| 任务创建模板 | templates/task-card.md |

不自动扫描其他目录，不把未知位置当作数据回退。规则只在 AGENTS.md 中维护，路径表不改变生命周期。
