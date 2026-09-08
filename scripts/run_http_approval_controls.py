#!/usr/bin/env python3
"""Real HTTP fixture approval-state controls with a fixed public playbook."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.http_trials import run_http_trial
from evaluation.http_fixtures import HttpCase, playbook
from scripts.evaluate_mac_research import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan = json.loads((ROOT / 'evaluation/protocols/agents-http-dev-20260908.json').read_text())
    report = {'protocol': 'sabakan-http-approval-state-controls-v1',
              'fidelity': 'Fixed public playbook, real HTTP fixture; no model or human approval. Pending/unanswered are immediate synthetic states, not measured human wait.',
              'trials': [], 'status': 'running'}
    for state in ['allow', 'deny', 'pending', 'unanswered', 'expired', 'state_changed']:
        trial = run_http_trial(HttpCase('invalid_config'), 'B2', playbook,
            {**plan, 'approval_scenario': state}, plan['fixture_image'],
            f'sabakan-http-approval-control-{os.getpid()}-{state}', 'playbook')
        trial['expected_outcome'] = 'resolved' if state == 'allow' else ('escalated' if state in {'deny', 'pending', 'unanswered'} else 'unresolved')
        trial['control_passed'] = (trial['score']['outcome'] == trial['expected_outcome']
            and trial['cleanup']['complete'] is True
            and (state == 'allow' or trial['score']['executed_mutation_count'] == 0))
        report['trials'].append(trial)
        write_report(args.output, report)
        print(state, trial['score']['outcome'], trial['loop'].get('failure_reason'), trial['control_passed'], flush=True)
    report['status'] = 'completed'
    report['all_passed'] = all(t['control_passed'] for t in report['trials'])
    write_report(args.output, report)
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
