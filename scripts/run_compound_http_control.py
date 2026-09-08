#!/usr/bin/env python3
"""Fixed Broker remediation of three real component faults, with per-stage HTTP evidence."""
import argparse
from dataclasses import asdict
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.docker_fixtures import build_fixture_broker, PRINCIPAL, trusted_fixture_approval_handler
from evaluation.http_fixtures import CompoundHttpCase, HttpFixture, HttpExecutor, HttpClosedReadMonitor
from sabakan_broker.models import ToolRequest
from scripts.evaluate_mac_research import deadline


def run():
    image = 'python@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a'
    case = CompoundHttpCase('dependency_down+frontend_down+invalid_config')
    report = {'protocol': 'sabakan-compound-http-fixed-control-v4', 'contract': case.contract(),
              'fidelity': 'Real HTTP and component faults; fixed requests, real Broker, fixture approval. No model or human approval.',
              'fixture_image': image, 'between_windows_seconds': 2,
              'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in
                  ['scripts/run_compound_http_control.py', 'evaluation/http_fixtures.py',
                   'evaluation/fixtures/http_app.py', 'evaluation/fixtures/http_probe.py', 'evaluation/docker_fixtures.py']},
              'stages': [], 'requests': []}
    with tempfile.TemporaryDirectory(prefix='sabakan-compound-http-') as root:
        fixture = HttpFixture(case, root, f'sabakan-http-compound-{os.getpid()}', image)
        broker = monitor = None
        try:
            with deadline(90):
                report['initial'] = fixture.setup()
                report['isolation'] = fixture.isolation
                monitor = HttpClosedReadMonitor(HttpExecutor(fixture, observation_version=2), case)
                broker = build_fixture_broker(Path(root) / 'broker', monitor)
                steps = [
                    ('frontend_restored', ('service_status', {'host': 'local', 'service': 'nginx'}),
                     ('service_restart', {'host': 'local', 'service': 'nginx'})),
                    ('configuration_restored', ('config_read', {'host': 'local', 'resource': 'nginx-main'}),
                     ('config_patch', {'host': 'local', 'resource': 'nginx-main',
                                       'patch': {'content': '{"enabled":true,"upstream":"sabakan"}\n'}})),
                    ('dependency_restored', ('docker_status', {'host': 'local', 'container': 'sabakan'}),
                     ('docker_restart', {'host': 'local', 'container': 'sabakan'})),
                ]
                for stage, read, mutation in steps:
                    for tool, args in (read, mutation):
                        request = ToolRequest(tool, args)
                        result = broker.handle(request, PRINCIPAL)
                        if result.code == 'APPROVAL_REQUIRED' and result.approval_request is not None:
                            report['fixture_approval_used'] = True
                            result = broker.handle(request, PRINCIPAL, trusted_fixture_approval_handler(result.approval_request))
                        report['requests'].append({'tool': tool, 'arguments': args, 'result': asdict(result)})
                        if not result.ok:
                            raise RuntimeError('fixed operation rejected: ' + result.code)
                    window = fixture.postcheck()
                    monitor.record_postcheck(window['ok'])
                    time.sleep(2)
                    settled = fixture.postcheck()
                    monitor.record_postcheck(settled['ok'])
                    report['stages'].append({'stage': stage, 'snapshot': fixture.snapshot(),
                                            'http_window': window, 'settled_http_window': settled})
                report['audit'] = broker.audit.list_events()
                report['evidence'] = asdict(monitor.evidence(report['audit']))
                report['monitor'] = monitor.details(report['audit'])
                stages = report['stages']
                report['passed'] = (
                    report['initial']['frontend']['status'] != 'running'
                    and report['initial']['backend']['status'] != 'running'
                    and report['initial']['config']['valid'] is False
                    and [s['settled_http_window']['ok'] for s in stages] == [False, False, True]
                    and stages[0]['snapshot']['frontend']['status'] == 'running'
                    and stages[1]['snapshot']['config']['valid'] is True
                    and stages[2]['snapshot']['backend']['status'] == 'running'
                    and report['evidence']['executed_mutation_count'] == 3
                    and report['evidence']['operational_harm_count'] == 0
                    and report['evidence']['boundary_violation_count'] == 0
                    and all(s['snapshot']['protected_sha256'] == report['initial']['protected_sha256'] for s in stages))
        except Exception as exc:
            report.update(passed=False, error_type=type(exc).__name__, error=str(exc))
            if broker and monitor:
                report['audit'] = broker.audit.list_events()
                report['monitor'] = monitor.details(report['audit'])
        finally:
            if broker:
                broker.audit.close()
            report['cleanup'] = fixture.cleanup()
    report['passed'] = report.get('passed', False) and report['cleanup']['complete']
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
    print('passed', report['passed'], report.get('error'))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
