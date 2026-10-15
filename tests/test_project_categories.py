import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ember.cli import main
from ember.project_registration import plan_project
from ember.store import Workspace, WorkspaceError


class ProjectCategoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.workspace = Workspace(self.root / "workspace")
        self.workspace.initialize()

    def create(self, identifier="autumn", **extra):
        return self.workspace.create_project({"id": identifier, "name": "秋季网站", "description": "秋季活动网站", **extra})

    def categories(self):
        return {p["id"]: p["category"] for p in self.workspace.snapshot()["projects"]}

    def test_category_is_optional_user_text_shown_in_snapshot(self):
        self.create(category="内容运营")
        self.create("notes")
        self.assertEqual(self.categories(), {"autumn": "内容运营", "notes": ""})

    def test_category_must_be_a_short_single_line(self):
        for bad in ("x" * 21, "a\nb", 3):
            with self.subTest(bad=bad), self.assertRaises(WorkspaceError):
                self.create(category=bad)

    def test_category_can_be_changed_and_cleared_without_touching_the_card(self):
        self.create()
        card = (self.workspace.path / "projects/autumn.md").read_bytes()
        self.workspace.update_project_category("autumn", {"category": "课程"})
        self.assertEqual(self.categories()["autumn"], "课程")
        self.workspace.update_project_category("autumn", {"category": ""})
        self.assertEqual(self.categories()["autumn"], "")
        self.assertNotIn("category", json.loads((self.workspace.path / "config/projects.json").read_text())["projects"][0])
        self.assertEqual((self.workspace.path / "projects/autumn.md").read_bytes(), card)
        with self.assertRaises(WorkspaceError) as caught:
            self.workspace.update_project_category("missing", {"category": "课程"})
        self.assertEqual(caught.exception.status, 404)

    def test_project_plan_carries_the_category(self):
        proposal = plan_project(self.workspace, {"id": "autumn", "name": "秋季网站", "kind": "project",
                                                 "description": "秋季活动网站", "category": "内容运营"})
        self.assertEqual(proposal["project"]["category"], "内容运营")

    def test_cli_sets_and_clears_the_category(self):
        self.create()
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.root / "home")}), contextlib.redirect_stdout(output):
            self.assertEqual(main(["project-category", "autumn", "内容运营", "--workspace", str(self.workspace.path)]), 0)
            self.assertEqual(main(["project-category", "autumn", "--clear", "--workspace", str(self.workspace.path)]), 0)
        self.assertEqual(self.categories()["autumn"], "")


if __name__ == "__main__":
    unittest.main()
