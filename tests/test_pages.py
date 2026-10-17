"""Page data for the shared templates comes only from this workspace's snapshot."""
import re
import tempfile
import unittest
from pathlib import Path

from ember.pages import report_preview, review_page_data, review_search, card_sections, file_preview, home_page_data, home_search, project_page, render_home, render_project, render_task, task_page, task_preview
from ember.store import Workspace


class TaskPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        workspace = Workspace(Path(cls.temp.name) / "Ember")
        workspace.initialize(example=True)
        cls.snapshot = workspace.snapshot()
        cls.workspace = workspace

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def task(self, task_id):
        return next(item for item in self.snapshot["tasks"] if item["id"] == task_id)

    def test_logs_keep_order_and_fold_program_records(self):
        item = self.task("autumn-plan")
        saved = item["logs"]
        item["logs"] = [{"date": "2026-10-14 12:07:22+08:00", "text": "人工记录 `a`。"},
                        {"date": "2026-10-14 12:00:05+08:00", "text": "添加输入快照：b.md。"},
                        {"date": "2026-10-14 12:00:04+08:00", "text": "添加输入快照：c.md。"},
                        {"date": "", "text": "2026-10-13 09:00:00+08:00：旧式记录。"}]
        try:
            html = render_task(self.snapshot, "autumn-plan")
        finally:
            item["logs"] = saved
        self.assertEqual(html.count('class="task-log-entry'), 3)
        self.assertIn("<time>2026-10-14 12:07</time><div>人工记录 <code>a</code>。</div>", html)
        self.assertIn("<summary>添加输入快照 · 2 条</summary>", html)
        self.assertIn("<time>2026-10-13 09:00</time><div>旧式记录。</div>", html)

    def test_page_data_follows_the_task(self):
        page = task_page(self.snapshot, "autumn-plan")
        self.assertEqual(page["status_label"], "待确认")
        self.assertEqual(page["project_href"], "#project/chenyu")
        self.assertEqual(page["materials"]["delivery"], "draft")
        self.assertEqual(page["materials"]["input_count"], 4)
        self.assertEqual(sum(1 for row in page["materials"]["inputs"] if row["meta"].startswith("快照")), 2)
        self.assertEqual(page["parent"]["href"], "#task/chenyu-line")
        self.assertTrue(page["body_html"].startswith('<h3 id="%E4%BB%BB%E5%8A%A1%E7%9B%AE%E6%A0%87">任务目标</h3>'))
        self.assertIn('data-action="promote"', page["heading_tools_html"])
        self.assertIsNone(task_page(self.snapshot, "missing"))

    def test_task_line_lists_members_and_no_script_or_style(self):
        html = render_task(self.snapshot, "chenyu-line")
        self.assertIn('class="task-group-related"', html)
        self.assertIn('href="#task/may-plan"', html)
        for forbidden in ("<script", "<style", " style="):
            self.assertNotIn(forbidden, html)



class HomePageTests(TaskPageTests):
    def test_home_page_data_and_markup(self):
        page = home_page_data(self.snapshot)
        self.assertEqual(len(page["overview"]["rows"]), len(self.snapshot["tasks"]))
        self.assertEqual(page["task_href_base"], "#task/")
        self.assertEqual(page["intents"][0]["href"], "#review")
        self.assertTrue(all(row["href"].startswith("#task/") for row in page["overview"]["rows"]))
        markup = render_home(self.snapshot)
        self.assertIn('id="homeCommandForm"', markup)
        self.assertNotIn('method="post"', markup)
        self.assertNotIn("<script", markup)

    def test_search_returns_tasks_first_then_materials_with_selections(self):
        result = home_search(self.snapshot, "秋季")
        kinds = [item["kind"] for item in result["items"]]
        self.assertEqual(kinds[0], "task")
        material = next(item for item in result["items"] if item["kind"] != "task")
        self.assertIn("file_id", material["selection"])
        self.assertTrue(material["preview_url"].startswith("api/home/file-preview?id="))
        self.assertEqual(home_search(self.snapshot, "  ")["items"], [])

    def test_previews(self):
        preview = task_preview(self.snapshot, "autumn-plan")
        self.assertEqual(preview["detail_url"], "#task/autumn-plan")
        self.assertIn("任务目标", preview["body_html"])
        self.assertIsNone(task_preview(self.snapshot, "missing"))
        item = next(f for f in self.snapshot["files"] if f["name"].endswith(".md"))
        data = file_preview(self.workspace.read_file(item["id"]))
        self.assertEqual(data["kind"], "markdown")
        self.assertTrue(data["raw_url"].startswith("api/preview?id="))



class ProjectPageTests(TaskPageTests):
    def test_card_sections_and_entries(self):
        sections = card_sections("# 标题\n\n前言\n\n## 项目总览\n\n概况\n\n## 时间线\n\n- 2026-09：开始")
        self.assertEqual(sections[""], "前言")
        self.assertEqual(sections["项目总览"], "概况")
        project = {"id": "p", "name": "示例", "locations": ["/srv/demo"],
                   "overview": "## 项目总览\n\n概况\n\n## 工作位置与入口\n\n| 类型 | 路径或网址 | 用途 |\n| --- | --- | --- |\n| 代码 | `/srv/demo` | 源码 |\n"}
        snapshot = {"projects": [project], "tasks": [], "files": []}
        page = project_page(snapshot, "p")
        rows = page["overview"]["sections"][0]["entries"][0]["rows"]
        self.assertEqual((rows[0]["environment"], rows[0]["value"], rows[0]["kind"]), ("本机", "/srv/demo", "path"))
        self.assertIn('data-action="reveal-location"', rows[0]["actions_html"])
        self.assertEqual([item["label"] for item in page["strip"]["items"]], ["说明正本"])
        self.assertIsNone(project_page(snapshot, "missing"))

    def test_example_project_page(self):
        page = project_page(self.snapshot, "chenyu")
        self.assertEqual(page["eyebrow"], "PROJECT")
        self.assertEqual(page["counts"]["tasks"], len(page["rows"]))
        self.assertTrue(all(row["href"].startswith("#task/") for row in page["rows"]))
        result = render_project(self.snapshot, "chenyu")
        self.assertEqual(result["kind"], "project")
        # The file pane carries its materials as an inert JSON block; nothing else may be a script.
        markup = re.sub(r'<script id="libraryMaterialData" type="application/json">.*?</script>', "", result["html"], flags=re.S)
        self.assertIn('data-project-panel="materials" hidden', markup)
        self.assertIn('data-action="new-task"', markup)
        for forbidden in ("<script", "<style", " style="):
            self.assertNotIn(forbidden, markup)



class ReviewPageTests(TaskPageTests):
    def test_review_data_search_and_reports(self):
        page = review_page_data(self.snapshot)
        self.assertEqual(page["stats"]["tasks"], len(self.snapshot["tasks"]))
        self.assertNotIn("group_action", page)
        self.assertEqual(page["finder"]["attrs"], [("data-task-folder-reveal", None)])
        found = review_search(self.snapshot, "秋季 方案")["items"]
        self.assertIn("autumn-plan", [item["task_id"] for item in found])
        self.assertEqual(review_search(self.snapshot, "秋季", status="completed")["items"], [])
        report = self.snapshot["reports"][0]
        preview = report_preview(self.snapshot, report["id"])
        self.assertTrue(preview["report_available"])
        self.assertIsNone(report_preview(self.snapshot, "missing"))


if __name__ == "__main__":
    unittest.main()
