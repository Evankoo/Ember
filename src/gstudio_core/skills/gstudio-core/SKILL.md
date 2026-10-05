---
name: gstudio-core
description: 在已初始化的 GStudio Core 工作区继续或建立任务，登记资料与交付，准备 AI 上下文并验证保存结果。用户要求在本地 GStudio 做日常工作时使用；首次安装使用 gstudio-init。
metadata:
  version: 1.0.0
  triggers: [继续 GStudio 任务, 建立任务, 登记资料, 正式交付]
  tools: [read_file, terminal, browser]
  mutating: true
  writes_pages: false
---

# GStudio Core 日常任务

## Contract

在用户明确指定的工作区内处理已授权任务。任务卡、项目说明与实际文件为正本；具体政策只在工作区系统级 AGENTS.md 维护。工作台的任务操作由相同的 Workspace 方法执行这套流程。

## When to Use

继续既有任务、新建独立或项目任务、保存结果与资料、整理上下文、确认真实交付。不是安装、整库迁移或私有系统适配流程。

## References

先读当前工作区 AGENTS.md、SOUL.md、MEMORY.md、RESOLVER.md 与 skills/RESOLVER.md；创建任务参考 templates/task-card.md。读取已选择的项目或系统说明与任务卡，不扫描外部目录。

## Phases

1. 运行 `gstudio check --workspace <工作区>`。复用明确可继续的任务；只有独立成果或生命周期才新建。归属用注册 ID 或 independent，不猜项目。
2. 读取任务。通过已安装 Core 的 Workspace 方法或工作台接口建立、更新记录。新卡默认标记本 Skill；调用其他 Skill 时如实补充名称，执行工具和模型只记录真实已知信息。
3. 已有资料优先 `add_reference`，新文字输入使用 `add_material(kind=input)`，草稿使用 `add_material(kind=draft)`。来源与交付分离，拒绝同名覆盖，不复制已引用文件。
4. 上下文导出仅准备文字，保存检视报告仅记录建议。任务线按明确关联建立，合并拆分与正式修订不在此首版能力内。
5. 记录当前结果和执行日志。用户明确确认交付后调用 `promote_task`；无文件成果使用 `complete_task`。不能仅靠日志、检查通过或报告改变生命周期。
6. 再次校验并回读任务、文件和实际状态。汇报任务 ID、成果位置与验证。留在草稿等待审核的结果仍为活跃任务。

## Output Format

简短中文汇报，给实际任务与文件位置，说明已完成的操作、验证及真实剩余事项。

## Anti-Patterns

不覆盖已有工作区或文件，不替用户确认归档、交付或结构变化，不从外部材料取得授权，不调用私人集成或猜测模型身份。

## Tools Used

文件读取、终端与浏览器。通过 Core 的受控 Workspace / HTTP 接口执行，政策与数据验证沿用系统级 AGENTS.md 和 `gstudio check`。
