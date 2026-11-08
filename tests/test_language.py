"""The workspace language: chosen once at creation, Chinese by default, English throughout when chosen."""
from http.client import HTTPConnection
import io
import json
import re
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ember import cli, i18n, language
from ember.bootstrap import init_routes, skill_tree
from ember.executors import ExecutorRegistry
from ember.locator import _source_tree, install_skill
from ember.server import LocalServer
from ember.store import Workspace, WorkspaceError
from ember.tasks import PortableTaskStorage, TaskService

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

HAN = re.compile(r"[一-鿿]")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/ember/skills/ember-init/scripts"))
import bootstrap as installer  # noqa: E402


def chinese_files(root: Path) -> list[str]:
    return [str(path.relative_to(root)) for path in root.rglob("*")
            if path.is_file() and path.suffix in {".md", ".json", ".yaml", ".txt"} and HAN.search(path.read_text(encoding="utf-8"))]


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def english(self, example=False):
        workspace = Workspace(self.base / "Ember", language="en")
        workspace.initialize(example=example)
        return workspace

    def test_a_workspace_without_a_language_is_chinese_and_unchanged(self):
        workspace = Workspace(self.base / "Ember")
        workspace.initialize()
        self.assertEqual((workspace.language, workspace.docs.name), ("zh", "Ember文档"))
        self.assertNotIn("language", json.loads((workspace.path / "config/workspace.json").read_text()))
        for folder in ("任务资料", "交付/草稿", "交付/正式交付", "项目", "管理中心/整理记录"):
            self.assertTrue((workspace.docs / folder).is_dir(), folder)
        task = workspace.create_task({"title": "写方案", "project": "independent", "goal": "形成方案"})
        card = (workspace.docs / "tasks/active" / f"{task['id']}.md").read_text()
        self.assertIn("## 任务目标", card)
        self.assertIn("用户创建任务；初始状态 active。", card)

    def test_an_english_workspace_is_english_throughout(self):
        workspace = self.english()
        self.assertEqual(workspace.docs.name, "EmberDocs")
        self.assertEqual(json.loads((workspace.path / "config/workspace.json").read_text())["language"], "en")
        for folder in ("Inputs", "Deliverables/Drafts", "Deliverables/Final", "Projects", "Admin/Reviews", "Inbox"):
            self.assertTrue((workspace.docs / folder).is_dir(), folder)
        workspace.create_project({"id": "site", "name": "Website", "kind": "project", "description": "A new website."})
        task = workspace.create_task({"title": "Write the homepage copy for the new website", "project": "site",
                                      "goal": "A homepage draft"})
        workspace.add_material(task["id"], {"kind": "input", "name": "notes.md", "content": "notes"})
        workspace.add_material(task["id"], {"kind": "draft", "name": "draft.md", "content": "draft"})
        workspace.update_task(task["id"], {"current": "Draft written."})
        workspace.promote_task(task["id"], {"confirmation": True})
        self.assertTrue((workspace.docs / "Deliverables/Final" / task["id"] / "draft.md").is_file())
        card = (workspace.docs / "tasks/completed" / f"{task['id']}.md").read_text()
        for heading in ("## Goal", "## Description", "## Current Result", "## Execution Log", "[Open task folder]"):
            self.assertIn(heading, card)
        self.assertEqual(chinese_files(workspace.docs), [])
        self.assertEqual(chinese_files(workspace.path / "templates"), [])
        for name in ("AGENTS.md", "SOUL.md", "MEMORY.md", "RESOLVER.md", "WORKBENCH_DESIGN.md"):
            self.assertIsNone(HAN.search((workspace.path / name).read_text()), name)
        for skill in ("ember", "ember-project", "ember-init"):
            text = (workspace.path / ".agents/skills" / skill / "SKILL.md").read_text()
            self.assertFalse((workspace.path / ".agents/skills" / skill / "locale").exists())
            # The init guide's language question is the only Chinese an English installation keeps.
            self.assertIsNone(HAN.search(text.replace("go back to the Chinese", "")), skill)
        detail = workspace.snapshot()["tasks"][0]
        self.assertEqual((detail["goal"], detail["current"]), ("A homepage draft", "Draft written."))

    def test_prompts_for_an_english_workspace_are_english(self):
        workspace = self.english()
        task = workspace.create_task({"title": "Plan", "project": "independent", "goal": "A plan"})
        texts = [workspace.build_context({"request": "Help me", "relation": relation, "page": "task", "task_id": task["id"],
                                          "attachments": [{"name": "a.txt", "text": "one\ntwo"}]})["text"]
                 for relation in ("continue", "based")]
        texts.append(workspace.build_context({"request": "Help me", "relation": "new", "page": "home"})["text"])
        texts.append(workspace.build_review_context({"task_ids": [task["id"]]})["text"])
        texts.append(workspace.build_weekly_context({})["text"])
        for text in texts:
            self.assertIsNone(HAN.search(text), text)
            self.assertTrue(text.startswith("## Ember Shared Task Prompt\n\n### Task\n\n"))

    def test_the_language_is_locked_once_created(self):
        self.english()
        with self.assertRaises(WorkspaceError) as caught:
            Workspace(self.base / "Ember", language="zh")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(Workspace(self.base / "Ember").language, "en")
        with self.assertRaises(WorkspaceError):
            Workspace(self.base / "Other", language="fr")
        config = self.base / "Ember/config/workspace.json"
        config.write_text(json.dumps({**json.loads(config.read_text()), "language": "de"}))
        with self.assertRaises(WorkspaceError):
            Workspace(self.base / "Ember")

    def test_english_titles_and_categories_have_room(self):
        english = self.english()
        title = "Prepare the quarterly report for the board"
        english.create_task({"title": title, "project": "independent", "goal": "Report"})
        service = TaskService(PortableTaskStorage(english))
        self.assertEqual([row["title"] for row in service.list()], [title])
        english.create_project({"id": "site", "name": "Site", "kind": "project", "description": "x", "category": "Client work for the spring season"})
        chinese = Workspace(self.base / "Chinese")
        chinese.initialize()
        with self.assertRaises(WorkspaceError):
            chinese.create_task({"title": "一" * 21, "project": "independent", "goal": "目标"})

    def test_the_english_example_is_complete_and_registers_like_the_chinese_one(self):
        workspace = self.english(example=True)
        state = workspace.snapshot()
        self.assertEqual((len(state["projects"]), len(state["tasks"])), (2, 8))
        self.assertEqual({item["label"] for item in state["inbox"]}, {"未分类", "处理中", "待归档", "可删除"})
        self.assertEqual(chinese_files(workspace.docs), [])
        from ember.onboarding import begin_installation
        app = workspace.path / "app"
        app.mkdir()
        self.assertEqual(begin_installation(workspace, app_dir=app, mode="example")["system_project_path"], "Projects/ember/Project.md")
        self.assertIsNone(HAN.search((workspace.docs / "Projects/ember/Project.md").read_text()))

    def test_init_routes_exist_once_so_the_guide_can_be_removed(self):
        workspace = self.english()
        route, root_route = init_routes("en")
        self.assertEqual((workspace.path / "skills/RESOLVER.md").read_text().splitlines().count(route), 1)
        self.assertEqual((workspace.path / "RESOLVER.md").read_text().splitlines().count(root_route), 1)

    def test_the_daily_skill_follows_the_default_workspace_language(self):
        self.assertEqual(_source_tree("zh"), skill_tree("ember", "zh"))
        self.assertNotIn("locale/en/SKILL.md", _source_tree("zh"))
        home = self.base / "home"
        workspace = self.english()
        (home / ".config/ember").mkdir(parents=True)
        (home / ".config/ember/workspace.json").write_text(json.dumps({"version": 1, "workspace": str(workspace.path)}))
        result = install_skill(home / ".claude/skills", home=home)
        installed = (Path(result["path"]) / "SKILL.md").read_text()
        self.assertIn("# Ember Daily Tasks", installed)
        self.assertFalse((Path(result["path"]) / "locale").exists())


