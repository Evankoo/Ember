# 与 GStudio 完整系统的对齐说明

GStudio Core 提炼的是 GStudio 的基础工作关系、页面职责和本地操作闭环。它使用新的实现和完整虚构的示例数据，保留可以独立安装的部分。它不是完整系统的等价副本，也不承诺直接迁移或双向同步生产工作区。

以下完整系统文件名均为仓库相对位置，只用于说明设计与规则来源；安装 Core 不需要这些文件、私人配置或真实业务数据。

## 常驻页面与动态工作区

五个常驻入口是任务台、项目视图、任务检视、资料浏览、设置。v0.3.0 起归档中心暂不在公开范围内。项目或系统工作属于用户创建的持续工作对象，应出现在动态工作区中，而不是变成额外的常驻工具页面。

Core 的动态工作区读取本地注册。用户可以新建 project（项目）或 system（系统）两类工作区对象，两者共享说明、任务、输入与交付机制。系统工作区承载持续的系统建设工作，不等同于运行 Agent 治理；当前版本没有完整系统的能力类型注册、外部知识页或执行器路由。

| 页面或对象 | 保留的职责 | 完整系统来源 | Core 实现 |
| --- | --- | --- | --- |
| 常驻导航与工作区 | 工具入口稳定；已注册工作对象动态出现 | `scripts/gstudio_workbench.py`、`WORKBENCH_DESIGN.md` | `src/gstudio_core/web/index.html`、`src/gstudio_core/web/app.js` |
| 任务台 | 描述本次要求，选任务关系与资料，检索已有任务 | `scripts/gstudio_workbench.py` | `src/gstudio_core/web/app.js`、`src/gstudio_core/store.py` |
| 项目视图 | 比较当前重要事项、进行中任务和近 30 天完成任务；独立任务另列 | `scripts/gstudio_workbench.py` | `src/gstudio_core/web/app.js` |
| 项目与系统工作区 | project / system 动态注册；常驻概览与时间线；任务、交付文件、输入资料是三个同级场景 | `scripts/gstudio_workbench.py`、`scripts/gstudio_project.py`、`config/projects.json` | `src/gstudio_core/web/app.js`、`src/gstudio_core/store.py` |
| 任务检视 | 阅读任务、明确所选范围、准备整理上下文、保存与回看报告 | `scripts/gstudio_workbench.py`、`scripts/gstudio_task_organization.py`、`scripts/gstudio_weekly_organization.py` | `src/gstudio_core/web/app.js`、`src/gstudio_core/store.py` |
| 资料浏览 | 以文件为主浏览、筛选、文本阅读和下载；任务是文件来源关系 | `scripts/gstudio_workbench.py`、`scripts/gstudio_task_inputs.py` | `src/gstudio_core/web/app.js`、`src/gstudio_core/store.py`、`src/gstudio_core/server.py` |
| 设置 | 已保存本机环境摘要、动态软件清单、修改检查保存、基础 Skills 与操作边界 | `scripts/gstudio_workbench.py` | `src/gstudio_core/web/app.js`、`src/gstudio_core/server.py`、`src/gstudio_core/executors.py` |
| 视觉语言 | 暖纸色、深色侧栏、共享文字层级、留白、响应式阅读布局 | `WORKBENCH_DESIGN.md`、`scripts/gstudio_workbench_assets.py` | `src/gstudio_core/web/app.css`、`src/gstudio_core/templates/WORKBENCH_DESIGN.md` |

Core 的项目或系统说明正本是 `projects/<id>.md`，`config/projects.json` 登记身份、kind、简短导航信息、当前重点和时间线。kind 只允许 project / system，旧记录省略时默认为 project。两类对象都拥有正式任务范围；independent 仍不能注册为工作区对象。已注册对象缺失说明会报错。当前完整系统同样由 GStudio 自己维护项目说明，EBrain 是可选知识能力，不是建项或说明依赖。Core 保留独立本地 Markdown 正本，不导入外部知识页，也不移动专业源码或业务数据。

## 任务、输入和交付

