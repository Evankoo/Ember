"""Focused optional UI checks; install Playwright/Chromium for local execution."""

import hashlib
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ember.executors import ExecutorRegistry
from ember.server import LocalServer
from ember.store import Workspace
from test_executors import software_fixture

try:
    from playwright.sync_api import expect, sync_playwright
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

    def test_project_page_shows_registered_working_directories(self):
        location = str(Path(self.temp.name) / "code/chenyu-site")
        self.workspace.update_project_locations("chenyu", {"add": location})
        self.addCleanup(self.workspace.update_project_locations, "chenyu", {"remove": location})
        self.page.goto(self.base + "/#project/chenyu")
        # Registered after the card was written: shown once, in the location strip.
        expect(self.page.locator(".project-location-strip code", has_text=location)).to_be_visible()
        expect(self.page.locator(".context-reader-timeline li")).to_have_count(2)
        expect(self.page.locator(".project-entry-row")).to_have_count(1)
        self.page.goto(self.base + "/#project/studio")
        expect(self.page.locator("main h1")).to_contain_text("栖木")
        expect(self.page.locator(".project-location-strip code")).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_task_page_fits_just_above_the_drawer_breakpoint(self):
        self.page.goto(self.base + "/#task/autumn-plan")
        expect(self.page.locator("main h1")).to_have_text("秋季内容方案")
        for width in (1181, 1200, 1215, 1240):
            self.page.set_viewport_size({"width": width, "height": 900})
            right = self.page.locator(".task-delivery-workspace").evaluate("e => e.getBoundingClientRect().right")
            self.assertLessEqual(right, width, width)
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), width)
        self.assert_untouched()

    def test_task_page_lists_log_rows_and_folds_program_records(self):
        def with_logs(route):
            state = route.fetch().json()
            item = next(task for task in state["data"]["tasks"] if task["id"] == "autumn-plan")
            item["executor"] = "claude-code"
            item["logs"] = [{"date": "2026-10-14 12:07:22+08:00", "text": "人工记录 `a`。"},
                            {"date": "2026-10-14 12:00:05+08:00", "text": "添加输入快照：b.md。"},
                            {"date": "2026-10-14 12:00:04+08:00", "text": "添加输入快照：c.md。"},
                            {"date": "", "text": "2026-10-13 09:00:00+08:00：旧式记录。"}]
            route.fulfill(json=state)
        self.page.route("**/api/state", with_logs)
        self.page.goto(self.base + "/#task/autumn-plan")
        log = self.page.locator(".task-execution-log")
        expect(log.locator(".task-log-entry")).to_have_count(3)
        expect(log.locator(".task-log-entry").first.locator("time")).to_have_text("2026-10-14 12:07")
        expect(log.locator("summary")).to_have_text("添加输入快照 · 2 条")
        expect(log.locator(".task-log-entry").last.locator("time")).to_have_text("2026-10-13 09:00")
        expect(self.page.locator(".task-technical-info h3")).to_have_text("技术信息")
        expect(self.page.locator(".task-technical-summary")).to_contain_text("执行器 Claude Code")
        expect(self.page.locator(".task-delivery-file .task-file-kind").first).to_have_text("MD")
        expect(self.page.locator(".task-file-preview .article h1, .task-file-preview .article h2").first).to_be_visible()
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        self.assert_untouched()

    def test_home_requires_a_request_before_confirming(self):
        self.page.goto(self.base + "/#home")
        for value in ("", "   "):
            self.page.locator("#context-request").fill(value)
            self.page.locator("#context-prepare").click()
            expect(self.page.locator("#notice")).to_have_text("请先描述本轮要求")
            self.assertFalse(self.page.locator("#home-confirm-dialog").evaluate("node => node.open"))
        self.page.locator("#context-request").fill("整理活动资料")
        self.page.locator("#context-prepare").click()
        self.page.locator("#prompt-state.ready").wait_for()
        expect(self.page.locator("#confirm-request")).to_have_value("整理活动资料")
        self.page.locator("#confirm-request").fill("改过的任务")
        self.page.locator('[data-action="confirm-reset"]').click()
        expect(self.page.locator("#confirm-request")).to_have_value("整理活动资料")
        expect(self.page.locator("#prompt-preview")).to_contain_text("授权边界")
        expect(self.page.locator('input[name="confirm-route"][value="continue"]')).to_be_disabled()
        self.assert_untouched()

    def test_task_page_previews_files_and_opens_the_drawer_when_narrow(self):
        self.page.goto(self.base + "/#task/autumn-plan")
        expect(self.page.locator("#task-file-preview-title")).to_have_text("秋季内容方案V0.2草稿.md")
        expect(self.page.locator(".task-preview-actions")).to_contain_text("Finder 中显示")
        self.page.locator('[data-action="task-files"][data-id="input"]').click()
        first = self.page.locator(".task-input-row .task-input-name").first
        name = first.inner_text()
        first.click()
        expect(self.page.locator("#task-file-preview-title")).to_have_text(name)
        self.page.set_viewport_size({"width": 1000, "height": 900})
        expect(self.page.locator("#task-material-toggle")).to_be_visible()
        self.page.locator("#task-material-toggle").click()
        expect(self.page.locator("#task-materials")).to_have_class(re.compile("is-open"))
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#task-materials")).not_to_have_class(re.compile("is-open"))
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        self.assert_untouched()

    def test_update_button_shows_the_release_and_a_copyable_prompt(self):
        newer = {"tag": "v99.0.0", "url": "https://github.com/Evankoo/Ember/releases/tag/v99.0.0",
                 "published_at": "2026-10-20", "notes": "<img src=x onerror=window.bad=1> 新功能"}
        with patch("ember.updates.fetch_latest", return_value=newer):
            self.page.goto(self.base + "/#library")
            expect(self.page.locator("#update-button")).to_be_visible()
            self.page.locator("#update-button").click()
            expect(self.page.locator(".update-summary")).to_contain_text("发现新版本 99.0.0")
            self.assertEqual(self.page.locator(".update-notes img").count(), 0)
            self.page.locator('[data-action="copy-update"]').click()
            expect(self.page.locator("#update-feedback")).to_contain_text("已复制")
            self.assertIn("ember-99.0.0-py3-none-any.whl", self.page.evaluate("window.__copies")[-1])
        self.page.locator("#dialog-close").click()
        with patch("ember.updates.fetch_latest", side_effect=OSError("offline")):
            self.page.locator("#update-button").click()
            expect(self.page.locator(".update-summary")).to_contain_text("没能检查更新")
        self.assertFalse(self.page.evaluate("Boolean(window.bad)"))
        self.assert_untouched()

    def test_project_task_list_filters_without_losing_search_focus(self):
        self.page.goto(self.base + "/#project/chenyu")
        expect(self.page.locator(".project-task-row")).to_have_count(5)
        search = self.page.locator("#project-search")
        search.press_sequentially("秋季")
        expect(self.page.locator(".project-task-row")).to_have_count(3)
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "project-search")
        search.fill("")
        self.page.locator('[data-action="project-task-filter"][data-id="completed"]').click()
        expect(self.page.locator(".project-task-row")).to_have_count(1)
        expect(self.page.locator(".project-task-row a")).to_have_text("五月内容方案")
        self.page.locator('.project-task-row a').click()
        expect(self.page.locator("main h1")).to_have_text("五月内容方案")
        self.assert_untouched()

    def workspace_bytes(self):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for root in (self.workspace.path, self.workspace.docs) for path in root.rglob("*") if path.is_file()}

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
        self.page.locator("#prompt-state.ready").wait_for()

    def assert_untouched(self):
        self.assertEqual(self.workspace_bytes(), self.original_files)
        for path in self.native:
            self.assertEqual(path.read_text(), "invalid private model configuration: must stay untouched\n")
        self.assertEqual(self.errors, [])

    def test_five_public_pages_and_retired_archive_route_on_desktop_and_mobile(self):
        routes = {'home': '想让 AI 帮你做什么', 'projects': '项目视图', 'review': '任务检视', 'library': '资料浏览', 'settings': '设置'}
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

    def test_guided_installation_empty_then_daily_first_task_and_confirmed_removal(self):
        from urllib.request import Request, urlopen
        from ember import __version__
        from ember.onboarding import begin_installation, record_installation
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'app'
            app.mkdir()
            workspace = Workspace(Path(temporary) / 'new-data')
            workspace.initialize()
            system = begin_installation(workspace, app_dir=app, executor='opencode')
            receipt = {**system, 'version': __version__, 'workspace': str(workspace.path),
                       'app_dir': str(app.resolve()), 'mode': 'empty', 'status': 'ready', 'stage': 'complete',
                       'checks': ['workspace-contract', 'persisted-workflow', 'loopback-health'],
                       'verification_workspace_cleaned': True, 'service_running': False}
            (app / 'installation.json').write_text(json.dumps(receipt))
            record_installation(workspace, receipt)
            self.assertEqual(workspace.snapshot()['tasks'], [])
            server = LocalServer(workspace, 0, executor_registry=ExecutorRegistry(Path(temporary) / 'home'))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'

            def post(path, payload):
                request = Request(base + path, data=json.dumps(payload).encode(), method='POST',
                                  headers={'Content-Type': 'application/json', 'X-Ember-Token': server.csrf_token})
                with urlopen(request) as response:
                    return json.load(response)['data']

            try:
                self.page.goto(base + '/#home')
                expect(self.page.locator('#home-count')).to_have_text('0')
                first = post('/api/tasks', {'title': '余烬首次使用', 'project': 'ember',
                    'work_type': 'system', 'artifact_mode': 'none', 'executor': 'opencode',
                    'skills_used': ['ember-init', 'ember'], 'goal': '安装并完成新手实操'})
                post('/api/tasks/' + first['id'] + '/materials', {'kind': 'input', 'name': '安装记录.json',
                    'source_locator': 'ember-init:installation-receipt', 'content': json.dumps(receipt)})
                post('/api/tasks/' + first['id'], {'current': '真实对话已整理，等待用户检查任务卡。',
                     'next': '用户检查 OK 后再创建练习项目。', 'log_entry': '日常 Skill 创建第一张任务卡。'})
                for width in (1440, 390):
                    self.page.set_viewport_size({'width': width, 'height': 1000})
                    self.page.goto(base + '/#home')
                    self.page.reload()
                    self.page.locator('#home-task-list', has_text='余烬首次使用').wait_for()
                    self.assertEqual(self.page.locator('#home-count').inner_text(), '1')
                    self.page.goto(base + '/#task/' + first['id'])
                    self.page.locator('#main-content h1', has_text='余烬首次使用').wait_for()
                    self.assertIn('等待用户检查任务卡', self.page.locator('#main-content').inner_text())
                    self.page.goto(base + '/#settings')
                    self.page.locator('#settings-skills .compact-skill-row').first.wait_for()
                    self.assertEqual(self.page.locator('#settings-skills .compact-skill-row strong').all_text_contents(),
                                     ['ember-init', 'ember', 'ember-project'])
                self.assertEqual(workspace.snapshot()['tasks'][0]['status'], 'active')
                post('/api/projects', {'id': 'practice', 'name': '余烬练习项目', 'kind': 'project',
                    'description': '隔离测试中模拟用户确认的练习', 'overview': '# 余烬练习项目'})
                post('/api/tasks/' + first['id'], {'skills_used': ['ember-project'],
                    'current': '隔离测试模拟完成引导与最终确认。', 'log_entry': '测试夹具确认建项，模拟最终完成与移除确认。'})
                post('/api/tasks/' + first['id'] + '/complete', {'confirmation': True})
                post('/api/onboarding/remove-init-skill', {'task_id': first['id'], 'confirmation': True})
                for width in (1440, 390):
                    self.page.set_viewport_size({'width': width, 'height': 1000})
                    self.page.goto(base + '/#settings')
                    self.page.reload()
                    expect(self.page.locator('#settings-skills .compact-skill-row')).to_have_count(2)
                    self.assertEqual(self.page.locator('#settings-skills .compact-skill-row strong').all_text_contents(),
                                     ['ember', 'ember-project'])
                    self.assertNotIn('三项基础 Skill', self.page.locator('#main-content').inner_text())
                    self.page.goto(base + '/#project/practice')
                    self.page.locator('#main-content h1', has_text='余烬练习项目').wait_for()
                    self.page.goto(base + '/#task/' + first['id'])
                    self.page.locator('#main-content h1', has_text='余烬首次使用').wait_for()
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
                state = workspace.snapshot()
                self.assertEqual((len(state['projects']), len(state['tasks'])), (2, 1))
                self.assertEqual(state['tasks'][0]['status'], 'completed')
                self.assertFalse((workspace.path / '.agents/skills/ember-init').exists())
                self.assertFalse((workspace.path / '交付/正式交付' / first['id']).exists())
                self.assertTrue((app / 'installation-report.md').is_file())
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
        # The only program in the list becomes the default automatically.
        self.assertEqual(self.page.locator("#default-software").input_value(), identifier)
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
        # Measure resting styles: no button under the pointer, transitions finished.
        self.page.mouse.move(0, 0)
        self.page.wait_for_timeout(300)
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

    def test_discovery_is_explicit_text_safe_and_choosing_sets_the_default_without_saving(self):
        result = {"candidates": [{**self.entries[1], "label": '<img src=x onerror="window.bad=1">', "source": "本机目录"}],
                  "warnings": [], "limited": False, "scope": "只读查找"}
        with patch.object(self.registry, "discover", return_value=result) as discover:
            self.settings()
            discover.assert_not_called()
            self.page.locator("#find-software").click()
            choose = self.page.locator('[data-action="choose-found-software"]')
            choose.wait_for()
            self.assertEqual(self.page.locator("#software-candidates img").count(), 0)
            # Results open directly under the find button, in a height-limited list.
            panel = self.page.locator("#software-candidates").bounding_box()
            found = self.page.locator("#find-software").bounding_box()
            self.assertLess(panel["y"] - (found["y"] + found["height"]), 40)
            self.assertEqual(self.page.locator(".software-candidate-list").evaluate("node => getComputedStyle(node).overflowY"), "auto")
            self.assertEqual(choose.inner_text(), "选用")
            choose.press("Enter")
            self.assertEqual(self.page.locator("[data-software-id]").count(), 1)
            identifier = self.page.locator("[data-software-id]").get_attribute("data-software-id")
            self.assertEqual(self.page.locator("#default-software").input_value(), identifier)
            self.assertTrue(self.page.locator("#software-candidates").is_hidden())
            self.assertEqual(self.page.evaluate("document.activeElement.id"), "default-software")
            self.assertIn("尚未保存", self.page.locator("#software-editor-state").inner_text())
            # Searching again marks it as already listed instead of offering it twice.
            self.page.locator("#find-software").click()
            again = self.page.locator('[data-action="choose-found-software"]')
            again.wait_for()
            self.assertEqual(again.inner_text(), "设为默认")
            self.page.locator('[data-action="close-found-software"]').click()
            self.assertTrue(self.page.locator("#software-candidates").is_hidden())
            self.assertFalse(self.registry.path.exists())
            self.assertEqual(discover.call_count, 2)
        self.assert_untouched()

    def test_saving_without_a_default_points_to_the_default_field(self):
        self.settings()
        for name, entry in (("第一个助手", self.entries[0]), ("第二个助手", self.entries[1])):
            self.page.locator("#software-name").fill(name)
            self.page.locator("#software-kind").select_option(entry["kind"])
            self.page.locator("#software-path").fill(entry["path"])
            self.page.locator("#add-software").click()
        self.assertEqual(self.page.locator("[data-software-id]").count(), 2)
        self.page.locator("#default-software").select_option("")
        self.page.locator("#save-software").click()
        self.assertIn("选择默认软件", self.page.locator("#software-editor-state").inner_text())
        self.assertEqual(self.page.locator("#software-editor-state").get_attribute("data-state"), "error")
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "default-software")
        self.assertIn("needs-choice", self.page.locator("#software-default-field").get_attribute("class"))
        self.assertFalse(self.registry.path.exists())
        self.page.locator("#default-software").select_option(index=1)
        self.assertNotIn("needs-choice", self.page.locator("#software-default-field").get_attribute("class"))
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
            self.page.wait_for_function("()=>document.getElementById('confirm-feedback').textContent.includes('已打开')")
            launch.assert_called_once()
            payload, workspace = launch.call_args.args
            self.assertEqual(set(payload), {"executor_id", "expected_revision", "confirmation"})
            self.assertTrue(payload["confirmation"])
            self.assertEqual(workspace, self.workspace.path)
            copies = self.page.evaluate("window.__copies")
            self.assertEqual(copies[0], copies[1])
            self.assertTrue(copies[0].startswith("## 余烬 · Ember 共享任务提示\n\n### 任务\n\n请整理当前任务"))
        self.assert_untouched()

    def test_clipboard_failure_and_stale_saved_configuration_never_launch_a_program(self):
        self.save_fixture()
        self.preview()
        with patch.object(self.registry, "open_software") as launch:
            self.page.evaluate("()=>{navigator.clipboard.writeText=async()=>{throw new Error('denied')}}")
            self.page.locator("#copy-open-context-button").click()
            self.page.wait_for_function("()=>document.getElementById('confirm-feedback').textContent.includes('复制失败')")
            self.assertTrue(self.page.locator("#confirm-feedback").is_visible())
            launch.assert_not_called()
        self.page.evaluate("()=>{navigator.clipboard.writeText=async text=>window.__copies.push(text)}")
        payload = {"executors": [{**entry, "label": entry["label"] + "已修改"} for entry in self.entries],
                   "default_executor": "other-cli", "expected_revision": self.registry.snapshot()["revision"]}
        self.registry.save(payload)
        with patch("ember.executors.subprocess.run") as run:
            self.page.locator("#copy-open-context-button").click()
            self.page.wait_for_function("()=>document.getElementById('confirm-feedback').textContent.includes('已改变')")
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
