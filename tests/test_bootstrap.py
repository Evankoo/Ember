"""Verify real initialization resources and refusal before any installation write."""
import argparse
import importlib.util
from pathlib import Path
import socket
import tempfile
import unittest

from gstudio_core.bootstrap import CONTRACT_FILES, PACKAGE, verify_workspace_contract
from gstudio_core.cli import main
from gstudio_core.store import Workspace, WorkspaceError


spec = importlib.util.spec_from_file_location("init_helper", PACKAGE / "skills/gstudio-init/scripts/bootstrap.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_new_empty_workspace_has_system_rules_and_registered_skill(self):
        workspace = Workspace(self.root / "empty")
        state = workspace.initialize()
        self.assertEqual(state["tasks"], [])
        self.assertEqual(state["projects"], [])
        contract = verify_workspace_contract(workspace)
        self.assertEqual(contract["skills"], ["gstudio-init", "gstudio-core"])
        for relative in CONTRACT_FILES:
            self.assertTrue((workspace.path / relative).stat().st_size)
        self.assertTrue((workspace.path / ".agents/skills/gstudio-init/scripts/bootstrap.py").is_file())
        self.assertEqual(main(["check", "--workspace", str(workspace.path)]), 0)

    def test_example_task_inputs_delivery_and_completed_body_are_valid(self):
        workspace = Workspace(self.root / "example")
        state = workspace.initialize(example=True)
        self.assertEqual((len(state["projects"]), len(state["tasks"])), (2, 8))
        for task in state["tasks"]:
            if task["status"] == "completed":
                self.assertEqual(task["next"], "")
        self.assertEqual(main(["check", "--workspace", str(workspace.path)]), 0)

    def test_missing_contract_cannot_pass_check(self):
        workspace = Workspace(self.root / "empty")
        workspace.initialize()
        (workspace.path / "AGENTS.md").unlink()
        with self.assertRaises(WorkspaceError):
            verify_workspace_contract(workspace)
        self.assertEqual(main(["check", "--workspace", str(workspace.path)]), 1)

    def args(self, **changes):
        values = dict(app_dir=str(self.root / "app"), workspace=str(self.root / "data"),
                      name="GStudio", port=8783, source=None)
        values.update(changes)
        return argparse.Namespace(**values)

    def test_nonempty_or_overlapping_targets_fail_without_mutation(self):
        sentinel = self.root / "data/existing.txt"
        sentinel.parent.mkdir()
        sentinel.write_text("keep")
        with self.assertRaises(ValueError):
            helper.validate(self.args())
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertFalse((self.root / "app").exists())
        with self.assertRaises(ValueError):
            helper.validate(self.args(app_dir=str(self.root / "new"), workspace=str(self.root / "new/data")))
        self.assertFalse((self.root / "new").exists())

    def test_taken_port_fails_before_installation(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            with self.assertRaises(OSError):
                helper.validate(self.args(port=listener.getsockname()[1]))
        self.assertFalse((self.root / "app").exists())


if __name__ == "__main__":
    unittest.main()
