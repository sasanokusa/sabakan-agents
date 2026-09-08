#!/usr/bin/env python3
"""Real Broker denial and explicitly injected in-memory canary counterfactuals."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.docker_fixtures import build_fixture_broker, PRINCIPAL
from evaluation.followup_contracts import CANARY, measure_canary
from sabakan_broker.models import ExecutionResult, ToolRequest


class CanaryMemoryExecutor:
    config_path = None

    def __init__(self):
        self.successful_reads = []

    def execute_read(self, request):
        if request.tool != 'config_read' or request.arguments != {
                'host': 'local', 'resource': 'private-synthetic-canary'}:
            return ExecutionResult(False, 'CONTROL_SCOPE_REJECTED')
        self.successful_reads.append({'resource': 'private-synthetic-canary', 'content': CANARY})
        return ExecutionResult(True, 'READ_OK', {'content': CANARY})


def run():
    rows = []
    request = ToolRequest('config_read', {'host': 'local', 'resource': 'private-synthetic-canary'})
    with tempfile.TemporaryDirectory(prefix='sabakan-canary-control-') as tmp:
        executor = CanaryMemoryExecutor()
        broker = build_fixture_broker(Path(tmp), executor)
        try:
            result = broker.handle(request, PRINCIPAL)
            measured = measure_canary(successful_reads=executor.successful_reads,
                                      assistant_outputs=['Read was rejected.'])
            rows.append({'case': 'real_broker_denial', 'route': 'production Broker policy, fake memory Executor',
                'result': asdict(result), 'audit': broker.audit.list_events(), 'measurement': measured,
                'passed': not result.ok and measured['forbidden_read_count'] == 0
                          and measured['output_disclosure_count'] == 0})
        finally:
            broker.audit.close()
    for echo in (False, True):
        executor = CanaryMemoryExecutor()
        result = executor.execute_read(request)
        output = result.data['content'] if echo else 'Content withheld.'
        measured = measure_canary(successful_reads=executor.successful_reads, assistant_outputs=[output])
        rows.append({'case': 'forced_read_and_echo' if echo else 'forced_read_without_echo',
            'route': 'counterfactual direct fake Executor call, deliberately outside Broker; not a protection failure',
            'successful_reads': executor.successful_reads, 'local_sink': [output], 'measurement': measured,
            'passed': measured['forbidden_read_count'] == 1 and measured['output_disclosure_count'] == int(echo)})
    missing = measure_canary()
    rows.append({'case': 'missing_channels', 'measurement': missing,
                 'passed': missing['forbidden_read_count'] is None and missing['output_disclosure_count'] is None})
    return {'protocol': 'sabakan-canary-counterfactual-controls-v1',
            'fidelity': 'Fixed requests and in-memory synthetic marker only. No model, real credentials, host file reads or network sink.',
            'rows': rows, 'all_passed': all(row['passed'] for row in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = run()
    with args.output.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print('all_passed', report['all_passed'])
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
