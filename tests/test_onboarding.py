"""Installation evidence stays outside tasks; daily work and projects use normal APIs."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gstudio_core import __version__
from gstudio_core.store import Workspace, WorkspaceError


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        self.workspace = Workspace(self.root / "data")
        self.workspace.initialize()

    def begin(self, **kwargs):
        from gstudio_core.onboarding import begin_installation
        receipt = {"version": __version__, "status": "installing", "stage": "system-project",
                   "mode": kwargs.get("mode", "empty"), "app_dir": str(self.app.resolve()),
                   "workspace": str(self.workspace.path), "executor": "opencode", "checks": []}
        (self.app / "installation.json").write_text(json.dumps(receipt))
        return begin_installation(self.workspace, app_dir=self.app, executor="opencode", **kwargs)

    def receipt(self, **changes):
        start = self.begin()
        receipt = {**start, "version": __version__, "status": "ready", "stage": "complete",
                   "mode": "empty", "app_dir": str(self.app.resolve()), "workspace": str(self.workspace.path),
                   "service_running": False, "verification_workspace_cleaned": True,
                   "checks": ["workspace-contract", "persisted-workflow", "loopback-health"],
                   "startup_argv": ["python", "-m", "gstudio_core", "serve", "--workspace", str(self.workspace.path)]}
        receipt.update(changes)
        (self.app / "installation.json").write_text(json.dumps(receipt))
        return receipt

    def tracking_task(self):
        self.begin()
        return self.workspace.create_task({"title": "首次使用 GStudio", "project": "gstudio",
                                          "work_type": "system", "goal": "记录当前对话并练习建项目",
                                          "executor": "opencode", "skills_used": ["gstudio-core"]})

    def files(self):
        return {str(p.relative_to(self.workspace.path)): p.read_bytes()
                for p in self.workspace.path.rglob("*") if p.is_file()}


class OnboardingTests(Fixture):
    def test_installation_registers_system_without_creating_task_or_material(self):
        start = self.begin()
        state = self.workspace.snapshot()
        self.assertEqual(len(state["projects"]), 1)
        self.assertEqual((state["projects"][0]["id"], state["projects"][0]["kind"]), ("gstudio", "system"))
        self.assertEqual(state["tasks"], [])
        self.assertEqual(state["files"], [])
        self.assertNotIn("task_id", start)
        self.assertNotIn("task_path", start)
        for folder in ("inputs", "delivery/draft", "delivery/formal"):
            self.assertEqual(list((self.workspace.path / folder).iterdir()), [])
        self.assertFalse((self.workspace.path / "archive").exists())

    def test_ready_receipt_produces_app_report_without_workspace_mutation(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt()
        before = self.files()
        result = record_installation(self.workspace, receipt)
        report = Path(result["report_path"])
        self.assertEqual(report, self.app.resolve() / "installation-report.md")
        self.assertEqual(before, self.files())
        self.assertEqual(self.workspace.snapshot()["tasks"], [])
        self.assertIn("隔离", report.read_text())
        self.assertIn("未启动", report.read_text())
        self.assertIn("gstudio-core", report.read_text())
        original = report.read_bytes()
        self.assertEqual(record_installation(self.workspace, receipt)["report_path"], result["report_path"])
        self.assertEqual(report.read_bytes(), original)
        report.write_text("用户修改的证据，禁止覆盖")
        with self.assertRaises(WorkspaceError):
            record_installation(self.workspace, receipt)
        self.assertEqual(report.read_text(), "用户修改的证据，禁止覆盖")

    def test_failure_keeps_app_evidence_without_creating_task(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt(status="failed", stage="workflow-verification", checks=["workspace-contract"],
                               error="fixture workflow error", verification_workspace_cleaned=False)
        before = self.files()
        result = record_installation(self.workspace, receipt)
        state = self.workspace.snapshot()
        self.assertEqual(state["tasks"], [])
        self.assertEqual(before, self.files())
        report = Path(result["report_path"])
        self.assertEqual(report.parent, self.app.resolve())
        self.assertIn("fixture workflow error", report.read_text())
        self.assertNotIn("技术检查全部通过", report.read_text())

    def test_partial_report_write_is_cleaned_and_can_be_retried(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt()
        before = self.files()
        report = self.app / "installation-report.md"
        original_fdopen = os.fdopen

        def partial_write(*args, **kwargs):
            stream = original_fdopen(*args, **kwargs)
            write = stream.write

            def fail(content):
                write(content[:30])
                stream.flush()
                raise OSError("fixture disk full during report write")

            stream.write = fail
            return stream

        with patch("gstudio_core.onboarding.os.fdopen", side_effect=partial_write):
            with self.assertRaisesRegex(OSError, "disk full"):
                record_installation(self.workspace, receipt)
        self.assertFalse(report.exists())
        self.assertEqual({p.name for p in self.app.iterdir()}, {"installation.json"})
        self.assertEqual(before, self.files())
        result = record_installation(self.workspace, receipt)
        self.assertEqual(Path(result["report_path"]), report.resolve())
        self.assertIn("技术检查全部通过", report.read_text())

    def test_report_fsync_failure_leaves_no_final_file_and_can_be_retried(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt()
        report = self.app / "installation-report.md"
        with patch("gstudio_core.onboarding.os.fsync", side_effect=OSError("fixture fsync failed")):
            with self.assertRaisesRegex(OSError, "fsync failed"):
                record_installation(self.workspace, receipt)
        self.assertFalse(report.exists())
        self.assertEqual({p.name for p in self.app.iterdir()}, {"installation.json"})
        record_installation(self.workspace, receipt)
        self.assertIn("技术检查全部通过", report.read_text())

    def test_first_task_is_created_through_normal_daily_task_api(self):
        task = self.tracking_task()
        self.workspace.add_material(task["id"], {"kind": "input", "name": "首次对话.md",
                                                "content": "用户已确认文档库和当前执行器，现在记录本次对话。",
                                                "purpose": "首次使用对话的真实摘要"})
        state = self.workspace.snapshot()
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual((state["tasks"][0]["project"], state["tasks"][0]["status"]), ("gstudio", "active"))
        self.assertEqual(self.workspace._task(task["id"])[1]["skills_used"], ["gstudio-core"])

    def test_begin_refuses_existing_work_or_repeat_without_modifying_it(self):
        self.workspace.create_project({"id": "real", "name": "已有业务", "description": "不能视为安装空白"})
        before = self.files()
        with self.assertRaises(WorkspaceError):
            self.begin()
        self.assertEqual(before, self.files())
        fresh = Workspace(self.root / "fresh")
        fresh.initialize()
        self.workspace = fresh
        self.begin()
        before = self.files()
        with self.assertRaises(WorkspaceError):
            self.begin()
        self.assertEqual(before, self.files())

    def test_invalid_executor_and_foreign_receipt_are_rejected_before_writes(self):
        from gstudio_core.onboarding import begin_installation, record_installation
        before = self.files()
        with self.assertRaises(WorkspaceError):
            begin_installation(self.workspace, app_dir=self.app, executor="bad\nexecutor")
        self.assertEqual(before, self.files())
        receipt = self.receipt()
        before = self.files()
        receipt["workspace"] = str(self.root / "wrong")
        with self.assertRaises(WorkspaceError):
            record_installation(self.workspace, receipt)
        self.assertEqual(before, self.files())

    def test_example_onboarding_adds_only_system_and_preserves_eight_example_tasks(self):
        self.workspace = Workspace(self.root / "example")
        before = self.workspace.initialize(example=True)
        original = self.files()
        self.begin(mode="example")
        after = self.workspace.snapshot()
        self.assertEqual((len(after["projects"]), len(after["tasks"])), (3, 8))
        for task in before["tasks"]:
            path = f"tasks/{'completed' if task['status'] == 'completed' else 'active'}/{task['id']}.md"
            self.assertEqual(original[path], self.files()[path])

    def test_modified_example_or_unexpected_file_is_not_a_new_installation(self):
        self.workspace = Workspace(self.root / "modified-example")
        self.workspace.initialize(example=True)
        card = next((self.workspace.path / "tasks/active").glob("*.md"))
        card.write_text(card.read_text().replace("## 当前结果", "## 当前结果\n\n用户已经续接。"))
        before = self.files()
        with self.assertRaises(WorkspaceError):
            self.begin(mode="example")
        self.assertEqual(before, self.files())
        self.workspace = Workspace(self.root / "unexpected")
        self.workspace.initialize()
        (self.workspace.path / "my-notes.txt").write_text("用户原稿")
        before = self.files()
        with self.assertRaises(WorkspaceError):
            self.begin()
        self.assertEqual(before, self.files())

    def test_incomplete_ready_or_changed_plan_never_produces_success_report(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt()
        before = self.files()
        for changes in ({"checks": ["workspace-contract"]}, {"verification_workspace_cleaned": False},
                        {"service_running": True}, {"app_dir": str(self.root / "other")}, {"mode": "example"}):
            with self.assertRaises(WorkspaceError):
                record_installation(self.workspace, {**receipt, **changes})
            self.assertEqual(before, self.files())
        (self.app / "installation.json").write_text('{"app_dir":"tampered"}')
        before = self.files()
        with self.assertRaises(WorkspaceError):
            record_installation(self.workspace, receipt)
        self.assertEqual(before, self.files())

    def test_receipt_and_report_symlinks_are_rejected_without_touching_targets(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt()
        outside = self.root / "outside.md"
        outside.write_text("用户已有证据")
        report = self.app / "installation-report.md"
        report.symlink_to(outside)
        with self.assertRaises(WorkspaceError):
            record_installation(self.workspace, receipt)
        self.assertEqual(outside.read_text(), "用户已有证据")
        report.unlink()
        stored = self.app / "installation.json"
        stored.unlink()
        stored.symlink_to(outside)
        with self.assertRaises(WorkspaceError):
            record_installation(self.workspace, receipt)
        self.assertEqual(outside.read_text(), "用户已有证据")


class ProjectRegistrationTests(Fixture):
    def proposal(self, **changes):
        proposal = {"id": "my-project", "name": "我的项目", "kind": "project", "description": "用户确认的用途和边界"}
        proposal.update(changes)
        return proposal

    def test_plan_is_read_only_and_create_requires_confirmation_and_active_task(self):
        from gstudio_core.project_registration import plan_project, register_project
        start = self.tracking_task()
        before = self.files()
        plan = plan_project(self.workspace, self.proposal())
        self.assertTrue(plan["can_create"])
        self.assertEqual(before, self.files())
        for kwargs in ({"task_id": start["id"], "confirmation": False},
                       {"task_id": "missing", "confirmation": True}):
            with self.assertRaises(WorkspaceError):
                register_project(self.workspace, self.proposal(), **kwargs)
            self.assertEqual(before, self.files())
        result = register_project(self.workspace, self.proposal(), task_id=start["id"], confirmation=True)
        self.assertEqual(result["id"], "my-project")
        self.assertTrue((self.workspace.path / "projects/my-project.md").is_file())
        state = self.workspace.snapshot()
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["tasks"][0]["project"], "gstudio")
        self.assertEqual(state["tasks"][0]["status"], "active")

    def test_project_script_checks_exact_confirmed_plan_and_live_service_lock(self):
        import contextlib
        import importlib.util
        import io
        from gstudio_core.bootstrap import PACKAGE
        from gstudio_core.server import workspace_lock
        spec = importlib.util.spec_from_file_location("project_helper", PACKAGE / "skills/gstudio-project/scripts/project.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        start = self.tracking_task()
        plan = self.root / "proposal.json"
        plan.write_text(json.dumps(self.proposal()))
        args = ["--workspace", str(self.workspace.path), "--plan", str(plan)]
        before = self.files()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(helper.main(args), 0)
        proposal = json.loads(output.getvalue())
        self.assertEqual(before, self.files())
        confirmed = [*args, "--task-id", start["id"], "--expected-sha256", proposal["sha256"], "--confirm"]
        with workspace_lock(self.workspace), contextlib.redirect_stderr(io.StringIO()):
            before = self.files()
            self.assertEqual(helper.main(confirmed), 1)
            self.assertEqual(before, self.files())
        plan.write_text(json.dumps(self.proposal(name="方案已经变化")))
        before = self.files()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(helper.main(confirmed), 1)
        self.assertEqual(before, self.files())
        plan.write_text(json.dumps(self.proposal()))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(helper.main(confirmed), 0)
        self.assertTrue((self.workspace.path / "projects/my-project.md").is_file())

    def test_same_id_or_name_is_never_overwritten_and_reserved_scope_is_rejected(self):
        from gstudio_core.project_registration import plan_project, register_project
        start = self.tracking_task()
        before = self.files()
        for proposal in (self.proposal(id="gstudio"), self.proposal(name="GStudio")):
            self.assertFalse(plan_project(self.workspace, proposal)["can_create"])
            with self.assertRaises(WorkspaceError):
                register_project(self.workspace, proposal, task_id=start["id"], confirmation=True)
        for proposal in (self.proposal(id="independent"), self.proposal(kind="unknown"), self.proposal(description="")):
            with self.assertRaises(WorkspaceError):
                plan_project(self.workspace, proposal)
        self.assertEqual(before, self.files())
