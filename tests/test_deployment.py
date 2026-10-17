"""Deployment boundaries and one-workbench behavior without host discovery."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ember.application import Application
from ember.deployment import Deployment, DeploymentError, current_deployment


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.profile = self.root / 'profile.json'
        self.data = {'schema_version': 1, 'environment': 'test', 'isolation_root': str(self.root)}
        for key in ('runtime_root', 'shared_root', 'inbox_root', 'archive_root', 'local_config_root', 'repository_root'):
            self.data[key] = str(self.root / key)
        self.write()
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        current_deployment.cache_clear()
        self.addCleanup(current_deployment.cache_clear)

    def write(self):
        self.profile.write_text(json.dumps(self.data))

    def test_explicit_roots_are_kept_separate(self):
        deployment = Deployment.load(self.profile)
        self.assertEqual(deployment.shared_root, self.root / 'shared_root')
        self.assertEqual(deployment.repository_root, self.root / 'repository_root')
        self.assertNotEqual(deployment.runtime_root, deployment.repository_root)

    def test_missing_profile_never_falls_back_to_host(self):
        with self.assertRaises(DeploymentError):
            Deployment.load(self.root / 'missing.json')
        with self.assertRaises(DeploymentError):
            current_deployment()

    def test_missing_canonical_data_never_creates_empty_fallback(self):
        app = Application(self.profile)
        with self.assertRaises(DeploymentError):
            app.check()
        self.assertFalse(app.deployment.shared_root.exists())
        self.assertFalse(app.deployment.runtime_root.exists())

    def test_cli_rejects_competing_workspace_and_profile(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from ember.cli import main
        for command in ('check', 'serve'):
            with self.subTest(command=command), redirect_stderr(StringIO()) as errors:
                self.assertEqual(main(['--deployment-profile', str(self.profile), command, '--workspace', str(self.root / 'foreign')]), 1)
                self.assertIn('Do not combine', errors.getvalue())
        self.assertFalse((self.root / 'foreign').exists())

    def test_bad_schema_and_missing_environment_fail_closed(self):
        for patch in ({'schema_version': 2}, {'environment': ''}):
            with self.subTest(patch=patch):
                data = dict(self.data, **patch)
                self.profile.write_text(json.dumps(data))
                with self.assertRaises(DeploymentError):
                    Deployment.load(self.profile)

    def test_all_roots_must_be_absolute_and_inside_boundary(self):
        for key in ('runtime_root', 'shared_root', 'inbox_root', 'archive_root', 'local_config_root', 'repository_root'):
            for value in ('relative', str(self.root.parent / 'foreign')):
                with self.subTest(key=key, value=value):
                    self.profile.write_text(json.dumps(dict(self.data, **{key: value})))
                    with self.assertRaises(DeploymentError):
                        Deployment.load(self.profile)

    def test_isolation_boundary_must_be_absolute_and_available(self):
        for value in ('relative', 5, str(self.root / 'missing-boundary')):
            with self.subTest(value=value):
                self.profile.write_text(json.dumps(dict(self.data, isolation_root=value)))
                with self.assertRaises(DeploymentError):
                    Deployment.load(self.profile)

    def test_symlink_escape_is_rejected(self):
        link = self.root / 'escape'
        link.symlink_to(self.root.parent, target_is_directory=True)
        self.data['shared_root'] = str(link / 'foreign')
        self.write()
        with self.assertRaises(DeploymentError):
            Deployment.load(self.profile)

    def test_equal_and_nested_data_roots_are_rejected(self):
        for value in (self.data['shared_root'], str(Path(self.data['shared_root']) / 'nested')):
            self.data['archive_root'] = value
            self.write()
            with self.assertRaises(DeploymentError):
                Deployment.load(self.profile)

    def test_process_cannot_switch_profile_or_edit_its_roots(self):
        Application(self.profile)
        changed = self.root / 'other.json'
        changed.write_text(self.profile.read_text())
        with self.assertRaises(DeploymentError):
            Application(changed)
        self.data['shared_root'] = str(self.root / 'another-shared')
        self.write()
        with self.assertRaises(DeploymentError):
            Application(self.profile)

    def test_environment_overrides_cannot_escape_isolation(self):
        for key in ('GSTUDIO_SHARED_WORKSPACE_ROOT', 'GSTUDIO_TASK_INPUTS_ROOT', 'GSTUDIO_ARCHIVE_INBOX_ROOT', 'GSTUDIO_PROJECT_ARCHIVE_ROOT', 'GSTUDIO_WORKSPACE_INBOX_ROOT', 'GSTUDIO_LOCAL_CONFIG_ROOT'):
            with self.subTest(key=key), mock.patch.dict(os.environ, {key: str(self.root.parent / 'foreign')}):
                with self.assertRaises(DeploymentError):
                    Application(self.profile)

    def test_production_and_retired_ports_are_rejected_before_read_or_write(self):
        app = Application(self.profile)
        for port in (8765, 18783, -1, 65536):
            with self.subTest(port=port), mock.patch.object(app, 'check', side_effect=AssertionError('must not load data')):
                with self.assertRaises(DeploymentError):
                    app.serve(port)
        self.assertFalse(app.deployment.local_config_root.exists())

    def test_one_profile_cannot_start_two_workbenches(self):
        app = Application(self.profile)
        with app.service_lock():
            with self.assertRaises(DeploymentError):
                with app.service_lock():
                    self.fail('Second workbench acquired the lock')
        with app.service_lock():
            pass

    def test_lock_rejects_symlink_and_preserves_target(self):
        app = Application(self.profile)
        app.deployment.local_config_root.mkdir()
        target = self.root / 'target'
        target.write_text('preserve')
        (app.deployment.local_config_root / 'workbench-service.lock').symlink_to(target)
        with self.assertRaises(OSError):
            with app.service_lock():
                self.fail('symlink lock accepted')
        self.assertEqual(target.read_text(), 'preserve')

    def test_runtime_tools_use_finite_allowlist(self):
        app = Application(self.profile)
        with self.assertRaises(DeploymentError):
            app.run_tool('os', ['system'])
        with self.assertRaises(DeploymentError):
            app.run_tool('../foreign.py', [])
