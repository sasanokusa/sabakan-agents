#!/usr/bin/env python3
"""Audit the frozen candidate screening without promoting it to holdout evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_lfm_observations import analyze, summarize_trial


def candidate_analysis(report):
    result = analyze(report)
    rows = [summarize_trial(t) for t in report['trials']]
    result['rows'] = rows
    result['paired_observation_comparison'] = False
    result['screening'] = {
        'resolved': sum(r['outcome'] == 'resolved' for r in rows),
        'appropriate_non_intervention': sum(r['outcome'] == 'appropriate_non_intervention' for r in rows),
        'planned_trials': len(report['plan']['matrix']),
        'started_trials': sum(r['started'] for r in rows),
    }
    result['screening']['passes_fixed_gate'] = (
        result['matrix_complete'] and report['status'] == 'completed'
        and result['screening']['started_trials'] == result['screening']['planned_trials']
        and result['screening']['resolved'] > 0
        and result['screening']['appropriate_non_intervention'] > 0)
    result['limitations'].append('Partial GPU offload with background workload; no full-offload fit or main model ranking claim.')
    return result


def compare_deadlines(baseline, followup):
    before, after = candidate_analysis(baseline), candidate_analysis(followup)
    fixed_keys = ('model', 'model_sha256', 'runtime_image', 'fixture_image',
                  'context_size', 'gpu_layers', 'generation', 'reasoning_mode',
                  'reasoning_budget', 'max_turns', 'conditions', 'matrix', 'intervention')
    fixed = {key: baseline['plan'].get(key) == followup['plan'].get(key)
             and key in baseline['plan'] for key in fixed_keys}
    pairs = []
    for old in baseline['trials']:
        matches = [t for t in followup['trials'] if t['case_id'] == old['case_id']
                   and t['observation'] == old['observation']]
        if len(matches) != 1:
            continue
        new = matches[0]
        def initial(t):
            requests = t.get('http_requests', [])
            return requests[0].get('request') if requests else None
        pairs.append({'case_id': old['case_id'],
                      'initial_request_identical': initial(old) == initial(new) if initial(old) is not None and initial(new) is not None else None,
                      'before': summarize_trial(old), 'after': summarize_trial(new)})
    return {'fixed_plan_fields': fixed,
            'both_matrices_complete': before['matrix_complete'] and after['matrix_complete'],
            'deadlines': [baseline['plan']['deadline_seconds'], followup['plan']['deadline_seconds']],
            'pairs': pairs,
            'interpretation': 'Sequential development diagnosis with changed trace instrumentation; not randomized causal or unused evaluation evidence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    result = candidate_analysis(json.loads(args.input.read_text()))
    result['input_sha256'] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    if args.baseline:
        result['deadline_comparison'] = compare_deadlines(
            json.loads(args.baseline.read_text()), json.loads(args.input.read_text()))
        result['baseline_sha256'] = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    with args.output.open('x') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write('\n')
    return 0 if result['matrix_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
