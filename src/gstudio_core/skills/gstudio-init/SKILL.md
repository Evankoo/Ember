---
name: gstudio-init
version: 1.4.0
description: 一步一步引导首次安装 GStudio，确认程序与数据目录，建立 GStudio 系统项目和真实安装首任务，登记三项基础 Skill，在隔离工作区验证任务与交付并把结果写回，登记本机默认工作区并经确认把日常 Skill 装到 AI 工具的全局目录，启动工作台后引导可选的首个业务项目和人工验收。不重置、迁移或升级已有工作区。
triggers: [初始化 GStudio, 安装 GStudio, 安装 GStudio Core, 建立新工作区, 首次使用 GStudio]
tools: [read_file, terminal, browser]
mutating: true
writes_pages: false
---

# GStudio 首次安装引导

## Contract

输入是用户已确认的首次安装范围、程序目录、数据目录、名称及模式。输出是独立应用环境、新工作区、**GStudio 系统项目 + 一项真实安装任务**、三项基础 Skill、实际检查证据和待人工验收的草稿。安装任务属于本机的 GStudio 系统项目，不是开发者的私有系统或示例业务。

每一阶段简短说明“正在做什么、验证了什么、下一步是什么”，不要只扔出一串命令。沿用当前对话已确认的信息，只补问影响结果的关键缺项，一次一项；已经授权的新目录安装不重复索取许可。默认名称 GStudio、端口 8783、空白业务模式。确认目录时同时解释将建立系统项目和首任务，业务建项另行确认。

空白业务模式完成后是一个系统项目和一项真实安装任务，没有虚构业务。示例模式另外包含完全虚构的两个项目、八项任务，最终是三个项目、九项任务。技术测试一律放在隔离工作区，成功后仅清理脚本自己创建的测试目录，失败现场保留。通过测试不等于用户接受，不自动正式交付或完成任务。

## When to Use

- 新电脑首次安装本机 GStudio，并带领用户走完首次使用。
- 使用本版已安装的 GStudio 在全新目录建立独立工作区；不改写旧工作区。
- 验证新安装的规则、项目、首任务、资料、交付和本机工作台。

## References

- 先读同目录 `scripts/bootstrap.py`，使用标准库编排安装和隔离验证。
- 安装后读工作区 `AGENTS.md`、`SOUL.md`、`MEMORY.md`、`RESOLVER.md`、`skills/RESOLVER.md` 与 `templates/task-card.md`；系统级 AGENTS.md 是规则正本。
- 三项 Skill 的唯一正文在 `.agents/skills/gstudio-init`、`gstudio-core`、`gstudio-project`，`skills/manifest.json` 及 Resolver 登记它们。
- 首个业务项目使用 `gstudio-project`，日常任务交给 `gstudio-core`；不要复制私有系统建项规范。

## Phases

### 1. 确认环境和安装选择

确认 macOS / Linux 与真实 Python 3.10+ 解释器，不能假定系统 `python3` 合格。沿用已给出的目录、名称和模式；只问缺项。用户未给目录时提出两个清楚、互不包含的新目录，先确认；非空、符号链接、包含关系或端口冲突时停止，不删除现场。

### 2. 解释并建立文件夹

说明程序目录保存 `.venv` 与安装收据，工作区保存规则、项目、任务、输入、草稿和正式交付。空业务模式不创建示例客户；安装过程会登记 `gstudio` / GStudio / `kind:system` 和“GStudio初始化验收”首任务。解释用户同意的是本次安装，不包含任意业务项目、软件登录或资料迁移。

### 3. 安装独立环境

使用实际解释器和路径，不猜执行器或模型：

```text
<真实Python> <Skill目录>/scripts/bootstrap.py --app-dir <程序目录> --workspace <数据目录> --mode empty|example --name <名称> --port 8783 --executor <实际调用工具>
```

实际调用工具可为 opencode、codex、workbuddy、claude-code 等；未知则 manual，不能填模型名。独立初始包含 `gstudio-init`、`gstudio-core`、`gstudio-project` 三个 Skill 文件夹，init 内含 `assets/gstudio_core-0.6.0-py3-none-any.whl`；没有 wheel 时用固定 v0.6.0 地址。开发可传 `--source`。PyYAML 依赖仍须网络或缓存，不声称完全离线。

### 4. 建立系统项目和真实首任务

脚本通过既有项目接口登记独立 `projects/gstudio.md` 和注册表，再创建一个普通活跃安装任务。它记录目标、当前阶段、后续人工验收，以及 `inputs/<task_id>/安装计划.json` 的来源、用途和指纹。无成果时不造交付目录。失败不另建“重试任务”，不重置或覆盖部分安装；保留原收据和任务，明确修复范围。

### 5. 回读三项基础 Skill

检查工作区规则、任务模板、三项 Skill 正文、版本、脚本、manifest 和 Resolver。安装到工作区的 Skill 不等于自动加入所有客户端：若当前工具不发现 `.agents/skills`，让用户按该客户端规则导入或显式读取，不改其账号、权限或模型配置。

### 6. 隔离测试并写回首任务

