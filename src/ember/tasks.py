"""One task application service, with adapters for the two existing card formats.

Adapters preserve their storage and confirmation contracts. They never convert
historical cards merely to satisfy the normalized application view.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
from typing import Protocol


class TaskError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class TaskStorage(Protocol):
    def records(self) -> list[dict]: ...
    def execute(self, operation: str, task_id: str, payload: dict) -> dict: ...


class TaskService:
    OPERATIONS = frozenset({'create', 'update', 'promote', 'complete'})

    def __init__(self, storage: TaskStorage):
        self.storage = storage

    def list(self) -> list[dict]:
        records = self.storage.records()
        ids = [record['id'] for record in records]
        if len(ids) != len(set(ids)):
            raise TaskError('Duplicate task IDs; refusing an ambiguous task view.', 409)
        return records

    def get(self, task_id: str) -> dict:
        if not isinstance(task_id, str) or not task_id or '/' in task_id or '\\' in task_id or task_id in {'.', '..'}:
            raise TaskError('Invalid task ID.', 404)
        record = next((row for row in self.list() if row['id'] == task_id), None)
        if record is None:
            raise TaskError('Task not found.', 404)
        return record

    def execute(self, operation: str, payload: dict, task_id: str = '') -> dict:
        if operation not in self.OPERATIONS or not isinstance(payload, dict):
            raise TaskError('Unknown task operation or invalid payload.')
        if operation == 'create':
            title = payload.get('title')
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 20 or any(x in title for x in ('\n', '\r', '…', '...')):
                raise TaskError('任务标题应为 1–20 字的单行完整短语，不含省略号。')
        elif not task_id:
            raise TaskError('Task ID is required.')
        if operation in {'promote', 'complete'} and payload.get('confirmation') is not True:
            raise TaskError('任务完成需要明确 confirmation:true；部署原有的额外确认仍须满足。')
        return self.storage.execute(operation, task_id, payload)


def _sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r'(?m)^## ([^\n]+)\s*$', body))
    return {m.group(1).strip(): body[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(body)].strip()
            for i, m in enumerate(matches)}


def _record(metadata: dict, body: str, path: Path, lifecycle: str, source_bytes: bytes | None = None) -> dict:
    parts = _sections(body)
    return {'id': metadata['task_id'], 'title': metadata.get('title', ''),
            'project': metadata.get('project', 'independent'), 'status': metadata.get('status') or lifecycle,
            'work_type': metadata.get('work_type', ''), 'task_kind': metadata.get('task_kind', ''),
            'artifact_mode': metadata.get('artifact_mode', ''), 'goal': parts.get('任务目标', ''),
            'description': parts.get('任务描述', ''), 'current': parts.get('当前结果', parts.get('当前判断', '')),
            'next': parts.get('下一步', ''), 'execution_log': parts.get('执行日志', ''),
            'executor': metadata.get('executor', ''), 'skills_used': metadata.get('skills_used', []),
            'created_at': str(metadata.get('created_at', '')), 'updated_at': str(metadata.get('updated_at', '')),
            'related_task_ids': metadata.get('related_task_ids', []),
            'source': {'format': metadata.get('type', ''), 'lifecycle': lifecycle,
                       'sha256': hashlib.sha256(source_bytes if source_bytes is not None else path.read_bytes()).hexdigest()}}


class PortableTaskStorage:
    def __init__(self, workspace):
        self.workspace = workspace

    def records(self) -> list[dict]:
        return [_record(metadata, body, path, path.parent.name)
                for path, metadata, body in self.workspace._task_cards().values()]

    def execute(self, operation: str, task_id: str, payload: dict) -> dict:
        method = getattr(self.workspace, '_' + {'create': 'create_task', 'update': 'update_task',
                                               'promote': 'promote_task', 'complete': 'complete_task'}[operation])
        try:
            return method(payload) if operation == 'create' else method(task_id, payload)
        except TaskError:
            raise


class RuntimeTaskStorage:
    def __init__(self):
        from .runtime import gstudio_task
        self.reader = gstudio_task

    def records(self) -> list[dict]:
        result = []
        # Catch a physical active/completed collision before the legacy reader's
        # first-source compatibility deduplication can hide it.
        for _, root in self.reader.task_roots():
            seen = set()
            for state in ('active', 'completed'):
                directory = root / state
                for path in directory.glob('*.md'):
                    if path.name in seen:
                        raise TaskError('Same task exists in active and completed directories.', 409)
                    seen.add(path.name)
        for root, lifecycle, path in self.reader.task_files():
            raw = path.read_bytes()
            text = raw.decode('utf-8')
            record = self.reader.task_record(root, lifecycle, path, source_text=text)
            _, body = self.reader.frontmatter(text)
            metadata = {'task_id': record['task_id'], 'type': record['task_card_type'],
                        **{key: record.get(key, '') for key in ('title', 'project', 'status', 'work_type', 'task_kind',
                                                               'artifact_mode', 'created_at', 'updated_at', 'executor')},
                        'skills_used': record.get('skills_used', []), 'related_task_ids': record.get('related_task_ids', [])}
            result.append(_record(metadata, body, path, lifecycle, raw))
        return result

    def execute(self, operation: str, task_id: str, payload: dict) -> dict:
        from .runtime import gstudio_mcp_server, task_gate
        if operation == 'create':
            required = {'external_system', 'correlation_id', 'title', 'goal'}
            if not required <= payload.keys() or payload.keys() - (required | {'project', 'existing_task_id'}):
                raise TaskError('Runtime creation requires the existing idempotent ensure contract.')
            return gstudio_mcp_server.gstudio_task_ensure(external_system=payload['external_system'], correlation_id=payload['correlation_id'],
                title=payload['title'], objective=payload['goal'], project=payload.get('project', 'independent'), existing_task_id=payload.get('existing_task_id', ''))
        if operation == 'update':
            return self._update_result(task_id, payload)
        import argparse
        organization = payload.get('organization_task_id')
        if not isinstance(organization, str) or not organization:
            raise TaskError('Runtime lifecycle requires its confirmed organization task; confirmation alone cannot bypass it.')
        if set(payload) - {'confirmation', 'organization_task_id'}:
            raise TaskError('Unknown runtime lifecycle fields.')
        args = argparse.Namespace(task_id=task_id, organization_task_id=organization)
        function = task_gate.command_promote_delivery if operation == 'promote' else task_gate.command_complete_task
        if function(args):
            raise TaskError('Existing task lifecycle gate rejected the operation.', 409)
        return {'id': task_id, 'status': 'completed' if operation == 'complete' else 'active'}

    def _update_result(self, task_id: str, payload: dict) -> dict:
        from .runtime import task_gate
        from .runtime.gstudio_central_store import _locked
        from .runtime.gstudio_system_bridge import summary
        allowed = {'current', 'next', 'log_entry', 'expected_sha256'}
        if set(payload) - allowed or not any(key in payload for key in ('current', 'next', 'log_entry')):
            raise TaskError('Only bounded current/next/log_entry fields can be updated through this service.')
        found = self.reader.find_task(task_id)
        if not found or found[1] != 'active':
            raise TaskError('Only an active task can be updated.', 409)
        path = found[2]
        canonical = self.reader.SHARED_TASK_ROOT.resolve()
        if path.is_symlink() or path.resolve().parent != canonical / 'active':
            raise TaskError('Task is not a canonical active card.')
        with _locked(path):
            old_bytes = path.read_bytes()
            old = old_bytes.decode("utf-8")
            expected = payload.get('expected_sha256')
            if not isinstance(expected, str) or hashlib.sha256(old_bytes).hexdigest() != expected:
                raise TaskError('Task changed; reload its current SHA before updating.', 409)
            _, _, problems = task_gate.validate_task(task_id)
            problems.extend(task_gate.task_body_structure_errors(old))
            if problems:
                raise TaskError('Task preflight rejected this update: ' + '; '.join(problems), 409)
            revised = old
            for key, heading in (('current', '当前结果'), ('next', '下一步')):
                if key in payload:
                    value = summary(payload[key])
                    if not value:
                        raise TaskError('Task summaries must be nonempty bounded text.')
                    pattern = re.compile(r'(?m)^## ' + heading + r'\s*$[\s\S]*?(?=^## |\Z)')
                    if pattern.search(revised):
                        revised = pattern.sub(lambda _: '## ' + heading + '\n\n' + value + '\n\n', revised, count=1)
                    else:
                        revised = revised.replace('## 执行日志', '## ' + heading + '\n\n' + value + '\n\n## 执行日志', 1)
            stamp = task_gate._beijing_now()
            revised = task_gate._replace_top_value(revised, 'updated_at', stamp)
            entry = summary(payload.get('log_entry') or '用户更新任务结果。')
            revised = self.reader.prepend_execution_log_entry(revised, stamp + '：' + entry)
            self.reader.atomic_write(path, revised)
            _, _, problems = task_gate.validate_task(task_id)
            if problems:
                self.reader.atomic_write(path, old)
                raise TaskError('Updated task failed validation; original restored.', 409)
        if failure := task_gate.sync_workbench_index(path):
            raise TaskError('Record saved; index refresh must be retried: ' + failure, 503)
        return {'id': task_id, 'status': 'active', 'sha256': hashlib.sha256(revised.encode()).hexdigest()}
