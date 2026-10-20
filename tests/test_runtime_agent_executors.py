"""Agent verification reads the executors that are actually installed on this machine."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from runtime_fixture import make_runtime_fixture


class RuntimeAgentExecutorTests(unittest.TestCase):
    def run_in_runtime(self, code: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            profile = make_runtime_fixture(root)
            env = dict(os.environ, EMBER_DEPLOYMENT_PROFILE=str(profile),
                       PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
            result = subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_opencode_readiness_lists_the_whole_catalog(self):
        # Current OpenCode prints help for `models <provider>`, so readiness must not depend on it.
        self.run_in_runtime(r'''
from unittest.mock import patch
from ember.runtime import ember_agent as agent
values = dict(adapters='opencode', opencode_primary_provider='opencode-go', opencode_primary_model='glm-5.3-flash',
              primary_provider='openai', primary_model='gpt', fallback_model='deepseek-v4-flash')
calls = []
def output(command, timeout=15):
    calls.append(command)
    if command[1:] == ['auth', 'list']:
        return 'OpenCode Go api' if command[0] == 'opencode' else ''
    if command == ['opencode', 'models']:
        return 'opencode-go/glm-5.3-flash\n'
    return 'usage: opencode models'
with patch.object(agent, 'agent_definition', return_value=(values, '')), \
     patch.object(agent, '_adapter_paths', return_value={}), \
     patch.object(agent, '_command_path', side_effect=lambda name, fallbacks: name), \
     patch.object(agent, '_run_text', side_effect=output):
    status = agent.executor_status('material-manager')
assert status['opencode']['primary_ready'] and status['opencode']['state'] == 'available', status
assert ['opencode', 'models', 'opencode-go'] not in calls, calls
''')

    def test_codex_is_found_in_the_bundled_cli_directory(self):
        self.run_in_runtime(r'''
from pathlib import Path
from unittest.mock import patch
from ember.runtime import ember_agent as agent
bundled = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
values = dict(adapters='codex', primary_provider='openai', primary_model='gpt', fallback_model='deepseek-v4-flash')
with patch.object(agent, 'agent_definition', return_value=(values, '')), \
     patch.object(agent, '_adapter_paths', return_value={}), \
     patch.object(agent.shutil, 'which', return_value=None), \
     patch.object(agent, '_run_text', return_value=''), \
     patch.object(Path, 'is_file', lambda path: str(path) == bundled):
    status = agent.executor_status('material-manager')
assert status['codex']['resolved'] == bundled and status['codex']['installed'], status
''')

    def test_network_guardian_checks_only_its_opencode_model(self):
        self.run_in_runtime(r'''
from unittest.mock import patch
from ember.runtime import ember_agent as agent
values = dict(adapters='opencode', primary_provider='deepseek', primary_model='deepseek-flash', fallback_model='none')
catalog = {'text': 'deepseek/deepseek-flash\n'}
calls = []
def output(command, timeout=15):
    calls.append(command)
    return catalog['text'] if command == ['opencode', 'models'] else ''
with patch.object(agent, 'agent_definition', return_value=(values, '')), \
     patch.object(agent, '_adapter_paths', return_value={}), \
     patch.object(agent, '_command_path', side_effect=lambda name, fallbacks: name), \
     patch.object(agent, '_run_text', side_effect=output):
    ready = agent.executor_status('ai-network-guardian')
    catalog['text'] = 'opencode-go/glm-5.3-flash\n'
    missing = agent.executor_status('ai-network-guardian')
assert list(ready) == ['opencode'] and ready['opencode']['state'] == 'available', ready
assert ready['opencode']['generation_verified'] is False and ready['opencode']['fallback_ready'] is False
assert missing['opencode']['state'] == 'needs_configuration', missing
assert all(command[0] == 'opencode' for command in calls), calls
''')


if __name__ == '__main__':
    unittest.main()
