"""The deferred archive module is absent; historical user files stay intact."""
import json
from http.client import HTTPConnection
from pathlib import Path
import re
import tempfile
import threading
import unittest

import yaml

from gaiora.executors import ExecutorRegistry
from gaiora.server import LocalServer
from gaiora.store import Workspace, WorkspaceError


class ArchiveScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        self.workspace = Workspace(self.root)

    def bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_empty_initialization_has_no_archive_module_or_ledger(self):
        state = self.workspace.initialize()
        self.assertFalse((self.root / 'archive').exists())
        self.assertFalse((self.root / '.gaiora/archive-records.json').exists())
        self.assertNotIn('archives', state)
        self.assertNotIn('archive_records', state)
        self.assertFalse(hasattr(self.workspace, 'archive_item'))

    def test_fictional_workspace_does_not_ship_archive_data(self):
        state = self.workspace.initialize(example=True)
        self.assertEqual(len(state['tasks']), 8)
        self.assertFalse((self.root / 'archive').exists())
        self.assertFalse((self.root / '.gaiora/archive-records.json').exists())
        self.assertNotIn('archive', {f['kind'] for f in state['files']})

    def test_existing_archives_and_bad_legacy_receipt_are_left_untouched(self):
        self.workspace.initialize()
        legacy = self.root / 'archive/sample/previous/notes.md'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('Historical user-owned file: preserve it.\n')
        (self.root / '.gaiora/archive-records.json').write_text('old malformed receipt: do not migrate\n')
        before = self.bytes()
        state = Workspace(self.root).snapshot()
        self.assertNotIn('archives', state)
        self.assertNotIn(legacy.relative_to(self.root).as_posix(), {f['id'] for f in state['files']})
        with self.assertRaises(WorkspaceError):
            self.workspace.read_file(legacy.relative_to(self.root).as_posix())
        self.assertEqual(self.bytes(), before)

    def test_explicit_legacy_archive_input_reference_is_still_readable(self):
        self.workspace.initialize()
        task = self.workspace.create_task({'title': '历史资料引用', 'goal': '保留明确来源'})['id']
        relative = 'archive/sample/previous/guide.md'
        legacy = self.root / relative
        legacy.parent.mkdir(parents=True)
        legacy.write_text('Only the explicitly referenced old input is readable.\n')
        card = self.root / f'tasks/active/{task}.md'
        text = card.read_text()
        header = yaml.safe_load(text.split('---', 2)[1])
        header['inputs'] = {'items': [{'id': 'legacy-input', 'storage': 'archive', 'path': relative, 'purpose': '历史依据'}]}
        card.write_text('---\n' + yaml.safe_dump(header, allow_unicode=True, sort_keys=False) + '---' + text.split('---', 2)[2])
        before = self.bytes()
        state = self.workspace.snapshot()
        self.assertEqual(state['tasks'][0]['inputs'], [relative])
        self.assertEqual(self.workspace.read_file(relative)['text'], legacy.read_text())
        self.assertEqual(self.bytes(), before)

    def test_legacy_input_reference_cannot_escape_follow_links_or_read_directories(self):
        self.workspace.initialize()
        task = self.workspace.create_task({'title': '旧来源安全边界', 'goal': '拒绝不安全的旧引用'})['id']
        card = self.root / f'tasks/active/{task}.md'
        text = card.read_text()
        outside = Path(self.temp.name) / 'outside.md'
        outside.write_text('Outside content must not be read.\n')
        folder = self.root / 'archive/sample'
        folder.mkdir(parents=True)
        (folder / 'link.md').symlink_to(outside)
        for relative in ('archive/../../outside.md', 'archive/sample/link.md', 'archive/sample', 'archive/missing.md'):
            with self.subTest(relative=relative):
                header = yaml.safe_load(text.split('---', 2)[1])
                header['inputs'] = {'items': [{'id': 'legacy-input', 'storage': 'archive', 'path': relative}]}
                card.write_text('---\n' + yaml.safe_dump(header, allow_unicode=True, sort_keys=False) + '---' + text.split('---', 2)[2])
                before = self.bytes()
                with self.assertRaises(WorkspaceError):
                    self.workspace.snapshot()
                self.assertEqual(self.bytes(), before)
                self.assertEqual(outside.read_text(), 'Outside content must not be read.\n')

    def test_public_frontend_contains_no_archive_page_action_or_styles(self):
        package = Path(__file__).resolve().parents[1] / 'src/gaiora'
        for filename, forbidden in (
            ('web/index.html', 'href="#archive"'),
            ('web/app.js', 'renderArchive'),
            ('web/app.js', '/api/archive'),
            ('web/app.css', '.archive-'),
        ):
            with self.subTest(filename=filename, forbidden=forbidden):
                self.assertNotIn(forbidden, (package / filename).read_text())

    def test_ci_wheel_check_python_is_valid(self):
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load((root / '.github/workflows/check.yml').read_text())
        checked = 0
        for job in workflow['jobs'].values():
            for step in job['steps']:
                for code in re.findall(r"(?ms)^python - <<'PY'\n(.*?)^PY$", step.get('run', '')):
                    compile(code, '<CI wheel verification>', 'exec')
                    checked += 1
        self.assertGreater(checked, 0)

    def test_retired_archive_post_is_404_and_does_not_write(self):
        self.workspace.initialize(example=True)
        before = self.bytes()
        registry = ExecutorRegistry(Path(self.temp.name) / 'machine-home')
        server = LocalServer(self.workspace, 0, executor_registry=registry)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            item = next(x for x in self.workspace.snapshot()['inbox'] if x['label'] == '待归档')
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            conn.request('POST', '/api/archive', json.dumps({'id': item['id'], 'project': 'chenyu', 'revision': 0, 'confirmation': True}),
                         {'Content-Type': 'application/json', 'X-Gaiora-Token': server.csrf_token})
            response = conn.getresponse()
            response.read()
            conn.close()
            self.assertEqual(response.status, 404)
            self.assertEqual(self.bytes(), before)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
