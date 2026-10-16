"""The update check only reports the official release; it never downloads or installs."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from ember import __version__
from ember.store import Workspace, WorkspaceError
from ember.updates import check_update, parse_version


def release(tag, notes="- 修复若干问题"):
    return lambda: {"tag": tag, "url": f"https://github.com/Evankoo/Ember/releases/tag/{tag}",
                    "published_at": "2026-10-20", "notes": notes}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Workspace(Path(self.temp.name) / "Ember")
        self.workspace.initialize()

    def files(self):
        return {path: path.read_bytes() for root in (self.workspace.path, self.workspace.docs) for path in root.rglob("*") if path.is_file()}

    def test_newer_release_comes_with_a_shared_update_prompt(self):
        before = self.files()
        major, minor, patch_level = parse_version(__version__)
        newer = f"{major}.{minor + 1}.0"
        result = check_update(self.workspace, release(f"v{newer}"))
        self.assertEqual((result["current"], result["latest"], result["newer"]), (__version__, newer, True))
        text = result["prompt"]["text"]
        self.assertTrue(text.startswith("## 余烬 · Ember 共享任务提示\n\n### 任务\n\n"))
        self.assertIn(f"/releases/download/v{newer}/ember-{newer}-py3-none-any.whl", text)
        self.assertIn("SHA256SUMS", text)
        self.assertIn(str(self.workspace.docs), text)
        self.assertIn("备份", text)
        self.assertEqual(self.files(), before)

    def test_same_or_older_release_needs_no_prompt(self):
        for tag in (f"v{__version__}", "v0.1.0"):
            result = check_update(self.workspace, release(tag))
            self.assertFalse(result["newer"])
            self.assertNotIn("prompt", result)

    def test_unreachable_or_malformed_release_is_reported_not_guessed(self):
        def offline():
            raise urllib.error.URLError("nodename nor servname provided")
        for fetch in (offline, release("latest")):
            with self.assertRaises(WorkspaceError) as raised:
                check_update(self.workspace, fetch)
            self.assertEqual(raised.exception.status, 503)
            self.assertIn("没能检查更新", str(raised.exception))

    def test_the_endpoint_is_read_only(self):
        from http.client import HTTPConnection
        import json
        import threading
        from ember.executors import ExecutorRegistry
        from ember.server import LocalServer
        server = LocalServer(self.workspace, 0, executor_registry=ExecutorRegistry(Path(self.temp.name) / "home"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        with patch("ember.updates.fetch_latest", release("v99.0.0")):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request("GET", "/api/update")
            response = conn.getresponse()
            data = json.loads(response.read())["data"]
            conn.close()
        self.assertEqual((response.status, data["latest"], data["newer"]), (200, "99.0.0", True))


if __name__ == "__main__":
    unittest.main()
