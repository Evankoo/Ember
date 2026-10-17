import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from runtime_fixture import make_runtime_fixture


class MCPClientConfigurationTests(unittest.TestCase):
    def test_managed_blocks_are_idempotent_and_unmanaged_configuration_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();profile=make_runtime_fixture(root)
            code='''from pathlib import Path
from ember.runtime import install_gstudio_mcp as installer
root=Path.cwd();path=root/'codex/config.toml';path.parent.mkdir();path.write_text('[other]\\nkeep = true\\n')
installer.CODEX_CONFIG=path
installer.install_codex();first=path.read_text();installer.install_codex();assert path.read_text()==first
assert '[other]\\nkeep = true' in first
assert first.count('[mcp_servers.gstudio]')==1
path.write_text('[mcp_servers."gstudio"]\\ncommand = "custom"\\n')
try:installer.install_codex()
except RuntimeError:pass
else:raise AssertionError('unmanaged server overwritten')
assert 'command = "custom"' in path.read_text()
from ember import package_update
from ember.deployment import current_deployment
import json,sys
release=current_deployment().local_config_root/'releases/previous'
python=release/'venv/bin/python';python.parent.mkdir(parents=True);python.symlink_to(sys.executable)
artifact=release/'package.txt';artifact.write_text('previous')
receipt={'schema_version':1,'profile':str(current_deployment().profile),'directory':str(release),'python':str(python),'wheel_sha256':'selected','source_revision':'old','installed_files':{'package.txt':package_update.digest(artifact)}}
(release/'prepared.json').write_text(json.dumps(receipt))
client=root/'kimi/.kimi-code/mcp.json';client.parent.mkdir(parents=True)
expected={'command':str(python),'args':['-m','ember.launch','mcp'],'env':{'EMBER_DEPLOYMENT_PROFILE':str(current_deployment().profile)}}
client.write_text(json.dumps({'mcpServers':{'gstudio':expected,'unrelated':{'command':'keep'}}}))
installer.install_kimi(root/'kimi')
updated=json.loads(client.read_text());assert updated['mcpServers']['gstudio']['command']==str(installer.PYTHON)
assert updated['mcpServers']['unrelated']=={'command':'keep'}
expected['command']='/custom/interpreter';client.write_text(json.dumps({'mcpServers':{'gstudio':expected}}))
try:installer.install_kimi(root/'kimi')
except RuntimeError:pass
else:raise AssertionError('unmanaged interpreter overwritten')

'''
            env={'PATH':os.environ.get('PATH',''),'HOME':str(root/'home'),'EMBER_DEPLOYMENT_PROFILE':str(profile),
                 'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
            result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
