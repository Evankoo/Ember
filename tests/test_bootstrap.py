"""Verify real initialization resources and refusal before any installation write."""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from gstudio_core import __version__
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
        self.assertEqual(contract["skills"], ["gstudio-init", "gstudio-core", "gstudio-project"])
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

    def test_three_skills_have_conformant_frontmatter_and_registered_versions(self):
        workspace = Workspace(self.root / "skills")
        workspace.initialize()
        manifest = workspace._json("skills/manifest.json")
        resolver = (workspace.path / "skills/RESOLVER.md").read_text()
        required = ["Contract", "When to Use", "References", "Phases", "Output Format", "Anti-Patterns", "Tools Used"]
        self.assertEqual(len(manifest["skills"]), 3)
        for record in manifest["skills"]:
            text = (workspace.path / record["path"]).read_text()
            header = yaml.safe_load(text.split("---", 2)[1])
            self.assertEqual(header["name"], record["name"])
            self.assertEqual(header["version"], record["version"])
            self.assertTrue(header["description"])
            self.assertTrue(header["triggers"])
            self.assertTrue(header["tools"])
            positions = [text.index("## " + heading) for heading in required]
            self.assertEqual(positions, sorted(positions))
            self.assertIn(record["path"].removeprefix(".agents/skills/"), resolver)
        self.assertEqual(helper.VERSION, __version__)

    def test_missing_contract_cannot_pass_check(self):
        workspace = Workspace(self.root / "empty")
        workspace.initialize()
        (workspace.path / "AGENTS.md").unlink()
        with self.assertRaises(WorkspaceError):
            verify_workspace_contract(workspace)
        self.assertEqual(main(["check", "--workspace", str(workspace.path)]), 1)

    def args(self, **changes):
        values = dict(app_dir=str(self.root / "app"), workspace=str(self.root / "data"),
                      name="GStudio", port=8783, source=None, mode="empty", executor="opencode")
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

    def run_installer_fixture(self, *, fail_workflow=False):
        """Mock only package installation; run real Core subprocesses and writes."""
        real_run = subprocess.run

        def run(argv, **kwargs):
            if argv[1:3] == ["-m", "venv"]:
                python = Path(argv[3]) / "bin/python"
                python.parent.mkdir(parents=True)
                python.symlink_to(sys.executable)
                return subprocess.CompletedProcess(argv, 0)
            if argv[1:4] == ["-m", "pip", "install"]:
                return subprocess.CompletedProcess(argv, 0)
            if fail_workflow and argv[1:3] == ["-c", helper.SMOKE]:
                raise RuntimeError("fixture isolated workflow failed")
            # The fixture does not create a real venv; retain this test interpreter's dependencies.
            if Path(argv[0]) == self.root.resolve() / "app/.venv/bin/python":
                argv = [sys.executable, *argv[1:]]
            return real_run(argv, **kwargs)

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with patch.object(helper.subprocess, "run", side_effect=run):
            result = helper.run(self.args(source=str(Path(__file__).resolve().parents[1]), port=port))
        return result, json.loads((self.root / "app/installation.json").read_text())

    def test_real_installer_stages_write_back_one_installation_task(self):
        result, receipt = self.run_installer_fixture()
        self.assertEqual(result, 0)
        self.assertEqual((receipt["status"], receipt["writeback_status"]), ("ready", "verified"))
        self.assertTrue(receipt["verification_workspace_cleaned"])
        self.assertFalse(Path(receipt["verification_workspace"]).exists())
        workspace = Workspace(self.root / "data")
        state = workspace.snapshot()
        self.assertEqual((len(state["projects"]), len(state["tasks"])), (1, 1))
        self.assertEqual(state["tasks"][0]["id"], receipt["task_id"])
        self.assertEqual(state["tasks"][0]["status"], "active")
        self.assertTrue((workspace.path / receipt["report_path"]).is_file())

    def test_real_installer_failure_is_written_to_same_task_and_retains_test_directory(self):
        result, receipt = self.run_installer_fixture(fail_workflow=True)
        self.assertEqual(result, 1)
        self.assertEqual((receipt["status"], receipt["stage"], receipt["writeback_status"]), ("failed", "workflow-verification", "verified"))
        self.assertEqual(receipt["checks"], ["workspace-contract"])
        self.assertTrue(Path(receipt["verification_workspace"]).is_dir())
        self.addCleanup(lambda: __import__("shutil").rmtree(receipt["verification_workspace"]))
        state = Workspace(self.root / "data").snapshot()
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["tasks"][0]["id"], receipt["task_id"])
        self.assertIn("fixture isolated workflow failed", state["tasks"][0]["current"])


if __name__ == "__main__":
    unittest.main()
