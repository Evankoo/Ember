"""Final acceptance can retire init without weakening ordinary workspace checks."""
import contextlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from ember.bootstrap import PACKAGE, install_workspace_contract, verify_workspace_contract
from ember.executors import ExecutorRegistry
from ember.onboarding_completion import INIT, PENDING, main, remove_init_skill
from ember.server import LocalServer, workspace_lock
from ember.store import Workspace, WorkspaceError


class OnboardingCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = Workspace(self.root / "workspace")
        self.workspace.initialize()
        self.workspace.create_project({"id": "ember", "name": "Ember", "kind": "system",
                                       "description": "本机系统维护", "overview": "# 余烬\n"})
        self.task = self.workspace.create_task({"title": "余烬新手引导", "project": "ember",
            "work_type": "system", "artifact_mode": "none", "skills_used": ["ember", "ember-project"],
            "goal": "真实记录安装对话和已确认练习", "executor": "manual"})
        self.receipt = {"workspace": str(self.workspace.path), "status": "ready", "system_project_id": "ember"}
        self.workspace.add_material(self.task["id"], {"kind": "input", "name": "安装记录.json",
            "source_locator": "ember-init:installation-receipt", "content": json.dumps(self.receipt)})
        self.workspace.create_project({"id": "practice", "name": "练习项目", "kind": "project",
                                      "description": "用户确认的第一次建项", "overview": "# 练习项目\n"})
        self.workspace.complete_task(self.task["id"], {"confirmation": True})
        self.payload = {"task_id": self.task["id"], "confirmation": True}

    def bytes(self):
        return {str(path.relative_to(self.workspace.path)): path.read_bytes()
                for path in self.workspace.path.rglob("*") if path.is_file()}

    def test_refuses_missing_or_nonliteral_confirmation_without_mutation(self):
        before = self.bytes()
        for confirmation in (None, False, 1, "true"):
            with self.subTest(confirmation=confirmation), self.assertRaises(WorkspaceError):
                remove_init_skill(self.workspace, {"task_id": self.task["id"], "confirmation": confirmation})
        self.assertEqual(before, self.bytes())

    def test_rejects_wrong_or_active_task_without_mutation(self):
        active = self.workspace.create_task({"title": "普通任务", "project": "ember", "work_type": "system",
                                            "artifact_mode": "none", "goal": "其他工作"})
        before = self.bytes()
        for identifier in ("does-not-exist", active["id"]):
            with self.assertRaises(WorkspaceError):
                remove_init_skill(self.workspace, {"task_id": identifier, "confirmation": True})
        self.assertEqual(before, self.bytes())

    def test_completed_unrelated_task_is_not_enough(self):
        other = self.workspace.create_task({"title": "其他系统任务", "project": "ember", "work_type": "system",
            "artifact_mode": "none", "goal": "其他工作", "skills_used": ["ember", "ember-project"]})
        self.workspace.complete_task(other["id"], {"confirmation": True})
        before = self.bytes()
        with self.assertRaisesRegex(WorkspaceError, "安装记录"):
            remove_init_skill(self.workspace, {"task_id": other["id"], "confirmation": True})
        self.assertEqual(before, self.bytes())

    def test_receipt_must_belong_to_ready_installation_and_both_skills_must_be_used(self):
        cases = [(dict(self.receipt, workspace=str(self.root / "different")), ["ember", "ember-project"]),
                 (dict(self.receipt, status="failed"), ["ember", "ember-project"]),
                 (self.receipt, ["ember"])]
        for receipt, skills in cases:
            task = self.workspace.create_task({"title": "待核对安装记录", "project": "ember", "work_type": "system",
                "artifact_mode": "none", "goal": "核对首次安装", "skills_used": skills})
            self.workspace.add_material(task["id"], {"kind": "input", "name": "安装记录.json",
                "source_locator": "ember-init:installation-receipt", "content": json.dumps(receipt)})
            self.workspace.complete_task(task["id"], {"confirmation": True})
            before = self.bytes()
            with self.assertRaises(WorkspaceError):
                remove_init_skill(self.workspace, {"task_id": task["id"], "confirmation": True})
            self.assertEqual(before, self.bytes())

    def test_tampered_receipt_snapshot_is_rejected_before_cleanup(self):
        receipt = self.workspace.path / "inputs" / self.task["id"] / "安装记录.json"
        original = receipt.read_text()
        # Both variants still describe the same ready installation; the second
        # even preserves byte size, so the existing SHA-256 gate must catch it.
        for modified in (original + "\n", original.replace('"status": "ready"', '"status" :"ready"')):
            receipt.write_text(modified)
            before = self.bytes()
            with self.assertRaisesRegex(WorkspaceError, "输入快照.*不一致"):
                remove_init_skill(self.workspace, self.payload)
            self.assertEqual(before, self.bytes())
            self.assertFalse((self.workspace.path / PENDING).exists())
        receipt.write_text(original)

    def test_removes_only_official_init_and_preserves_tasks_projects_inputs_and_custom_routes(self):
        for relative in ("RESOLVER.md", "skills/RESOLVER.md"):
            with (self.workspace.path / relative).open("a") as stream:
                stream.write("\n用户自己的补充指引。\n")
        before = self.bytes()
        package_skill = (PACKAGE / "skills/ember-init/SKILL.md").read_bytes()
        result = remove_init_skill(self.workspace, self.payload)
        self.assertTrue(result["removed"])
        self.assertFalse(result["already_removed"])
        self.assertFalse((self.workspace.path / INIT).exists())
        self.assertFalse((self.workspace.path / PENDING).exists())
        contract = verify_workspace_contract(self.workspace)
        self.assertEqual(contract["skills"], ["ember", "ember-project"])
        self.assertEqual(len(self.workspace.snapshot()["tasks"]), 1)
        self.assertEqual(len(self.workspace.snapshot()["projects"]), 2)
        for name, content in before.items():
            if not name.startswith(INIT + "/") and name not in ("RESOLVER.md", "skills/RESOLVER.md", "skills/manifest.json"):
                self.assertEqual((self.workspace.path / name).read_bytes(), content, name)
        for relative in ("RESOLVER.md", "skills/RESOLVER.md"):
            self.assertIn("用户自己的补充指引。", (self.workspace.path / relative).read_text())
        self.assertEqual((PACKAGE / "skills/ember-init/SKILL.md").read_bytes(), package_skill)

    def test_idempotent_retry_does_not_change_completion_date_or_other_data(self):
        first = remove_init_skill(self.workspace, self.payload)
        before = self.bytes()
        second = remove_init_skill(self.workspace, self.payload)
        self.assertTrue(second["already_removed"])
        self.assertEqual(second["completed_at"], first["completed_at"])
        self.assertEqual(before, self.bytes())

    def test_missing_init_without_completion_record_still_fails(self):
        shutil.rmtree(self.workspace.path / INIT)
        with self.assertRaises(WorkspaceError):
            verify_workspace_contract(self.workspace)

    def test_forged_completion_without_accepted_receipt_does_not_pass(self):
        shutil.rmtree(self.workspace.path / INIT)
        manifest = self.workspace._json("skills/manifest.json")
        manifest["skills"] = [item for item in manifest["skills"] if item["name"] != "ember-init"]
        manifest["onboarding_completion"] = {"task_id": "unknown", "completed_at": "2026-10-13T10:00:00+08:00", "removed_skill": INIT}
        self.workspace._write_json("skills/manifest.json", manifest)
        with self.assertRaises(WorkspaceError):
            verify_workspace_contract(self.workspace)

    def test_modified_init_refuses_without_mutation(self):
        (self.workspace.path / INIT / "SKILL.md").write_text("用户改过的 Skill\n")
        before = self.bytes()
        with self.assertRaisesRegex(WorkspaceError, "已修改"):
            remove_init_skill(self.workspace, self.payload)
        self.assertEqual(before, self.bytes())

    def test_extra_file_even_bytecode_is_preserved(self):
        for filename in ("personal-notes.md", "custom.pyc"):
            extra = self.workspace.path / INIT / filename
            extra.write_text("用户文件")
            before = self.bytes()
            with self.assertRaises(WorkspaceError):
                remove_init_skill(self.workspace, self.payload)
            self.assertEqual(before, self.bytes())
            extra.unlink()

    def test_symlink_inside_init_is_never_followed(self):
        external = self.root / "important.txt"
        external.write_text("用户文件")
        (self.workspace.path / INIT / "linked.txt").symlink_to(external)
        with self.assertRaisesRegex(WorkspaceError, "符号链接"):
            remove_init_skill(self.workspace, self.payload)
        self.assertEqual(external.read_text(), "用户文件")
        self.assertTrue((self.workspace.path / INIT / "SKILL.md").exists())

    def test_partial_document_failure_preserves_recovery_and_retry_finishes(self):
        atomic = self.workspace._atomic_text
        def fail_manifest(relative, content, **kwargs):
            if relative == "skills/manifest.json":
                raise WorkspaceError("模拟写入失败")
            return atomic(relative, content, **kwargs)
        with patch.object(self.workspace, "_atomic_text", side_effect=fail_manifest):
            with self.assertRaisesRegex(WorkspaceError, "同一任务重试"):
                remove_init_skill(self.workspace, self.payload)
        self.assertTrue((self.workspace.path / PENDING / "skill/SKILL.md").is_file())
        with self.assertRaisesRegex(WorkspaceError, "尚未完成"):
            verify_workspace_contract(self.workspace)
        result = remove_init_skill(self.workspace, self.payload)
        self.assertTrue(result["removed"])
        self.assertEqual(verify_workspace_contract(self.workspace)["skills"], ["ember", "ember-project"])

    def test_partial_deletion_is_recoverable_and_does_not_recreate_removed_files(self):
        def fail_delete(path):
            (path / "SKILL.md").unlink()
            raise OSError("模拟删除失败")
        with patch("ember.onboarding_completion.shutil.rmtree", side_effect=fail_delete):
            with self.assertRaises(WorkspaceError):
                remove_init_skill(self.workspace, self.payload)
        self.assertFalse((self.workspace.path / PENDING / "skill/SKILL.md").exists())
        self.assertTrue(remove_init_skill(self.workspace, self.payload)["removed"])
        self.assertEqual(verify_workspace_contract(self.workspace)["skills"], ["ember", "ember-project"])

    def test_cleanup_retry_refuses_intervening_user_edits(self):
        with patch("ember.onboarding_completion.shutil.rmtree", side_effect=OSError("模拟失败")):
            with self.assertRaises(WorkspaceError):
                remove_init_skill(self.workspace, self.payload)
        custom = self.workspace.path / PENDING / "skill/my-work.md"
        custom.write_text("后来加入的用户文件")
        with self.assertRaises(WorkspaceError):
            remove_init_skill(self.workspace, self.payload)
        self.assertEqual(custom.read_text(), "后来加入的用户文件")

    def test_reinstall_contract_cannot_restore_retired_skill(self):
        remove_init_skill(self.workspace, self.payload)
        before = self.bytes()
        with self.assertRaises(WorkspaceError):
            install_workspace_contract(self.workspace)
        self.assertEqual(before, self.bytes())
        self.assertFalse((self.workspace.path / INIT).exists())

    def test_daily_and_project_skills_still_required_after_completion(self):
        remove_init_skill(self.workspace, self.payload)
        for name in ("ember", "ember-project"):
            skill = self.workspace.path / ".agents/skills" / name / "SKILL.md"
            original = skill.read_bytes()
            skill.unlink()
            with self.assertRaises(WorkspaceError):
                verify_workspace_contract(self.workspace)
            skill.write_bytes(original)

    def test_offline_cli_removes_skill_under_workspace_lock(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = main(["--workspace", str(self.workspace.path), "--task-id", self.task["id"], "--confirm"])
        self.assertEqual(result, 0)
        self.assertTrue(json.loads(output.getvalue())["removed"])
        self.assertEqual(verify_workspace_contract(self.workspace)["skills"], ["ember", "ember-project"])

    def test_cli_refuses_when_service_holds_workspace_lock(self):
        with workspace_lock(self.workspace), contextlib.redirect_stderr(io.StringIO()):
            result = main(["--workspace", str(self.workspace.path), "--task-id", self.task["id"], "--confirm"])
        self.assertEqual(result, 1)
        self.assertTrue((self.workspace.path / INIT).exists())

    def test_http_requires_token_and_settings_health_state_remain_available(self):
        server = LocalServer(self.workspace, 0, executor_registry=ExecutorRegistry(self.root / "home"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, payload=None, token=None):
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"Content-Type": "application/json", "X-Ember-Token": token or "invalid"}
            connection.request("POST" if payload else "GET", path, json.dumps(payload) if payload else None, headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        try:
            self.assertEqual(request("/api/onboarding/remove-init-skill", self.payload)[0], 403)
            status, result = request("/api/onboarding/remove-init-skill", self.payload, server.csrf_token)
            self.assertEqual(status, 200, result)
            for path in ("/api/state", "/api/health", "/api/settings"):
                status, result = request(path)
                self.assertEqual(status, 200, result)
                if path == "/api/settings":
                    self.assertEqual([item["name"] for item in result["data"]["skills"]], ["ember", "ember-project"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
