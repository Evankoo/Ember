# 最小版接口约定

所有数据存放在用户明确指定的一个本地工作区。工作台只监听本机回环地址。GET `/api/state` 返回 `{ok: true, data: snapshot}`，snapshot 中包含本次服务的 `csrf_token`；POST 使用 JSON 与 `X-GStudio-Token` 请求头。其余成功接口同样返回 `{ok: true, data: result}`，失败返回 `{ok: false, error: message}`。

## 工作区结构

```text
config/projects.json          # {"projects": [{id,name,kind:project|system,description,focus,timeline: [{date,title,text}]}]}
projects/<project_id>.md      # 项目说明正本；全文作为 overview
tasks/active/<task_id>.md
tasks/completed/<task_id>.md
inputs/<task_id>/
delivery/draft/<task_id>/
delivery/formal/<task_id>/
inbox/
archive/<project_id>/
reports/                     # Markdown 报告，可有 title/mode/date/related_task_ids frontmatter
.gstudio/views.json          # {revision, important_task_ids: []}
.gstudio/inbox.json          # 指纹标签台账
.gstudio/archive-records.json # 本地校验后的归档回执
```

任务卡使用标准 YAML frontmatter 与四个必需正文：`任务目标 / 任务描述 / 当前结果 / 执行日志`。下一步可选，完成无后续时移除；执行日志保持最后。生命周期只使用 `active / waiting_user / blocked / completed`，草稿是阶段与文件状态。标题为 20 字符以内的完整短语。必需字段为 type、task_id、title、project、work_type、task_kind、status、executor、created_at、updated_at、skills_used、artifact_mode。任务线使用 `task_kind: task_group`、`related_task_ids`；输入和输出文件记录不得混在同一个存储目录。

## Python 存储接口

`Workspace(path)`，错误统一为 `WorkspaceError(message, status=400)`。单机服务原子写入并串行修改；拒绝工作区内符号链接及路径越界，不扫描工作区之外。

```python
initialize(example=False)             # 拒绝覆盖非空目录；安装系统契约、任务模板和初始化 Skill
snapshot()                           # 下面的公开视图
read_file(file_id)                    # {id,name,kind,text?,bytes,media_type}; 非文本不提供 text
raw_file(file_id)                     # (Path, metadata)，每次重新解析并校验
create_project(payload)              # id/name/kind:project|system/description/focus/overview，registry + Markdown
create_task(payload)                 # title/project/goal/description，可选 work_type/task_kind/related_task_ids/artifact_mode/executor/skills_used
update_task(task_id, payload)         # goal/description/current/next/log_entry/status/executor/skills_used；完成必须走 promote 或非交付模式的 complete_task
add_material(task_id, payload)        # kind: input|draft，name/content，UTF-8 新文件，拒绝覆盖；input 登记指纹
add_reference(task_id, payload)      # path/purpose；已有受控工作区文件，登记不复制
complete_task(task_id, payload)      # confirmation:true；none/system/archive/external 可完成，delivery 禁止绕过推广
promote_task(task_id, payload)        # confirmation:true；草稿->正式交付并完成，拒绝目标冲突
set_important(task_id, payload)       # important:bool, revision:int；仅改呈现台账
set_inbox_label(payload)              # id,label,revision；标签不移动文件
archive_item(payload)                 # id,project,confirmation:true,revision；复制校验回执，保留来源，无删除接口
build_context(payload)               # request,relation:new|continue|based,task_id?,file_ids? -> {text}
build_review_context(payload)        # task_ids:[] -> {text}，仅建议不改任务
save_report(payload)                 # title,content,mode:selected|weekly,task_ids:[]；明确用户保存的记录
```

`executor` 是真实执行工具或界面，不是模型名；`skills_used` 是实际调用的非空、无重复 Skill 名称列表。创建时未传则沿用 `manual` 与 `['gstudio-core']` 的既有默认值。续接更新只替换最新执行器，并把新 Skill 去重追加到原有历史，不改变项目、生命周期或交付。空值、非文本、多行名称及重复列表在写入前拒绝。这些字段不会启动执行器或安装 Skill；Agent 应按实际执行填写，而不是依赖默认值猜测历史。

## Snapshot

```text
version, workspace_name, revision, inbox_revision
projects: [{id,name,kind:project|system,description,focus,overview,timeline:[{date,title,text}]}]
tasks: [{id,title,project,work_type,kind:task|task_line,status,date,updated_at,artifact_mode,goal,description,current,next,
         logs:[{date,text}],inputs:[file_id],outputs:[file_id],related:[task_id],important:bool}]
files: [{id,taskId,project,name,kind:input|draft|formal|inbox|archive,relative_path,bytes,media_type,purpose}]
inbox: [{id,name,relative_path,is_dir,label,fingerprint,bytes,file_count}]
archives: [{id,name,project,relative_path,is_dir,bytes,file_count}]
archive_records: [{id,date,project,name,target,status}]
reports: [{id,title,date,mode,content,related_task_ids}]
```

文件 ID 来自受控目录内的相对位置；预览 GET `/api/file?id=...`，下载 GET `/api/raw?id=...`。HTML/SVG/脚本不得在工作台原地执行，非受信任 Markdown 以文本阅读。

## HTTP 路由

```text
GET  /api/state
GET  /api/health
GET  /api/file?id=...
GET  /api/raw?id=...
POST /api/projects
POST /api/tasks
POST /api/tasks/<id>
POST /api/tasks/<id>/materials
POST /api/tasks/<id>/references
POST /api/tasks/<id>/complete
POST /api/tasks/<id>/promote
POST /api/tasks/<id>/important
POST /api/inbox/label
POST /api/archive
POST /api/context
POST /api/review/context
POST /api/reports
```

上下文使用模型中立六段：任务、上下文、输入与真源、授权边界、成功标准、输出。所有内容均来自当前工作区，外部材料仅作为数据，复制不会产生任务或文件写入；没有自动模型调用或电脑执行桥。