| 规则 | Core 保留的行为 | 完整系统来源 | Core 实现 |
| --- | --- | --- | --- |
| 紧凑任务头 | 新卡包含 type、task_id、title、project、work_type、task_kind、status、executor、created_at、updated_at、skills_used、artifact_mode 共 12 个必需字段；北京时区时间含明确偏移 | `AGENTS.md`、`skills/gstudio/references/task-card-template.md`、`scripts/task_gate.py` | `src/gstudio_core/store.py`、`src/gstudio_core/templates/templates/task-card.md` |
| 真实执行登记 | 创建和续接接口可登记真实 executor 与 skills_used；续接追加 Skill 历史而不改变任务归属或生命周期；不推断模型或自动启动执行器 | `AGENTS.md`、`skills/gstudio/SKILL.md` | `src/gstudio_core/store.py`、`docs/api.md` |
| 人类可读正文 | 任务目标、任务描述、当前结果、执行日志四个必需板块；下一步按需出现；日志是最后一个二级板块，最新记录在前 | `AGENTS.md`、`scripts/task_gate.py`、`scripts/gstudio_task.py` | `src/gstudio_core/store.py` |
| 短标题 | 最多 20 个字符、单行完整名称、不含省略号；目标和背景分别写入正文 | `AGENTS.md`、`scripts/task_gate.py` | `src/gstudio_core/store.py`、`src/gstudio_core/web/app.js` |
| 四个生命周期状态 | active、waiting_user、blocked、completed；新任务为 active，等待或阻碍由用户明确设置；不会从结果文字自动推断完成 | `AGENTS.md`、`scripts/gstudio_task.py`、`scripts/task_gate.py` | `src/gstudio_core/store.py`、`src/gstudio_core/web/app.js` |
| 独立任务范围 | independent 可拥有任务，不注册成项目，也不是待分类数据的回退位置 | `AGENTS.md`、`scripts/gstudio_task.py` | `src/gstudio_core/store.py`、`src/gstudio_core/web/app.js` |
| 任务线 | task_kind: task_group；线卡单向登记 related_task_ids；至少关联两项同项目普通任务；保留原卡、原输入与原交付，并生成非空说明和索引 | `AGENTS.md`、`skills/gstudio/references/task-group-standard.md`、`scripts/task_gate.py` | `src/gstudio_core/store.py` |
| 呈现重要性 | 重要事项使用独立 revision 台账；不修改任务的项目、状态、正文或交付 | `AGENTS.md`、`scripts/gstudio_workbench.py` | `src/gstudio_core/store.py`、工作区 `.gstudio/views.json` |
| 输入快照 | 位于 inputs/<task_id>/；登记 id、名称、用途、storage、来源位置与环境、size、SHA-256 和 added_at；同名拒绝覆盖；检查存在、归属、大小与真实摘要 | `AGENTS.md`、`scripts/gstudio_task_inputs.py` | `src/gstudio_core/store.py` |
| 输入引用 | 已有受控资料登记为 reference；来源文件不复制，引用位置必须存在于工作区文件索引 | `AGENTS.md`、`scripts/gstudio_task_inputs.py` | `src/gstudio_core/store.py`、`src/gstudio_core/web/app.js` |
| 真实草稿交付 | 输入不能放入交付目录；真实成果出现后才登记 delivery.folder、state:draft 与单一 Quick Navigation；任务线是预建非空交付的例外 | `AGENTS.md`、`skills/gstudio/references/task-card-template.md` | `src/gstudio_core/store.py` |
| 正式交付完成 | 明确确认后复制并校验草稿，登记 state:final 与当前正式目录，同时完成任务卡并清除下一步；拒绝合并或覆盖既有正式目标 | `AGENTS.md`、`scripts/task_gate.py` | `src/gstudio_core/store.py`、`src/gstudio_core/web/app.js` |
| 无文件成果完成 | none、system、archive、external 使用独立确认收口，不为完成伪造交付目录；delivery 必须走正式交付推广 | `AGENTS.md`、`scripts/task_gate.py` | `src/gstudio_core/store.py`、`src/gstudio_core/server.py`、`src/gstudio_core/web/app.js` |

完整系统区分操作验证与生命周期变更：preflight / finalize 的通过不等于任务完成。Core 使用读取校验及明确完成接口保留这个区别，没有复制完整系统的整理控制任务、执行租约和自动治理实现。

## 资料状态与 AI 上下文

| 规则 | Core 保留的行为 | 完整系统来源 | Core 实现 |
| --- | --- | --- | --- |
| Inbox 四标签 | 未分类、处理中、待归档、可删除；标签绑定内容指纹，只修改台账，不重命名或移动来源 | `AGENTS.md`、`scripts/gstudio_archive_inbox.py` | `src/gstudio_core/store.py`、工作区 `.gstudio/inbox.json` |
| 模型中立上下文 | 六段结构：任务、上下文、输入与真源、授权边界、成功标准、输出；基于当前所选记录，文件与外部材料不能扩大授权 | `skills/gstudio/references/shared-prompt-standard.md` | `src/gstudio_core/store.py`、`src/gstudio_core/web/app.js` |
| 通用本机执行环境 | 只读发现常见软件或手工添加，默认项来自本机确认清单；持久化只写用户私有 Core 配置，已保存摘要与未保存草稿分开 | `scripts/gstudio_executor_settings.py`、`scripts/gstudio_workbench.py` | `src/gstudio_core/executors.py`、`src/gstudio_core/web/app.js` |
| 明确复制并打开 | 用户核对上下文后可单独复制，或明确打开已保存默认软件；启动路径安全引用、不传业务提示词、用户手工粘贴发送，不改任务状态 | `scripts/gstudio_workbench_service.py` | `src/gstudio_core/server.py`、`src/gstudio_core/executors.py` |
| 整理建议与报告 | 建议区分 no_change、task_group、merge、split；保存报告只记录文字，不授权结构、完成或删除操作 | `AGENTS.md`、`scripts/gstudio_task_organization.py`、`scripts/gstudio_weekly_organization.py` | `src/gstudio_core/store.py`、工作区 `reports/` |

