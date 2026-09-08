#!/usr/bin/env python3
"""Run an immutable, counterbalanced primary matrix with one model at a time."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.condition_matrix import validate_matrix
from evaluation.http_case_pool import http_cases


def validate_design(plan, children):
    models = {row['model']: row for row in plan['models']}
    if len(models) != len(plan['models']) or len(children) != len(plan['blocks']):
        raise ValueError('duplicate model or missing block')
    expected = Counter((model, case['case_id'], condition, repetition)
        for model, spec in models.items() for case in plan['http_case_pool']
        for condition in spec['conditions'] for repetition in range(plan['repetitions']))
    actual = Counter()
    for block, child in zip(plan['blocks'], children):
        if child['model'] not in models or child['model_sha256'] != models[child['model']]['sha256']:
            raise ValueError('unexpected block model')
        if child.get('http_case_pool') != plan['http_case_pool']:
            raise ValueError('block case pool drift')
        if any(child.get(key) != value for key, value in plan['common'].items()):
            raise ValueError('block common settings drift')
        if child['conditions'] != {key: plan['conditions'][key] for key in models[child['model']]['conditions']}:
            raise ValueError('block harness drift')
        for row in validate_matrix(child, http_cases(child)):
            if row.get('study_repetition') != block['study_repetition']:
                raise ValueError('block repetition mismatch')
            actual[(child['model'], row['case_id'], row['condition'], row['study_repetition'])] += 1
    if actual != expected:
        raise ValueError('primary matrix missing or duplicated rows')
    return sum(expected.values())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cleanup_interrupted(pid):
    """Only this child runner's explicitly named disposable resources."""
    commands = [['docker', 'rm', '-f', f'sabakan-lfm-diagnostic-{pid}']]
    prefix = f'sabakan-http-model-{pid}-'
    for kind, query in [('container', ['docker', 'ps', '-a']), ('network', ['docker', 'network', 'ls'])]:
        found = subprocess.run(query + ['--filter', f'name={prefix}', '--format', '{{.Names}}' if kind == 'container' else '{{.Name}}'],
                               capture_output=True, text=True, timeout=15)
        for name in found.stdout.splitlines():
            if name.startswith(prefix):
                commands.append(['docker', 'rm', '-f', name] if kind == 'container' else ['docker', 'network', 'rm', name])
    results = []
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            results.append({'command': command, 'returncode': result.returncode, 'stderr': result.stderr.strip()})
        except subprocess.TimeoutExpired:
            results.append({'command': command, 'timeout': True})
    return results


def remaining_resources(pid):
    result = {}
    for kind, query, template in [('containers', ['docker', 'ps', '-a'], '{{.Names}}'),
                                  ('networks', ['docker', 'network', 'ls'], '{{.Name}}')]:
        try:
            found = subprocess.run(query + ['--filter', f'name={pid}', '--format', template],
                                   capture_output=True, text=True, timeout=15)
            result[kind] = ([name for name in found.stdout.splitlines()
                if name == f'sabakan-lfm-diagnostic-{pid}' or name.startswith(f'sabakan-http-model-{pid}-')]
                if found.returncode == 0 else None)
        except subprocess.TimeoutExpired:
            result[kind] = None
    result['complete'] = result['containers'] == [] and result['networks'] == []
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan = json.loads(args.plan.read_text())
    if plan.get('protocol') != 'sabakan-gtx1650-primary-sequence-v1' or plan.get('execution_allowed') is not True:
        raise ValueError('frozen executable primary sequence required')
    children = []
    paths = []
    for block in plan['blocks']:
        path = ROOT / block['plan']
        if digest(path) != block['plan_sha256']:
            raise ValueError('child plan hash mismatch')
        children.append(json.loads(path.read_text()))
        paths.extend([block['output'], block['log']])
    if len(paths) != len(set(paths)) or any((ROOT / path).exists() for path in paths):
        raise ValueError('block output or log exists or overlaps; never retry silently')
    count = validate_design(plan, children)
    started = time.monotonic()
    report = {'protocol': plan['protocol'], 'plan_sha256': digest(args.plan), 'plan': plan,
              'expected_trials': count, 'status': 'running', 'blocks': []}
    def save():
        temporary = args.output.with_suffix(args.output.suffix + '.partial')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(args.output)
    save()
    for block in plan['blocks']:
        drift = [path for path, sha in plan['source_sha256'].items() if digest(ROOT / path) != sha]
        if drift:
            report.update(status='source_drift', changed_sources=drift)
            break
        remaining = plan['budget_seconds'] - (time.monotonic()-started)
        if remaining < block['timeout_seconds'] or shutil.disk_usage(ROOT).free < plan['minimum_free_bytes']:
            report['status'] = 'resource_budget_stop'
            break
        record = {**block, 'started_offset_seconds': time.monotonic()-started}
        report['blocks'].append(record)
        command = [sys.executable, 'scripts/diagnose_lfm_observations.py', '--plan', block['plan'],
                   '--output', block['output'], '--port', str(plan['port'])]
        with (ROOT / block['log']).open('x') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            record.update(pid=process.pid, command=command, status='running')
            save()
            try:
                record['returncode'] = process.wait(timeout=block['timeout_seconds'])
                record['status'] = 'exited'
            except subprocess.TimeoutExpired:
                record['status'] = 'block_timeout'
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                record['cleanup'] = cleanup_interrupted(process.pid)
        record['elapsed_seconds'] = time.monotonic()-started-record['started_offset_seconds']
        record['resource_check'] = remaining_resources(process.pid)
        if not record['resource_check']['complete']:
            record['cleanup'] = cleanup_interrupted(process.pid)
            record['resource_check'] = remaining_resources(process.pid)
        path = ROOT / block['output']
        record['output_sha256'] = digest(path) if path.exists() else None
        save()
        print(block['id'], record['status'], record.get('returncode'), flush=True)
        if not record['resource_check']['complete']:
            report['status'] = 'cleanup_not_verified'
            break
    else:
        report['status'] = 'completed' if all(b.get('returncode') == 0 for b in report['blocks']) else 'completed_with_block_failures'
    report['unstarted_blocks'] = [b['id'] for b in plan['blocks'][len(report['blocks']):]]
    report['elapsed_seconds'] = time.monotonic()-started
    save()
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
