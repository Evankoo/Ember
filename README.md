# GStudio Core

一个本地运行、以 Markdown 任务卡为正本的工作台。把项目背景、任务、输入资料、草稿和正式交付放在清楚的位置，再导出上下文交给你选择的 AI 工具。

这是从 GStudio 工作系统提炼出的单机最小版，包含可操作的示例工作区。它使用暖纸色页面、深色侧栏和克制的文字层级；任务台、项目视图、归档中心、任务检视、资料浏览与设置始终可进入。

## 用初始化 Skill 安装

下载发行页的 [gstudio-init-1.0.0.zip](https://github.com/Evankoo/GStudio-Core/releases/download/v0.1.0/gstudio-init-1.0.0.zip)，解压，将 `gstudio-init` 文件夹放进你使用的 Agent 的 Skills 目录。对 Agent 说：**“使用 gstudio-init 安装 GStudio Core，建立一个空白工作区。”**

Skill 会逐项补齐缺少的目录和示例选择，建立独立环境、系统规则、任务模板和自己的 Skill 登记，再验证任务与交付流程。ZIP 内含 Core wheel，PyYAML 依赖仍需要联网或已有缓存。支持读取 `SKILL.md` 的其他 Agent 也可调用其中的标准库安装脚本。

已有 Core 时，`gstudio skill-path` 可查看同样的初始化 Skill。新工作区内也会保留 `.agents/skills/gstudio-init/`，后续无需下载私有系统配置。

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
python -m pip install ./gstudio_core-0.1.0-py3-none-any.whl
gstudio init ./workspace --example
gstudio serve --workspace ./workspace
```

安装时需要下载 PyYAML。服务启动后不请求外部网络。`python -m gstudio_core` 与 `gstudio` 命令等价。

## 从示例开始

示例里的客户、项目、文件、任务及历史全部虚构：两个项目、八项任务（含一条任务线）、输入与交付、四种 Inbox 标签、历史归档和两份检视报告。

1. 在任务台搜索“秋季”，查看待确认的方案和相关资料。
2. 进入“晨屿咖啡内容合作”，在任务、交付文件和输入资料之间切换。
3. 在任务详情记录当前结果、下一步或执行日志，添加文字输入或草稿；已有资料可登记为引用，保留来源。
4. 确认草稿后执行正式交付，文件复制校验后进入正式目录，任务进入已完成。没有文件成果的任务可通过单独的确认操作完成。
5. 在归档中心查看“阅读活动资料”，确认项目后复制归档。原件保留，成功回执写入工作区。
6. 在任务检视选择任务，生成上下文；把外部 AI 的建议粘贴回来保存为报告。保存报告不会合并任务或改变任务状态。

希望使用空工作区时，改用 `gstudio init ./my-workspace`，然后从界面新建项目、系统工作区与任务。初始化拒绝覆盖非空目录。`gstudio check --workspace ./workspace` 会检查系统契约、任务卡、资料引用及已登记快照的存在、大小与 SHA-256。

## 核心边界

| 保留 | 用途 |
| --- | --- |
| 项目、系统与独立任务 | 动态工作区、概览和任务入口；独立任务有自己的范围 |
| 任务卡与任务线 | 目标、描述、当前结果、下一步、日志；任务线只引用关联任务 |
| 输入、草稿、正式交付 | 分开存放；新增输入与草稿拒绝同名覆盖 |
| 任务检视 | 选择任务、导出上下文、保存人工确认的检视报告 |
| 资料浏览 | 以文件为主浏览、文本预览和下载 |
| 本地归档 | Inbox 标签、确认复制、校验和回执；保留来源 |
| AI 上下文导出 | 复制给外部 AI；本软件不自动执行模型或系统命令 |

双机同步、NAS 挂载、EBrain、运行 Agent、模型认证、邮件、业务 Skills、自动发布和后台服务属于完整系统的集成层，本仓库不包含它们。它也不提供永久删除、自动任务合并或自动备份。请自行备份工作区。

服务只监听本机回环地址，不提供公网部署与多用户登录。请勿直接用反向代理公开工作区。

## 数据与开发

任务 Markdown、项目 Markdown 和实际文件是工作区正本，`.gstudio` 中保存展示标签和归档回执。使用相对路径；不会扫描机器上的其他目录。不要将自己的工作区提交到公开仓库。

- [与实际系统的对照和精简差异](docs/system-alignment.md)
- [初始化 Skill 与安装验证](docs/initialization.md)
- [提炼范围](docs/extraction.md)
- [工作区与使用说明](docs/workspace.md)
- [HTTP 与存储接口](docs/api.md)
- [安全边界](SECURITY.md)
- [第三方声明](NOTICE.md)

```bash
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps -w dist
```

原创代码、示例和初始化 Skill 采用 [MIT](LICENSE)；标题字体单独遵守 SIL Open Font License 1.1，见 `src/gstudio_core/web/fonts/OFL.txt`。
