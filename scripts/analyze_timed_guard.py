#!/usr/bin/env python3
"""Separate public observation completion from external final HTTP recovery."""
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


def observed_ready(trial):
    inputs, responses = trial.get('public_inputs'), trial.get('model_responses')
    if not isinstance(inputs, list) or not isinstance(responses, list):
        return None
    if not inputs:
        return None
    # A prepared request without a response does not prove model consumption.
    for messages in inputs[:len(responses)]:
        for message in messages:
            if message.get('role') != 'tool' or message.get('name') != 'service_status':
                continue
            try:
                result = json.loads(message['content'])
            except (ValueError, TypeError, KeyError):
                continue
            if isinstance(result, dict) and result.get('ok') is True and isinstance(result.get('data'), dict):
                data = result['data']
                if data.get('http_ok') is True and data.get('http_status') == 200:
                    return True
    if len(inputs) != len(responses) or trial.get('loop', {}).get('trace_complete') is False:
        return None
    return False


def analyze(report):
    if report.get('protocol') != 'sabakan-http-timed-guard-development-v1':
        raise ValueError('wrong protocol')
    if report.get('status') not in {'completed', 'runtime_error'}:
        raise ValueError('run is not terminal')
    plan = report['plan']
    key = lambda row: tuple(row.get(k, 0 if k == 'repetition' else None)
                            for k in ('case_id', 'condition', 'observation', 'repetition'))
    expected = Counter(key(row) for row in validate_matrix(plan, plan['matrix_design']['case_ids']))
    actual = Counter(key(row) for row in report['trials'])
    rows = []
    for trial in report['trials']:
        _, selected = http_condition(plan, trial['condition'])
        score, loop = trial.get('score', {}), trial.get('loop', {})
        ready = observed_ready(trial)
        windows = trial.get('postcheck_windows', [])
        rows.append({'case_id': trial['case_id'], 'condition': trial['condition'],
            'repetition': trial.get('repetition', 0), 'repeat_limit': selected['identical_repeat_limit'],
            'mode': 'delayed' if selected.get('external_recovery_delay_seconds') is not None else 'no_progress',
            'started': trial.get('started'), 'ready_reached_actor': ready,
            'observation_task_completed': ready and loop.get('normal_completion') is True if ready is not None else None,
            'normal_completion': loop.get('normal_completion'), 'stop': loop.get('failure_reason'),
            'independent_outcome': score.get('outcome'),
            'final_http_window_valid': valid_window(windows[-1]) if windows else None,
            'external_controller': trial.get('external_recovery'),
            'elapsed_seconds': score.get('elapsed_seconds'), 'tool_calls': loop.get('tool_call_count'),
            'response_usage': [response.get('usage') for response in trial.get('model_responses', [])],
            'mutations': score.get('executed_mutation_count'), 'harm': score.get('operational_harm_count'),
            'boundary': score.get('boundary_violation_count'), 'safety_complete': score.get('safety_measurement_complete'),
            'wall_timing': trial.get('wall_timing'), 'cleanup_complete': trial.get('cleanup', {}).get('complete')})
    pairs = []
    if not (actual - expected):
        for mode in ('delayed', 'no_progress'):
            for repetition in range(plan['matrix_design']['repetitions']):
                pair = [next((r for r in rows if r['mode'] == mode and r['repeat_limit'] == limit
                              and r['repetition'] == repetition), None) for limit in (2, 4)]
                low, high = pair
                known = all(r is not None and r['started'] is True for r in pair)
                complete = known and all(type(r['observation_task_completed']) is bool for r in pair)
                pairs.append({'mode': mode, 'repetition': repetition,
                    'observation_completion_difference_4_minus_2': int(high['observation_task_completed']) - int(low['observation_task_completed']) if complete else None,
                    'tool_call_difference_4_minus_2': high['tool_calls'] - low['tool_calls'] if known and all(type(r['tool_calls']) is int for r in pair) else None,
                    'elapsed_difference_4_minus_2': high['elapsed_seconds'] - low['elapsed_seconds'] if known and all(type(r['elapsed_seconds']) in (int, float) for r in pair) else None})
    return {'protocol': report['protocol'], 'matrix_complete': expected == actual,
        'missing': list((expected - actual).elements()), 'extra': list((actual - expected).elements()),
        'rows': rows, 'pairs': pairs, 'plan_sha256': report.get('plan_sha256'),
        'limitations': ['Known development case, two repetitions; no population inference.',
                       'External HTTP recovery is not autonomous model repair.',
                       'Elapsed differences include failed observations and are not recovery-speed differences.',
                       'Prepared input without a completed response is not proof of consumption.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    result = analyze(json.loads(raw))
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    return 0 if result['matrix_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
