# 统一应用与部署

同一 Ember 包提供任务服务、界面及完整运行模块。`TaskService` 是共同任务入口，`Workspace` 的旧方法、完整部署的 `Application.tasks` 以及两种 HTTP 服务的 `/api/tasks` 使用同一服务与规范化记录。历史 portable / full Markdown 格式通过适配器保留，不批量改写卡片或放宽部署原有的确认规则。

## 所有权

| 层 | 内容与边界 |
|---|---|
| `application` / `tasks` | 显式部署、共同任务服务、受控命令；缺正本/重复 ID/过期修订拒绝 |
| `runtime` / `runtime.pages` | 完整任务、输入、交付、组织、报告、归档、Agent、MCP 及页面模块；保留历史协议 |
| `ember_ui` | 唯一共享界面，仍由同步工具维护 |
| `package_update` / `launch` | 校验 wheel、预验证安装、原子选择、回退与同一工作台进程锁 |
| `compat` | 旧 CLI 的薄转接；调用同一安装包，不复制业务实现 |
| `integrations` | 本地可选集成的显式清单、相对路径和 SHA 校验；不自动发现或下载 |

真实项目注册、业务 Skill、Agent 定义、账号与资料仍属部署。双机 Git 同步、SSH 隧道、NAS 自动挂载和相关布局维护保留为本地私有集成，开源包仅有兼容名称和接入接口。缺少该集成不会阻止通用项目/任务服务启动；也不会伪造双机已可用。

## 显式完整部署

```json
{
  "schema_version": 1,
  "environment": "local",
  "runtime_root": "/isolated/deployment/runtime",
  "shared_root": "/isolated/deployment/documents",
  "inbox_root": "/isolated/deployment/inbox",
  "archive_root": "/isolated/deployment/archive",
  "local_config_root": "/isolated/deployment/local-config",
  "repository_root": "/isolated/source",
  "isolation_root": "/isolated"
}
```

安装此构建的 `full` extra 后，部署提供既有规则、Skill 和配置，资料原位引用：

```sh
ember --deployment-profile /isolated/deployment/profile.json check
ember --deployment-profile /isolated/deployment/profile.json runtime gstudio_project validate
ember --deployment-profile /isolated/deployment/profile.json serve --port 0
```

资料根以 profile 为准；环境变量不能在应用启动时悄悄替换它。历史 locator 可通过部署配置 `path_aliases: [{"from": "...", "to": "..."}]` 只读解析，不修改原卡。隔离模式只返回边界内的解析结果，未复制的外部资料保持不可用。隔离部署不占用生产/已停试装端口，不安装或重启宿主常驻服务，不覆盖客户端配置。

未提供 profile 的旧 portable 初始化、CLI 和工作区保持兼容。完整部署保留自己更严格的整理确认、权限、租约和原始目录规则；`confirmation:true` 不能绕过它们。对外 task 记录包含原格式、生命周期和源 SHA；完整部署的有界结果更新要求当前 SHA 并执行原 preflight。

## 包更新与回退

更新先构建 wheel 并核对 SHA，再在独立版本目录安装依赖、检查实际数据根、校验任务与全部已安装包文件。成功后以锁和 revision 原子选择活动版本；旧安装及资料不删除。构建、检查或服务重启失败保留上一选择；重复/过期选择拒绝。包更新不会迁移或覆盖用户规则、Skill、项目和资料。

`ember.launch` 从唯一活动选择启动注册服务；MCP 同样使用该入口及显式 profile。旧 CLI 薄转接可先用 `compat.stage_launchers` 生成到部署的待审目录，既有脚本不会被它自动覆盖。生产替换和客户端切换属于独立部署步骤。

## 验证与分发

公共 `tests/` 仅用临时虚构资料，覆盖 portable / full 记录、共同服务、幂等、SHA 冲突、组织确认、路径隔离、包文件完整性、版本选择/回退和本地集成边界。已有部署的原完整回归在私有测试目录运行，不进入公开树。Linux Python 3.10/3.12 和浏览器分别验证；实际 wheel 另装到隔离环境，清除 PYTHONPATH 后运行。

初始化 ZIP、wheel、源码树、版本、UI 与许可资源都须通过发行门禁。候选构建和“检查通过”不代表已公开发行或已切换任何生产服务。私人 Git 历史、部署配置和第三方业务 Skill 不随公开包分发。
