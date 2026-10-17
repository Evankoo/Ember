"""Page data for the shared templates comes only from this workspace's snapshot."""
import tempfile
import unittest
from pathlib import Path

from ember.pages import render_task, task_page
from ember.store import Workspace


class TaskPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        workspace = Workspace(Path(cls.temp.name) / "Ember")
        workspace.initialize(example=True)
        cls.snapshot = workspace.snapshot()

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


if __name__ == "__main__":
    unittest.main()
