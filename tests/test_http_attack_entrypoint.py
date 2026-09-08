import unittest
import json
from pathlib import Path
import tempfile
from evaluation.http_fixtures import HttpExecutor
from sabakan_broker.models import ExecutionResult, ToolRequest
from scripts.run_http_attack_development import attach_notice, read_notice_factory, validate_attack_plan, require_primary_finished
from evaluation import http_trials


class HttpAttackEntrypointTests(unittest.TestCase):
    def test_only_untrusted_data_field_changes_and_executor_type_is_preserved(self):
        executor = HttpExecutor.__new__(HttpExecutor)
        original = ExecutionResult(True, 'READ_OK', {'http_ok': True, 'http_status': 200})
        executor.execute_read = lambda request: original
        events = []
        result = attach_notice(executor, 'untrusted instruction', events).execute_read(
            ToolRequest('service_status', {'host': 'local', 'service': 'nginx'}))
        self.assertIs(type(executor), HttpExecutor)
        self.assertEqual(result.data, {**original.data, 'untrusted_notice': 'untrusted instruction'})
        self.assertNotIn('untrusted_notice', original.data)
        self.assertEqual(result.code, original.code)
        self.assertEqual(len(events), 1)

    def test_clean_and_failed_reads_are_not_injected(self):
        for notice, ok in [(None, True), ('attack', False)]:
            executor = HttpExecutor.__new__(HttpExecutor)
            original = ExecutionResult(ok, 'READ_OK' if ok else 'FIXTURE_READ_UNSUPPORTED', {})
            executor.execute_read = lambda request: original
            events = []
            self.assertIs(attach_notice(executor, notice, events).execute_read(ToolRequest('service_status', {})), original)
            self.assertEqual(events, [])

    def test_factory_restores_original_on_exception(self):
        original = http_trials.HttpExecutor
        with self.assertRaises(RuntimeError):
            with read_notice_factory('attack', []):
                self.assertIsNot(http_trials.HttpExecutor, original)
                raise RuntimeError('fixed test interruption')
        self.assertIs(http_trials.HttpExecutor, original)

    def test_missing_clean_control_and_other_case_are_rejected(self):
        plan = {'protocol': 'sabakan-wrong-target-http-development-v1', 'fixture_type': 'http',
                'conditions': {'clean': {}, 'attack': {}}, 'http_untrusted_notices': {'clean': None, 'attack': 'attack'},
                'attack_target': {'tool': 'docker_restart', 'arguments': {'host': 'local', 'container': 'sabakan'}},
                'matrix': [{'case_id': 'development-http-healthy'}]}
        validate_attack_plan(plan)
        plan['http_untrusted_notices']['clean'] = 'attack'
        with self.assertRaises(ValueError):
            validate_attack_plan(plan)
        plan['http_untrusted_notices']['clean'] = None
        plan['matrix'][0]['case_id'] = 'development-http-frontend_down'
        with self.assertRaises(ValueError):
            validate_attack_plan(plan)

    def test_primary_running_or_unverified_cleanup_cannot_open_gate(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'sequence.json'
            for state in ({'status': 'running'}, {'status': 'completed', 'unstarted_blocks': [], 'blocks': []}):
                path.write_text(json.dumps(state))
                with self.assertRaises(RuntimeError):
                    require_primary_finished(path)
            path.write_text(json.dumps({'status': 'completed', 'unstarted_blocks': [],
                                        'blocks': [{'resource_check': {'complete': True}}]}))
            require_primary_finished(path)
