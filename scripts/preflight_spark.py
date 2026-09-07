#!/usr/bin/env python3
"""Bounded CPU format/tool-call preflight; no Broker mutation or research trial."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from scripts.download_models import sha256
from scripts.evaluate_llamacpp import http_json
from scripts.evaluate_mac_research import deadline, TrialTimeout, write_report
from sabakan_broker.schema import openai_tool_schemas
from evaluation.adapters import adapt_output


def limits():
    resource.setrlimit(resource.RLIMIT_AS, (12 * 1024**3, 12 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (1800, 1800))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18085)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan_path = ROOT / 'evaluation/protocols/spark-cpu-preflight-20260907.json'
    plan = json.loads(plan_path.read_text())
    model = next(m for m in json.loads((ROOT / 'models/manifest.json').read_text())['models'] if m['label'] == plan['model'])
    weight = ROOT / model['path']
    if sha256(weight) != model['sha256']:
        raise ValueError('weight hash mismatch')
    server = args.server.resolve(strict=True)
    command = [str(server), '-m', str(weight.resolve()), '--host', '127.0.0.1', '--port', str(args.port),
               '-c', '2048', '-ngl', '0', '-np', '1', '-t', '4', '-tb', '4',
               '--reasoning', 'off', '--reasoning-budget', '0', '--jinja']
    report = {'protocol': plan['protocol'], 'plan': plan, 'plan_sha256': sha256(plan_path),
              'model': model, 'server_sha256': sha256(server), 'command': command,
              'runtime_files_sha256': {p.name: sha256(p) for p in sorted(server.parent.iterdir())
                  if p.is_file() and ('.so' in p.name or p == server)},
              'status': 'starting', 'requests': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    started = time.monotonic()
    process = None
    with tempfile.TemporaryFile(mode='w+') as logs:
        try:
            with deadline(600):
                process = subprocess.Popen(command, stdout=logs, stderr=logs, start_new_session=True, preexec_fn=limits)
                base = f'http://127.0.0.1:{args.port}'
                expires = time.monotonic() + 180
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f'server exited with {process.returncode}')
                    try:
                        http_json(base + '/health', None, timeout=2)
                        break
                    except (OSError, ValueError, RuntimeError):
                        if time.monotonic() >= expires:
                            raise TimeoutError('server startup exceeded 180 seconds')
                        time.sleep(0.5)
                report['load_seconds'] = time.monotonic() - started
                report['props'] = http_json(base + '/props', None, timeout=10)
                tools = [s for s in openai_tool_schemas() if s['function']['name'] == 'service_status']
                messages = [{'role': 'user', 'content': 'Use the service_status function to inspect service nginx on host local. If the result is running, answer briefly that it is healthy and finish.'}]
                def query():
                    payload = {'model': 'local', 'messages': messages, 'tools': tools, 'tool_choice': 'auto',
                               'max_tokens': 128, 'temperature': 0, 'seed': 42, 'stream': False}
                    record = {'request': json.loads(json.dumps(payload))}
                    report['requests'].append(record)
                    try:
                        response = http_json(base + '/v1/chat/completions', payload, timeout=180)
                        record['response'] = response
                        return response['choices'][0]['message']
                    except BaseException as exc:
                        record['error'] = f'{type(exc).__name__}: {exc}'
                        raise
                first = query()
                proposal = adapt_output(first.get('content') or '', first)
                report['canonical'] = asdict(proposal)
                calls = first.get('tool_calls') or []
                correct = (len(calls) == 1 and calls[0]['function']['name'] == 'service_status'
                           and json.loads(calls[0]['function']['arguments']) == {'host': 'local', 'service': 'nginx'})
                report['checks'] = {'typed_call_correct': correct}
                report['checks']['canonical_call_correct'] = proposal.envelope_valid and proposal.proposal.get('tool_calls') == [
                    {'tool': 'service_status', 'arguments': {'host': 'local', 'service': 'nginx'}}]
                if correct:
                    messages.append(first)
                    messages.append({'role': 'tool', 'tool_call_id': calls[0]['id'], 'name': 'service_status',
                                     'content': json.dumps({'ok': True, 'code': 'READ_OK', 'data': {'status': 'running'}})})
                    second = query()
                    report['checks']['normal_text_after_synthetic_result'] = bool(second.get('content')) and not second.get('tool_calls')
                else:
                    report['checks']['normal_text_after_synthetic_result'] = False
                report['status'] = 'completed'
        except (Exception, TrialTimeout) as exc:
            report.update(status='error', error=f'{type(exc).__name__}: {exc}')
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
            report['server_returncode'] = process.returncode if process else None
            logs.seek(0)
            report['server_logs'] = logs.read()
            report['elapsed_seconds'] = time.monotonic() - started
            write_report(args.output, report)
    return 0 if report['status'] == 'completed' and all(report['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
