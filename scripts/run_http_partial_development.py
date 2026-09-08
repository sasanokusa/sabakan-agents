#!/usr/bin/env python3
"""Isolated HTTP partial-write comparison using original Executor recovery paths."""
import argparse
from contextlib import contextmanager
import json
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation import http_trials
from scripts import diagnose_lfm_observations as runner
from scripts.run_http_attack_development import require_primary_finished
from scripts.run_partial_config_controls import ObservedWritePath


@contextmanager
def partial_write_factory(mode, instances):
    if mode not in {None, 'partial_restore', 'partial_restore_failed'}:
        raise ValueError('unknown HTTP partial-write mode')
    original = http_trials.HttpExecutor
    def factory(*args, **kwargs):
        executor = original(*args, **kwargs)
        if mode is not None:
            observed = ObservedWritePath(executor.config_path, mode)
            executor.config_path = observed
            instances.append(observed)
        return executor
    http_trials.HttpExecutor = factory
    try:
        yield
    finally:
        http_trials.HttpExecutor = original


def validate_plan(plan):
    if plan.get('protocol') != 'sabakan-http-partial-write-development-v1' or plan.get('fixture_type') != 'http':
        raise ValueError('explicit partial-write HTTP protocol required')
    modes = plan.get('http_partial_write_modes')
    if not isinstance(modes, dict) or set(modes) != set(plan['conditions']):
        raise ValueError('every condition needs an explicit fault mode')
    if set(modes.values()) != {None, 'partial_restore', 'partial_restore_failed'}:
        raise ValueError('clean, partial restore and failed restore controls required')
    if any(row.get('case_id') != 'development-http-invalid_config' for row in plan['matrix']):
        raise ValueError('known invalid-config development case required')
    if plan.get('approval_mode') != 'fixture_auto_signature':
        raise ValueError('separate-plane fixture approval required')
    if plan.get('fixture_verification_failure') or plan.get('fixture_rollback_snapshot_loss'):
        raise ValueError('do not combine partial writes with other fault interventions')


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--plan', type=Path, required=True)
    args, _ = parser.parse_known_args()
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    for source, expected in plan['entrypoint_source_sha256'].items():
        if hashlib.sha256((ROOT / source).read_bytes()).hexdigest() != expected:
            raise RuntimeError('partial-write entrypoint source drift: ' + source)
    require_primary_finished(ROOT / plan['requires_completed_sequence'])
    live = subprocess.run(['docker', 'ps', '--filter', 'name=sabakan-lfm-diagnostic-', '--format', '{{.Names}}'],
                          capture_output=True, text=True, timeout=10)
    if live.returncode or live.stdout.strip():
        raise RuntimeError('cannot verify an idle comparison runtime')
    original = runner.run_http_trial
    def trial(case, condition, chat, selected, image, name, model):
        mode, instances = plan['http_partial_write_modes'][condition], []
        with partial_write_factory(mode, instances):
            record = original(case, condition, chat, selected, image, name, model)
        events = [event for observed in instances for event in observed.events]
        record['partial_write'] = {'mode': mode, 'write_events': events,
            'injection_reached': any(e.get('phase') == 'candidate_partial_write' for e in events),
            'scope': 'First candidate write persists a prefix then raises injected OSError. Failed-restore mode rejects only the second write. Subsequent writes use the original path. Real disposable file; not real ENOSPC.',
            'attribution': 'Fault controller, not model action; actual HTTP effects use independent monitor snapshots.'}
        return record
    runner.run_http_trial = trial
    try:
        return runner.main()
    finally:
        runner.run_http_trial = original


if __name__ == '__main__':
    raise SystemExit(main())
