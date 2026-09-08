#!/usr/bin/env python3
"""Run the fixed Issue #8 development observation comparison on CUDA."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from evaluation.agent_loop import COMMON_SYSTEM_PROMPT
from evaluation.diagnostic_observations import InformativeExecutor
from evaluation.attack_conditions import availability_executor, preserve_legacy_goal_scope
from evaluation.research_cases import MonitoredExecutor, research_cases, playbook
from evaluation.condition_matrix import validate_matrix
from evaluation.planned_cases import planned_cases
from evaluation.runtime_overlay import with_runtime_overlay
from evaluation.http_fixtures import HttpCase, FAULTS, playbook as http_playbook
from evaluation.http_conditions import http_condition
from evaluation.http_trials import run_http_trial
from scripts.download_models import sha256
from scripts.evaluate_llamacpp import docker_command, http_json, require_runtime
from scripts.evaluate_mac_research import run_trial, write_report, digest

PLAN = ROOT / 'evaluation/protocols/lfm-observation-dev-20260907.json'


def command_output(args, timeout=10):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return {'returncode': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}


def start_runtime(model, plan, name, port):
    command = docker_command(model, name, port, plan['runtime_image'], plan['context_size'],
                             plan['gpu_layers'], plan['reasoning_budget'], plan['reasoning_mode'])
    command = with_runtime_overlay(command, plan.get('runtime_overlay'))
    command[3:3] = ['--memory', plan['budget']['server_ram_limit'], '--cpus', plan['budget']['server_cpu_limit'],
                    '--pids-limit', str(plan['budget']['server_pids_limit']), '--security-opt', 'no-new-privileges']
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=45)
    expires = time.monotonic() + plan['budget']['server_start_seconds']
    last_error = None
    while time.monotonic() < expires:
        state = command_output(['docker', 'inspect', '--format', '{{.State.Status}}', name])
        if state['returncode'] != 0 or state['stdout'] in {'exited', 'dead'}:
            raise RuntimeError(f'model server stopped: {state}')
        try:
            http_json(f'http://127.0.0.1:{port}/health', None, timeout=2)
            return command
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f'server startup deadline: {last_error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18083)
    parser.add_argument('--plan', type=Path, default=PLAN,
                        help='Frozen development plan; defaults to the original LFM comparison')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan = json.loads(args.plan.read_text())
    fixture_type = plan.get('fixture_type', 'availability')
    if fixture_type not in {'availability', 'http'}:
        raise ValueError('unknown development fixture type')
    cases = ({'development-http-' + fault: HttpCase(fault) for fault in FAULTS}
             if fixture_type == 'http' else {c.case_id: c for c in research_cases('development')})
    if 'case_pool' in plan:
        if fixture_type != 'availability' or 'matrix_design' not in plan:
            raise ValueError('explicit availability case pool requires a matrix design')
        cases = planned_cases(plan)
    matrix = validate_matrix(plan, cases)
    if fixture_type == 'http':
        if 'attack_notices' in plan:
            raise ValueError('attack notices require availability fixture')
        for row in matrix:
            http_condition(plan, row['condition'])
    else:
        for row in matrix:
            availability_executor(plan, row, cases)
    manifest = json.loads((ROOT / 'models/manifest.json').read_text())
    model = next(m for m in manifest['models'] + manifest.get('archived_models', []) if m['label'] == plan['model'])
    if sha256(ROOT / model['path']) != plan['model_sha256']:
        raise ValueError('model SHA mismatch')
    require_runtime()
    model_spec = {**model, 'path': ROOT / model['path']}
    report = {
        'protocol': plan['protocol'], 'plan': plan, 'plan_sha256': sha256(args.plan),
        'base_commit': command_output(['git', 'rev-parse', 'HEAD'])['stdout'],
        'source_sha256': {str(p.relative_to(ROOT)): sha256(p)
            for folder in ('src', 'evaluation', 'scripts', 'config') for p in sorted((ROOT / folder).rglob('*'))
            if p.is_file() and p.suffix in {'.py', '.yaml'}},
        'model': model, 'prompt_sha256': digest(COMMON_SYSTEM_PROMPT + ('\n' + plan['system_prompt_suffix'] if plan.get('system_prompt_suffix') else '')),
        'platform': platform.platform(), 'python': sys.version,
        'gpu': command_output(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,driver_version', '--format=csv']),
        'gpu_processes_before': command_output(['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory', '--format=csv']),
        'runtime_image': command_output(['docker', 'image', 'inspect', plan['runtime_image']]),
        'trials': [], 'gpu_samples': [], 'status': 'starting',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    started = time.monotonic()
    stop_sampling = threading.Event()
    def sample_gpu():
        while not stop_sampling.is_set():
            sample = {'offset_seconds': time.monotonic() - started}
            try:
                sample['device'] = command_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], timeout=3)
                sample['processes'] = command_output(['nvidia-smi', '--query-compute-apps=pid,used_memory', '--format=csv,noheader'], timeout=3)
            except Exception as exc:
                sample['error'] = str(exc)
            report['gpu_samples'].append(sample)
            stop_sampling.wait(0.5)
    sampler = threading.Thread(target=sample_gpu, daemon=True)
    sampler.start()
    name = f'sabakan-lfm-diagnostic-{os.getpid()}'
    url = f'http://127.0.0.1:{args.port}'
    try:
        load_started = time.monotonic()
        report['server_command'] = start_runtime(model_spec, plan, name, args.port)
        report['load_seconds'] = time.monotonic() - load_started
        for endpoint in ('/props', '/v1/models'):
            try:
                report[endpoint] = http_json(url + endpoint, None, timeout=10)
            except Exception as exc:
                report[endpoint] = {'error': str(exc)}
        warmup = {'model': 'local', 'messages': [{'role': 'user', 'content': 'Hello'}], 'max_tokens': 8, 'temperature': 0, 'stream': False}
        report['warmup'] = {'request': warmup, 'response': http_json(url + '/v1/chat/completions', warmup, timeout=120)}
        report['status'] = 'running'
        for index, row in enumerate(matrix):
            if time.monotonic() - started >= plan['budget']['total_seconds']:
                report['trials'].append({**row, 'started': False, 'error': 'TOTAL_BUDGET_EXHAUSTED'})
                continue
            requests = []
            report['active_trial'] = {**row, 'index': index, 'phase': 'before_setup',
                                      'start_status': 'unknown', 'http_requests': requests}
            write_report(args.output, report)
            def chat(messages, tools):
                payload = {'model': 'local', 'messages': messages, 'tools': list(tools),
                           'tool_choice': 'auto', **plan['generation'], 'stream': False}
                request_record = {'request': copy.deepcopy(payload), 'schema_sha256': digest(list(tools))}
                requests.append(request_record)
                report['active_trial'].update(phase='model_request_prepared', start_status='started')
                write_report(args.output, report)
                try:
                    response = http_json(url + '/v1/chat/completions', payload, timeout=plan['deadline_seconds'])
                except BaseException as exc:
                    request_record['error'] = f'{type(exc).__name__}: {exc}'
                    report['active_trial']['phase'] = 'model_request_error'
                    write_report(args.output, report)
                    raise
                request_record['response'] = copy.deepcopy(response)
                report['active_trial']['phase'] = 'model_response_received'
                write_report(args.output, report)
                choice = response['choices'][0]
                return {**choice['message'], 'finish_reason': choice.get('finish_reason'),
                        'usage': response.get('usage', {}), 'timings': response.get('timings', {})}
            if fixture_type == 'http':
                actor, trial_plan = http_condition(plan, row['condition'])
                record = run_http_trial(cases[row['case_id']], row['condition'],
                                        http_playbook if actor == 'playbook' else chat, trial_plan, plan['fixture_image'],
                                        f'sabakan-http-model-{os.getpid()}-{index}',
                                        'playbook' if actor == 'playbook' else plan['model'])
            else:
                record = run_trial(cases[row['case_id']], row['condition'],
                                   playbook if row['condition'] == 'B0' else chat, plan, plan['fixture_image'],
                                   f'sabakan-lfm-case-{os.getpid()}-{index}',
                                   'playbook' if row['condition'] == 'B0' else plan['model'],
                                   executor_factory=availability_executor(plan, row, cases))
                if 'attack_notices' in plan:
                    preserve_legacy_goal_scope(record)
            record.update(row)
            record['http_requests'] = requests
            report['trials'].append(record)
            report.pop('active_trial', None)
            write_report(args.output, report)
            print(index + 1, row, record['score']['outcome'], record['loop'].get('failure_reason'), flush=True)
        report['status'] = 'completed'
    except Exception as exc:
        report['status'] = 'runtime_error'
        report['error'] = f'{type(exc).__name__}: {exc}'
        for row in matrix[len(report['trials']):]:
            report['trials'].append({**row, 'started': False, 'error': 'RUNTIME_UNAVAILABLE'})
    finally:
        report['server_logs'] = command_output(['docker', 'logs', name], timeout=20)
        report['server_removal'] = command_output(['docker', 'rm', '-f', name], timeout=25)
        stop_sampling.set()
        sampler.join(timeout=10)
        report['gpu_processes_after'] = command_output(['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory', '--format=csv'])
        report['elapsed_seconds'] = time.monotonic() - started
        write_report(args.output, report)
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
