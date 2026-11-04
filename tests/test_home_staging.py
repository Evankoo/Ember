"""Files dropped on the home page: any type is staged, named in the prompt, and registered byte for byte as a task input."""
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import quote

from ember.executors import ExecutorRegistry
from ember.server import LocalServer
from ember.store import STAGING, STAGING_DAYS, Workspace, WorkspaceError

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


class HomeStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Workspace(Path(self.temp.name) / "Ember")
        self.workspace.initialize()
        self.task = self.workspace.create_task({"title": "海报改版", "goal": "按参考图改海报"})["id"]

    def stage(self, name="参考图.png", data=PNG):
        return self.workspace.stage_file(name, io.BytesIO(data), len(data))

    def test_any_file_is_staged_in_the_system_directory(self):
        staged = self.stage()
        path = Path(staged["path"])
        self.assertEqual((staged["name"], staged["size"], path.read_bytes()), ("参考图.png", len(PNG), PNG))
        self.assertEqual(path.parent.parent, self.workspace.path / STAGING)
        self.assertEqual(self.workspace.staged_file(staged["staging_id"]), path)

    def test_bad_names_sizes_and_short_bodies_are_refused(self):
        for name in ("", ".hidden", "../x.png", "a/b.png"):
            with self.assertRaisesRegex(WorkspaceError, "单个可见文件名"):
                self.stage(name)
        with self.assertRaisesRegex(WorkspaceError, "256 MB"):
            self.workspace.stage_file("大.mov", io.BytesIO(b""), 257 * 1024 * 1024)
        with self.assertRaisesRegex(WorkspaceError, "完整收到"):
            self.workspace.stage_file("半截.pdf", io.BytesIO(b"abc"), 10)
        root = self.workspace.path / STAGING
        self.assertEqual(list(root.iterdir()) if root.exists() else [], [])
        for staging_id in ("x", "../../config", "0" * 16):
            with self.assertRaises(WorkspaceError):
                self.workspace.staged_file(staging_id)

    def test_registering_copies_the_bytes_into_task_inputs_and_drops_the_staged_copy(self):
        staged = self.stage()
        material = self.workspace.add_material(self.task, {"kind": "input", "staging_id": staged["staging_id"], "purpose": "海报参考"})
        stored = self.workspace.docs / material["relative_path"]
        self.assertEqual(material["relative_path"], f"任务资料/{self.task}/参考图.png")
        self.assertEqual(stored.read_bytes(), PNG)
        self.assertFalse(Path(staged["path"]).parent.exists())
        item = self.workspace._task(self.task)[1]["inputs"]["items"][-1]
        self.assertEqual((item["size"], item["source_locator"], item["purpose"]), (len(PNG), "workbench:home-drop", "海报参考"))
        again = self.stage()
        with self.assertRaisesRegex(WorkspaceError, "拒绝覆盖"):
            self.workspace.add_material(self.task, {"kind": "input", "staging_id": again["staging_id"]})
        self.assertTrue(Path(again["path"]).exists())
        for payload in ({"kind": "draft", "staging_id": again["staging_id"]},
                        {"kind": "input", "staging_id": again["staging_id"], "content": "x"}):
            with self.assertRaisesRegex(WorkspaceError, "只能登记为输入资料"):
                self.workspace.add_material(self.task, payload)

    def test_the_prompt_names_the_staged_file_and_how_to_register_it(self):
        staged = self.stage("合同.pdf", b"%PDF-1.7 test")
        for relation, target in (("new", "新建的任务卡"), ("continue", "本任务")):
            payload = {"request": "看一下合同", "relation": relation, "staged_files": [staged["staging_id"]]}
            if relation == "continue":
                payload["task_id"] = self.task
            text = self.workspace.build_context(payload)["text"]
            self.assertIn(f"「合同.pdf」（13 字节，暂存编号 {staged['staging_id']}）：{staged['path']}", text)
            self.assertIn(f"在{target}上用 `add_material(kind=input, staging_id=<暂存编号>)`", text)
        with self.assertRaisesRegex(WorkspaceError, "已过期清理"):
            self.workspace.build_context({"request": "看一下", "staged_files": ["0" * 16]})

    def test_unregistered_files_are_cleaned_after_a_week(self):
        old, fresh = self.stage("旧.png"), self.stage("新.png")
        stale = time.time() - (STAGING_DAYS + 1) * 86400
        os.utime(Path(old["path"]).parent, (stale, stale))
        self.stage("再拖一个.png")
        self.assertFalse(Path(old["path"]).exists())
        self.assertTrue(Path(fresh["path"]).exists())

    def test_upload_endpoint_takes_the_raw_file_with_the_page_token(self):
        server = LocalServer(self.workspace, 0, executor_registry=ExecutorRegistry(Path(self.temp.name) / "home"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))

        def post(token):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request("POST", "/api/home/stage-file", PNG, {"Content-Type": "application/octet-stream",
                                                                "X-Ember-Token": token, "X-File-Name": quote("参考 图.png")})
            response = conn.getresponse()
            body = json.loads(response.read())
            conn.close()
            return response.status, body

        status, body = post(server.csrf_token)
        self.assertEqual((status, body["data"]["name"]), (200, "参考 图.png"))
        self.assertEqual(Path(body["data"]["path"]).read_bytes(), PNG)
        self.assertEqual(post("wrong")[0], 403)


if __name__ == "__main__":
    unittest.main()
