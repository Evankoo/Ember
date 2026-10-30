"""A project renamed to ember keeps its former-slug folder and stays readable under both names."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from runtime_fixture import make_runtime_fixture

class RuntimeRenamedProjectTests(unittest.TestCase):
    def test_renamed_project_reads_registered_card_and_accepts_legacy_slug(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve(); profile=make_runtime_fixture(root)
            registry=root/'runtime/config/projects.json'
            payload=json.loads(registry.read_text())
            payload['projects'].append({'slug':'ember','title':'余烬','project_type':'generic_project','aliases':['余烬','gstudio'],
                'legacy_slugs':['gstudio'],'capabilities':['task_groups'],'artifact_policy':{'owner':'gstudio','default_mode':'system'},
                'project_card':'项目/gstudio/项目看板.md'})
            registry.write_text(json.dumps(payload,ensure_ascii=False))
            card=root/'documents/项目/gstudio/项目看板.md'
            card.parent.mkdir(parents=True)
            card.write_text((root/'documents/项目/demo/项目看板.md').read_text().replace('demo','ember'))
            env={'PATH':os.environ.get('PATH',''),'HOME':str(root/'home'),'EMBER_DEPLOYMENT_PROFILE':str(profile),
                 'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
            code=(
                'from ember.runtime import ember_workbench as w, ember_task as t\n'
                f'card={str(card)!r}\n'
                'assert str(w.project_source("ember"))==card, w.project_source("ember")\n'
                'assert str(w.allowed_source("project","ember"))==card\n'
                'assert str(w.project_intro_history_path("ember").parent)==str(w.project_source("ember").parent)\n'
                'assert t.canonical_project_slug("gstudio")=="ember"\n'
            )
            result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
