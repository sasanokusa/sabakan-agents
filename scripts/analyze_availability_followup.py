#!/usr/bin/env python3
"""Analyze the frozen availability followup without mixing pilot records."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.condition_matrix import validate_matrix
from evaluation.planned_cases import planned_cases
from evaluation.mechanism_audit import audit_surface
from scripts.analyze_mac_research import _group_metrics, _paired_value, _percentile


def key(row):
    return tuple(row.get(k) for k in ('case_id', 'condition', 'observation', 'repetition'))


def paired(report, comparator, metric):
    plan = report['plan']
    index = {key(t): t for t in report['trials']}
    differences, missing = {}, []
    families = {c['case_id']: c['kind'] for c in plan['case_pool']}
    for case in plan['case_pool']:
        cid = case['case_id']
        if metric in {'resolution', 'elapsed_resolution'} and not case['unhealthy']:
            continue
        if metric == 'nonintervention' and case['unhealthy']:
            continue
        values = []
        for repetition in range(plan['matrix_design']['repetitions']):
            pair = [index.get((cid, c, 'informative', repetition)) for c in ('B2', comparator)]
            observed = [_paired_value(t, metric) if t else None for t in pair]
            if any(v is None for v in observed):
                missing.append({'case_id': cid, 'repetition': repetition,
                                'reason': 'unstarted, missing measurement, or not joint success'})
                continue
            values.append(observed[0] - observed[1])
        # Do not silently average a subset of planned repetitions.
        if len(values) == plan['matrix_design']['repetitions']:
            differences[cid] = statistics.mean(values)
    clusters = {}
    for cid, value in differences.items():
        clusters.setdefault(families[cid], []).append(value)
    bootstrap = []
    if clusters:
        rng = random.Random(20260908)
        names = sorted(clusters)
        for _ in range(2000):
            sample = [value for name in rng.choices(names, k=len(names)) for value in clusters[name]]
            bootstrap.append(statistics.mean(sample))
    interval = [_percentile(bootstrap, .025), _percentile(bootstrap, .975)]
    return {'case_differences': differences, 'paired_case_count': len(differences),
            'family_count': len(clusters), 'missing_pairs': missing,
            'mean_difference': statistics.mean(differences.values()) if differences else None,
            'observed_range': [min(differences.values()), max(differences.values())] if differences else None,
            'family_cluster_percentile_interval': interval,
            'degenerate_interval': bool(bootstrap) and interval[0] == interval[1],
            'interpretation': 'Descriptive sensitivity only; at most two shared families. No equivalence or no-risk inference.'}


def analyze(report):
    if report.get('protocol') != 'sabakan-availability-ablation-followup-v1':
        raise ValueError('wrong protocol')
    if report.get('status') not in {'completed', 'runtime_error'}:
        raise ValueError('report is still running')
    plan = report['plan']
    expected = Counter(key(r) for r in validate_matrix(plan, planned_cases(plan)))
    actual = Counter(key(t) for t in report['trials'])
    complete = actual == expected
    result = {'protocol': report['protocol'], 'matrix_complete': complete,
              'missing_cells': list((expected-actual).elements()),
              'extra_cells': list((actual-expected).elements()),
              'groups': {c: _group_metrics('playbook' if c == 'B0' else plan['model'], c,
                         [t for t in report['trials'] if t.get('condition') == c]) for c in plan['conditions']},
              'comparisons': {},
              'mechanism_audit': [{**dict(zip(('case_id', 'condition', 'observation', 'repetition'), key(t))),
                                   **(audit_surface(t, plan['conditions'][t['condition']]) if t.get('condition') in plan['conditions'] else {'measured': False, 'reason': 'unknown condition'})}
                                  for t in report['trials']],
              'limitations': plan['analysis_contract'],
              'server_removed': report.get('server_removal', {}).get('returncode') == 0}
    # Duplicate or unexpected rows invalidate paired estimates, never last-row-wins.
    if not (actual-expected):
        result['comparisons'] = {c: {m: paired(report, c, m) for m in
            ('resolution', 'nonintervention', 'operational_harm', 'boundary_violation',
             'guard_intervention', 'elapsed_resolution', 'calls')}
            for c in ('B1', 'A_no_staging', 'A_no_hints')}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.input.read_bytes()
    result = analyze(json.loads(data))
    result['input_sha256'] = hashlib.sha256(data).hexdigest()
    result['analyzer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return 0 if result['matrix_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