脚本先 check 真实工作区，再在临时工作区创建测试项目、任务、输入和交付，验证正式交付复制/指纹、无文件完成、引用不复制及本机 HTTP 健康检查。成功与失败都写回同一安装任务，成果为“安装验收.md”或“安装失败说明.md”草稿。回读 `<程序目录>/installation.json` 的阶段、检查、首任务路径和报告路径，再次 check；写回失败明确报告，不能只看命令退出码。

### 7. 启动并带用户看工作台

按收据 `startup_argv` 前台启动，读取 `/api/health` 并实际核对任务台、项目视图、任务检视、资料浏览、设置五个入口。带用户进入 GStudio 系统项目、安装首任务及验收草稿，让用户看清“任务如何留下过程”。无法保持运行就给出命令和未完成项，不声称已启动；停止用该服务的 Ctrl+C，不安装后台守护程序。

已有本版 GStudio 只建新工作区时，先用其 `init <全新目录>`，再用同一解释器运行 `-m gstudio_core.onboarding begin --workspace <新目录> --app-dir <实际应用目录> --mode empty|example --executor <实际工具>`，在原任务继续上述检查与隔离测试，并用 `record_installation` / `onboarding record` 写回**本次真实证据**。这个分支不重装依赖、不复用旧收据路径、不覆盖旧收据，不能跳过检查或填造 ready；低层 `init` 本身只建骨架。

### 8. 让任意目录的 AI 都能接着做

向用户说明：以后在别的项目目录里和 AI 协作时，AI 要能找到这个工作区，才能续接或记录任务。

- **默认工作区。** 安装脚本已自动执行 `gstudio use`，把工作区和程序 Python 记在 `~/.config/gstudio-core/workspace.json`；回读收据 `default_workspace`。若为 `kept-existing`，说明本机已有另一个默认工作区，向用户展示两者，只有用户明确选择切换才运行 `<程序Python> -m gstudio_core use <新工作区> --replace`。
- **全局日常 Skill。** 工作区内的 Skill 只在工作区目录里生效。确定当前 AI 工具的用户级 Skills 目录（以该工具文档为准，例如 Claude Code `~/.claude/skills`、Codex `~/.agents/skills`、OpenCode `~/.config/opencode/skills`），说明将写入 `<目录>/gstudio-core/`，取得用户确认后运行 `<程序Python> -m gstudio_core install-skill --target <目录>`。结果 `unchanged` 表示已是同一版本，`upgraded` 表示识别为官方旧版本并已替换；内容被本地改过的副本会停止，不覆盖，请用户先比较。装过的目录会被记住，以后升级程序后运行 `<程序Python> -m gstudio_core install-skill`（不带参数）即可全部更新。用户使用多个 AI 工具时逐个确认。
- **不需要 MCP。** 日常 Skill 通过本机文件和命令工作，能读写本机文件的 AI 工具都可以使用；不安装 MCP、插件或修改客户端账号、权限和模型设置。

完成后用一句话验证：在工作区以外的目录让 AI 运行 `<程序Python> -m gstudio_core where`，能显示该工作区即为成功。

### 9. 引导首个业务项目（可跳过）

问用户现在是否有具体业务需要。没有就停在系统项目，不猜分类或造“我的项目”。有的话，读取 `gstudio-project`，收齐名称、用途、范围、project/system 类型与本机工作目录，查重并展示完整方案；得到明确确认后登记、回读和 check。本次首个项目记在原安装任务日志，不改其归属；以后真实业务目标另按 `gstudio-core` 判断是否建任务。

### 10. 人工验收和交接

分别说明已安装、技术检查通过、工作台当前运行、首个业务项目是否已建、人工验收是否完成。只有用户明确接受安装成果并确认正式交付后，才通过既有 promotion 接口完成首任务；否则保持 active + draft。后续同一安装问题继续首任务，有独立目标的系统维护另建卡，不把它变成永久发布容器。

设置页默认软件配置是可选后续步骤，初始化不自动登记或启动 AI 客户端；路径可用不等于登录/模型可用。上下文单独复制，明确确认打开也不自动粘贴或发送。

## Output Format

简短中文阶段总结：实际程序/数据目录、GStudio 系统项目和首任务位置、三项 Skill、本机默认工作区与全局日常 Skill 的安装状态、安装收据、验收草稿、真实检查与当前运行状态、启动/停止方法、业务项目及待人工确认项。任务尚未验收就写明，不把程序安装成功等同于完成整个首次使用。

## Anti-Patterns

- 不覆盖、重置或迁移已有工作区，不删除失败现场或用户文件。
- 不把模拟测试任务留在真实空业务工作区，不自动创建虚构业务项目。
- 不读取私有 GStudio、NAS、真实历史任务或认证配置作为模板。
- 不安装执行器、插件、MCP、凭据、邮件、守护程序或公网监听，不自动运行 AI；全局日常 Skill 只在用户确认后写入，不覆盖已有不同副本。
- 不用测试通过代替人工验收，不制造占位交付或替用户正式交付、完成任务。
- 不恢复已撤下的归档模块，不把安装授权当作任意建项或资料迁移授权。

## Tools Used

文件读取、终端与浏览器。安装使用参数数组启动子进程；首任务和结果使用 `onboarding` 与既有 `Workspace`，建项使用 `gstudio-project` 的既有受控接口，不拼接任意 shell 命令。