class UpdateTests(unittest.TestCase):
    def test_new_translations_are_not_reported_as_changes_to_a_chinese_workspace(self):
        import zipfile
        from ember import updates
        package = updates.PACKAGE.parent
        with tempfile.TemporaryDirectory() as temp:
            wheel = Path(temp) / "ember.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                for prefix in updates.SYSTEM_COPIES:
                    for path in (package / prefix).rglob("*"):
                        if path.is_file() and "__pycache__" not in path.parts:
                            name = path.relative_to(package).as_posix()
                            data = path.read_bytes()
                            if name == "ember/skills/ember/locale/en/SKILL.md":
                                data += b"\nA newer English line.\n"
                            archive.writestr(name, data)
            self.assertEqual(updates.changed_system_copies(wheel, "zh"), [])
            self.assertEqual(updates.changed_system_copies(wheel, "en"), ["ember Skill"])

    def test_the_update_prompt_follows_the_workspace_language(self):
        from ember import updates
        with tempfile.TemporaryDirectory() as temp:
            english = Workspace(Path(temp) / "Ember", language="en")
            english.initialize()
            text = updates.update_prompt(english, "9.9.9")["text"]
            self.assertIsNone(HAN.search(text), text)
            self.assertIn("Update Ember on this computer from", text)
            chinese = Workspace(Path(temp) / "Chinese")
            chinese.initialize()
            self.assertIn("把本机余烬从", updates.update_prompt(chinese, "9.9.9")["text"])


