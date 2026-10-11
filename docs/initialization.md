# 初始化系统 Skill

`gstudio-init` 随 Core 安装，也作为独立的 Skill ZIP 发布。它建立可以继续使用的系统工作区，不只是载入展示网页。

## 安装包包含什么

- `SKILL.md`：当前选择复用、逐项补齐缺项、检查与交接流程。
- `agents/openai.yaml`：可识别的名称、说明与默认提示词。
- `scripts/bootstrap.py`：标准库编排脚本，支持独立环境、新工作区、真实保存流程验证和安装收据。
- 独立发行 ZIP 的 `assets/`：相同版本 Core wheel，包含代码、虚构示例、规则与模板；依赖 PyYAML 仍需要网络或缓存。
- `LICENSE`：MIT；Core 内字体保留独立 OFL 许可证。

可以把解压后的 `gstudio-init` 放进 Agent 使用的 Skills 目录，再说“使用 gstudio-init 安装 GStudio Core”。不同 Agent 的 Skill 目录由其自身约定决定，不替用户修改全局配置。

## 引导与执行

Skill 先确定真实 Python 版本和系统，沿用用户已给出的选择，只询问缺少的关键项目：应用目录、数据目录、示例或空白模式。名字默认 GStudio，端口默认 8783。两个目录必须为空或不存在且互不包含。

脚本可独立运行：

```text
python3 /path/to/gstudio-init/scripts/bootstrap.py --app-dir /path/to/app --workspace /path/to/data --mode empty --name GStudio --port 8783
```

使用本地代码或 wheel 时，加 `--source /path/to/source-or-wheel`。没有附带 wheel 时，下载固定的官方 GitHub v0.2.0 发行包。脚本以参数数组调用命令，不执行用户文本拼接的 shell 命令。

工作区内会建立 `AGENTS.md`、`SOUL.md`、空白 `MEMORY.md`、`RESOLVER.md`、`WORKBENCH_DESIGN.md`、任务模板和 Skill 登记。只安装 `gstudio-init` 1.0.2 与日常入口 `gstudio-core` 1.2.0，manifest 记录对应版本，Resolver 路由首次安装和日常工作。`gstudio-core` 先判断是否需要任务卡，读取项目说明并继续原任务，按实际需要调用用户已有的业务 Skill；Core 不安装私人依赖。`AGENTS.md` 定义规则，Skill 引用规则，模板及 Resolver 各负责创建和位置，不引入第二套政策。

空白模式没有项目、任务和业务文件。示例模式包含两个虚构项目、八项任务、十八个输入与交付等文件、Inbox 四种状态和两份检视报告。系统工作区可在安装后新建，不虚构一个已经运行的私人系统。

## 安装验证与收据

复用已有 Core 时，为新工作区构造独立的 check / serve 命令，不复用旧安装收据里的目录。

安装先运行 `gstudio check`，再在成功后清理、失败保留的临时工作区创建项目、任务、输入、草稿与正式交付，验证无文件完成、引用不复制及本机 HTTP 健康状态。临时验证不往用户空白工作区写入测试任务。

应用目录的 `installation.json` 记录阶段、成功或失败、工作区、实际启动及检查参数。脚本结束时服务没有常驻运行；Skill 随后按收据在前台启动并检查页面。停止时对原服务进程按 Ctrl+C；重启同一命令会读回原数据。

非空目录、路径重叠或端口占用在安装前拒绝。中途失败保留现场与收据，不自动删除或重试覆盖。没有后台守护、模型认证、NAS、业务数据导入或已有工作区迁移。

升级应用不会自动替换已有工作区内的规则和 Skill。不要把 `init` 当升级命令；如需采用新版契约，先备份并逐项核对本地修改，按明确确认的范围同步。见 [v0.2.0 更新说明](update-0.2.0.md)。本机软件仍由用户在设置页自行确认；安装不会自动查找、登记、保存或打开 AI 软件。

## 开发验收

`tests/test_bootstrap.py` 检查系统入口、空白与示例数据，以及禁止覆盖、目录重叠、端口占用和缺失契约。真实发行前另用独立新环境执行脚本，从打包的 wheel 初始化并回读，防止源码可运行而安装包漏资源。
