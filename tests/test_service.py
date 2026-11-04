import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest import mock

from ember import service
from ember.store import WorkspaceError


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)

    def test_macos_install_writes_a_user_agent_that_restarts_only_after_failure(self):
        finished = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(service.sys, "platform", "darwin"), mock.patch.object(service.os, "getuid", return_value=501, create=True), \
                mock.patch.object(service, "_launchctl", return_value=finished) as launchctl, mock.patch.object(service, "_healthy", return_value=True):
            result = service.install("/工作区", 8790, home=self.home)
        agent = plistlib.loads(service._plist_path(self.home).read_bytes())
        self.assertEqual(agent["ProgramArguments"][-4:], ["--workspace", "/工作区", "--port", "8790"])
        self.assertEqual(agent["KeepAlive"], {"SuccessfulExit": False})
        self.assertIn(mock.call("bootstrap", "gui/501", str(service._plist_path(self.home))), launchctl.call_args_list)
        self.assertEqual(result["url"], "http://127.0.0.1:8790/")
        self.assertTrue(result["running"])

    def test_failed_macos_start_is_reported(self):
        failed = subprocess.CompletedProcess([], 5, "", "denied")
        with mock.patch.object(service.sys, "platform", "darwin"), mock.patch.object(service.os, "getuid", return_value=501, create=True), \
                mock.patch.object(service, "_launchctl", return_value=failed):
            with self.assertRaisesRegex(WorkspaceError, "denied"):
                service.install("/工作区", home=self.home)

    def test_status_before_install_says_how_to_install(self):
        with self.assertRaisesRegex(WorkspaceError, "ember service install"):
            service.status(home=self.home)

    def test_linux_points_to_its_own_service_manager(self):
        with mock.patch.object(service.sys, "platform", "linux"):
            with self.assertRaisesRegex(WorkspaceError, "Linux"):
                service.install("/工作区", home=self.home)

    def test_supervisor_restarts_after_a_crash_and_stops_after_a_clean_exit(self):
        (self.home / ".config/ember").mkdir(parents=True)
        (self.home / ".config/ember/service.json").write_text(json.dumps({"workspace": "/工作区", "port": 8783}), encoding="utf-8")
        outcomes = iter([subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)])
        with mock.patch.object(service.subprocess, "CREATE_NO_WINDOW", 0, create=True), mock.patch.object(service.time, "sleep") as sleep, \
                mock.patch.object(service.subprocess, "run", side_effect=lambda *a, **k: next(outcomes)) as run:
            service.supervise(home=self.home)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(service.RESTART_DELAY_SECONDS)

    def test_first_install_offers_the_service_only_with_consent(self):
        guide = (Path(service.__file__).parent / "skills/ember-init/SKILL.md").read_text(encoding="utf-8")
        phase = guide[guide.index("### 8. 询问工作台是否登录后自动启动"):guide.index("### 9. ")]
        self.assertIn("要开启吗？", phase)
        self.assertIn("-m ember service install --workspace <系统目录> --port <端口>", phase)
        self.assertLess(phase.index("先停止这个由本次启动的进程"), phase.index("-m ember service install"))
        self.assertNotIn("守护程序", guide)


if __name__ == "__main__":
    unittest.main()
