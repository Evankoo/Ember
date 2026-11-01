import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ember import compat
from ember.store import Workspace, WorkspaceError


class CompatTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_second_lock_on_same_file_reports_busy(self):
        path = self.root / "lock"
        first = os.open(path, os.O_CREAT | os.O_RDWR)
        second = os.open(path, os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, second)
        compat.lock_file(first, blocking=False)
        with self.assertRaises(BlockingIOError):
            compat.lock_file(second, blocking=False)
        os.close(first)
        compat.lock_file(second, blocking=False)

    def test_publish_new_never_replaces_and_consumes_the_temporary(self):
        temporary, target = self.root / "new", self.root / "target"
        temporary.write_text("new", encoding="utf-8")
        compat.publish_new(temporary, target)
        self.assertFalse(temporary.exists())
        temporary.write_text("other", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            compat.publish_new(temporary, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_replace_waits_out_a_brief_windows_sharing_violation(self):
        calls = []

        def busy_once(source, target):
            calls.append(source)
            if len(calls) == 1:
                raise PermissionError(13, "in use")

        with mock.patch.object(compat, "WINDOWS", True), mock.patch.object(compat.os, "replace", busy_once), \
                mock.patch.object(compat.time, "sleep"):
            compat.replace_file("a", "b")
        self.assertEqual(len(calls), 2)

    def test_replace_does_not_hide_a_permission_error_elsewhere(self):
        with mock.patch.object(compat, "WINDOWS", False), \
                mock.patch.object(compat.os, "replace", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError):
                compat.replace_file("a", "b")

    def test_windows_names_that_change_meaning_are_refused(self):
        for name in ("C:", "file.txt:stream", "CON", "nul.txt", "COM1", "lpt9.md", "name.", "name ", 'a"b', "a?b"):
            self.assertFalse(compat.windows_name_allowed(name), name)
        for name in ("任务资料", "console.md", "com10.txt", "a.b c.md", "成果.md"):
            self.assertTrue(compat.windows_name_allowed(name), name)

    def test_workspace_refuses_a_drive_or_stream_path_on_windows(self):
        workspace = Workspace(self.root / "system", self.root / "docs")
        workspace.initialize()
        with mock.patch.object(compat, "WINDOWS", True):
            for value in ("C:/Windows/win.ini", "tasks/active/a.md:stream", "交付/CON"):
                with self.assertRaises(WorkspaceError):
                    workspace._safe(value)
            self.assertEqual(workspace._safe(Path("tasks") / "active").name, "active")


if __name__ == "__main__":
    unittest.main()
