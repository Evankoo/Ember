from pathlib import Path
import tempfile
import unittest
from ember.store import Workspace, WorkspaceError
from ember.tasks import TaskService, PortableTaskStorage, TaskError


class TaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Workspace(Path(self.temp.name) / 'Ember')
        self.workspace.initialize()
        self.service = TaskService(PortableTaskStorage(self.workspace))

    def create(self, **extra):
        return self.service.execute('create', {'title': '接口验证', 'goal': '保留任务和权限', **extra})

    def test_workspace_compatibility_entry_uses_same_service(self):
        task = self.workspace.create_task({'title': '共同入口', 'goal': '验证兼容'})
        self.assertEqual(self.service.get(task['id'])['goal'], '验证兼容')
        self.workspace.update_task(task['id'], {'current': '已经核对'})
        self.assertEqual(self.service.get(task['id'])['current'], '已经核对')

    def test_normalized_record_preserves_source_and_digest(self):
        task = self.create()
        row = self.service.get(task['id'])
        self.assertEqual(row['source']['format'], 'ember_task')
        self.assertEqual(row['source']['lifecycle'], 'active')
        self.assertEqual(len(row['source']['sha256']), 64)
        self.assertEqual(row['task_kind'], 'task')
        self.assertEqual(row['project'], 'independent')

    def test_unknown_command_and_traversal_rejected(self):
        with self.assertRaises(TaskError):
            self.service.execute('delete_all', {})
        for identifier in ('../outside', '', '/tmp/file', '..'):
            with self.subTest(identifier=identifier), self.assertRaises(TaskError):
                self.service.get(identifier)

    def test_completed_task_remains_read_only(self):
        task = self.create()
        self.service.execute('complete', {'confirmation': True}, task['id'])
        self.assertEqual(self.service.get(task['id'])['status'], 'completed')
        with self.assertRaises(WorkspaceError):
            self.service.execute('update', {'current': '不能覆盖'}, task['id'])

    def test_confirmation_cannot_be_string_or_integer(self):
        task = self.create()
        for value in ('true', 1, None, False):
            with self.subTest(value=value), self.assertRaises(TaskError):
                self.service.execute('complete', {'confirmation': value}, task['id'])
        self.assertEqual(self.service.get(task['id'])['status'], 'active')

    def test_delivery_cannot_be_closed_as_no_file(self):
        task = self.create(artifact_mode='delivery')
        with self.assertRaises(WorkspaceError):
            self.service.execute('complete', {'confirmation': True}, task['id'])
        self.assertEqual(self.service.get(task['id'])['status'], 'active')

    def test_duplicate_record_ids_fail_closed(self):
        class Storage:
            def records(self):
                return [{'id': 'same'}, {'id': 'same'}]
        with self.assertRaises(TaskError):
            TaskService(Storage()).list()
