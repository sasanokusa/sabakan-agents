#!/usr/bin/env python3
"""Real temporary-file writes with injected partial-I/O faults; no model or Docker."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.docker_fixtures import DockerFixtureExecutor, build_fixture_broker, PRINCIPAL, trusted_fixture_approval_handler
from sabakan_broker.models import ToolRequest


def snapshot(path):
    raw = path.read_bytes()
    valid, error, _ = DockerFixtureExecutor._validation(raw)
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'valid': valid,
            'validation_error': error}


class ObservedWritePath:
    """Inject after actual prefix write, before Executor's normal rollback path."""
    def __init__(self, path, mode):
        if mode not in {'partial_restore', 'partial_restore_failed', 'validation_failed'}:
            raise ValueError('unknown fixed fault mode')
        self.path, self.mode = Path(path), mode
        self.events = []
        self.attempts = 0

    def __str__(self):
        return str(self.path)

    def __getattr__(self, key):
        return getattr(self.path, key)

    def write_bytes(self, data):
        self.attempts += 1
        before = snapshot(self.path)
        if self.attempts == 1 and self.mode.startswith('partial_'):
            count = self.path.write_bytes(data[:max(1, len(data)//2)])
            self.events.append({'phase': 'candidate_partial_write', 'bytes_written': count,
                                'before': before, 'after': snapshot(self.path), 'injected_error': 'OSError'})
            raise OSError('fixed partial-write injection after prefix persisted')
        if self.attempts == 2 and self.mode == 'partial_restore_failed':
            self.events.append({'phase': 'rollback_write_rejected', 'bytes_written': 0,
                                'before': before, 'after': snapshot(self.path), 'injected_error': 'OSError'})
            raise OSError('fixed rollback-write injection before write')
        count = self.path.write_bytes(data)
        self.events.append({'phase': 'candidate_write' if self.attempts == 1 else 'rollback_write',
                            'bytes_written': count, 'before': before, 'after': snapshot(self.path)})
        return count


def run_control(mode, approve=True):
    with tempfile.TemporaryDirectory(prefix='sabakan-partial-file-') as root:
        path = Path(root) / 'service.json'
        path.write_text('{"enabled":true,"upstream":"sabakan"}\n')
        observed = ObservedWritePath(path, mode)
        executor = DockerFixtureExecutor({}, config_path=observed)
        broker = build_fixture_broker(Path(root) / 'broker', executor)
        row = {'mode': mode, 'approval_supplied': approve, 'initial': snapshot(path)}
        try:
            content = '{invalid JSON\n' if mode == 'validation_failed' else '{\n "enabled": true, "upstream": "sabakan"\n}\n'
            request = ToolRequest('config_patch', {'host': 'local', 'resource': 'nginx-main',
                                                  'patch': {'content': content}})
            result = broker.handle(request, PRINCIPAL)
            row['initial_broker_code'] = result.code
            if approve:
                if result.code != 'APPROVAL_REQUIRED' or result.approval_request is None:
                    raise RuntimeError('expected separate-plane approval request')
                result = broker.handle(request, PRINCIPAL, trusted_fixture_approval_handler(result.approval_request))
            row.update(result_code=result.code, result_ok=result.ok,
                       reported_mutation_executed=result.mutation_executed,
                       write_events=observed.events, final=snapshot(path))
            # Never persist a signed approval, secret, or nonce from the approval object.
            row['audit'] = broker.audit.list_events()
            row['partial_write_observed'] = any(e['phase'] == 'candidate_partial_write' for e in observed.events)
            row['intermediate_invalid_config_observed'] = any(e['after']['valid'] is False for e in observed.events)
            row['original_bytes_restored'] = row['initial']['sha256'] == row['final']['sha256']
            row['residual_change_observed'] = not row['original_bytes_restored']
            expected_partial = approve and mode.startswith('partial_')
            expected_residual = approve and mode == 'partial_restore_failed'
            row['passed'] = (row['initial_broker_code'] == 'APPROVAL_REQUIRED'
                and not result.ok and row['partial_write_observed'] == expected_partial
                and row['residual_change_observed'] == expected_residual
                and row['intermediate_invalid_config_observed'] == approve
                and len(observed.events) == (2 if approve else 0))
        finally:
            broker.audit.close()
    row['temporary_directory_removed'] = not Path(root).exists()
    row['passed'] &= row['temporary_directory_removed']
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    rows = [run_control(mode) for mode in ('partial_restore', 'partial_restore_failed', 'validation_failed')]
    rows.append(run_control('partial_restore', approve=False))
    report = {'protocol': 'sabakan-partial-config-file-controls-v1', 'rows': rows,
              'all_passed': all(row['passed'] for row in rows),
              'fidelity': 'Real temporary-file writes and original Executor/Broker path; simulated OSError, no HTTP service, Docker, model, host configuration or credentials.',
              'limitation': 'Intermediate file validity is measured at write boundaries, not continuous availability or service impact.',
              'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in
                  ['scripts/run_partial_config_controls.py', 'evaluation/docker_fixtures.py', 'src/sabakan_broker/broker.py']}}
    with args.output.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print('all_passed', report['all_passed'])
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
