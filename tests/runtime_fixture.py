"""Fictional full-format fixture; contains no deployment data or private integrations."""
from pathlib import Path
import json


def make_runtime_fixture(root: Path) -> Path:
    root = root.resolve()
    runtime, shared = root / 'runtime', root / 'documents'
    config = runtime / 'config'
    config.mkdir(parents=True)
    for path in (shared / 'tasks/active', shared / 'tasks/completed', shared / '项目/demo', root / 'inbox', root / 'archive', root / 'local-config', root / 'repository'):
        path.mkdir(parents=True, exist_ok=True)
    profile = root / 'profile.json'
    data = {'schema_version': 1, 'environment': 'test', 'isolation_root': str(root),
            'runtime_root': str(runtime), 'shared_root': str(shared), 'inbox_root': str(root / 'inbox'),
            'archive_root': str(root / 'archive'), 'local_config_root': str(root / 'local-config'),
            'repository_root': str(root / 'repository')}
    profile.write_text(json.dumps(data))
    configs = {
        'workspace-environments.json': {'environments': {'test': {'label': 'Fictional test environment',
            'shared_workspace_root': str(root / 'must-not-be-used'), 'workspace_inbox_root': str(root / 'inbox')}}, 'path_equivalence_rules': []},
        'archive-names.json': {},
        'projects.json': {'schema_version':3, 'independent_scope':{'slug':'independent','is_project':False}, 'default_project':'independent', 'projects':[{
            'slug':'demo','title':'虚构测试项目','project_type':'generic_project','aliases':['测试项目'],
            'capabilities':['task_groups','ember_delivery'], 'artifact_policy':{'owner':'gstudio','default_mode':'none'},
            'project_card':'项目/demo/项目看板.md'}]},
        'project-types.json': {'schema_version':1, 'project_types':[{'slug':'generic_project','title':'通用项目',
            'required_capabilities':['task_groups'], 'allowed_artifact_modes':['none','delivery','system','archive','external']}], 'work_categories':[]},
        'ember-workbench.json': {'host':'127.0.0.1','port':0,'log_directory':str(root/'logs')},
        'agents.json': {'version':1,'runtime_agents':{},'roles':{}},
        'ember-archive.json': {'display_root':str(root/'archive'), 'canonical_root':str(root/'archive')},
        'ember-sync.json': {'runtime_mode':'package','install_services_after_update':[],'restart_workbench_after_update':False},
        'project-priorities.json': {},
        'weekly-organization.json': {'launch_agent_label':'test.weekly','log_directory':str(root/'logs'),'weekday':1,'hour':3,'minute':0},
        'task-index-sync.json': {'launch_agent_label':'test.index','interval_seconds':60,'log_directory':str(root/'logs')},
    }
    for name, value in configs.items():
        (config / name).write_text(json.dumps(value, ensure_ascii=False))
    (runtime / 'skills').mkdir()
    (runtime / 'skills/manifest.json').write_text('{"skills": []}')
    (shared / '项目/demo/项目看板.md').write_text('''---
type: gstudio_project
project: demo
title: 虚构测试项目
created_at: "2026-10-17 12:00:00+08:00"
updated_at: "2026-10-17 12:00:00+08:00"
---
# 虚构测试项目

## 项目总览
仅供自动化验证的虚构项目。

## 当前阶段
自动化验证。

## 时间线
测试初始记录。

## 运行身份
测试 fixture。

## 说明正本
本文件是测试正本。

## 运行边界
仅测试目录。

## 成果策略
无文件收口与草稿测试。

## 系统入口
无外部入口。

## 整理记录
暂无。
''')
    return profile