## 初始化后的公共系统契约

Core 将系统规则与用户数据的位置一并明确。初始化拒绝覆盖非空工作区，安装系统级 AGENTS.md、SOUL.md、空白 MEMORY.md、RESOLVER.md、WORKBENCH_DESIGN.md、任务模板、Skills 路由与初始化 Skill。公开模板不含真实记忆、私人路径或账户配置。

| 完整系统入口 | Core 对应位置 |
| --- | --- |
| `AGENTS.md`、`SOUL.md`、`MEMORY.md`、`RESOLVER.md` | `src/gstudio_core/templates/` 中的公共模板，由 `src/gstudio_core/bootstrap.py` 安装到新工作区 |
| `skills/RESOLVER.md` 与 `skills/gstudio/SKILL.md` 的启动路由职责 | 工作区 `skills/RESOLVER.md`、带版本的 `skills/manifest.json`；`gstudio-init` 负责新安装，`gstudio-core` 精简适配总入口、任务必要性、项目上下文、续接、校验与人工确认职责 |
| `skills/gstudio/references/task-card-template.md` | 工作区 `templates/task-card.md` |
| `scripts/workspace_paths.py` 与机器环境解析 | `src/gstudio_core/cli.py` 显式指定工作区；工作区 `RESOLVER.md` 使用相对位置 |
| `scripts/task_gate.py` 的执行前后数据验证职责 | `src/gstudio_core/store.py` 的读取及写入检查、`src/gstudio_core/bootstrap.py` 的契约检查、`gstudio check` |

初始化 Skill 负责建立新安装和新工作区，不取得重置已有数据或运行私人集成的权限。它不替代日常任务卡，也不复制完整系统的所有下游 Skills。

`gstudio-core` 与完整版 `gstudio` 对应的是通用职责，不是同一份文件。普通只读检索不强制建卡；同一目标调用其他 Skill 或换执行器仍继续原任务。独立维护目标使用新卡，不把原发布任务当作永久容器。Core 使用本地 `gstudio check` 与受控 Workspace / HTTP 接口落实流程，不照搬完整系统的 NAS、跨机租约、外部 MCP 或业务发布能力。

## 有意精简的差异

| 方面 | 完整系统 | Core 的公开最小范围 |
| --- | --- | --- |
| 工作位置与同步 | 共享 NAS 正本、双 Mac 运行环境、共享锁及系统同步 | 用户明确指定的本地工作区，同一工作区一个服务；没有共享盘或双机同步 |
| 项目说明与知识 | 注册类型、业务分类、能力配置；GStudio 共享项目说明正本，外部知识能力可选 | project / system 最小两类，本地 Markdown 说明；没有完整能力类型、业务分类或外部知识写回 |
| 任务检视 | 所选整理、周报与周自动治理、控制任务、逐项执行回执 | 手动选择、构造建议上下文、保存人工报告；没有周自动治理 |
| AI 执行 | 通用软件清单和专用 Agent 路由、模型及能力治理 | 六段上下文；明确确认后只打开本机已登记软件，不调用模型、不自动提交；没有私人 Agent 路由或能力授权 |
| 资料摄入 | 文件快照、外部引用、配置容量阈值及归档路由 | 界面新增 UTF-8 文字最多 1 MiB；引用仅限已索引工作区文件；没有外部来源读取或自动下载 |
| 归档流程 | NAS 来源、归档队列、项目归档后端及严格选择确认的删除流程 | v0.3.0 暂不发布归档中心或复制接口；已有文件保留，仅兼容旧任务明确输入引用 |
| 正式推广 | 将已批准草稿目录推广到正式目录，更新卡片位置与导航 | 复制校验到正式目录并完成卡片，保留草稿副本追溯；当前交付正本仍由单一 state/folder 指向正式目录 |
| 结构与修订 | 有逐项确认的合并、拆分以及正式交付重开门禁 | 可阅读任务线和准备结构建议；不执行合并拆分，不重开或改写正式交付 |
| 数据兼容 | 兼容历史卡片和既有系统登记 | 只支持公开版声明的任务类型和路径；旧 kind/bytes 输入记录有有限读取兼容，不能据此整库迁移 |

这些差异是当前最小范围，不应被描述为完整系统能力已经开源。后续增加能力时，应同时更新系统契约、可执行校验、页面行为和示例证据。

## 验证对齐的方式

使用空工作区和独立虚构示例验证：新建项目与任务、重启回读、输入引用不复制、快照损坏检测、无文件完成、正式交付确认、重要性 revision、Inbox 标签不移动来源、已退役归档接口 404 且不写文件、旧归档原样保留、六段上下文无写入，以及桌面和手机页面职责。

存储、HTTP、软件登记与初始化测试位于 `tests/`；`test_browser.py` 可选使用真实 Chromium 检查设置和复制打开边界，软件启动全部模拟。工作区 `gstudio check` 验证当前数据与初始化契约。通过检查只说明该版本满足上述公开范围，不证明与完整系统的所有功能等价。本版没有把内部系统的飞书、AList 或运行 Agent 故障清单复制到公开设置页。
