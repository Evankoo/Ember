"""Shared workbench prompts carry the task-section rule and no cross-system policy copy."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from runtime_fixture import make_runtime_fixture

class RuntimePromptTests(unittest.TestCase):
    def test_shared_prompt_states_task_rule_without_bridge_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve(); profile=make_runtime_fixture(root)
            env=dict(os.environ,EMBER_DEPLOYMENT_PROFILE=str(profile),PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
            code=(
                'from ember.runtime import ember_workbench as w, ember_prompt_catalog as c\n'
                'p=w.shared_prompt_contract("读取任务","当前任务",authorization="只读",success="报告结果")\n'
                'b=p.split("### 授权边界",1)[1].split("### 成功标准",1)[0]\n'
                'assert b.count(c.TASK_REQUEST_RULE)==1, p\n'
                'assert "ember_task_register_external_result" not in p, p\n'
            )
            result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
