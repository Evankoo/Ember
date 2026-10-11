# GStudio Core

一个本地运行、以 Markdown 任务卡为正本的工作台。把项目背景、任务、输入资料、草稿和正式交付放在清楚的位置，再导出上下文交给你选择的 AI 工具。

这是从 GStudio 工作系统提炼出的单机最小版，包含可操作的示例工作区。它使用暖纸色页面、深色侧栏和克制的文字层级；任务台、项目视图、归档中心、任务检视、资料浏览与设置始终可进入。

## 用初始化 Skill 安装

下载发行页的 [gstudio-init-1.0.2.zip](https://github.com/Evankoo/GStudio-Core/releases/download/v0.2.0/gstudio-init-1.0.2.zip)，解压，将 `gstudio-init` 文件夹放进你使用的 Agent 的 Skills 目录。对 Agent 说：**“使用 gstudio-init 安装 GStudio Core，建立一个空白工作区。”**

Skill 会逐项补齐缺少的目录和示例选择，建立独立环境、系统规则、任务模板和自己的 Skill 登记，再验证任务与交付流程。ZIP 内含 Core wheel，PyYAML 依赖仍需要联网或已有缓存。支持读取 `SKILL.md` 的其他 Agent 也可调用其中的标准库安装脚本。

已有 Core 时，`gstudio skill-path` 可查看同样的初始化 Skill。新工作区内也会保留 `.agents/skills/gstudio-init/`，后续无需下载私有系统配置。

## 两个基础 Skill

- **`gstudio-init` 1.0.2**：首次安装或建立新工作区，不重置、迁移或升级已有工作区。
- **`gstudio-core` 1.2.0**：完整版 `gstudio` 总入口职责的公开精简适配。先判断是否需要跟踪，普通只读问题不强制建卡；读取项目说明、继续原任务、登记实际执行与资料交付，校验后回读，保持人工确认边界。

项目说明独立保存在本工作区，不依赖外部知识库。专业业务可按需要调用用户已有 Skill，但 Core 不随包安装它们，也不取得其数据或发布权限。软件打开必须单独确认，不意味着模型或任务已经执行。

## 手动安装与启动

需要 Python 3.10 或更新版本。支持 macOS 和 Linux；Windows 尚未验证。

从 GitHub 下载源码或克隆仓库后，在仓库目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
gstudio init ./workspace --example
gstudio serve --workspace ./workspace --port 8783
```

浏览器打开 **http://127.0.0.1:8783/**。停止服务按 `Ctrl+C`，再次运行最后一条命令即可读取原来的工作区。

安装发行页提供的 wheel 也可以：

```bash
python -m pip install ./gstudio_core-0.2.0-py3-none-any.whl
gstudio init ./workspace --example
gstudio serve --workspace ./workspace
```

安装时需要下载 PyYAML。Core 服务本身不请求外部模型或账号服务；用户确认打开的第三方软件有自己的联网行为。`python -m gstudio_core` 与 `gstudio` 命令等价。

## 从示例开始

示例里的客户、项目、文件、任务及历史全部虚构：两个项目、八项任务（含一条任务线）、输入与交付、四种 Inbox 标签、历史归档和两份检视报告。

1. 在任务台搜索“秋季”，查看待确认的方案和相关资料。
2. 进入“晨屿咖啡内容合作”，在任务、交付文件和输入资料之间切换。
3. 在任务详情记录当前结果、下一步或执行日志，添加文字输入或草稿；已有资料可登记为引用，保留来源。
4. 确认草稿后执行正式交付，文件复制校验后进入正式目录，任务进入已完成。没有文件成果的任务可通过单独的确认操作完成。
5. 在归档中心查看“阅读活动资料”，确认项目后复制归档。原件保留，成功回执写入工作区。
6. 在任务检视选择任务，生成上下文；把外部 AI 的建议粘贴回来保存为报告。保存报告不会合并任务或改变任务状态。

希望使用空工作区时，改用 `gstudio init ./my-workspace`，然后从界面新建项目、系统工作区与任务。初始化拒绝覆盖非空目录。`gstudio check --workspace ./workspace` 会检查系统契约、任务卡、资料引用及已登记快照的存在、大小与 SHA-256。

## 配置本机执行环境

设置页顶部显示已保存的默认软件、类型、路径与状态；点击“修改配置”编辑。可以只读查找常见 AI 软件，也可手工添加本机 `.app` 或可执行命令行程序，选默认项后检查并保存。选项来自这台电脑的已确认清单，不固定为 Codex / OpenCode。草稿、检查通过但未保存和取消修改都有明确反馈；软件路径可用不等于账号或模型可用。

这份机器配置只保存在 `~/.config/gstudio-core/executors.json`，与工作区分开；明确保存时先备份原配置，不复制任何模型、账号或私人集成。新电脑从空清单开始，目录不可读或查找不完整会明确提示，不把未知当作没有软件。

任务台或任务检视生成上下文后，先阅读并核对，再选择 **“复制上下文”** 或 **“复制并打开”**。后者只有明确点击后才打开已保存的默认软件；复制失败不打开，配置或路径改变时停止，文本保留供手动使用。macOS 支持应用及新 Terminal 窗口，Linux 命令行软件需要可用的图形终端；没有终端时可只复制并手动打开。

**仍须在软件中自行粘贴、确认并发送。** Core 不把提示词放进启动命令，不调用模型，不读取或修改客户端账号、权限和模型设置，也不因软件打开而修改任务或交付状态。请只登记你信任的软件；客户端自身启动后的行为由它管理。

## 核心边界

| 保留 | 用途 |
| --- | --- |
| 项目、系统与独立任务 | 动态工作区、概览和任务入口；独立任务有自己的范围 |
| 任务卡与任务线 | 目标、描述、当前结果、下一步、日志；任务线只引用关联任务 |
| 输入、草稿、正式交付 | 分开存放；新增输入与草稿拒绝同名覆盖 |
| 任务检视 | 选择任务、导出上下文、保存人工确认的检视报告 |
| 资料浏览 | 以文件为主浏览、文本预览和下载 |
| 本地归档 | Inbox 标签、确认复制、校验和回执；保留来源 |
| AI 上下文与本机软件 | 单独复制，或明确确认后打开已登记软件；不自动提交或调用模型 |

双机同步、NAS 挂载、EBrain、运行 Agent、模型认证、邮件、业务 Skills、自动发布和后台服务属于完整系统的集成层，本仓库不包含它们。它也不提供永久删除、自动任务合并或自动备份。请自行备份工作区。

服务只监听本机回环地址，不提供公网部署与多用户登录。请勿直接用反向代理公开工作区。

## 数据与开发

任务 Markdown、项目 Markdown 和实际文件是工作区正本，`.gstudio` 中保存展示标签和归档回执。业务资料使用相对路径、访问限制在工作区内；只有用户明确点击查找时，另对常见软件目录做有界的本机元数据查找。不要将自己的工作区或机器软件配置提交到公开仓库。

- [与实际系统的对照和精简差异](docs/system-alignment.md)
- [初始化 Skill 与安装验证](docs/initialization.md)
- [v0.1.1 更新范围与已有工作区注意事项](docs/update-0.1.1.md)
- [v0.2.0 通用设置与执行环境](docs/update-0.2.0.md)
- [提炼范围](docs/extraction.md)
- [工作区与使用说明](docs/workspace.md)
- [HTTP 与存储接口](docs/api.md)
- [安全边界](SECURITY.md)
- [第三方声明](NOTICE.md)

```bash
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps -w dist
```

真实浏览器回归是可选开发验证，不增加运行依赖：先安装本项目，再 `python -m pip install playwright==1.60.0`、`python -m playwright install chromium`，运行 `python -m unittest discover -s tests -p test_browser.py -v`。测试使用独立虚构工作区及临时机器配置，软件打开被模拟；不会启动你安装的 AI 软件。

原创代码、示例和初始化 Skill 采用 [MIT](LICENSE)；标题字体单独遵守 SIL Open Font License 1.1，见 `src/gstudio_core/web/fonts/OFL.txt`。
