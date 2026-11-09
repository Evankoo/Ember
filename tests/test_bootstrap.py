"""Verify real initialization resources and refusal before any installation write."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from ember import __version__
from ember.bootstrap import CONTRACT_FILES, PACKAGE, verify_workspace_contract
from ember.cli import main
from ember.store import Workspace, WorkspaceError


spec = importlib.util.spec_from_file_location("init_helper", PACKAGE / "skills/ember-init/scripts/bootstrap.py")
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
        self.assertEqual(contract["skills"], ["ember-init", "ember", "ember-project", "ember-review", "ember-skill-authoring"])
        for relative in CONTRACT_FILES:
            self.assertTrue((workspace.path / relative).stat().st_size)
        self.assertTrue((workspace.path / ".agents/skills/ember-init/scripts/bootstrap.py").is_file())
        self.assertEqual(main(["check", "--workspace", str(workspace.path)]), 0)

    def test_example_task_inputs_delivery_and_completed_body_are_valid(self):
        workspace = Workspace(self.root / "example")
        state = workspace.initialize(example=True)
        self.assertEqual((len(state["projects"]), len(state["tasks"])), (2, 8))
        for task in state["tasks"]:
            if task["status"] == "completed":
                self.assertEqual(task["next"], "")
        self.assertEqual(main(["check", "--workspace", str(workspace.path)]), 0)

    def test_bundled_skills_have_conformant_frontmatter_and_registered_versions(self):
        workspace = Workspace(self.root / "skills")
        workspace.initialize()
        manifest = workspace._json("skills/manifest.json")
        resolver = (workspace.path / "skills/RESOLVER.md").read_text()
        required = ["Contract", "When to Use", "References", "Phases", "Output Format", "Anti-Patterns", "Tools Used"]
        self.assertEqual(len(manifest["skills"]), 5)
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
        values = dict(app_dir=str(self.root / "app"), workspace=str(self.root / "data"), documents=None,
                      name="Ember", port=8783, source=None, mode="empty", executor="opencode")
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

    def test_default_locations_are_fixed_under_the_user_folder(self):
        with patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)}):
            app, workspace, documents, _ = helper.validate(self.args(app_dir=None, workspace=None))
        base = self.root.resolve()
        self.assertEqual((workspace, documents, app), (base / "Ember", base / "Ember文档", base / "Ember/app"))
        with self.assertRaises(ValueError):
            helper.validate(self.args(workspace=str(self.root / "sys"), documents=str(self.root / "sys/docs")))

    def test_default_installer_keeps_program_in_system_folder_and_data_in_library(self):
        result, receipt = self.run_installer_fixture(app_dir=None)
        self.assertEqual(result, 0)
        workspace = Workspace(self.root / "data")
        self.assertEqual(Path(receipt["app_dir"]), workspace.path / "app")
        self.assertEqual(Path(receipt["documents"]), workspace.docs)
        self.assertEqual(sorted(p.name for p in workspace.docs.iterdir()), ["Inbox", "tasks", "交付", "任务资料", "管理中心", "项目"])
        self.assertTrue((workspace.docs / "项目/ember/项目看板.md").is_file())
        self.assertFalse((workspace.path / "tasks").exists())
        self.assertTrue((workspace.path / "app/installation-report.md").is_file())

    def test_taken_port_fails_before_installation(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            with self.assertRaises(OSError):
                helper.validate(self.args(port=listener.getsockname()[1]))
        self.assertFalse((self.root / "app").exists())

    def test_wheel_download_falls_back_to_the_mirror(self):
        import io
        import urllib.error
        import zipfile
        calls = []
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr(f"ember-init/assets/{helper.WHEEL}", b"wheel")

        def urlopen(request, timeout):
            self.assertEqual(request.get_header("User-agent"), f"Ember/{helper.VERSION}")
            url = request.full_url
            calls.append(url)
            if "github.com" in url:
                raise urllib.error.URLError("timed out")
            return io.BytesIO(package.getvalue())
        with patch.object(helper.urllib.request, "urlopen", side_effect=urlopen):
            target = helper.download(self.root / helper.WHEEL)
        self.assertEqual(calls, list(helper.RELEASES))
        self.assertEqual(target.read_bytes(), b"wheel")

    def test_wheel_download_failure_names_every_source_and_leaves_no_file(self):
        import urllib.error

        def urlopen(request, timeout):
            raise urllib.error.URLError("timed out")
        with patch.object(helper.urllib.request, "urlopen", side_effect=urlopen):
            with self.assertRaises(RuntimeError) as raised:
                helper.download(self.root / helper.WHEEL)
        for url in helper.RELEASES:
            self.assertIn(url, str(raised.exception))
        self.assertFalse((self.root / helper.WHEEL).exists())

    def run_installer_fixture(self, *, fail_workflow=False, fail_package=False, pypi_fails_once=False, mode="empty", app_dir="app"):
        """Mock only package installation; run real Core subprocesses and writes."""
        real_run = subprocess.run
        self.pip_calls = []

        def run(argv, **kwargs):
            if argv[1:3] == ["-m", "venv"]:
                python = Path(argv[3]) / "bin/python"
                python.parent.mkdir(parents=True)
                python.symlink_to(sys.executable)
                return subprocess.CompletedProcess(argv, 0)
            if argv[1:4] == ["-m", "pip", "install"]:
                if fail_package:
                    raise RuntimeError("fixture package installation failed")
                self.pip_calls.append(argv)
                if pypi_fails_once and len(self.pip_calls) == 1:
                    raise subprocess.CalledProcessError(1, argv)
                return subprocess.CompletedProcess(argv, 0)
            if fail_workflow and argv[1:3] == ["-c", helper.SMOKE]:
                raise RuntimeError("fixture isolated workflow failed")
            # The fixture does not create a real venv; retain this test interpreter's dependencies.
            venv = ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
            if Path(argv[0]) in (self.root.resolve() / "app" / venv, self.root.resolve() / "data/app" / venv):
                argv = [sys.executable, *argv[1:]]
            return real_run(argv, **kwargs)

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.home = self.root / "home"
        self.home.mkdir(exist_ok=True)
        # Installer subprocesses write machine config under HOME; never touch the real one.
        with patch.object(helper.subprocess, "run", side_effect=run), patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}):
            result = helper.run(self.args(source=str(Path(__file__).resolve().parents[1]), port=port, mode=mode,
                                          app_dir=app_dir and str(self.root / app_dir)))
        app = self.root / app_dir if app_dir else self.root / "data/app"
        return result, json.loads((app / "installation.json").read_text())

    def test_real_installer_preserves_app_record_without_creating_first_task(self):
        result, receipt = self.run_installer_fixture()
        self.assertEqual(result, 0)
        self.assertEqual((receipt["status"], receipt["writeback_status"]), ("ready", "verified"))
        self.assertTrue(receipt["verification_workspace_cleaned"])
        self.assertFalse(Path(receipt["verification_workspace"]).exists())
        workspace = Workspace(self.root / "data")
        state = workspace.snapshot()
        self.assertEqual((len(state["projects"]), len(state["tasks"])), (1, 0))
        self.assertNotIn("task_id", receipt)
        self.assertNotIn("task_path", receipt)
        self.assertEqual(Path(receipt["report_path"]), self.root.resolve() / "app/installation-report.md")
        self.assertTrue(Path(receipt["report_path"]).is_file())
        self.assertEqual(state["files"], [])
        self.assertEqual(receipt["default_workspace"], "registered")
        registered = json.loads((self.home / ".config/ember/workspace.json").read_text())
        self.assertEqual(registered["workspace"], str(workspace.path))

    def test_installer_keeps_a_different_existing_default_workspace(self):
        self.home = self.root / "home"
        config = self.home / ".config/ember/workspace.json"
        config.parent.mkdir(parents=True)
        existing = {"version": 1, "workspace": str(self.root / "earlier"), "python": sys.executable}
        config.write_text(json.dumps(existing))
        result, receipt = self.run_installer_fixture()
        self.assertEqual(result, 0)
        self.assertEqual(receipt["default_workspace"], "kept-existing")
        self.assertIn("--replace", receipt["default_workspace_note"])
        self.assertEqual(json.loads(config.read_text()), existing)

    def test_example_installer_keeps_original_eight_tasks_without_a_ninth(self):
        result, receipt = self.run_installer_fixture(mode="example")
        self.assertEqual(result, 0)
        state = Workspace(self.root / "data").snapshot()
        self.assertEqual((len(state["projects"]), len(state["tasks"])), (3, 8))
        self.assertNotIn("task_id", receipt)

    def test_real_installer_failure_is_kept_in_app_and_retains_test_directory(self):
        result, receipt = self.run_installer_fixture(fail_workflow=True)
        self.assertEqual(result, 1)
        self.assertEqual((receipt["status"], receipt["stage"], receipt["writeback_status"]), ("failed", "workflow-verification", "verified"))
        self.assertEqual(receipt["checks"], ["workspace-contract"])
        self.assertTrue(Path(receipt["verification_workspace"]).is_dir())
        self.addCleanup(lambda: __import__("shutil").rmtree(receipt["verification_workspace"]))
        state = Workspace(self.root / "data").snapshot()
        self.assertEqual(state["tasks"], [])
        self.assertNotIn("task_id", receipt)
        self.assertEqual(Path(receipt["report_path"]).parent, self.root.resolve() / "app")
        self.assertIn("fixture isolated workflow failed", Path(receipt["report_path"]).read_text())

    def test_failed_pypi_install_is_retried_once_on_the_mirror(self):
        result, receipt = self.run_installer_fixture(pypi_fails_once=True)
        self.assertEqual((result, receipt["status"]), (0, "ready"))
        self.assertEqual(len(self.pip_calls), 2)
        self.assertNotIn("--index-url", self.pip_calls[0])
        self.assertEqual(self.pip_calls[1][-2:], ["--index-url", helper.PYPI_MIRROR])

    def test_package_failure_keeps_diagnostic_receipt_before_workspace_exists(self):
        result, receipt = self.run_installer_fixture(fail_package=True)
        self.assertEqual(result, 1)
        self.assertEqual((receipt["status"], receipt["stage"]), ("failed", "package"))
        self.assertIn("fixture package installation failed", receipt["error"])
        self.assertEqual(receipt["checks"], [])
        self.assertNotIn("task_id", receipt)
        self.assertNotIn("system_project_id", receipt)
        self.assertFalse((self.root / "data").exists())


if __name__ == "__main__":
    unittest.main()
