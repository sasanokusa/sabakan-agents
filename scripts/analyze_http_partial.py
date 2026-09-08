#!/usr/bin/env python3
"""Separate partial file effects, immediate restoration and independent HTTP recovery."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from evaluation.condition_matrix import validate_matrix
from scripts.analyze_primary_http import trial_metrics, number


def same_bytes(first, second):
    a, b = (first or {}).get('sha256'), (second or {}).get('sha256')
    return a == b if isinstance(a, str) and isinstance(b, str) else None


def file_evidence(trial, mode):
    observation = trial.get('partial_write')
    events = observation.get('write_events') if isinstance(observation, dict) else None
    partials = [e for e in events or [] if e.get('phase') == 'candidate_partial_write']
    immediate = []
    for index, event in enumerate(events or []):
        if event.get('phase') != 'candidate_partial_write':
            continue
        restore = events[index+1] if index+1 < len(events) else None
        if restore and restore.get('phase') not in {'rollback_write', 'rollback_write_rejected'}:
            restore = None
        immediate.append({'prefix_bytes_written': event.get('bytes_written'),
            'candidate_valid_after_prefix': event.get('after', {}).get('valid'),
            'restore_attempt_observed': restore is not None,
            'restore_write_rejected': restore.get('phase') == 'rollback_write_rejected' if restore else None,
            'original_bytes_restored_immediately': same_bytes(event.get('before'), restore.get('after')) if restore else None,
            'config_valid_after_restore_attempt': restore.get('after', {}).get('valid') if restore else None})
    initial, final = trial.get('initial_state', {}).get('config'), trial.get('final_state', {}).get('config')
    original = same_bytes(initial, final)
    return {'fault_mode': mode, 'write_observation_present': isinstance(events, list),
        'injection_reached': True if partials else False if isinstance(events, list) else None,
        'immediate_restoration': immediate,
        'later_write_events': [event for index, event in enumerate(events or []) if index >= 2],
        'final_original_bytes_restored': original,
        'final_residual_config_change': not original if original is not None else None,
        'final_config_valid': (final or {}).get('valid'),
        'write_event_count': len(events) if isinstance(events, list) else None,
        'write_observation_scope': 'no injection wrapper on clean condition' if mode is None else 'actual write boundaries, not continuous HTTP observation'}


def key(row):
    return tuple(row.get(k) for k in ('case_id', 'condition', 'observation', 'repetition'))


def analyze(report):
    if report.get('protocol') != 'sabakan-http-partial-write-development-v1' or report.get('status') not in {'completed', 'runtime_error'}:
        raise ValueError('terminal HTTP partial-write report required')
    plan = report['plan']
    slots = validate_matrix(plan, plan['matrix_design']['case_ids'])
    expected, actual = Counter(map(key, slots)), Counter(map(key, report['trials']))
    rows = []
    for slot in slots:
        options = plan['conditions'][slot['condition']]
        mode = plan['http_partial_write_modes'][slot['condition']]
        found = [t for t in report['trials'] if key(t) == key(slot)]
        row = {**slot, 'actor': options['actor'], 'fault_mode': mode,
               'measurement': 'missing' if not found else 'duplicate' if len(found) > 1 else 'recorded'}
        if len(found) == 1:
            t = found[0]
            row.update(trial_metrics(t, options))
            row.update(file_evidence(t, mode))
            row['approval_requests_observed'] = t.get('loop', {}).get('approval_required_count')
            row['broker_rollback'] = {k: t.get('loop', {}).get(k) for k in
                ('rollback_attempted_count', 'rollback_success_count')}
            row['config_executor_results'] = [{'request_id': e.get('request_id'), 'completed': e.get('completed'),
                    'result': e.get('result')} for e in t.get('monitor', {}).get('executor_events', [])
                    if e.get('kind') == 'mutation' and e.get('tool') == 'config_patch']
        rows.append(row)
    pairs = []
    for actor in ('playbook', 'model'):
        for repetition in range(plan['repetitions']):
            group = [r for r in rows if r['actor'] == actor and r['repetition'] == repetition]
            clean = next(r for r in group if r['fault_mode'] is None)
            for mode in ('partial_restore', 'partial_restore_failed'):
                fault = next(r for r in group if r['fault_mode'] == mode)
                pair = {'actor': actor, 'repetition': repetition, 'fault_mode': mode,
                        'clean_condition': clean['condition'], 'fault_condition': fault['condition'],
                        'clean_outcome': clean.get('outcome'), 'fault_outcome': fault.get('outcome'),
                        'injection_reached': fault.get('injection_reached')}
                for metric in ('elapsed_seconds', 'tool_calls', 'harm'):
                    a, c = fault.get(metric), clean.get(metric)
                    pair[metric+'_fault_minus_clean'] = a-c if number(a) and number(c) else None
                pairs.append(pair)
    return {'protocol': report['protocol'], 'matrix_complete': expected == actual,
            'missing': list((expected-actual).elements()), 'extra': list((actual-expected).elements()),
            'rows': rows, 'paired': pairs, 'limitations': [
                'One previously used invalid-config case, two repetitions; descriptive comparison only.',
                'Injected OSError after real prefix write, not actual disk exhaustion.',
                'Original invalid bytes restored is not HTTP recovery; immediate restoration and Broker rollback differ.',
                'Injection nonarrival is not recovery from partial apply. Retain later attempts and final independent postcheck.',
                'Clean write list is empty by construction, not evidence of no write; use independent Executor events.',
                'Boundary observations do not establish continuous availability; reported mutation flags do not prove no write.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    result = analyze(json.loads(raw))
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    result['analysis_source_sha256'] = {f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in
        ('scripts/analyze_http_partial.py', 'scripts/analyze_primary_http.py', 'evaluation/http_fixtures.py',
         'evaluation/condition_matrix.py')}
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    return 0 if result['matrix_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
