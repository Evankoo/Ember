# v0.1.1：通用入口与基础 Skill 对齐

本版从当前 GStudio 总入口提炼通用规则，不复制完整工作台、业务 Skill 或私人系统配置。保留单机框架与两个基础 Skill，界面和虚构业务示例不变。

## 更新内容

- `gstudio-core` 1.1.0：任务必要性判断、普通只读检索无卡、项目说明正本、同一目标继续原任务、下游 Skill 边界、操作前后校验与人工确认。
- `gstudio-init` 1.0.1：匹配 Core 0.1.1 安装包，初始化后转交日常入口；仍只用于新安装或新工作区。
- 两个 Skill 的标准 frontmatter、工作区 manifest 版本登记和 Resolver 路由同步更新。
- 创建和续接任务可通过原有受控接口填写真实 `executor`、`skills_used`；续接保留已有 Skill 历史，错误值在写入前拒绝。
- 系统模板和对照文档明确项目说明由工作区独立维护，不依赖 EBrain；校验通过不代表用户接受或任务完成。

没有新增业务 Skill、NAS、双机同步、知识库、模型登录或自动执行器，也不把外部正本搬进 Core。

## 已有安装与工作区

应用代码与用户工作区分开。采用新版应用不会自动改写任务、项目说明、工作区 `AGENTS.md` 或 `.agents/skills/`；`gstudio init` 仍拒绝非空目录，不可用于原地升级。

在原应用环境中安装新版 wheel 后，先用 `gstudio check --workspace <原工作区>` 检查已有数据。已有合法任务和不带 Skill 版本字段的旧 manifest 保持可读。

若要采用新版规则和 Skill，先备份工作区并与新版本模板逐项比较：`AGENTS.md`、`RESOLVER.md`、两个 `.agents/skills/` 目录，以及 `skills/manifest.json`、`skills/RESOLVER.md`。仅同步明确确认的变动，保留用户自己的规则和其他 Skill 登记，再执行校验与回读。不要整包覆盖、重新初始化或复制虚构任务到真实工作区。

本版没有自动迁移或契约升级命令；新初始化工作区直接获得新版规则与两个 Skill。
