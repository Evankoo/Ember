"""Registry-driven Agent cards in the installed private runtime."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from runtime_fixture import make_runtime_fixture


class RuntimeAgentSettingsTests(unittest.TestCase):
    def test_registered_agents_models_actions_and_missing_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            profile = make_runtime_fixture(root)
            env = dict(os.environ, EMBER_DEPLOYMENT_PROFILE=str(profile),
                       PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
            code = r'''
from unittest.mock import patch
from ember.runtime.pages import setting
r = setting.runtime
entries = {
    'material-manager': {'manifest': 'agents/material-manager/AGENT.md', 'adapter_files': {'hermes': ['one.md']}},
    'ai-network-guardian': {'manifest': 'agents/ai-network-guardian/AGENT.md', 'adapter_files': {'opencode': ['two.md']}},
}
(r.ROOT / 'one.md').write_text('adapter')
(r.ROOT / 'two.md').write_text('adapter')
values = {
    'material-manager': dict(display_name='资料管理员', description='归档', status='active', adapters='hermes', primary_model='primary', primary_provider='provider', fallback_model='fallback'),
    'ai-network-guardian': dict(display_name='AI网络检查员', description='<只读>', status='active', adapters='opencode', primary_model='deepseek-flash', primary_provider='deepseek', fallback_model='none'),
}
ledger = {'runs': [dict(agent_id='ai-network-guardian', updated_at='2026-10-20 02:12:35+08:00')]}
def definition(agent_id):
    return values[agent_id], ''
with patch.object(r.ember_agent, 'registry', return_value={'runtime_agents': entries}), \
     patch.object(r.ember_agent, 'read_ledger', return_value=ledger), \
     patch.object(r.ember_agent, 'agent_definition', side_effect=definition), \
     patch.object(r.ember_agent, 'executor_status', side_effect=AssertionError('no eager probes')):
    markup, count, ready, total = setting._agent_catalog('test-token')
    assert (count, ready, total) == (2, 2, 2)
    assert '资料管理员' in markup and 'AI网络检查员' in markup
    guardian = markup.split('data-agent-id="ai-network-guardian"', 1)[1]
    assert 'DeepSeek V4.1 Flash' in guardian and '无模型回退' in guardian
    assert '→ none' not in guardian and 'Hermes' not in guardian
    assert '/actions/agent-install' not in guardian and '/actions/agent-verify' not in guardian
    assert '尚无记录' not in guardian and '&lt;只读&gt;' in guardian
    assert '/actions/agent-install' in markup and '/actions/agent-verify' in markup
    assert '<details><summary>技术信息</summary>' in markup
    (r.ROOT / 'two.md').unlink()
    markup, count, ready, total = setting._agent_catalog('test-token')
    assert (count, ready, total) == (2, 1, 2) and '适配待核对' in markup
    with patch.object(r.ember_agent, 'agent_definition', side_effect=r.ember_agent.AgentError('broken')):
        markup, count, ready, total = setting._agent_catalog('test-token')
        assert count == 2 and markup.count('定义不可读') == 2
    with patch.object(r.ember_agent, 'registry', return_value={'runtime_agents': {}}):
        markup, count, ready, total = setting._agent_catalog('test-token')
        assert (count, ready, total) == (0, 0, 0) and '尚无已登记 Agent' in markup
'''
            result = subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
