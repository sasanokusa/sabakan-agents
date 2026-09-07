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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = candidate_analysis(json.loads(args.input.read_text()))
    result['input_sha256'] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    with args.output.open('x') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write('\n')
    return 0 if result['matrix_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
