"""Focused optional UI checks; install Playwright/Chromium for local execution."""

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gstudio_core.executors import ExecutorRegistry
from gstudio_core.server import LocalServer
from gstudio_core.store import Workspace
from test_executors import software_fixture

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Optional Playwright browser checks")
class SettingsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.home = Path(cls.temp.name) / "machine-home"
        cls.entries = software_fixture(cls.home)
        cls.registry = ExecutorRegistry(cls.home)
        cls.workspace = Workspace(Path(cls.temp.name) / "workspace")
        cls.workspace.initialize(example=True)
        cls.server = LocalServer(cls.workspace, 0, executor_registry=cls.registry)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.playwright.stop()
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join()
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        self.registry.path.unlink(missing_ok=True)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.context.close)
        self.context.add_init_script("""window.__copies=[]; Object.defineProperty(navigator,'clipboard',
            {value:{writeText:async text=>window.__copies.push(text)}});""")
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.errors, self.posts = [], []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.posts.append((request.url, request.post_data_json)) if request.method == "POST" else None)
        self.original_files = self.workspace_bytes()
        self.native = [self.home / ".codex/config.toml", self.home / ".config/opencode/opencode.jsonc"]
        for path in self.native:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("invalid private model configuration: must stay untouched\n")

    def workspace_bytes(self):
        return {str(path.relative_to(self.workspace.path)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.workspace.path.rglob("*") if path.is_file()}

    def settings(self):
        self.page.goto(self.base + "/#settings")
        self.page.locator("#software-summary[data-environment-state]").wait_for()

    def save_fixture(self):
        return self.registry.save({"executors": self.entries, "default_executor": "other-cli",
                                   "expected_revision": self.registry.snapshot()["revision"]})

    def preview(self):
        self.page.goto(self.base + "/#home")
        self.page.locator("#context-request").fill("请整理当前任务，不要发布或完成它。")
        self.page.locator("#context-prepare").click()
        self.page.locator("#context-output").wait_for()

    def assert_untouched(self):
        self.assertEqual(self.workspace_bytes(), self.original_files)
        for path in self.native:
            self.assertEqual(path.read_text(), "invalid private model configuration: must stay untouched\n")
        self.assertEqual(self.errors, [])

    def test_five_public_pages_and_retired_archive_route_on_desktop_and_mobile(self):
        routes = {'home': '任务台', 'projects': '项目视图', 'review': '任务检视', 'library': '资料浏览', 'settings': '设置'}
        for width in (1440, 1024, 390):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            for route, title in routes.items():
                self.page.goto(self.base + '/#' + route)
                self.page.locator('#main-content h1', has_text=title).wait_for()
                self.assertEqual(self.page.locator('[data-nav]').count(), 5)
                self.assertEqual(self.page.locator('a[href="#archive"]').count(), 0)
                self.assertEqual(self.page.locator('.archive-workspace').count(), 0)
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
            self.page.goto(self.base + '/#archive')
            self.page.locator('#main-content h1', has_text='页面不存在').wait_for()
            self.page.locator('#main-content a[href="#home"]').focus()
            self.page.keyboard.press('Enter')
            self.page.locator('#home-task-list').wait_for()
        self.assert_untouched()

    def test_empty_workspace_pages_have_no_archive_or_automatic_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(Path(temporary) / 'empty')
            workspace.initialize()
            before = {str(p.relative_to(workspace.path)): p.read_bytes() for p in workspace.path.rglob('*') if p.is_file()}
            server = LocalServer(workspace, 0, executor_registry=ExecutorRegistry(Path(temporary) / 'home'))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for width in (1440, 390):
                    self.page.set_viewport_size({'width': width, 'height': 1000})
                    self.page.goto(f'http://127.0.0.1:{server.server_port}/#home')
                    self.page.locator('#home-task-list .empty').wait_for()
                    self.assertEqual(self.page.locator('#home-count').inner_text(), '0')
                    self.assertEqual(self.page.locator('a[href="#archive"]').count(), 0)
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
                self.assertEqual(before, {str(p.relative_to(workspace.path)): p.read_bytes() for p in workspace.path.rglob('*') if p.is_file()})
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        self.assert_untouched()

    def test_unavailable_workspace_is_an_explicit_error_not_a_blank_success(self):
        self.page.route('**/api/state', lambda route: route.fulfill(status=503, content_type='application/json',
                                                                  body=json.dumps({'ok': False, 'error': 'fixture workspace unavailable'})))
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 1000})
            self.page.goto(self.base + '/#home')
            self.page.locator('#main-content h1', has_text='工作区读取失败').wait_for()
            self.assertIn('fixture workspace unavailable', self.page.locator('#main-content').inner_text())
            self.assertIn('不会被覆盖', self.page.locator('#main-content').inner_text())
            self.assertEqual(self.page.locator('a[href="#archive"]').count(), 0)
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
        self.assert_untouched()

    def test_guided_installation_first_task_and_three_skills_are_visible_without_completion(self):
        from gstudio_core import __version__
        from gstudio_core.onboarding import begin_installation, record_installation
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'app'
            app.mkdir()
            workspace = Workspace(Path(temporary) / 'new-data')
            workspace.initialize()
            first = begin_installation(workspace, app_dir=app, executor='opencode')
            record_installation(workspace, {**first, 'version': __version__, 'workspace': str(workspace.path),
                                'app_dir': str(app.resolve()), 'mode': 'empty', 'status': 'ready', 'stage': 'complete',
                                'checks': ['workspace-contract', 'persisted-workflow', 'loopback-health'],
                                'verification_workspace_cleaned': True, 'service_running': False})
            before = {str(p.relative_to(workspace.path)): p.read_bytes() for p in workspace.path.rglob('*') if p.is_file()}
            server = LocalServer(workspace, 0, executor_registry=ExecutorRegistry(Path(temporary) / 'home'))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                for width in (1440, 390):
                    self.page.set_viewport_size({'width': width, 'height': 1000})
                    self.page.goto(base + '/#home')
                    self.page.locator('#home-task-list', has_text='GStudio初始化验收').wait_for()
                    self.assertEqual(self.page.locator('#home-count').inner_text(), '1')
                    self.page.goto(base + '/#project/gstudio')
                    self.page.locator('#main-content h1', has_text='GStudio').wait_for()
                    self.assertIn('GStudio初始化验收', self.page.locator('#main-content').inner_text())
                    self.page.goto(base + '/#task/' + first['task_id'])
                    self.page.locator('#main-content h1', has_text='GStudio初始化验收').wait_for()
                    self.assertIn('人工验收尚未完成', self.page.locator('#main-content').inner_text())
                    self.page.goto(base + '/#settings')
                    self.page.locator('#settings-skills .core-skill').first.wait_for()
                    self.assertEqual(self.page.locator('#settings-skills .core-skill strong').all_text_contents(),
                                     ['gstudio-init', 'gstudio-core', 'gstudio-project'])
                    self.assertIn('三项基础 Skill', self.page.locator('#main-content').inner_text())
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
                self.assertEqual(before, {str(p.relative_to(workspace.path)): p.read_bytes() for p in workspace.path.rglob('*') if p.is_file()})
                self.assertEqual(workspace.snapshot()['tasks'][0]['status'], 'active')
                self.assertFalse((workspace.path / 'delivery/formal' / first['task_id']).exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        self.assert_untouched()

    def test_empty_manual_check_save_and_saved_summary_share_light_buttons(self):
        self.settings()
        self.assertEqual(self.page.locator("#default-software option").count(), 1)
        self.assertFalse(self.registry.path.exists())
        self.page.locator("#software-name").fill("我的其他助手")
        self.page.locator("#software-kind").select_option("command")
        self.page.locator("#software-path").fill(self.entries[1]["path"])
        self.page.locator("#add-software").click()
        identifier = self.page.locator("[data-software-id]").get_attribute("data-software-id")
        self.assertEqual(self.page.locator("#default-software").input_value(), "")
        self.page.locator("#default-software").select_option(identifier)
        self.page.locator("#check-software").click()
        self.page.locator('#software-editor-state[data-state="checked"]').wait_for()
        self.assertFalse(self.registry.path.exists())
        self.page.locator("#save-software").click()
        self.page.locator('#software-summary[data-environment-state="saved"]').wait_for()
        self.assertEqual(self.page.locator("#current-software-name").inner_text(), "我的其他助手")
        self.assertFalse(self.page.locator("#software-editor").is_visible())
        for width in (1440, 1024, 390):
            self.page.set_viewport_size({"width": width, "height": 1000})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        self.page.locator("#edit-software").click()
        palette = self.page.locator("#execution-environment .button").evaluate_all(
            "nodes=>nodes.filter(n=>n.getClientRects().length).map(n=>[getComputedStyle(n).backgroundColor,getComputedStyle(n).color,getComputedStyle(n).borderTopStyle])")
        self.assertEqual(len({item[0] for item in palette}), 1)
        self.assertEqual(len({item[1] for item in palette}), 1)
        self.assertTrue(all(item[2] == "solid" for item in palette))
        self.assert_untouched()

    def test_saved_draft_failed_check_and_cancel_preserve_current_environment(self):
        self.save_fixture()
        before = self.registry.path.read_bytes()
        self.settings()
        name = self.page.locator("#current-software-name").inner_text()
        self.page.locator("#edit-software").click()
        row = self.page.locator('[data-software-id="other-cli"]')
        row.locator('[data-software-field="label"]').fill("未保存的新名称")
        self.page.locator('#software-editor-state[data-state="dirty"]').wait_for()
        self.assertEqual(self.page.locator("#current-software-name").inner_text(), name)
        row.locator('[data-software-field="path"]').fill(str(self.home / "missing-program"))
        self.page.locator("#check-software").click()
        self.page.locator('#software-editor-state[data-state="error"]').wait_for()
        self.assertEqual(self.registry.path.read_bytes(), before)
        self.page.locator("#cancel-software").click()
        self.assertFalse(self.page.locator("#software-editor").is_visible())
        self.assertTrue(self.page.locator("#edit-software").evaluate("node=>node===document.activeElement"))
        self.assertEqual(self.page.locator("#current-software-name").inner_text(), name)
        self.assert_untouched()

    def test_discovery_is_explicit_text_safe_and_does_not_save_or_choose_default(self):
        result = {"candidates": [{**self.entries[1], "label": '<img src=x onerror="window.bad=1">', "source": "本机目录"}],
                  "warnings": [], "limited": False, "scope": "只读查找"}
        with patch.object(self.registry, "discover", return_value=result) as discover:
            self.settings()
            discover.assert_not_called()
            self.page.locator("#find-software").click()
            self.page.locator('[data-action="add-found-software"]').wait_for()
            self.assertEqual(self.page.locator("#software-candidates img").count(), 0)
            self.page.locator('[data-action="add-found-software"]').press("Enter")
            self.assertEqual(self.page.locator("[data-software-id]").count(), 1)
            self.assertEqual(self.page.locator("#default-software").input_value(), "")
            self.assertFalse(self.registry.path.exists())
            discover.assert_called_once_with()
        self.assert_untouched()

    def test_context_copy_and_confirmed_open_do_not_send_context_or_change_tasks(self):
        self.save_fixture()
        opened = {"opened": True, "label": self.entries[1]["label"], "submitted": False, "model_called": False}
        with patch.object(self.registry, "open_software", return_value=opened) as launch:
            self.preview()
            launch.assert_not_called()
            self.page.locator("#copy-context-button").click()
            self.assertEqual(len(self.page.evaluate("window.__copies")), 1)
            launch.assert_not_called()
            self.page.locator("#copy-open-context-button").click()
            self.page.wait_for_function("()=>document.getElementById('notice').textContent.includes('请手工粘贴')")
            launch.assert_called_once()
            payload, workspace = launch.call_args.args
            self.assertEqual(set(payload), {"executor_id", "expected_revision", "confirmation"})
            self.assertTrue(payload["confirmation"])
            self.assertEqual(workspace, self.workspace.path)
            self.assertTrue(self.page.locator("#context-output").is_visible())
        self.assert_untouched()

    def test_clipboard_failure_and_stale_saved_configuration_never_launch_a_program(self):
        self.save_fixture()
        self.preview()
        with patch.object(self.registry, "open_software") as launch:
            self.page.evaluate("()=>{navigator.clipboard.writeText=async()=>{throw new Error('denied')}}")
            self.page.locator("#copy-open-context-button").click()
            self.page.wait_for_function("()=>document.getElementById('notice').textContent.includes('没有打开')")
            launch.assert_not_called()
        self.page.evaluate("()=>{navigator.clipboard.writeText=async text=>window.__copies.push(text)}")
        payload = {"executors": [{**entry, "label": entry["label"] + "已修改"} for entry in self.entries],
                   "default_executor": "other-cli", "expected_revision": self.registry.snapshot()["revision"]}
        self.registry.save(payload)
        with patch("gstudio_core.executors.subprocess.run") as run:
            self.page.locator("#copy-open-context-button").click()
            self.page.wait_for_function("()=>document.getElementById('notice').textContent.includes('已改变')")
            run.assert_not_called()
        self.assert_untouched()

    def test_unreadable_configuration_is_unknown_not_an_empty_success(self):
        self.registry.path.parent.mkdir(parents=True, exist_ok=True)
        self.registry.path.write_text("broken configuration - preserve me")
        before = self.registry.path.read_bytes()
        self.settings()
        self.assertEqual(self.page.locator("#software-summary").get_attribute("data-environment-state"), "unavailable")
        self.assertIn("暂不可读", self.page.locator("#software-summary").inner_text())
        self.assertTrue(self.page.locator("#software-editor").is_visible())
        self.assertEqual(self.registry.path.read_bytes(), before)
        self.assert_untouched()
