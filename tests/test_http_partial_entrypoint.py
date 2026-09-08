import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from evaluation import http_trials
from evaluation.http_fixtures import HttpExecutor
from sabakan_broker.models import ToolRequest
from scripts.run_http_partial_development import partial_write_factory, validate_plan

ROOT = Path(__file__).resolve().parents[1]


class PartialHttpEntrypointTests(unittest.TestCase):
    def test_original_executor_real_partial_write_restore_and_later_retry(self):
        for mode in (None, 'partial_restore', 'partial_restore_failed'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                path = Path(root)/'service.json'
                initial = b'{invalid JSON\n'
                path.write_bytes(initial)
                fixture = SimpleNamespace(frontend='unused-front', backend='unused-back', config_path=path)
                instances = []
                original = http_trials.HttpExecutor
                with partial_write_factory(mode, instances), patch('evaluation.docker_fixtures._docker', side_effect=AssertionError('file-only test must not call Docker')):
                    executor = http_trials.HttpExecutor(fixture, observation_version=2)
                    self.assertIs(type(executor), HttpExecutor)
                    # This unit test covers file injection; real HTTP restarts belong to the later integration run.
                    executor._containers = {}
                    request = ToolRequest('config_patch', {'host':'local','resource':'nginx-main',
                        'patch':{'content':'{"enabled":true,"upstream":"sabakan"}'}})
                    result = executor.execute_mutation(request)
                    if mode is None:
                        self.assertTrue(result.ok)
                        self.assertEqual(instances, [])
                    else:
                        self.assertFalse(result.ok)
                        self.assertEqual(len(instances[0].events), 2)
                        self.assertEqual(instances[0].events[0]['phase'], 'candidate_partial_write')
                        self.assertEqual(path.read_bytes() == initial, mode == 'partial_restore')
                        # Failure is one-shot: a later authorized attempt can write normally.
                        self.assertTrue(executor.execute_mutation(request).ok)
                        self.assertTrue(executor._validation(path.read_bytes())[0])
                self.assertIs(http_trials.HttpExecutor, original)

    def test_factory_restored_after_error_and_unknown_mode_rejected(self):
        original = http_trials.HttpExecutor
        with self.assertRaises(RuntimeError):
            with partial_write_factory('partial_restore', []):
                raise RuntimeError('fixed test')
        self.assertIs(http_trials.HttpExecutor, original)
        with self.assertRaises(ValueError):
            with partial_write_factory('unknown', []):
                pass

    def test_plan_requires_explicit_isolated_conditions(self):
        plan = json.loads((ROOT/'evaluation/protocols/http-partial-write-dev-20260908.json').read_text())
        validate_plan(plan)
        plan['fixture_verification_failure'] = True
        with self.assertRaises(ValueError):
            validate_plan(plan)
        plan['fixture_verification_failure'] = False
        plan['matrix'][0]['case_id'] = 'other'
        with self.assertRaises(ValueError):
            validate_plan(plan)


if __name__ == '__main__':
    unittest.main()
