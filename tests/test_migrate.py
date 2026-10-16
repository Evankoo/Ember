"""Copy an old single-folder workspace into the system folder and document library."""
import json
from pathlib import Path
import tempfile
import unittest

from ember.migrate import legacy_path, migrate_layout
from ember.store import Workspace, WorkspaceError


def legacy_workspace(root: Path) -> Path:
    """Rebuild the 0.10 single-folder layout of the bundled example from a new one."""
    source = Workspace(root / "source")
    source.initialize(example=True)
    old = root / "old"
    renames = {"交付/草稿": "delivery/draft", "交付/正式交付": "delivery/formal", "任务资料": "inputs",
               "Inbox": "inbox", "管理中心/整理记录": "reports"}
    for base in (source.path, source.docs):
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(base).as_posix()
            if relative.startswith("项目/"):
                relative = "projects/" + relative.split("/")[1] + ".md"
            elif relative.endswith("workbench-views.json"):
                relative = ".ember/views.json"
            elif relative.endswith("inbox-labels.json"):
                relative = ".ember/inbox.json"
            for new, previous in renames.items():
                if relative.startswith(new + "/"):
                    relative = previous + relative[len(new):]
            text = path.read_bytes()
            if relative.startswith("tasks/"):
                decoded = text.decode()
                for new, previous in renames.items():
                    decoded = decoded.replace(new + "/", previous + "/")
                text = decoded.encode()
            target = old / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text)
    (old / ".DS_Store").write_bytes(b"finder")
    return old


class MigrateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_legacy_locators_map_to_chinese_folders(self):
        self.assertEqual(legacy_path("delivery/formal/a/b.md"), "交付/正式交付/a/b.md")
        self.assertEqual(legacy_path("inputs/a/"), "任务资料/a/")
        self.assertEqual(legacy_path("workbench:text-entry"), "workbench:text-entry")

    def test_old_workspace_is_copied_and_left_untouched(self):
        old = legacy_workspace(self.root)
        before = {p: p.read_bytes() for p in old.rglob("*") if p.is_file()}
        with self.assertRaises(WorkspaceError):
            Workspace(old).snapshot()
        result = migrate_layout(old, self.root / "Ember")
        self.assertEqual((result["projects"], result["tasks"], result["files"]), (2, 8, 16))
        self.assertEqual({p: p.read_bytes() for p in old.rglob("*") if p.is_file()}, before)
        workspace = Workspace(self.root / "Ember")
        self.assertEqual(workspace.docs, (self.root / "Ember文档").resolve())
        card = (workspace.docs / "tasks/completed/may-plan.md").read_text()
        self.assertIn("folder: 交付/正式交付/may-plan", card)
        self.assertIn("(<../../交付/正式交付/may-plan/>)", card)
        self.assertEqual(json.loads((workspace.path / "config/workspace.json").read_text())["migrated_from"], str(old.resolve()))
        self.assertFalse((workspace.docs / ".DS_Store").exists())

    def test_unknown_file_stops_before_writing(self):
        old = legacy_workspace(self.root)
        (old / "notes.txt").write_text("用户自己的文件")
        with self.assertRaises(WorkspaceError):
            migrate_layout(old, self.root / "Ember")
        self.assertFalse((self.root / "Ember").exists())


if __name__ == "__main__":
    unittest.main()
