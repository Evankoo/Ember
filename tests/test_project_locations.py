import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ember.cli import main
from ember.locator import register_default
from ember.project_registration import plan_project
from ember.store import Workspace, WorkspaceError


class ProjectLocationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.code = self.root / "code/autumn-site"
        (self.code / "src/pages").mkdir(parents=True)
        self.workspace = Workspace(self.root / "workspace")
        self.workspace.initialize()

    def run_cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(list(args))
        return code, output.getvalue(), errors.getvalue()

    def create(self, identifier="autumn", **extra):
        return self.workspace.create_project({"id": identifier, "name": "秋季网站", "description": "秋季活动网站",
                                              "focus": "完成首页", **extra})

    def test_new_project_card_uses_the_shared_skeleton_with_working_locations(self):
        result = self.create(locations=[str(self.code)])
        overview = (self.workspace.docs / "项目/autumn/项目看板.md").read_text(encoding="utf-8")
        for heading in ("## 项目总览", "## 工作位置与入口", "## 范围与要求", "## 当前阶段", "## 时间线"):
            self.assertIn(heading, overview)
        self.assertIn(f"`{self.code}`", overview)
        self.assertEqual(result["locations"], [str(self.code)])
        snapshot = next(p for p in self.workspace.snapshot()["projects"] if p["id"] == "autumn")
        self.assertEqual(snapshot["locations"], [str(self.code)])

    def test_project_without_location_says_it_is_pending(self):
        self.create()
        overview = (self.workspace.docs / "项目/autumn/项目看板.md").read_text(encoding="utf-8")
        self.assertIn("ember project-location", overview)
        self.assertEqual(next(p for p in self.workspace.snapshot()["projects"] if p["id"] == "autumn")["locations"], [])

    def test_locations_must_be_absolute_single_line_paths(self):
        for bad in (["relative/path"], ["/ok", "/ok"], ["/tmp/a\nb"], "/not-a-list"):
            with self.subTest(bad=bad), self.assertRaises(WorkspaceError):
                self.create(locations=bad)
        self.assertFalse((self.workspace.docs / "项目/autumn/项目看板.md").exists())

    def test_locations_are_added_and_removed_without_touching_the_card(self):
        self.create()
        card = (self.workspace.docs / "项目/autumn/项目看板.md").read_bytes()
        self.assertEqual(self.workspace.update_project_locations("autumn", {"add": str(self.code)})["locations"], [str(self.code)])
        self.assertEqual(self.workspace.update_project_locations("autumn", {"add": str(self.code)})["locations"], [str(self.code)])
        self.assertEqual(self.workspace.update_project_locations("autumn", {"remove": str(self.code)})["locations"], [])
        self.assertEqual((self.workspace.docs / "项目/autumn/项目看板.md").read_bytes(), card)
        with self.assertRaises(WorkspaceError) as caught:
            self.workspace.update_project_locations("missing", {"add": str(self.code)})
        self.assertEqual(caught.exception.status, 404)

    def test_current_directory_maps_to_the_most_specific_project(self):
        self.create(locations=[str(self.code.parent)])
        self.create("pages", locations=[str(self.code / "src")])
        self.assertEqual(self.workspace.project_for_directory(self.code / "src/pages")["project"], "pages")
        self.assertEqual(self.workspace.project_for_directory(self.code)["project"], "autumn")
        self.assertIsNone(self.workspace.project_for_directory(self.root / "elsewhere")["project"])
        self.assertIsNone(self.workspace.project_for_directory(Path(str(self.code.parent) + "-copy"))["project"])

    def test_cli_registers_and_resolves_from_the_default_workspace(self):
        self.create()
        register_default(self.workspace, home=self.home)
        code, output, _ = self.run_cli("project-location", "autumn", str(self.code))
        self.assertEqual((code, json.loads(output)["locations"]), (0, [str(self.code)]))
        code, output, _ = self.run_cli("which-project", "--dir", str(self.code / "src"))
        self.assertEqual((code, json.loads(output)["project"]), (0, "autumn"))
        code, output, _ = self.run_cli("which-project", "--dir", str(self.root))
        self.assertEqual((code, json.loads(output)["project"]), (0, None))
        self.assertEqual(self.run_cli("project-location", "autumn", str(self.code), "--remove")[0], 0)
        self.assertIsNone(json.loads(self.run_cli("which-project", "--dir", str(self.code))[1])["project"])

    def test_project_plan_accepts_locations(self):
        proposal = plan_project(self.workspace, {"id": "autumn", "name": "秋季网站", "kind": "project",
                                                 "description": "秋季活动网站", "locations": [str(self.code)]})
        self.assertEqual(proposal["project"]["locations"], [str(self.code)])
        self.assertIn("## 工作位置与入口", proposal["project"]["overview"])


if __name__ == "__main__":
    unittest.main()
