from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import scripts.diagnose_lfm_observations as runner


class DiagnosticCheckpointTests(unittest.TestCase):
    def test_payload_and_response_saved_before_trial_completion(self):
        source = Path('evaluation/protocols/agents-termination-dev-20260907.json')
        plan = json.loads(source.read_text())
        plan['matrix'] = plan['matrix'][:1]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'result.json'
            frozen = Path(tmp) / 'plan.json'
            frozen.write_text(json.dumps(plan))
            def http(url, payload=None, **kwargs):
                if output.exists():
                    current = json.loads(output.read_text())
                    if 'active_trial' in current:
                        self.assertEqual(current['active_trial']['phase'], 'model_request_prepared')
                        self.assertEqual(current['active_trial']['start_status'], 'started')
                        self.assertEqual(current['trials'], [])
                        self.assertEqual(current['active_trial']['http_requests'][0]['request'], payload)
                return {'choices': [{'message': {'content': 'done'}, 'finish_reason': 'stop'}]}
            def trial(case, condition, chat, *args, **kwargs):
                current = json.loads(output.read_text())
                self.assertEqual(current['active_trial']['phase'], 'before_setup')
                chat([{'role': 'user', 'content': 'check'}], [])
                current = json.loads(output.read_text())
                self.assertEqual(current['active_trial']['phase'], 'model_response_received')
                self.assertIn('response', current['active_trial']['http_requests'][0])
                return {'started': True, 'score': {'outcome': 'unresolved'}, 'loop': {}}
            with ExitStack() as stack:
                for name, replacement in [('require_runtime', lambda: None),
                    ('sha256', lambda p: plan['model_sha256']),
                    ('command_output', lambda *a, **k: {'stdout': '', 'returncode': 0}),
                    ('start_runtime', lambda *a: []), ('http_json', http), ('run_trial', trial)]:
                    stack.enter_context(patch.object(runner, name, replacement))
                stack.enter_context(patch.object(runner.threading, 'Thread'))
                stack.enter_context(patch.object(runner.sys, 'argv', ['runner', '--plan', str(frozen), '--output', str(output)]))
                self.assertEqual(runner.main(), 0)
            final = json.loads(output.read_text())
            self.assertNotIn('active_trial', final)
            self.assertEqual(len(final['trials']), 1)