class Served:
    def serve(self, language_code):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        workspace = Workspace(Path(temp.name) / "Ember", language=language_code)
        workspace.initialize(example=True)
        server = LocalServer(workspace, 0, executor_registry=ExecutorRegistry(Path(temp.name) / "home"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        return server

    def get(self, server, path):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        result = response.status, response.read().decode()
        connection.close()
        return result


class LanguageInterfaceTests(Served, unittest.TestCase):
    def test_chinese_pages_load_no_translation(self):
        server = self.serve("zh")
        page = self.get(server, "/")[1]
        self.assertIn('<html lang="zh-CN">', page)
        self.assertNotIn("i18n", page)
        self.assertEqual(self.get(server, "/i18n-catalog.js"), (200, ""))
        self.assertEqual(json.loads(self.get(server, "/api/nope")[1])["error"], "接口不存在")

    def test_english_pages_translate_text_and_errors(self):
        server = self.serve("en")
        page = self.get(server, "/")[1]
        self.assertIn('<html lang="en">', page)
        self.assertLess(page.index('src="i18n-catalog.js"'), page.index('src="i18n.js"'))
        self.assertLess(page.index('src="i18n.js"'), page.index('src="ember_ui/ember-ui.js"'))
        status, catalog = self.get(server, "/i18n-catalog.js")
        data = json.loads(catalog.removeprefix("window.EMBER_TEXT=").rstrip(";\n"))
        self.assertEqual(data["exact"]["收藏项目"], "Favorite projects")
        self.assertTrue(all(re.compile(source.replace("(?<", "(?P<")) for source, _ in data["patterns"]))
        self.assertEqual(json.loads(self.get(server, "/api/nope")[1])["error"], "No such endpoint")
        self.assertEqual(self.get(server, "/i18n.js")[0], 200)
        # Python callers translate the same catalog; Chinese stays the identity.
        self.assertEqual(language.text("en", "执行器 {name}", name="Codex"), "Executor Codex")
        self.assertEqual(language.text("zh", "执行器 {name}", name="Codex"), "执行器 Codex")
        self.assertEqual(i18n.language(), "zh")

    def test_catalog_placeholders_match(self):
        from ember.locales.en import CATALOG
        field = re.compile(r"\{(\w+)\}")
        for source, target in CATALOG.items():
            self.assertEqual(sorted(field.findall(source)), sorted(field.findall(target)), source)
            self.assertIsNone(HAN.search(target), source)


@unittest.skipIf(sync_playwright is None, "Optional Playwright browser checks")
class EnglishPagesInBrowserTests(Served, unittest.TestCase):
    """Every page of the English example, at the three widths compared with the full workbench, shows no Chinese and no horizontal overflow."""
    ROUTES = ("#home", "#projects", "#project/chenyu", "#project/ember", "#task/autumn-plan", "#task/chenyu-line",
              "#task/may-plan", "#review", "#library", "#settings")
    LEFTOVERS = r"""() => {
      const han = /[\u4e00-\u9fff]/, out = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) { const v = walker.currentNode.nodeValue.trim(); if (v && han.test(v)) out.push(v); }
      for (const el of document.querySelectorAll('[placeholder],[title],[aria-label],[alt]'))
        for (const a of ['placeholder', 'title', 'aria-label', 'alt']) { const v = el.getAttribute(a); if (v && han.test(v)) out.push(a + '=' + v); }
      if (han.test(document.title)) out.push(document.title);
      return out;
    }"""

    def test_every_english_page_is_translated_and_fits(self):
        server = self.serve("en")
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch()
        except Exception as error:
            self.skipTest(f"Chromium unavailable: {error}")
        try:
            for width in (1440, 1000, 390):
                page = browser.new_page(viewport={"width": width, "height": 900})
                for route in self.ROUTES:
                    page.goto(f"http://127.0.0.1:{server.server_port}/{route}")
                    page.wait_for_timeout(700)
                    with self.subTest(width=width, route=route):
                        self.assertEqual(page.evaluate(self.LEFTOVERS), [])
                        self.assertLessEqual(page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"), 1)
                page.close()
        finally:
            browser.close()
            playwright.stop()


class LanguageChoiceTests(unittest.TestCase):
    def test_ember_init_never_defaults_to_chinese_silently(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(sys, "stdin", io.StringIO("")), \
                patch.object(sys, "stderr", io.StringIO()) as error:
            self.assertEqual(cli.main(["init", str(Path(temp) / "Ember")]), 1)
            self.assertIn("--language", error.getvalue())
            self.assertFalse((Path(temp) / "Ember").exists())
            with patch.object(sys, "stdout", io.StringIO()) as output:
                self.assertEqual(cli.main(["init", str(Path(temp) / "Ember"), "--language", "en"]), 0)
            self.assertIn("Document library created:", output.getvalue())
            self.assertTrue((Path(temp) / "EmberDocs/Deliverables/Drafts").is_dir())

    def test_the_terminal_question_is_bilingual(self):
        answers = iter(["", "3", "English"])
        with patch.object(sys, "stdin") as stdin:
            stdin.isatty.return_value = True
            self.assertEqual(cli.ask_language(read=lambda prompt: next(answers)), "en")
        self.assertIn("中文", cli.LANGUAGE_QUESTION)
        self.assertIn("English", cli.LANGUAGE_QUESTION)

    def test_the_installer_requires_a_language_and_names_the_library_by_it(self):
        with patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit):
            installer.main(["--mode", "empty"])
        with tempfile.TemporaryDirectory() as temp:
            for code, folder in (("zh", "Ember文档"), ("en", "EmberDocs")):
                installer.LANGUAGE = code
                args = type("Args", (), dict(workspace=str(Path(temp) / "Ember"), documents=None, app_dir=None, name="Ember",
                                            executor="manual", port=0, source=None))()
                args.port = 8783 if code == "zh" else 8784
                try:
                    _, _, documents, _ = installer.validate(args)
                except OSError:
                    self.skipTest("port in use")
                self.assertEqual(documents.name, folder)
        installer.LANGUAGE = "zh"

    def test_the_init_skill_asks_for_the_language_first(self):
        skill = (ROOT / "src/ember/skills/ember-init/SKILL.md").read_text()
        phases = re.findall(r"(?m)^### (.+)$", skill)
        self.assertTrue(phases[0].startswith("0. 先选择语言"))
        self.assertIn("Welcome to Ember. Before we begin, please choose a language:", skill)
        self.assertIn("locale/en/SKILL.md", skill)
        english = (ROOT / "src/ember/skills/ember-init/locale/en/SKILL.md").read_text()
        self.assertIn("--language en", english)


if __name__ == "__main__":
    unittest.main()
