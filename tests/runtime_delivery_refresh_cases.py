"""Delivery refresh cases; run by test_runtime_delivery_refresh.py inside an isolated deployment."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ember.runtime import ember_task as task
from ember.runtime import ember_task_index_sync as sync


class DeliveryRefreshTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.shared = self.base / 'shared'
        self.source = self.shared / '交付/草稿/task-a'
        self.source.mkdir(parents=True)
        self.cache = self.base / 'cache'
        self.manifest = self.cache / 'draft/task-a/.gstudio-metadata.json'
        self.records = [{'record_type': 'task_card', 'task_id': 'task-a',
                         'delivery_folder': '交付/草稿/task-a/'}]
        for name, value in [('SHARED_WORKSPACE_ROOT', self.shared), ('DELIVERY_CACHE_ROOT', self.cache)]:
            patcher = mock.patch.object(task, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def refresh(self):
        return task.sync_delivery_cache_tasks(self.records, {'task-a'})

    def test_unchanged_card_refreshes_nested_addition_and_same_size_edit(self):
        root = self.shared / 'tasks'
        (root / 'active').mkdir(parents=True)
        (root / 'completed').mkdir()
        card = root / 'active/task-a.md'
        card.write_text('unchanged card')
        index = self.base / 'index.json'
        index.write_text(json.dumps({'records': self.records}))
        fingerprint, count, _, manifest, _ = sync._task_snapshot(root)
        state = self.base / 'state.json'
        state.write_text(json.dumps({'fingerprint': fingerprint, 'tasks': manifest,
                                     'source_task_count': count, 'record_count': 1}))
        nested = self.source / 'nested'
        nested.mkdir()
        file = nested / 'draft.md'
        file.write_text('old')
        with mock.patch.object(sync, 'STATE_PATH', state), \
             mock.patch.object(sync, 'LOCK_PATH', self.base / 'index.lock'), \
             mock.patch.object(task, 'TASK_INDEX_JSON', index), \
             mock.patch.object(task, 'sync_index_records') as rebuild, \
             mock.patch.object(task, 'sync_changed_task_records') as parse:
            sync.refresh_once(root=root)
            before = self.manifest.read_bytes()
            file.write_text('new')
            stat = file.stat()
            os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            (nested / 'new.md').write_text('added')
            sync.refresh_once(root=root)
            self.assertNotEqual(before, self.manifest.read_bytes())
            entries = json.loads(self.manifest.read_text())['entries']
            self.assertIn('nested/new.md', [entry['relative_path'] for entry in entries])
            rebuild.assert_not_called()
            parse.assert_not_called()
            self.assertEqual(card.read_text(), 'unchanged card')

    def test_unchanged_metadata_does_not_rewrite_cache(self):
        (self.source / 'draft.md').write_text('draft')
        self.refresh()
        before = self.manifest.stat().st_mtime_ns
        self.refresh()
        self.assertEqual(self.manifest.stat().st_mtime_ns, before)
        self.assertEqual(list(self.manifest.parent.iterdir()), [self.manifest])

    def test_failed_scan_and_missing_source_preserve_last_good_manifest(self):
        (self.source / 'draft.md').write_text('draft')
        self.refresh()
        before = self.manifest.read_bytes()
        with mock.patch.object(task.os, 'walk', side_effect=PermissionError('offline')):
            result = self.refresh()
        self.assertGreater(result['failed'], 0)
        self.assertEqual(before, self.manifest.read_bytes())
        self.source.rename(self.source.with_name('temporarily-unavailable'))
        result = self.refresh()
        self.assertGreater(result['failed'], 0)
        self.assertEqual(before, self.manifest.read_bytes())

    def test_deletion_and_rename_update_manifest_without_following_links(self):
        file = self.source / 'old.md'
        file.write_text('draft')
        self.refresh()
        file.rename(self.source / 'new.md')
        (self.source / 'link').symlink_to(self.base, target_is_directory=True)
        self.refresh()
        self.assertEqual([x['relative_path'] for x in json.loads(self.manifest.read_text())['entries']], ['new.md'])
        (self.source / 'new.md').unlink()
        self.refresh()
        self.assertEqual(json.loads(self.manifest.read_text())['entries'], [])


if __name__ == '__main__':
    unittest.main()
