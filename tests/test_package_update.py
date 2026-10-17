import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from ember.deployment import Deployment
from ember import package_update as update


class PackageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.root = root
        profile = root / 'profile.json'
        data = {'schema_version': 1, 'environment': 'test', 'isolation_root': str(root)}
        data.update({k: str(root / k) for k in ('runtime_root','shared_root','inbox_root','archive_root','local_config_root','repository_root')})
        profile.write_text(json.dumps(data))
        self.deployment = Deployment.load(profile)

    def release(self, name):
        directory = self.deployment.local_config_root / 'releases' / name
        python = directory / 'venv/bin/python'
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        (directory / 'package.txt').write_text(name)
        value = {'schema_version': 1, 'directory': str(directory), 'python': str(python),
                 'wheel_sha256': hashlib.sha256(name.encode()).hexdigest(), 'source_revision': name,
                 'profile': str(self.deployment.profile),
                 'installed_files': {'package.txt': update.digest(directory / 'package.txt')}}
        (directory / 'prepared.json').write_text(json.dumps(value))
        return value

    def test_activation_requires_prepared_receipt_and_cas(self):
        release = self.release('first')
        pointer = update.activate(release, self.deployment, expected_revision=0)
        self.assertEqual(pointer['revision'], 1)
        with self.assertRaises(update.UpdateError):
            update.activate(self.release('second'), self.deployment, expected_revision=0)
        self.assertEqual(update.active(self.deployment), pointer)

    def test_successful_second_activation_can_rollback(self):
        first, second = self.release('first'), self.release('second')
        update.activate(first, self.deployment, expected_revision=0)
        update.activate(second, self.deployment, expected_revision=1)
        restored = update.rollback(self.deployment, expected_revision=2)
        self.assertEqual(restored['active'], first)
        self.assertEqual(restored['revision'], 3)
        self.assertTrue(Path(second['python']).is_file())

    def test_tampered_package_or_receipt_cannot_activate(self):
        release = self.release('first')
        (Path(release['directory']) / 'package.txt').write_text('changed')
        with self.assertRaises(update.UpdateError):
            update.activate(release, self.deployment, expected_revision=0)
        self.assertIsNone(update.active(self.deployment))

    def test_corrupt_pointer_never_falls_back(self):
        self.deployment.local_config_root.mkdir()
        (self.deployment.local_config_root / 'active-release.json').write_text('invalid')
        with self.assertRaises(update.UpdateError):
            update.active(self.deployment)

    def test_failed_first_activation_preserves_receipt_but_restores_bootstrap(self):
        release = self.release('first')
        update.activate(release, self.deployment, expected_revision=0)
        update.restore_selection(None, self.deployment, expected_revision=1)
        self.assertIsNone(update.active(self.deployment))
        self.assertTrue((self.deployment.local_config_root / 'failed-first-activation-1.json').is_file())
        self.assertTrue(Path(release['python']).is_file())

    def test_failed_upgrade_restores_previous_with_new_revision(self):
        first, second = self.release('first'), self.release('second')
        prior = update.activate(first, self.deployment, expected_revision=0)
        update.activate(second, self.deployment, expected_revision=1)
        update.restore_selection(prior, self.deployment, expected_revision=2)
        restored = update.active(self.deployment)
        self.assertEqual(restored['active'], first)
        self.assertEqual(restored['revision'], 3)

    def test_other_profile_and_missing_prepared_files_are_rejected(self):
        release = self.release('first')
        forged = {**release, 'profile': '/different/profile.json'}
        with self.assertRaises(update.UpdateError):
            update.activate(forged, self.deployment, expected_revision=0)
        Path(release['python']).unlink()
        with self.assertRaises(update.UpdateError):
            update.activate(release, self.deployment, expected_revision=0)
