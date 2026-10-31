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
