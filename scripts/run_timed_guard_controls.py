#!/usr/bin/env python3
"""Real HTTP polling through Broker, changing only its identical-call limit."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.delayed_recovery import DelayedDependencyRecovery
from evaluation.docker_fixtures import build_fixture_broker, PRINCIPAL
from evaluation.http_fixtures import HttpFixture, HttpCase, HttpExecutor, HttpMonitor
from sabakan_broker.models import ToolRequest
from scripts.evaluate_mac_research import deadline, TrialTimeout


def run():
    image = 'python@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a'
    report = {'protocol': 'sabakan-timed-guard-controls-v1', 'rows': [],
        'contract': {'delay_seconds': 4, 'poll_interval_seconds': 3, 'max_calls': 6,
                     'outer_seconds': 25, 'repeat_limits': [2, 4],
                     'fidelity': 'Fixed polling, real Broker and HTTP. External recovery is not model/Broker repair.'}}
    for mode in ('delayed', 'no_progress'):
        for limit in (2, 4):
            with tempfile.TemporaryDirectory(prefix='sabakan-guard-http-') as tmp:
                fixture = HttpFixture(HttpCase('dependency_down'), tmp,
                    f'sabakan-http-guard-{os.getpid()}-{mode}-{limit}', image)
                broker = controller = monitor = None
                row = {'mode': mode, 'repeat_limit': limit, 'responses': [], 'ready_observed': False}
                try:
                    row['initial'] = fixture.setup()
                    monitor = HttpMonitor(HttpExecutor(fixture, observation_version=2), fixture.case)
                    broker = build_fixture_broker(Path(tmp) / 'broker', monitor, identical_repeat_limit=limit)
                    if mode == 'delayed':
                        controller = DelayedDependencyRecovery(fixture, 4)
                        controller.start()
                    started = time.monotonic()
                    with deadline(25):
                        for index in range(6):
                            if index:
                                time.sleep(3)
                            result = broker.handle(ToolRequest('service_status',
                                {'host': 'local', 'service': 'nginx'}), PRINCIPAL)
                            row['responses'].append({'offset_seconds': time.monotonic() - started,
                                                     'result': asdict(result)})
                            row['ready_observed'] = bool(result.ok and (result.data or {}).get('http_ok'))
                            if not result.ok or row['ready_observed']:
                                break
                    row['poll_elapsed_seconds'] = time.monotonic() - started
                    row['terminal_code'] = row['responses'][-1]['result']['code']
                except (Exception, TrialTimeout) as exc:
                    row['error_type'] = type(exc).__name__
                finally:
                    if controller:
                        controller.close()
                        row['controller'] = controller.record
                    if monitor:
                        row['postcheck'] = fixture.postcheck()
                        monitor.record_postcheck(row['postcheck']['ok'])
                        row['final'] = fixture.snapshot()
                        row['audit'] = broker.audit.list_events()
                        row['evidence'] = asdict(monitor.evidence(row['audit']))
                        row['monitor'] = monitor.details(row['audit'])
                    if broker:
                        broker.audit.close()
                    row['cleanup'] = fixture.cleanup()
                expected_ready = mode == 'delayed' and limit == 4
                row['expected_ready'] = expected_ready
                row['passed'] = ('error_type' not in row and row['ready_observed'] == expected_ready
                    and row.get('terminal_code') == ('READ_OK' if expected_ready else 'LOOP_DETECTED')
                    and row['cleanup']['complete'])
                report['rows'].append(row)
                print(mode, limit, row['passed'], row.get('terminal_code'), flush=True)
    report['all_passed'] = all(row['passed'] for row in report['rows'])
    return report


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
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
