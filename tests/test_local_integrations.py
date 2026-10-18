import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from ember import integrations


class LocalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'integrations/private'
        self.directory.mkdir(parents=True)
        self.source = self.directory / 'sync.py'
        self.source.write_text('VALUE = "private only"\n')
        self.entry = {'path': 'integrations/private/sync.py', 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}
        self.patch = patch.object(integrations, 'current_deployment', return_value=SimpleNamespace(runtime_root=self.root))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.fullname = 'ember.runtime.ember_system_sync'
        previous = sys.modules.get(self.fullname)
        self.addCleanup(lambda: sys.modules.pop(self.fullname, None) if previous is None else sys.modules.__setitem__(self.fullname, previous))
        self.write()

    def write(self):
        (self.root / 'integrations/manifest.json').write_text(json.dumps({'schema_version':1,'modules':{'ember_system_sync':self.entry}}))

    def test_explicit_hash_registered_module_can_load(self):
        self.assertEqual(integrations.load_runtime_extension('ember_system_sync').VALUE, 'private only')

    def test_missing_configuration_does_not_discover_host_modules(self):
        (self.root / 'integrations/manifest.json').unlink()
        with self.assertRaises(integrations.IntegrationError):
            integrations.load_runtime_extension('ember_system_sync')

    def test_tamper_and_unregistered_names_fail_closed(self):
        self.source.write_text('raise AssertionError("must not execute")')
        with self.assertRaises(integrations.IntegrationError):
            integrations.load_runtime_extension('ember_system_sync')
        with self.assertRaises(integrations.IntegrationError):
            integrations.load_runtime_extension('os')

    def test_traversal_and_symlink_escape_are_rejected(self):
        self.entry['path'] = '../outside.py'
        self.write()
        with self.assertRaises(integrations.IntegrationError):
            integrations.load_runtime_extension('ember_system_sync')
        link = self.directory / 'escape.py'
        link.symlink_to('/tmp/outside.py')
        self.entry['path'] = 'integrations/private/escape.py'
        self.write()
        with self.assertRaises(integrations.IntegrationError):
            integrations.load_runtime_extension('ember_system_sync')
