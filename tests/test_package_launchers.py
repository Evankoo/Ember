from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from ember import process
from ember.compat import stage_launchers
from ember.deployment import current_deployment
from runtime_fixture import make_runtime_fixture


class PackageLauncherTests(unittest.TestCase):
    def test_modules_are_quoted_as_arguments_never_shell(self):
        self.assertEqual(process.module_command('ember.runtime.gstudio_task','a b;$(x)',python='/path with space/python'),
                         ['/path with space/python','-m','ember.runtime.gstudio_task','a b;$(x)'])
        with self.assertRaises(ValueError):
            process.module_command('os.system')

    def test_package_probe_ignores_pythonpath_and_checkout(self):
        with patch.object(process.subprocess,'run') as run:
            run.return_value.returncode=0
            with patch.dict('os.environ',{'PYTHONPATH':'/untrusted'}):
                self.assertTrue(process.installed_package('/registered/python'))
        args=run.call_args.args[0]
        self.assertIn('-I',args)
        self.assertNotIn('PYTHONPATH',run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['cwd'],'/')

    def test_shims_are_staged_without_overwriting_existing_scripts(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            profile=make_runtime_fixture(Path(temporary))
            current_deployment.cache_clear()
            try:
                with patch.dict(os.environ,{},clear=True):
                    files=stage_launchers(profile,sys.executable)
                    self.assertGreater(len(files),14)
                    self.assertTrue(all('no business logic' in p.read_text() for p in files))
                    self.assertFalse((Path(temporary)/'runtime/scripts').exists())
                    self.assertEqual(stage_launchers(profile,sys.executable),files)
                    files[0].write_text('user changes')
                    with self.assertRaises(ValueError):stage_launchers(profile,sys.executable)
            finally:current_deployment.cache_clear()
