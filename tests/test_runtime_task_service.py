import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from runtime_fixture import make_runtime_fixture


class RuntimeTaskServiceTests(unittest.TestCase):
    def run_case(self, code):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            profile = make_runtime_fixture(root)
            env = {'PATH': os.environ.get('PATH',''), 'HOME': str(root / 'home'),
                   'EMBER_DEPLOYMENT_PROFILE': str(profile), 'PYTHONDONTWRITEBYTECODE':'1',
                   'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
            prelude = 'from pathlib import Path\nimport json\nfrom ember.application import Application\nfrom ember.tasks import TaskError\napp=Application('+repr(str(profile))+')\n'
            result = subprocess.run([sys.executable, '-c', prelude+code], env=env, cwd=root, text=True,
                                    capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            return result.stdout

    def test_profile_roots_are_authoritative_without_private_integrations(self):
        self.run_case('''assert app.check()['tasks'] == 0
from ember.runtime.workspace_paths import shared_workspace_root
assert shared_workspace_root() == app.deployment.shared_root
assert not (app.deployment.runtime_root/'integrations').exists()
''')

    def test_idempotent_creation_and_normalized_read(self):
        self.run_case('''payload={'title':'虚构任务','goal':'验证同一入口','project':'demo','external_system':'test','correlation_id':'same'}
first=app.tasks.execute('create',payload)
second=app.tasks.execute('create',payload)
assert first['task_id'] == second['task_id']
raw=(app.deployment.shared_root/'tasks/active'/f"{first['task_id']}.md").read_text()
assert 'skills_used:\\n  - ember\\n' in raw
rows=app.tasks.list(); assert len(rows)==1
row=rows[0]; assert row['project']=='demo' and row['source']['format']=='gstudio_task'
assert app.tasks.get(row['id'])['goal']=='验证同一入口'
''')

    def test_bounded_update_preserves_unknown_metadata_and_rejects_stale_revision(self):
        self.run_case('''result=app.tasks.execute('create',{'title':'保留字段','goal':'验证字节保留','external_system':'test','correlation_id':'update'})
id=result['task_id'];path=app.deployment.shared_root/'tasks/active'/f'{id}.md'
raw=path.read_text();path.write_text(raw.replace('type: gstudio_task','type: gstudio_task\\nunknown_field: "keep: exactly"'))
row=app.tasks.get(id)
app.tasks.execute('update',{'current':'已核对','next':'继续验证','expected_sha256':row['source']['sha256']},id)
assert 'unknown_field: "keep: exactly"' in path.read_text()
assert app.tasks.get(id)['current']=='已核对'
try: app.tasks.execute('update',{'current':'过期写入','expected_sha256':row['source']['sha256']},id)
except TaskError as exc: assert exc.status==409
else: raise AssertionError('stale update accepted')
assert app.tasks.get(id)['current']=='已核对'
''')

    def test_confirmation_cannot_bypass_original_organization_gate(self):
        self.run_case('''task=app.tasks.execute('create',{'title':'确认边界','goal':'保留门禁','external_system':'test','correlation_id':'guard'})
id=task['task_id'];before=app.tasks.get(id)
try:app.tasks.execute('complete',{'confirmation':True},id)
except TaskError:pass
else:raise AssertionError('organization authority bypassed')
assert app.tasks.get(id)==before
from unittest.mock import patch
from ember.runtime import task_gate
with patch.object(task_gate,'command_promote_delivery',return_value=0) as gate:
 result=app.tasks.execute('promote',{'confirmation':True,'organization_task_id':'confirmed-test-round'},id)
 assert result['status']=='active'
 gate.assert_called_once()
assert app.tasks.get(id)==before
''')

    def test_duplicate_active_and_completed_card_is_not_silently_deduplicated(self):
        self.run_case('''task=app.tasks.execute('create',{'title':'重复检查','goal':'拒绝歧义','external_system':'test','correlation_id':'duplicate'})
id=task['task_id'];active=app.deployment.shared_root/'tasks/active'/f'{id}.md'
(app.deployment.shared_root/'tasks/completed'/active.name).write_bytes(active.read_bytes())
try:app.tasks.list()
except TaskError:pass
else:raise AssertionError('duplicate hidden by legacy reader')
''')

    def test_common_read_api_and_existing_search_route(self):
        self.run_case('''import threading,urllib.request
from ember.runtime.ember_workbench_service import WorkbenchServer
server=WorkbenchServer(('127.0.0.1',0))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
base=f'http://127.0.0.1:{server.server_port}'
try:
 with urllib.request.urlopen(base+'/api/tasks') as response:assert json.loads(response.read())=={'tasks':[]}
 with urllib.request.urlopen(base+'/api/tasks/search?q=demo') as response:assert response.status==200
finally:server.shutdown();server.server_close();thread.join()
''')

    def test_all_three_historical_types_read_without_rewriting(self):
        self.run_case('''root=app.deployment.shared_root/'tasks/active'
raws={}
for i,kind in enumerate(['gstudio_task','media_content_task','ember_task']):
 id=f'20200101-legacy-{i}'
 text=f'---\\ntype: {kind}\\ntask_id: {id}\\nproject: demo\\nprimary_goal: 旧资料\\nlegacy_extra: keep: irregular YAML\\n---\\n# 旧资料\\n\\n原始说明\\n'
 path=root/f'{id}.md';path.write_text(text);raws[path]=path.read_bytes()
rows=app.tasks.list();assert len(rows)==3
assert {row['source']['format'] for row in rows}=={'gstudio_task','media_content_task','ember_task'}
assert all(path.read_bytes()==raw for path,raw in raws.items())
''')

    def test_isolated_reference_translation_never_returns_production_source(self):
        self.run_case('''from ember.runtime import workspace_paths
p=app.deployment.runtime_root/'config/workspace-environments.json';config=json.loads(p.read_text())
config['path_aliases']=[{'from':'/unavailable-production-root','to':str(app.deployment.shared_root)}];p.write_text(json.dumps(config))
assert workspace_paths.equivalent_path_strings(Path('/unavailable-production-root/交付/item.txt'))=={str(app.deployment.shared_root/'交付/item.txt')}
assert workspace_paths.equivalent_path_strings(Path('/other-external/file.txt'))==set()
''')
