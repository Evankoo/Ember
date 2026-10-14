"""Exercise the local HTTP trust boundary and a real persisted workflow."""
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import quote
from unittest.mock import patch

import yaml

from gaiora.server import LocalServer, workspace_lock
from gaiora.executors import ExecutorRegistry
from gaiora.store import Workspace, WorkspaceError
from test_executors import software_fixture


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.workspace = Workspace(self.root)
        self.workspace.initialize(example=True)
        self.registry = ExecutorRegistry(Path(self.temp.name) / "machine-home")
        self.server = LocalServer(self.workspace, 0, executor_registry=self.registry)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method="GET", payload=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        values = dict(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            values.setdefault("Content-Type", "application/json")
            values.setdefault("X-Gaiora-Token", self.server.csrf_token)
        conn.request(method, path, body=body, headers=values)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def data(self, path, method="GET", payload=None):
        status, _, body = self.request(path, method, payload)
        self.assertEqual(status, 200, body)
        return json.loads(body)["data"]

    def test_host_origin_and_write_token_are_enforced(self):
        self.assertEqual(self.request("/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/api/tasks", "POST", {"title": "x"}, {"X-Gaiora-Token": "invalid"})[0], 403)
        # Neither mutation nor data disclose to a foreign browser origin.
        self.assertEqual(len(self.workspace.snapshot()["tasks"]), 8)

    def test_health_requires_installed_workspace_contract(self):
        health = self.data("/api/health")
        self.assertEqual(health["status"], "ready")
        self.assertEqual(health["contract"]["skills"], ["gaiora-init", "gaiora", "gaiora-project"])
        (self.root / "AGENTS.md").unlink()
        self.assertEqual(self.request("/api/health")[0], 404)

    def test_settings_readback_exposes_only_installed_core_skills_and_local_metadata(self):
        manifest_path = self.root / "skills/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["skills"].extend([
            {"name": "private-custom-skill", "path": ".agents/skills/private-custom-skill/SKILL.md", "purpose": "Not part of Core"},
            {"name": "gaiora", "path": "unregistered/private/SKILL.md", "purpose": "Unregistered duplicate"},
            None,
        ])
        manifest_path.write_text(json.dumps(manifest))
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch.object(self.registry, "discover") as discovery, patch("gaiora.executors.subprocess.run") as launch:
            settings = self.data("/api/settings")
        self.assertEqual({item["name"] for item in settings["skills"]}, {"gaiora-init", "gaiora", "gaiora-project"})
        self.assertEqual(len(settings["skills"]), 3)
        self.assertEqual(settings["execution_environment"]["executors"], [])
        self.assertFalse(self.registry.path.exists())
        self.assertEqual(before, {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        discovery.assert_not_called()
        launch.assert_not_called()

    def test_executor_check_save_open_require_tokens_confirmation_and_current_revision(self):
        entries = software_fixture(self.registry.home)
        payload = {"executors": entries, "default_executor": "other-app", "expected_revision": self.registry.snapshot()["revision"]}
        before = self.workspace.snapshot()
        self.assertEqual(self.request("/api/executors/save", "POST", payload, {"X-Gaiora-Token": "invalid"})[0], 403)
        self.assertFalse(self.registry.path.exists())
        self.data("/api/executors/check", "POST", payload)
        self.assertFalse(self.registry.path.exists())
        saved = self.data("/api/executors/save", "POST", payload)
        open_payload = {"executor_id": "other-app", "expected_revision": saved["revision"], "confirmation": False}
        with patch("gaiora.executors.sys.platform", "darwin"), patch("gaiora.executors.subprocess.run") as launch:
            self.assertEqual(self.request("/api/executors/open", "POST", open_payload)[0], 400)
            self.assertEqual(self.request("/api/executors/open", "POST", {**open_payload, "confirmation": True, "path": "/bin/sh"})[0], 400)
            launch.assert_not_called()
            result = self.data("/api/executors/open", "POST", {**open_payload, "confirmation": True})
            self.assertTrue(result["opened"])
            self.assertFalse(result["submitted"])
            self.assertEqual(launch.call_args.args[0], ["/usr/bin/open", "-a", entries[0]["path"]])
        self.assertEqual(self.workspace.snapshot(), before)
        self.assertFalse(self.registry.path.is_relative_to(self.root))

    def test_discovery_is_explicit_read_only_and_cannot_accept_arbitrary_scan_roots(self):
        response = {"candidates": [], "warnings": [], "limited": False, "scope": "fixture"}
        with patch.object(self.registry, "discover", return_value=response) as discovery:
            self.assertEqual(self.request("/api/executors/discover", "POST", {}, {"Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.request("/api/executors/discover", "POST", {"roots": ["/private"]})[0], 400)
            discovery.assert_not_called()
            self.assertEqual(self.data("/api/executors/discover", "POST", {}), response)
            discovery.assert_called_once_with()
        self.assertFalse(self.registry.path.exists())

    def test_reference_and_nonfile_completion_are_persisted(self):
        task = self.data("/api/tasks", "POST", {"title": "引用与无文件验证", "project": "independent", "goal": "保留引用与结果", "artifact_mode": "none"})
        identifier = task["id"]
        source = "delivery/formal/may-plan/五月内容方案V1.0.md"
        result = self.data(f"/api/tasks/{identifier}/references", "POST", {"path": source, "purpose": "复用已交付资料"})
        self.assertEqual(result["storage"], "reference")
        self.assertFalse((self.root / "inputs" / identifier).exists())
        self.assertEqual(self.request(f"/api/tasks/{identifier}/complete", "POST", {"confirmation": False})[0], 400)
        self.data(f"/api/tasks/{identifier}", "POST", {"current": "已核对引用", "log_entry": "无需独立文件"})
        self.data(f"/api/tasks/{identifier}/complete", "POST", {"confirmation": True})
        saved = next(t for t in Workspace(self.root).snapshot()["tasks"] if t["id"] == identifier)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["inputs"], [source])
        self.assertFalse((self.root / "delivery/formal" / identifier).exists())

    def test_static_traversal_and_private_workspace_are_not_served(self):
        for path in ["/../pyproject.toml", "/assets/%2e%2e/server.py", "/.git/config", "/config/projects.json", "/assets/..%5cserver.py"]:
            self.assertEqual(self.request(path)[0], 404, path)
        self.assertEqual(self.request("/api/raw?id=" + quote("../../outside.txt"))[0], 400)

    def test_binary_or_active_file_is_an_attachment(self):
        material = self.data("/api/tasks/autumn-plan/materials", "POST", {
            "kind": "draft", "name": "test.html", "content": "<script>window.pwned=true</script>"})
        status, headers, body = self.request("/api/raw?id=" + quote(material["id"]))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn(b"<script>", body)
        preview = self.data("/api/file?id=" + quote(material["id"]))
        self.assertEqual(preview["text"], "<script>window.pwned=true</script>")

    def test_file_cannot_be_swapped_for_a_symlink_after_indexing(self):
        item = self.workspace.snapshot()["files"][0]
        outside = Path(self.temp.name) / "secret.txt"
        outside.write_text("private")
        target = self.root / item["id"]
        target.unlink()
        target.symlink_to(outside)
        status, _, body = self.request("/api/raw?id=" + quote(item["id"]))
        self.assertEqual(status, 400)
        self.assertNotIn(b"private", body)

    def test_real_task_material_delivery_and_reload(self):
        task = self.data("/api/tasks", "POST", {"title": "安装验证", "project": "studio", "goal": "验证持久保存"})
        identifier = task["id"]
        self.data(f"/api/tasks/{identifier}", "POST", {"current": "已保存结果", "next": "确认交付", "log_entry": "一次真实验证"})
        self.data(f"/api/tasks/{identifier}/materials", "POST", {"kind": "input", "name": "输入.md", "content": "独立输入"})
        self.data(f"/api/tasks/{identifier}/materials", "POST", {"kind": "draft", "name": "产物.md", "content": "完整产物"})
        self.assertEqual(self.request(f"/api/tasks/{identifier}/promote", "POST", {"confirmation": False})[0], 400)
        self.data(f"/api/tasks/{identifier}/promote", "POST", {"confirmation": True})
        reloaded = Workspace(self.root).snapshot()
        saved = next(x for x in reloaded["tasks"] if x["id"] == identifier)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["current"], "已保存结果")
        self.assertTrue((self.root / "tasks/completed" / (identifier + ".md")).is_file())
        self.assertEqual((self.root / "delivery/formal" / identifier / "产物.md").read_text(), "完整产物")

    def test_execution_metadata_is_persisted_through_existing_task_routes(self):
        task = self.data("/api/tasks", "POST", {"title": "执行器登记", "goal": "如实记录", "executor": "codex", "skills_used": ["gaiora"]})
        identifier = task["id"]
        self.data(f"/api/tasks/{identifier}", "POST", {"executor": "opencode", "skills_used": ["example-skill"]})
        path = self.root / f"tasks/active/{identifier}.md"
        metadata = yaml.safe_load(path.read_text().split("---", 2)[1])
        self.assertEqual(metadata["executor"], "opencode")
        self.assertEqual(metadata["skills_used"], ["gaiora", "example-skill"])
        before = path.read_bytes()
        self.assertEqual(self.request(f"/api/tasks/{identifier}", "POST", {"executor": ""})[0], 400)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(Workspace(self.root).snapshot()["tasks"][0]["status"], "active")

    def test_download_rejects_link_swap_at_final_open(self):
        original = self.workspace.raw_file
        outside = Path(self.temp.name) / "private.txt"
        outside.write_text("do-not-disclose")
        item = self.workspace.snapshot()["files"][0]

        def swap(identifier):
            path, metadata = original(identifier)
            path.unlink()
            path.symlink_to(outside)
            return path, metadata

        with patch.object(self.workspace, "raw_file", side_effect=swap):
            status, _, body = self.request("/api/raw?id=" + quote(item["id"]))
        self.assertEqual(status, 400)
        self.assertNotIn(b"do-not-disclose", body)

    def test_context_and_report_do_not_change_task_lifecycle(self):
        before = {x["id"]: x["status"] for x in self.workspace.snapshot()["tasks"]}
        context = self.data("/api/review/context", "POST", {"task_ids": ["autumn-plan", "autumn-assets"]})
        self.assertIn("autumn-plan", context["text"])
        self.data("/api/reports", "POST", {"title": "手动检视", "content": "建议等待确认", "mode": "selected", "task_ids": ["autumn-plan"]})
        self.assertEqual(before, {x["id"]: x["status"] for x in self.workspace.snapshot()["tasks"]})

    def test_second_service_is_rejected_and_lock_is_released(self):
        with workspace_lock(self.workspace):
            with self.assertRaises(WorkspaceError):
                with workspace_lock(Workspace(self.root)):
                    self.fail("second service must not acquire the workspace")
        with workspace_lock(self.workspace):
            pass


if __name__ == "__main__":
    unittest.main()
