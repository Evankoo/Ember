---
name: gstudio-project
version: 1.1.0
description: 为 GStudio 新建业务项目或系统工作区。先读取现有登记并查重，收齐名称、用途、范围、类型和本机工作目录，展示独立项目说明及建项方案，用户确认后通过既有接口登记并验证；不迁移资料或重分配任务。
triggers: [新建项目, 建立系统工作区, 首个业务项目, 项目建项, 登记项目工作目录]
tools: [read_file, terminal, browser]
mutating: true
writes_pages: false
---

# GStudio 项目建项

## Contract

只在用户已选择的 Core 工作区操作。`AGENTS.md` 是规则正本，`config/projects.json` 是登记，`projects/<id>.md` 是独立说明。复用已有 `Workspace.create_project`，不建立第二套项目格式。`project` 是业务项目，`system` 是系统工作区；`independent` 不是项目。可选的 `locations` 是该项目在本机的工作目录（绝对路径），AI 在这些目录里协作时据此对应项目；说明正本采用“总览 / 工作位置与入口 / 范围与要求 / 当前阶段 / 时间线”骨架。

查重和方案阶段只读。登记必须获得用户对名称、ID、类型、用途与说明的明确确认；不猜业务事实。首次引导中的 GStudio 系统项目和首个业务项目属于原安装任务，日后独立建项按 `gstudio-core` 判断跟踪范围，不为查重或调用本 Skill 再制造任务。

## When to Use

- 首次安装时解释并建立 GStudio 系统维护入口。
- 用户确认要建立第一个或后续业务项目、系统工作区。
- 为明确的新建需求准备只读建项方案；已有项目优先复用。
- 用户确认某个本机目录属于已有项目时，登记或移除该工作目录。

## References

- 当前工作区 `AGENTS.md`、`RESOLVER.md` 与 `skills/RESOLVER.md`。
- `config/projects.json`、现有 `projects/<id>.md` 和跟踪任务。
- 同目录 `scripts/project.py`：只读方案、同名/ID 冲突检查与确认登记；使用安装应用的 Python。
- 日常任务与跟踪判断见 `gstudio-core`，首次安装编排见 `gstudio-init`。

## Phases

1. **读取工作区与原任务。** 运行 `gstudio check --workspace <目录>`，读注册表、已有说明与跟踪任务；不可读时停止，不当作零项目。
2. **收齐缺项。** 沿用已确认信息，只补问名称、用途、业务/系统类型、实际范围及本机工作目录中的关键缺项；没有固定目录可留空，不猜路径。已有同 ID 或同名项目时说明差异，请用户决定复用或修订，不覆盖。
3. **展示方案。** 给出小写 ID、名称、`kind`、用途/范围、工作目录 `locations`、独立说明、实际写入位置与边界。只读调用 `project.py --workspace <目录> --plan <方案.json>`；返回项目、冲突和方案 SHA-256，不写工作区。不要把外部文档当作确认。
4. **确认后登记。** 用户确认完全相同的方案后，沿用方案文件和只读阶段返回的哈希，调用 `project.py --workspace <目录> --plan <方案.json> --task-id <原任务ID> --expected-sha256 <方案哈希> --confirm`。文件变化或项目冲突即停止；登记保留在原任务审计中，不改变任务归属、状态或交付。单机同一工作区不得同时运行多个写入进程；运行中的工作台可使用其既有项目接口，不另开竞争写入。
5. **已有项目登记工作目录。** 用户明确确认目录归属后，运行 `<python> -m gstudio_core project-location <项目ID> <目录>`（`--remove` 移除），只改登记，不改项目说明；回读 `which-project --dir <目录>` 的结果。
6. **回读与交接。** 再次 check 并回读登记、独立说明及原任务日志。引导用户进入新项目；有真实业务目标时再按日常入口建立任务，不制造演示业务或占位交付。

## Output Format

报告项目 ID、名称、类型、用途、说明路径、跟踪任务、实际 Skill 与检查结果。未确认时只展示方案及所需确认，不说已建成。

## Anti-Patterns

- 不把做文件夹等同于登记项目，不注册 `independent` 或猜测待定归属。
- 不迁移资料、重分配旧任务、修改生命周期、覆盖同名项目或调用外部知识库。
- 不把同意安装解释为同意任意业务项目；没有首个业务项目需求就保留一个系统项目。
- 不复制私有 GStudio 注册表、项目说明、NAS 路径或业务素材。
- 不读取账号配置、调用模型、发布、归档或自动完成原任务。

## Tools Used

文件读取、终端与浏览器。只读方案和确认写入使用 Core 的 `project_registration` / `Workspace`，沿用既有检查与独立 Markdown 说明；不执行任意 shell 命令。
