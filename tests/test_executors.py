import json
import os
import plistlib
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gstudio_core.executors import ExecutorRegistry
from gstudio_core.store import WorkspaceError


def software_fixture(home):
    folder = Path(home) / "本机软件 with spaces"
    app = folder / "Other Assistant.app"
    executable = app / "Contents/MacOS/assistant"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "example.assistant", "CFBundleExecutable": "assistant",
    }))
    command = folder / "assistant-cli"
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o700)
    return [
        {"id": "other-app", "label": "我的桌面助手", "kind": "app", "path": str(app)},
        {"id": "other-cli", "label": "我的命令行助手", "kind": "command", "path": str(command)},
    ]


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.registry = ExecutorRegistry(self.home)
        self.entries = software_fixture(self.home)
        self.workspace = self.home / "工作区 with spaces"
        self.workspace.mkdir()
        self.native = [self.home / ".codex/config.toml", self.home / ".config/opencode/opencode.jsonc"]
        for path in self.native:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("invalid native configuration: must never be parsed\n")
        self.native_before = [path.read_bytes() for path in self.native]

    def payload(self, entries=None, default="other-cli"):
        return {"executors": self.entries if entries is None else entries,
                "default_executor": default, "expected_revision": self.registry.snapshot()["revision"]}

    def saved(self, default="other-cli"):
        self.registry.save(self.payload(default=default))
        return self.registry.snapshot()

    def open_payload(self, view):
        return {"executor_id": view["default_executor"], "expected_revision": view["revision"], "confirmation": True}

    def test_empty_machine_has_no_hardcoded_choices_or_automatic_files(self):
        with patch("gstudio_core.executors.subprocess.run") as run:
            view = self.registry.snapshot()
        self.assertEqual(view["executors"], [])
        self.assertEqual(view["default_executor"], "")
        self.assertTrue(view["registry_readable"])
        self.assertFalse(view["ready"])
        self.assertFalse(self.registry.path.exists())
        run.assert_not_called()

    def test_check_is_read_only_and_save_is_private_and_outside_workspace(self):
        with patch("gstudio_core.executors.subprocess.run") as run:
            checked = self.registry.validate(self.payload())
            self.assertFalse(self.registry.path.exists())
            self.assertFalse(checked["authentication_verified"])
            view = self.saved()
        run.assert_not_called()
        self.assertEqual(view["executors"], self.entries)
        self.assertTrue(view["ready"])
        self.assertEqual(self.registry.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.registry.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertEqual([path.read_bytes() for path in self.native], self.native_before)

    def test_invalid_or_duplicate_entries_stop_before_any_write(self):
        invalid = [
            self.entries + [self.entries[0]],
            [{**self.entries[0], "id": "../outside"}],
            [{**self.entries[0], "kind": "shell"}],
            [{**self.entries[0], "label": ""}],
            [{**self.entries[1], "path": self.entries[1]["path"] + " --auto"}],
            [{**self.entries[1], "path": "relative-command"}],
        ]
        for entries in invalid:
            with self.subTest(entries=entries):
                with self.assertRaises(WorkspaceError):
                    self.registry.save(self.payload(entries, entries[0]["id"]))
                self.assertFalse(self.registry.path.exists())
        with self.assertRaises(WorkspaceError):
            self.registry.save(self.payload(default="unknown"))

    def test_failed_saved_path_does_not_fall_back_to_another_program(self):
        self.saved()
        Path(self.entries[1]["path"]).chmod(0o600)
        view = self.registry.snapshot()
        self.assertFalse(view["ready"])
        self.assertEqual(view["default_executor"], "other-cli")
        with patch("gstudio_core.executors.subprocess.run") as run:
            with self.assertRaises(WorkspaceError):
                self.registry.open_software(self.open_payload(view), self.workspace)
        run.assert_not_called()

    def test_unreadable_configuration_is_unknown_not_a_successful_empty_scan(self):
        self.registry.path.parent.mkdir(parents=True)
        self.registry.path.write_text('{"private": "do-not-echo",')
        before = self.registry.path.read_bytes()
        view = self.registry.snapshot()
        self.assertFalse(view["registry_readable"])
        self.assertFalse(view["ready"])
        self.assertNotIn("do-not-echo", view["error"])
        with self.assertRaises(WorkspaceError):
            self.registry.save(self.payload())
        self.assertEqual(self.registry.path.read_bytes(), before)

    def test_symlink_and_duplicate_json_configuration_fail_closed(self):
        self.registry.path.parent.mkdir(parents=True)
        target = self.home / "external.json"
        target.write_text("{}")
        self.registry.path.symlink_to(target)
        self.assertFalse(self.registry.snapshot()["registry_readable"])
        with self.assertRaises(WorkspaceError):
            self.registry.save(self.payload())
        self.assertEqual(target.read_text(), "{}")
        self.registry.path.unlink()
        self.registry.path.write_text('{"executors": [], "executors": []}')
        self.assertFalse(self.registry.snapshot()["registry_readable"])

    def test_stale_save_and_stale_open_cannot_overwrite_or_launch(self):
        old = self.saved()
        self.registry.save(self.payload(default="other-app"))
        current = self.registry.path.read_bytes()
        with self.assertRaises(WorkspaceError):
            self.registry.save({**self.payload(), "expected_revision": old["revision"]})
        with patch("gstudio_core.executors.subprocess.run") as run:
            with self.assertRaises(WorkspaceError):
                self.registry.open_software(self.open_payload(old), self.workspace)
        run.assert_not_called()
        self.assertEqual(self.registry.path.read_bytes(), current)

    def test_changed_configuration_has_a_private_backup_and_failure_keeps_original(self):
        self.saved()
        before = self.registry.path.read_bytes()
        result = self.registry.save(self.payload(default="other-app"))
        backup = Path(result["backup_folder"])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / "executors.json").read_bytes(), before)
        self.assertEqual((backup / "executors.json").stat().st_mode & 0o777, 0o600)
        before = self.registry.path.read_bytes()
        from gstudio_core.executors import _atomic_write
        def fail_target(path, contents):
            if path == self.registry.path:
                raise OSError("private-error-not-for-output")
            return _atomic_write(path, contents)
        with patch("gstudio_core.executors._atomic_write", side_effect=fail_target):
            with self.assertRaises(WorkspaceError) as failure:
                self.registry.save(self.payload())
        self.assertNotIn("private-error", str(failure.exception))
        self.assertEqual(self.registry.path.read_bytes(), before)

    def test_all_programs_can_be_removed_without_legacy_default_reappearing(self):
        self.saved()
        self.registry.save(self.payload([], ""))
        self.assertEqual(self.registry.snapshot()["executors"], [])
        self.assertEqual(self.registry.snapshot()["default_executor"], "")

    def test_app_launch_uses_only_current_saved_id_after_explicit_confirmation(self):
        view = self.saved(default="other-app")
        before = self.registry.path.read_bytes()
        with patch("gstudio_core.executors.sys.platform", "darwin"), patch("gstudio_core.executors.subprocess.run") as run:
            with self.assertRaises(WorkspaceError):
                self.registry.open_software({**self.open_payload(view), "confirmation": False}, self.workspace)
            run.assert_not_called()
            result = self.registry.open_software(self.open_payload(view), self.workspace)
            self.assertTrue(result["opened"])
            self.assertEqual(run.call_args.args[0], ["/usr/bin/open", "-a", self.entries[0]["path"]])
        self.assertEqual(self.registry.path.read_bytes(), before)
        self.assertEqual([path.read_bytes() for path in self.native], self.native_before)

    def test_mac_command_opens_new_terminal_with_unicode_and_spaces_safely(self):
        view = self.saved()
        with patch("gstudio_core.executors.sys.platform", "darwin"), patch("gstudio_core.executors.subprocess.run") as run:
            self.registry.open_software(self.open_payload(view), self.workspace)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/osascript", "-"])
        script = run.call_args.kwargs["input"]
        command = "cd " + shlex.quote(str(self.workspace.resolve())) + " && exec " + shlex.quote(self.entries[1]["path"])
        self.assertIn(json.dumps(command, ensure_ascii=False), script)
        self.assertNotIn("in front window", script)
        self.assertNotIn("--prompt", script)

    def test_linux_command_uses_a_terminal_not_a_background_model_job(self):
        view = self.saved()
        with patch("gstudio_core.executors.sys.platform", "linux"), patch("gstudio_core.executors.shutil.which", return_value="/usr/bin/xterm"), patch.dict(os.environ, {"DISPLAY": ":test"}), patch("gstudio_core.executors.subprocess.Popen") as launch:
            self.registry.open_software(self.open_payload(view), self.workspace)
        argv = launch.call_args.args[0]
        self.assertEqual(argv[:4], ["/usr/bin/xterm", "-e", "/bin/sh", "-c"])
        self.assertIn(shlex.quote(self.entries[1]["path"]), argv[4])
        self.assertFalse(launch.call_args.kwargs.get("shell", False))

    def test_client_cannot_submit_a_path_prompt_or_model_to_the_open_endpoint(self):
        view = self.saved()
        with patch("gstudio_core.executors.subprocess.run") as run:
            for extra in ({"path": "/bin/sh"}, {"prompt": "business text"}, {"model": "invented"}):
                with self.assertRaises(WorkspaceError):
                    self.registry.open_software({**self.open_payload(view), **extra}, self.workspace)
            with self.assertRaises(WorkspaceError):
                self.registry.open_software({**self.open_payload(view), "executor_id": "unknown"}, self.workspace)
        run.assert_not_called()

    def test_discovery_is_bounded_metadata_only_and_does_not_register_candidates(self):
        app = Path(self.entries[0]["path"])
        app.rename(app.with_name("Claude.app"))
        command = Path(self.entries[1]["path"])
        command.rename(command.with_name("gemini"))
        with patch("gstudio_core.executors.subprocess.run") as run:
            found = self.registry.discover(application_roots=[app.parent], command_dirs=[command.parent])
        self.assertEqual({entry["kind"] for entry in found["candidates"]}, {"app", "command"})
        self.assertTrue(all(entry["id"].startswith("local-") for entry in found["candidates"]))
        self.assertFalse(self.registry.path.exists())
        self.assertEqual([path.read_bytes() for path in self.native], self.native_before)
        run.assert_not_called()

    def test_discovery_distinguishes_partial_failure_and_limits_from_no_matches(self):
        empty = self.registry.discover(application_roots=[self.home / "missing"], command_dirs=[])
        self.assertEqual(empty["candidates"], [])
        self.assertEqual(empty["warnings"], [])
        with patch("gstudio_core.executors.os.scandir", side_effect=PermissionError("private-details")):
            partial = self.registry.discover(application_roots=[self.home], command_dirs=[])
        self.assertTrue(partial["warnings"])
        self.assertNotIn("private-details", json.dumps(partial))
        with patch("gstudio_core.executors.DISCOVERY_ENTRY_LIMIT", 0):
            limited = self.registry.discover(application_roots=[self.home], command_dirs=[])
        self.assertTrue(limited["limited"])


if __name__ == "__main__":
    unittest.main()
