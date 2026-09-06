"""Runner integration without Docker, CUDA, or model inference."""
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from evaluation.docker_fixtures import fixture_cases
from scripts import evaluate_agent_loop as runner
from scripts.evaluate_mac_research import TrialTimeout


class LegacyRunnerTests(unittest.TestCase):
    def test_outer_timeout_saves_exactly_one_unresolved_trial(self):
        case = replace(fixture_cases()[0], setup=lambda *_: ({}, None), postcheck=lambda _: True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new.json'
            args = SimpleNamespace(output=output, models=['fake'], max_tokens=384,
                context_size=8192, gpu_layers=0, reasoning_budget=0, reasoning_mode='off',
                port=18080, request_timeout=1, trial_timeout=1, docker_image='unused')
            with (
                patch.object(runner, 'parse_args', return_value=args),
                patch.object(runner, 'MODEL_SPECS', {'fake': {'label': 'fake', 'repo': 'unused', 'path': runner.ROOT / 'models/unused.gguf'}}),
                patch.object(runner, 'require_runtime'),
                patch.object(runner, 'fixture_cases', return_value=(case,)),
                patch.object(runner, 'start_server', return_value=(0, {})),
                patch.object(runner, 'stop_server'),
                patch.object(runner, '_remove_container'),
                patch.object(runner, 'run_agent_loop', side_effect=TrialTimeout()),
            ):
                self.assertEqual(runner.main(), 0)
            report = json.loads(output.read_text())
            trials = report['models'][0]['results']
            self.assertEqual(len(trials), 1)
            self.assertEqual(trials[0]['failure_reason'], 'OUTER_TIMEOUT')
            self.assertIsNone(trials[0]['tool_call_count'])
            self.assertIsNone(trials[0]['mutation_count'])
            self.assertEqual(report['models'][0]['legacy_v2_diagnostics']['excluded_incomplete_trials'], 1)
            self.assertEqual(trials[0]['research_score']['outcome'], 'unresolved')
            self.assertEqual(report['models'][0]['metrics']['started_trial_count'], 1)
