#!/usr/bin/env python3
"""Summarize saved observations using a separately verified interruption record."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from scripts.analyze_availability_followup import analyze, key


def analyze_interrupted(raw, evidence):
    if hashlib.sha256(raw).hexdigest() != evidence['raw_report_sha256']:
        raise ValueError('interruption evidence refers to another report')
    report = json.loads(raw)
    if report['status'] != 'running' or evidence['saved_trials'] != len(report['trials']):
        raise ValueError('interruption state does not match saved report')
    planned = report['plan']['matrix']
    count = len(report['trials'])
    if [key(t) for t in report['trials']] != [key(t) for t in planned[:count]]:
        raise ValueError('saved trials are not the planned prefix')
    if evidence['remaining_planned_rows'] != planned[count:]:
        raise ValueError('remaining rows differ from original matrix')
    # In-memory analysis view only; the original stale status is preserved on disk.
    view = copy.deepcopy(report)
    view['status'] = 'runtime_error'
    result = analyze(view)
    result.update(observation_status='externally_observed_interruption',
                  original_status=report['status'],
                  planned_cell_count=len(planned), saved_cell_count=count,
                  unsaved_cell_count=len(planned)-count,
                  unsaved_start_status=evidence['current_row_start_status'],
                  input_sha256=hashlib.sha256(raw).hexdigest(),
                  cleanup=evidence['cleanup'],
                  interpretation='Saved observations only. No imputation, replacement, completed experiment, or condition ranking.')
    result['cell_coverage_by_condition'] = {
        c: {'planned': sum(r['condition'] == c for r in planned),
            'saved': sum(r['condition'] == c for r in report['trials'])}
        for c in report['plan']['conditions']}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--interruption', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.interruption.read_bytes()
    result = analyze_interrupted(args.input.read_bytes(), json.loads(evidence))
    result['interruption_sha256'] = hashlib.sha256(evidence).hexdigest()
    with args.output.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
