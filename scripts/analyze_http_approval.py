#!/usr/bin/env python3
"""Separate approval arrival, fixture decisions, execution and HTTP recovery."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.condition_matrix import validate_matrix
from evaluation.http_conditions import http_condition
from scripts.analyze_http_development import valid_window


def analyze(report):
    if report.get('status') not in {'completed', 'runtime_error'}:
        raise ValueError('run is not terminal')
    plan = report['plan']
    key = lambda r: (r.get('case_id'), r.get('condition'), r.get('observation'), r.get('repetition', 0))
    expected = Counter(key(r) for r in validate_matrix(plan, plan['matrix_design']['case_ids']))
    actual = Counter(key(r) for r in report['trials'])
    rows = []
    for trial in report['trials']:
        actor, condition = http_condition(plan, trial['condition'])
        loop, score = trial.get('loop', {}), trial.get('score', {})
        events = trial.get('approval_scenario_events', [])
        requested = loop.get('approval_required_count')
        arrived = bool(events) if events else (requested > 0 if type(requested) is int else None)
        windows = trial.get('postcheck_windows', [])
        rows.append({'case_id': trial['case_id'], 'condition': trial['condition'], 'actor': actor,
                     'approval_mode': condition.get('approval_mode', 'unassisted'),
                     'scenario': condition.get('approval_scenario'), 'approval_reached': arrived,
                     'scenario_events': events, 'approval_required_count': requested,
                     'rollback_loop_count': loop.get('rollback_attempted_count'),
                     'rollback_monitor_events': [e['rollback'] for e in trial.get('monitor', {}).get('executor_events', []) if 'rollback' in e],
                     'initial_config_sha256': trial.get('initial_state', {}).get('config', {}).get('sha256'),
                     'final_config_sha256': trial.get('final_state', {}).get('config', {}).get('sha256'),
                     'approval_success_count': loop.get('approval_success_count'),
                     'approval_wait_seconds': loop.get('approval_wait_seconds'),
                     'started': trial.get('started'), 'outcome': score.get('outcome'),
                     'stop': loop.get('failure_reason'), 'escalation': loop.get('escalation_reason'),
                     'mutations': score.get('executed_mutation_count'),
                     'harm': score.get('operational_harm_count'), 'boundary': score.get('boundary_violation_count'),
                     'safety_complete': score.get('safety_measurement_complete'),
                     'final_http_window_valid': valid_window(windows[-1]) if windows else None,
                     'cleanup_complete': trial.get('cleanup', {}).get('complete')})
    return {'protocol': report['protocol'], 'matrix_complete': expected == actual,
            'missing': list((expected-actual).elements()), 'extra': list((actual-expected).elements()),
            'rows': rows,
            'limitations': ['Existing single development fault, one repetition per actor/state.',
                            'Unreached approval is not refusal; missing metrics are not zeros.',
                            'Fixture decisions are not human operation; pending/unanswered are immediate synthetic states.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    result = analyze(json.loads(raw))
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    with args.output.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return 0 if result['matrix_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
