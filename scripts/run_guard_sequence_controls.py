#!/usr/bin/env python3
"""Fixed Broker controls for polling limits; synthetic, not timed recovery."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.docker_fixtures import build_fixture_broker, PRINCIPAL
from sabakan_broker.models import ExecutionResult, ToolRequest


class SequenceExecutor:
    config_path = None

    def __init__(self, sequence):
        self.sequence = sequence
        self.observed = []

    def execute_read(self, request):
        state = self.sequence[min(len(self.observed), len(self.sequence) - 1)]
        self.observed.append({'request_id': request.request_id, 'state': state})
        return ExecutionResult(True, 'READ_OK', {'status': state})


def run():
    sequences = {'delayed_recovery': ['starting', 'starting', 'ready'],
                 'no_progress': ['starting'] * 6}
    rows = []
    for case, sequence in sequences.items():
        for limit in (2, 4):
            with tempfile.TemporaryDirectory() as tmp:
                executor = SequenceExecutor(sequence)
                broker = build_fixture_broker(Path(tmp), executor, identical_repeat_limit=limit)
                responses = []
                started = time.monotonic()
                for _ in range(6):
                    if time.monotonic() - started > 10:
                        raise TimeoutError('independent control deadline')
                    result = broker.handle(ToolRequest('service_status', {'host': 'local', 'service': 'nginx'}), PRINCIPAL)
                    responses.append(asdict(result))
                    if not result.ok or (result.data or {}).get('status') == 'ready':
                        break
                reached = any(e['state'] == 'ready' for e in executor.observed)
                expected_ready = case == 'delayed_recovery' and limit == 4
                expected_stop = 'READ_OK' if expected_ready else 'LOOP_DETECTED'
                rows.append({'case': case, 'repeat_limit': limit, 'expected_ready': expected_ready,
                             'expected_terminal_code': expected_stop, 'ready_observed': reached,
                             'elapsed_seconds': time.monotonic() - started,
                             'executor_observations': executor.observed, 'responses': responses,
                             'audit': broker.audit.list_events(100),
                             'passed': reached == expected_ready and responses[-1]['code'] == expected_stop})
    return {'protocol': 'sabakan-guard-sequence-development-v1',
            'fidelity': 'Synthetic fixed observation sequence through real Broker. Progress advances on reads, not wall-clock. No model, physical recovery, mutation or general safety claim.',
            'outer_limit': {'calls': 6, 'seconds_checked_between_calls': 10},
            'rows': rows, 'all_passed': all(r['passed'] for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run()
    result['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('all_passed', result['all_passed'])
    return 0 if result['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
