# 分步初始化与安装首任务

`gstudio-init` 1.2.0 建立新安装；`gstudio-project` 1.0.0 组织建项；`gstudio-core` 1.4.0 接管日常工作。三项 Skill 同时放在初始 ZIP 和 wheel 中，并登记到新工作区。

## 初始包与使用方式

下载官方 v0.4.0 的 `gstudio-init-1.2.0.zip`，解压后有三个同级目录：`gstudio-init/`、`gstudio-core/`、`gstudio-project/`。将它们放到所用 Agent 的 Skills 目录，先调用 `gstudio-init`。客户端的 Skill 发现规则由客户端自己管理；安装不自动适配四种 AI 客户端的全局配置，也不认证模型。

`gstudio-init` 中的标准库脚本编排安装，`assets/` 附带 `gstudio_core-0.4.0-py3-none-any.whl`。wheel 包含 Core、三项 Skill、系统规则、模板、页面及虚构示例。PyYAML 仍需要网络或缓存；源码及 Skill 为 MIT，字体保留 OFL 许可证。

## 九步引导

1. **确认环境与选择。** 检查实际 Python ≥3.10、macOS / Linux；复用已经给出的选择，只问缺少的程序目录、工作区目录及空白 / 示例模式。默认名称 GStudio、端口 8783。两个目录必须为空或不存在且互不包含；说明会保留真实安装任务，再取得安装确认。
2. **说明并建立目录。** 程序环境放在应用目录，任务与资料放在工作区。先展示用途，确认后创建，不把工作区放进程序目录。
3. **安装程序与契约。** 建立独立 `.venv`，安装 wheel，建立规则、项目注册位置、任务目录、输入与交付目录、三项 Skill 及 manifest / Resolver。
4. **建立系统项目和首任务。** 查重后登记 `id:gstudio / name:GStudio / kind:system`，专门管理新用户这台电脑上的 Core 安装与维护。创建真实 `GStudio初始化验收` 任务，记录实际 executor 与调用的 Skill；已确认目录等选择保存为输入快照。此时不预建空交付目录。
5. **回读登记。** 核对项目说明、首任务、输入来源 / 摘要、三项 Skill 版本及路由。系统项目不是私人生产系统的复制，不导入账号或历史。
6. **隔离测试并写回。** 先检查真实工作区，再在拥有的临时工作区验证新建项目和任务、输入、草稿、正式交付、无文件完成、引用与本机 HTTP 健康。模拟测试任务不留在用户工作区。成功清理临时测试目录，失败保留；进度、实际错误及验收草稿写回同一首任务。
7. **启动并检查工作台。** 按收据实际参数在前台启动，检查健康接口、五个页面、系统项目、首任务和 Skill 登记。分清“安装就绪”和“当前服务正在运行”；停止为服务进程 `Ctrl+C`，再次用同一命令回读数据。
8. **可选建立第一个业务项目。** 问用户实际用途、名称与边界；不需要时跳过，不虚构项目。调用 `gstudio-project` 只读查重并展示完整方案，用户确认相同方案后登记 `config/projects.json` 和 `projects/<id>.md`，回读。此步骤仍用安装跟踪任务；后续独立业务目标另建业务任务。
9. **人工验收与交接。** 展示实际证据与下一步。技术测试通过仍是 `active` 任务及草稿；只有用户确认验收和正式交付后才走受控推广完成。接着交给 `gstudio-core`，不把首任务变成全部维护工作的永久容器。

## 目录与首次结果

```text
app/                         程序目录
  .venv/                     独立 Python 环境
  installation.json          真实安装阶段、收据及 check / serve 参数
data/                        工作区目录
  AGENTS.md SOUL.md MEMORY.md RESOLVER.md WORKBENCH_DESIGN.md
  .agents/skills/             三项 Skill 正文与脚本
  skills/manifest.json        版本登记与路由
  config/projects.json        项目与系统注册
  projects/gstudio.md         新用户的系统项目说明
  tasks/active/<task_id>.md   本次真实安装任务
  inputs/<task_id>/           安装选择快照
  delivery/draft/<task_id>/   出现真实验收或失败说明后才创建
```

引导的空白模式没有虚构业务数据，完成技术验证后保留 **一系统 / 一真实安装任务**。示例模式保留原有两项目 / 八项虚构任务，再添加真实系统及首任务，合计 **三项目 / 九任务**。底层 `gstudio init` 仍是零项目 / 零任务结构（示例为二 / 八），不会自动启动完整引导。

## 命令与收据

使用检查通过的实际 Python 路径运行：

```text
python3 /path/to/gstudio-init/scripts/bootstrap.py --app-dir /path/to/app --workspace /path/to/data --mode empty --name GStudio --port 8783 --executor opencode
```

`--executor` 填真实调用工具，未知用 `manual`，不猜模型。`--source` 可指定本地源码或 wheel；没有附带 wheel 时只下载固定官方 v0.4.0 包。命令使用参数数组，不执行拼接的用户 shell 文本。

`installation.json` 记录版本、状态、阶段、目录、首任务、验收草稿、检查结果和真实 check / startup 参数。`ready` 要求契约、保存流程与 HTTP 三项技术检查及成功清理隔离测试；不意味着前台服务已经启动或用户已经验收。写回失败会明确失败并保留现场，不把“生成了文件”当作验收成功。

中途失败不覆盖或重新初始化现场。建立首任务之后的失败写回原卡；若程序尚未安装或任务尚未建立，则只有应用收据，不能假报任务已经存在。重复创建首系统 / 首任务、修改过的示例、额外文件、篡改输入或外工作区收据都被拒绝；人工改过的交付不会被脚本覆盖。

建项脚本先只读输出方案和 SHA-256；登记必须提供未完成跟踪任务、`--confirm` 和原方案摘要。重复 ID / 名称、方案变化或当前服务占用会停止；服务运行时可通过既有 HTTP 建项接口并在原任务登记实际 Skill 和日志，不启动第二个写入者。

## 已有安装与安全边界

复用已安装的相同版本 Core 只能对确认的新工作区建立引导；重新构造这个工作区的 check / serve 参数及收据，不复用旧收据目录。已有数据、旧规则和 Skill 不自动升级；先备份并确认单独变更范围，不把 `init` 当作升级命令。

安装不配置后台守护、NAS、模型认证、Mem0 或业务数据，不查找、登记或打开 AI 软件，也不恢复归档中心。前台服务只监听回环地址。详见 [v0.4.0 变化](update-0.4.0.md)。

## 验证

`test_bootstrap.py` 验证完整编排成功和失败写回；`test_onboarding.py` 验证首任务、收据、隔离边界、查重、确认方案及写锁；真实 Chromium 验证首任务和三项 Skill 的桌面 / 手机显示。发布还必须使用打包的三 Skill ZIP 和 wheel 做空白、示例新安装与公开下载后的回读，不仅依赖源码测试。
