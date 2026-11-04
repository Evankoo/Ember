"""The update check reports the official release; 更新 installs only a checksum-verified program package."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from ember import __version__
from ember import updates
from ember.store import Workspace, WorkspaceError
from ember.updates import MIRROR, RELEASES, check_update, fetch_latest, fetch_wheel, install_update, parse_version


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
        self.assertIn(f"{MIRROR}/v{newer}/ember-{newer}-py3-none-any.whl", text)
        self.assertEqual(result["source"], "github")
        self.assertIn("SHA256SUMS", text)
        self.assertIn(str(self.workspace.docs), text)
        self.assertIn("备份", text)
        self.assertIn("已移除的不恢复", text)
        self.assertNotIn("三个 Skill", text)
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

    def test_mirror_answers_when_github_cannot(self):
        def offline(*args, **kwargs):
            raise urllib.error.URLError("timed out")
        mirror = {"tag": "99.0.0", "url": "https://github.com/Evankoo/Ember/releases/tag/v99.0.0",
                  "published_at": "2026-11-03", "notes": "", "source": "mirror"}
        for github in (offline, release("latest")):
            with patch("ember.updates.fetch_github", side_effect=github), \
                    patch("ember.updates.fetch_mirror", return_value=mirror) as fetch_mirror:
                result = check_update(self.workspace)
            fetch_mirror.assert_called_once()
            self.assertEqual((result["latest"], result["newer"], result["source"]), ("99.0.0", True, "mirror"))

    def test_github_answer_skips_the_mirror(self):
        with patch("ember.updates.fetch_github", release("v99.0.0")), patch("ember.updates.fetch_mirror") as fetch_mirror:
            self.assertEqual(fetch_latest()["tag"], "v99.0.0")
        fetch_mirror.assert_not_called()

    def test_both_sources_unreachable_is_reported(self):
        def offline(*args, **kwargs):
            raise urllib.error.URLError("timed out")
        with patch("ember.updates.fetch_github", side_effect=offline), patch("ember.updates.fetch_mirror", side_effect=offline):
            with self.assertRaises(WorkspaceError) as raised:
                check_update(self.workspace)
        self.assertEqual(raised.exception.status, 503)
        self.assertIn("国内下载源", str(raised.exception))

    def wheel(self, version="99.0.0", agents=b"# rules\n"):
        path = Path(self.temp.name) / f"ember-{version}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("ember/__init__.py", f'__version__ = "{version}"\n')
            archive.writestr("ember/templates/AGENTS.md", agents)
            archive.writestr("ember/skills/ember/SKILL.md", b"skill\n")
        return path.read_bytes()

    def sources(self, data, sums=None, github_down=False):
        name = "ember-99.0.0-py3-none-any.whl"
        listing = f"{sums or hashlib.sha256(data).hexdigest()}  {name}\n".encode()
        calls = []
        def get(url):
            calls.append(url)
            if github_down and url.startswith(RELEASES):
                raise urllib.error.URLError("timed out")
            return listing if url.endswith("SHA256SUMS") else data
        return get, calls

    def installed_package(self):
        package = Path(self.temp.name) / "venv/lib/site-packages/ember"
        (package / "templates").mkdir(parents=True)
        (package / "skills/ember").mkdir(parents=True)
        (package / "templates/AGENTS.md").write_bytes(b"# rules\n")
        (package / "skills/ember/SKILL.md").write_bytes(b"skill\n")
        return patch("ember.updates.PACKAGE", package)

    def test_wheel_comes_from_github_or_the_mirror_and_must_match_its_checksums(self):
        data = self.wheel()
        get, calls = self.sources(data)
        self.assertEqual(fetch_wheel("99.0.0", get), (data, "GitHub"))
        self.assertTrue(all(url.startswith(RELEASES) for url in calls))
        get, calls = self.sources(data, github_down=True)
        self.assertEqual(fetch_wheel("99.0.0", get), (data, "国内下载源"))
        self.assertTrue(calls[-1].startswith(MIRROR))
        get, calls = self.sources(data, sums="0" * 64)
        with self.assertRaisesRegex(WorkspaceError, "SHA256SUMS 不一致"):
            fetch_wheel("99.0.0", get)
        self.assertFalse(any(url.startswith(MIRROR) for url in calls))

    def test_install_puts_the_verified_wheel_into_this_environment_and_reports_changed_rules(self):
        before = self.files()
        get, _ = self.sources(self.wheel(agents=b"# new rules\n"))
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if "pip" in command:
                self.assertTrue(Path(command[-1]).is_file())
            return subprocess.CompletedProcess(command, 0, "", "")
        with self.installed_package():
            result = install_update(self.workspace, {"version": "99.0.0", "confirmation": True}, release("v99.0.0"), get, run)
        self.assertEqual(commands[0][:5], [sys.executable, "-m", "pip", "install", "--upgrade"])
        self.assertEqual(commands[1], [sys.executable, "-m", "ember", "install-skill"])
        self.assertEqual((result["installed"], result["source"], result["system_copies_changed"]), ("99.0.0", "GitHub", ["AGENTS.md"]))
        self.assertEqual(self.files(), before)

    def test_failed_pip_retries_the_pypi_mirror_then_reports(self):
        get, _ = self.sources(self.wheel())
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "ERROR: No matching distribution found for PyYAML")
        with self.installed_package(), self.assertRaisesRegex(WorkspaceError, "PyYAML") as raised:
            install_update(self.workspace, {"version": "99.0.0", "confirmation": True}, release("v99.0.0"), get, run)
        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(commands[1][-2:], ["--index-url", updates.PYPI_MIRROR])
        self.assertEqual(len(commands), 2)

    def test_install_needs_the_confirmed_current_release_and_an_installed_program(self):
        get, calls = self.sources(self.wheel())
        never = lambda *a, **k: self.fail("nothing may run")
        with self.installed_package():
            for payload, fetch, message in (({"version": "99.0.0"}, release("v99.0.0"), "确认"),
                                            ({"version": "98.0.0", "confirmation": True}, release("v99.0.0"), "重新打开"),
                                            ({"version": __version__, "confirmation": True}, release(f"v{__version__}"), "已是最新")):
                with self.assertRaisesRegex(WorkspaceError, message):
                    install_update(self.workspace, payload, fetch, get, never)
        with patch("ember.updates.PACKAGE", Path(self.temp.name) / "checkout/src/ember"), self.assertRaisesRegex(WorkspaceError, "源码运行"):
            install_update(self.workspace, {"version": "99.0.0", "confirmation": True}, release("v99.0.0"), get, never)
        self.assertEqual(calls, [])

    def test_restart_leaves_a_login_service_to_restart_the_program(self):
        with patch.object(updates.sys, "platform", "darwin"), patch.dict(updates.os.environ, {"XPC_SERVICE_NAME": updates.LABEL}):
            with self.assertRaises(SystemExit) as raised:
                updates.restart()
        self.assertEqual(raised.exception.code, 75)
        with patch.object(updates.sys, "platform", "darwin"), patch.dict(updates.os.environ, {"XPC_SERVICE_NAME": "0"}), \
                patch.object(updates.sys, "argv", ["/x/ember/__main__.py", "serve", "--port", "8783"]), patch.object(updates.os, "execv") as execv:
            updates.restart()
        execv.assert_called_once_with(sys.executable, [sys.executable, "-m", "ember", "serve", "--port", "8783"])

    def test_install_endpoint_answers_then_stops_the_server_for_the_restart(self):
        from http.client import HTTPConnection
        import json
        import threading
        from ember.executors import ExecutorRegistry
        from ember.server import LocalServer
        server = LocalServer(self.workspace, 0, executor_registry=ExecutorRegistry(Path(self.temp.name) / "home"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        installed = {"previous": __version__, "installed": "99.0.0", "source": "GitHub", "skills_refreshed": True, "system_copies_changed": []}
        with patch("ember.updates.install_update", return_value=installed) as install:
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request("POST", "/api/update/install", json.dumps({"version": "99.0.0", "confirmation": True}),
                         {"Content-Type": "application/json", "X-Ember-Token": server.csrf_token})
            response = conn.getresponse()
            data = json.loads(response.read())["data"]
            conn.close()
        thread.join(5)
        self.assertEqual((response.status, data["installed"]), (200, "99.0.0"))
        install.assert_called_once()
        self.assertFalse(thread.is_alive())
        self.assertTrue(server.restart_requested)

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
