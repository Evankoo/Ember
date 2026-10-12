# GStudio

**延续每一次 AI 协作。**

你和各类 AI 协作时，GStudio 把值得留下的任务记成本地文件：目标、资料、结果、下一步。换个对话、换个 AI 工具，也能从上次停下的地方继续。

本仓库是 GStudio 的开源单机版。MIT 许可，支持 macOS / Linux。

[介绍页](https://ai.evan-manual.com/gstudio/) · [在线演示](https://ai.evan-manual.com/gstudio/demo/) · [最新发行版](https://github.com/Evankoo/GStudio-Core/releases/latest) · [更新记录](CHANGELOG.md)

![GStudio 工作台：一张任务卡的目标、当前结果、下一步、执行日志和任务资料](docs/images/workbench.png)

## 为什么需要

AI 用得越多，上下文越分散：

- 新开一个对话，背景又要重讲一遍。
- 上次确认过的方案，埋在哪段聊天记录里？
- 换了个 AI 工具，之前的积累一样也带不走。

GStudio 把这些收在一处：每项值得留下的工作，都是一张本地任务卡。

## 安装

### 让 AI 帮你安装（推荐）

把这句话发给能读写本机文件的 AI 工具，比如 Codex、Claude Code、OpenCode：

```text
请按官方初始化 Skill，帮我安装 GStudio：
https://github.com/Evankoo/GStudio-Core
```

AI 会从[最新发行版](https://github.com/Evankoo/GStudio-Core/releases/latest)下载 `gstudio-init-*.zip`，解压出三个 Skill，然后由初始化 Skill 一步一步带你完成：

1. 确认程序目录和工作区目录；
2. 安装独立的 Python 环境和工作区规则；
3. 建立 `GStudio` 系统项目，并把这次安装记成第一张真实任务卡；
4. 在临时目录里验证任务、资料和交付，把结果写回这张任务卡；
5. 把工作区登记为本机默认，并在你确认后把日常 Skill 装进 AI 工具的全局 Skills 目录，让任意目录里的 AI 都能找到它；
6. 启动工作台，按需建立第一个业务项目，由你验收。

### 手动安装

需要 Python 3.10 或更新版本。在仓库目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
gstudio init ./workspace --example
gstudio use ./workspace
gstudio serve
```

浏览器打开 **http://127.0.0.1:8783/**，按 `Ctrl+C` 停止。`--example` 会放入完全虚构的示例客户、项目和任务；去掉它就是空白工作区。

## 怎么用

**照常协作，随时接续。**

1. **照常和 AI 协作。** 在能读写本机文件的 AI 工具里，像平时一样提需求。
2. **AI 记成任务卡。** 日常 Skill `gstudio-core` 让 AI 边工作边建卡、续卡，写回目标、资料、结果和下一步。任务卡始终写进 GStudio 工作区，你正在做的项目目录不会多出文件。
3. **随时接续。** 下次说一句“接着上次的秋季方案”，AI 就从那张任务卡读起；忘了上次的结论，也能在工作台里搜到。

给项目登记本机工作目录后，AI 在那个目录里协作时会自动对应到这个项目，不用每次说明“这是哪个项目的事”。

也可以在工作台里挑好资料、整理成任务说明，复制给任意 AI 工具，在那个工具里确认发送。

### AI 怎么找到工作区

初始化（或 `gstudio use <工作区>`）会把工作区位置和程序的 Python 路径记在 `~/.config/gstudio-core/workspace.json`。日常 Skill 在当前目录不是工作区时读取这个文件。`gstudio where` 可以查看当前登记；本机已登记另一个工作区时不会被悄悄替换，需要明确使用 `--replace`。

全局 Skill 也可以手动安装：

```bash
gstudio install-skill --target ~/.claude/skills
```

目标目录以你所用 AI 工具的文档为准，例如 Claude Code `~/.claude/skills`、Codex `~/.agents/skills`、OpenCode `~/.config/opencode/skills`。已装的官方旧版本会被直接升级；被你改过的副本会停止，不覆盖。装过的目录会被记住，升级 GStudio 后运行 `gstudio install-skill`（不带参数）即可全部更新。不需要安装 MCP。

### AI 怎么知道是哪个项目

```bash
gstudio project-location autumn-site ~/code/autumn-site
gstudio which-project --dir ~/code/autumn-site/src
```

第一条把目录登记到项目 `autumn-site`，第二条返回它对应的项目。日常 Skill 会先这样查；查不到时问你，不按目录名猜。

## 设计原则

**你的工作，始终在你手里。**

- **本地普通文件。** 任务卡是 Markdown，成果保留原格式，用任何编辑器都能打开。
- **换 AI 工具照样用。** 任务卡不属于任何一个 AI 工具，今天用 Codex，明天换 Claude Code，上下文都在。
- **你确认才算定稿。** AI 写完只是草稿，你确认采用，才复制成正式成果并完成任务。
- **开源，只在本机运行。** 代码公开可查；服务只监听本机，不调用模型，不自动发送提示词，打开 AI 软件前都要你确认。

## 包含什么

| 部分 | 说明 |
| --- | --- |
| 工作台 | 任务台、项目视图、任务检视、资料浏览、设置五个页面，加项目与任务详情 |
| 任务卡 | 目标、描述、当前结果、下一步和执行日志；任务线只引用关联任务 |
| 资料与交付 | 输入、草稿、正式交付分开存放；同名文件拒绝覆盖 |
| 三个 Skill | `gstudio-init` 首次安装，`gstudio-core` 日常接续，`gstudio-project` 确认后建项目 |
| 命令行 | `init`、`use`、`where`、`check`、`serve`、`install-skill`、`which-project`、`project-location` |

开源版是单机基础版，不包含完整版的归档中心、多机同步、知识库、运行 Agent、模型认证和自动发布，也不提供永久删除、自动合并任务或自动备份。请自行备份工作区。详见 [开源版范围](docs/scope.md)。

服务只监听本机回环地址，不提供公网部署或多用户登录，请勿用反向代理把工作区公开到网上。

## 更多文档

- [工作区与使用说明](docs/workspace.md)
- [初始化流程](docs/initialization.md)
- [HTTP 与存储接口](docs/api.md)
- [开源版范围](docs/scope.md)
- [安全边界](SECURITY.md)
- [更新记录](CHANGELOG.md)

## 开发

```bash
python -m unittest discover -s tests -v
rm -rf build src/*.egg-info && python -m pip wheel . --no-deps -w dist
```

打包前先清理 `build/`，避免旧文件混进 wheel。真实浏览器测试是可选的：安装 `playwright==1.60.0` 和 Chromium 后运行 `python -m unittest discover -s tests -p test_browser.py -v`，测试使用独立的虚构工作区。

原创代码、示例和 Skill 采用 [MIT](LICENSE)；标题字体单独遵守 SIL Open Font License 1.1，见 `src/gstudio_core/web/fonts/OFL.txt`。
