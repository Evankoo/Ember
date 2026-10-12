"""First real installation task and independently confirmed project registration."""
import json
from pathlib import Path
import tempfile
import unittest

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
        return begin_installation(self.workspace, app_dir=self.app, executor="opencode", **kwargs)

    def receipt(self, **changes):
        start = self.begin()
        receipt = {**start, "version": __version__, "status": "ready", "stage": "complete",
                   "mode": "empty", "app_dir": str(self.app.resolve()), "workspace": str(self.workspace.path),
                   "service_running": False, "verification_workspace_cleaned": True,
                   "checks": ["workspace-contract", "persisted-workflow", "loopback-health"],
                   "startup_argv": ["python", "-m", "gstudio_core", "serve", "--workspace", str(self.workspace.path)]}
        receipt.update(changes)
        return receipt

    def files(self):
        return {str(p.relative_to(self.workspace.path)): p.read_bytes()
                for p in self.workspace.path.rglob("*") if p.is_file()}


class OnboardingTests(Fixture):
    def test_first_task_is_real_active_and_owned_by_gstudio_system(self):
        start = self.begin()
        state = self.workspace.snapshot()
        self.assertEqual(len(state["projects"]), 1)
        self.assertEqual((state["projects"][0]["id"], state["projects"][0]["kind"]), ("gstudio", "system"))
        self.assertEqual(len(state["tasks"]), 1)
        task = state["tasks"][0]
        self.assertEqual((task["id"], task["project"], task["status"]), (start["task_id"], "gstudio", "active"))
        self.assertIn("初始化", task["title"])
        self.assertIn("人工", task["goal"])
        self.assertFalse((self.workspace.path / "delivery/draft" / task["id"]).exists())
        header, _ = self.workspace._task(task["id"])[1:]
        self.assertEqual(header["executor"], "opencode")
        self.assertEqual(header["skills_used"], ["gstudio-init", "gstudio-project"])
        self.assertEqual(header["inputs"]["items"][0]["source_locator"], "gstudio-init:confirmed-choices")
        self.assertFalse((self.workspace.path / "archive").exists())

    def test_ready_receipt_produces_real_draft_not_automatic_completion(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt()
        result = record_installation(self.workspace, receipt)
        task = self.workspace.snapshot()["tasks"][0]
        report = self.workspace.path / result["report_path"]
        self.assertEqual(task["status"], "active")
        self.assertIn("尚未", task["current"])
        self.assertIn("人工", task["next"])
        self.assertIn("隔离", report.read_text())
        self.assertIn("未启动", report.read_text())
        self.assertFalse((self.workspace.path / "delivery/formal" / task["id"]).exists())
        original = report.read_bytes()
        self.assertEqual(record_installation(self.workspace, receipt)["report_path"], result["report_path"])
        self.assertEqual(report.read_bytes(), original)
        report.write_text("用户修改的证据，禁止覆盖")
        with self.assertRaises(WorkspaceError):
            record_installation(self.workspace, receipt)
        self.assertEqual(report.read_text(), "用户修改的证据，禁止覆盖")

    def test_failure_keeps_same_task_and_does_not_claim_test_success(self):
        from gstudio_core.onboarding import record_installation
        receipt = self.receipt(status="failed", stage="workflow-verification", checks=["workspace-contract"],
                               error="fixture workflow error", verification_workspace_cleaned=False)
        result = record_installation(self.workspace, receipt)
        state = self.workspace.snapshot()
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["tasks"][0]["status"], "active")
        self.assertIn("失败", state["tasks"][0]["current"])
        self.assertIn("fixture workflow error", (self.workspace.path / result["report_path"]).read_text())
        self.assertNotIn("技术检查全部通过", state["tasks"][0]["current"])

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

    def test_example_onboarding_adds_only_one_real_system_and_task(self):
        self.workspace = Workspace(self.root / "example")
        before = self.workspace.initialize(example=True)
        original = self.files()
        self.begin(mode="example")
        after = self.workspace.snapshot()
        self.assertEqual((len(after["projects"]), len(after["tasks"])), (3, 9))
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
        header = self.workspace._task(receipt["task_id"])[1]
        plan = self.workspace.path / header["inputs"]["items"][0]["path"]
        plan.write_text('{"app_dir":"tampered"}')
        before = self.files()
        with self.assertRaises(WorkspaceError):
            record_installation(self.workspace, receipt)
        self.assertEqual(before, self.files())


class ProjectRegistrationTests(Fixture):
    def proposal(self, **changes):
        proposal = {"id": "my-project", "name": "我的项目", "kind": "project", "description": "用户确认的用途和边界"}
        proposal.update(changes)
        return proposal

    def test_plan_is_read_only_and_create_requires_confirmation_and_active_task(self):
        from gstudio_core.project_registration import plan_project, register_project
        start = self.begin()
        before = self.files()
        plan = plan_project(self.workspace, self.proposal())
        self.assertTrue(plan["can_create"])
        self.assertEqual(before, self.files())
        for kwargs in ({"task_id": start["task_id"], "confirmation": False},
                       {"task_id": "missing", "confirmation": True}):
            with self.assertRaises(WorkspaceError):
                register_project(self.workspace, self.proposal(), **kwargs)
            self.assertEqual(before, self.files())
        result = register_project(self.workspace, self.proposal(), task_id=start["task_id"], confirmation=True)
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
        start = self.begin()
        plan = self.root / "proposal.json"
        plan.write_text(json.dumps(self.proposal()))
        args = ["--workspace", str(self.workspace.path), "--plan", str(plan)]
        before = self.files()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(helper.main(args), 0)
        proposal = json.loads(output.getvalue())
        self.assertEqual(before, self.files())
        confirmed = [*args, "--task-id", start["task_id"], "--expected-sha256", proposal["sha256"], "--confirm"]
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
        start = self.begin()
        before = self.files()
        for proposal in (self.proposal(id="gstudio"), self.proposal(name="GStudio")):
            self.assertFalse(plan_project(self.workspace, proposal)["can_create"])
            with self.assertRaises(WorkspaceError):
                register_project(self.workspace, proposal, task_id=start["task_id"], confirmation=True)
        for proposal in (self.proposal(id="independent"), self.proposal(kind="unknown"), self.proposal(description="")):
            with self.assertRaises(WorkspaceError):
                plan_project(self.workspace, proposal)
        self.assertEqual(before, self.files())
