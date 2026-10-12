import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from gstudio_core.cli import main
from gstudio_core import locator
from gstudio_core.locator import config_path, install_skill, read_default, register_default
from gstudio_core.store import Workspace, WorkspaceError


class LocatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.workspace = Workspace(self.root / "workspace")
        self.workspace.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(list(args))
        return code, output.getvalue(), errors.getvalue()

    def test_default_workspace_is_recorded_in_private_machine_config(self):
        record = register_default(self.workspace, python="/opt/gstudio/.venv/bin/python", home=self.home)
        path = config_path(self.home)
        self.assertEqual(path, self.home / ".config/gstudio-core/workspace.json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), record)
        self.assertEqual(record["workspace"], str(self.workspace.path))
        self.assertEqual(record["python"], "/opt/gstudio/.venv/bin/python")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(read_default(self.home), record)
        self.assertFalse((self.workspace.path / ".config").exists())

    def test_missing_config_is_not_a_default_and_unreadable_config_is_not_empty(self):
        self.assertIsNone(read_default(self.home))
        path = config_path(self.home)
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            read_default(self.home)
        with self.assertRaises(WorkspaceError):
            register_default(self.workspace, home=self.home)
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_a_different_default_is_never_replaced_silently(self):
        register_default(self.workspace, home=self.home)
        other = Workspace(self.root / "other")
        other.initialize()
        with self.assertRaises(WorkspaceError) as caught:
            register_default(other, home=self.home)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(read_default(self.home)["workspace"], str(self.workspace.path))
        register_default(other, replace=True, home=self.home)
        self.assertEqual(read_default(self.home)["workspace"], str(other.path))

    def test_only_a_valid_workspace_can_become_the_default(self):
        empty = self.root / "not-a-workspace"
        empty.mkdir()
        with self.assertRaises(WorkspaceError):
            register_default(Workspace(empty), home=self.home)
        self.assertIsNone(read_default(self.home))

    def test_cli_uses_registered_workspace_when_none_is_given(self):
        code, _, errors = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("gstudio use", errors)
        self.assertEqual(self.run_cli("use", str(self.workspace.path))[0], 0)
        code, output, _ = self.run_cli("where")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["workspace"], str(self.workspace.path))
        code, output, _ = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("校验通过", output)

    def test_where_reports_a_default_that_is_no_longer_available(self):
        register_default(self.workspace, home=self.home)
        (self.workspace.path / "AGENTS.md").unlink()
        code, _, errors = self.run_cli("where")
        self.assertEqual(code, 1)
        self.assertIn(str(self.workspace.path), errors)

    def test_daily_skill_installs_globally_without_overwriting_different_content(self):
        target = self.home / ".claude/skills"
        result = install_skill(target, home=self.home)
        installed = target / "gstudio-core/SKILL.md"
        self.assertEqual((result["status"], result["path"]), ("installed", str(target / "gstudio-core")))
        self.assertIn("~/.config/gstudio-core/workspace.json", installed.read_text(encoding="utf-8"))
        self.assertEqual(install_skill(target, home=self.home)["status"], "unchanged")
        installed.write_text("local edit", encoding="utf-8")
        with self.assertRaises(WorkspaceError) as caught:
            install_skill(target, home=self.home)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(installed.read_text(encoding="utf-8"), "local edit")

    def test_symlinked_skills_folder_is_allowed_but_a_symlinked_skill_is_not(self):
        real = self.root / "dotfiles-skills"
        real.mkdir()
        link = self.home / "skills"
        link.symlink_to(real, target_is_directory=True)
        self.assertEqual(install_skill(link, home=self.home)["status"], "installed")
        self.assertTrue((real / "gstudio-core/SKILL.md").is_file())
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        target = self.home / "other-skills"
        target.mkdir()
        (target / "gstudio-core").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            install_skill(target, home=self.home)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_cli_installs_the_daily_skill(self):
        target = self.home / ".agents/skills"
        code, output, _ = self.run_cli("install-skill", "--target", str(target))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "installed")
        self.assertTrue((target / "gstudio-core/agents/openai.yaml").is_file())


    def fake_official_copy(self, target, text="old official"):
        old = target / "gstudio-core"
        (old / "agents").mkdir(parents=True)
        (old / "SKILL.md").write_text(text, encoding="utf-8")
        (old / "agents/openai.yaml").write_text("old", encoding="utf-8")
        return {"9.9.9": locator.fingerprint(locator._read_tree(old))}

    def test_previous_official_copy_is_upgraded_in_place(self):
        target = self.home / ".claude/skills"
        known = self.fake_official_copy(target)
        with mock.patch.object(locator, "_official_fingerprints", return_value=known):
            result = install_skill(target, home=self.home)
        self.assertEqual((result["status"], result["from"]), ("upgraded", "9.9.9"))
        self.assertIn("~/.config/gstudio-core/workspace.json", (target / "gstudio-core/SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["gstudio-core"])

    def test_released_fingerprint_matches_both_installed_and_zip_copies(self):
        self.assertEqual(locator._official_fingerprints()["1.5.0"],
                         "75a2c4033058cabd2a05dccbedb852a6f86818dc4e6a0247f586651fde5a55a2")
        target = self.home / ".claude/skills"
        install_skill(target, home=self.home)
        (target / "gstudio-core/LICENSE").write_text("MIT", encoding="utf-8")
        self.assertEqual(install_skill(target, home=self.home)["status"], "unchanged")

    def test_failed_install_leaves_no_partial_skill(self):
        target = self.home / ".claude/skills"
        real_rename = os.rename
        with mock.patch.object(locator.os, "rename", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                install_skill(target, home=self.home)
        self.assertEqual(list(target.iterdir()), [])
        known = self.fake_official_copy(target)
        before = locator._read_tree(target / "gstudio-core")
        calls = []

        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("interrupted")
            return real_rename(source, destination)

        with mock.patch.object(locator, "_official_fingerprints", return_value=known), \
                mock.patch.object(locator.os, "rename", side_effect=fail_second):
            with self.assertRaises(OSError):
                install_skill(target, home=self.home)
        self.assertEqual(locator._read_tree(target / "gstudio-core"), before)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["gstudio-core"])

    def test_install_skill_without_target_refreshes_every_remembered_folder(self):
        code, _, errors = self.run_cli("install-skill")
        self.assertEqual(code, 1)
        self.assertIn("--target", errors)
        first, second = self.home / ".claude/skills", self.home / ".agents/skills"
        for target in (first, second):
            self.assertEqual(self.run_cli("install-skill", "--target", str(target))[0], 0)
        (first / "gstudio-core").rename(self.root / "removed-by-user")
        code, output, _ = self.run_cli("install-skill")
        self.assertEqual(code, 0)
        statuses = {item["path"]: item["status"] for item in json.loads(output)}
        self.assertEqual(statuses, {str(first / "gstudio-core"): "installed", str(second / "gstudio-core"): "unchanged"})


    def test_refresh_finds_copies_installed_before_targets_were_remembered(self):
        claude, codex = self.home / ".claude/skills", self.home / ".agents/skills"
        known = self.fake_official_copy(claude)
        codex.mkdir(parents=True)
        with mock.patch.object(locator, "_official_fingerprints", return_value=known):
            code, output, _ = self.run_cli("install-skill")
        self.assertEqual(code, 0)
        self.assertEqual([(item["path"], item["status"]) for item in json.loads(output)],
                         [(str(claude / "gstudio-core"), "upgraded")])
        self.assertFalse((codex / "gstudio-core").exists())
        self.assertEqual(locator.remembered_targets(self.home), [str(claude)])


if __name__ == "__main__":
    unittest.main()
