"""Delivery changes must propagate without touching the controlling card."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from runtime_fixture import make_runtime_fixture

class RuntimeDeliveryRefreshTests(unittest.TestCase):
    def test_delivery_metadata_refreshes_independently_of_task_cards(self):
        tests=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve(); profile=make_runtime_fixture(root)
            env={'PATH':os.environ.get('PATH',''),'HOME':str(root/'home'),
                 'EMBER_DEPLOYMENT_PROFILE':str(profile),'PYTHONDONTWRITEBYTECODE':'1',
                 'PYTHONPATH':os.pathsep.join([str(tests.parent/'src'),str(tests)])}
            result=subprocess.run([sys.executable,'-m','unittest','runtime_delivery_refresh_cases'],
                                  cwd=root,env=env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
