"""Installed full-runtime page modules must resolve their package-relative helpers."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from runtime_fixture import make_runtime_fixture

class RuntimePageImportTests(unittest.TestCase):
    def test_full_page_helpers_import_in_an_isolated_deployment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve(); profile=make_runtime_fixture(root)
            env=dict(os.environ,EMBER_DEPLOYMENT_PROFILE=str(profile),PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
            code='from ember.runtime.pages import common,task,setting; assert callable(task.task_overview_data)'
            result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
