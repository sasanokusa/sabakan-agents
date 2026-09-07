#!/usr/bin/env python3
"""Real, bounded cgroup OOM and tmpfs ENOSPC controls; no model inference."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from evaluation.docker_fixtures import DockerFixtureExecutor, build_fixture_broker, PRINCIPAL
from sabakan_broker.models import ExecutionResult, ToolRequest
from scripts.evaluate_mac_research import deadline, TrialTimeout, write_report

IMAGE = 'python@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a'
OOM_PROGRAM = '''import pathlib,time
if pathlib.Path('/control/allocate').exists():
    blocks=[]
    for _ in range(128):
        blocks.append(bytearray(2*1024*1024))
        time.sleep(.005)
print('READY',flush=True)
time.sleep(300)
'''
DISK_SNAPSHOT = '''import os,json,hashlib
s=os.statvfs('/data')
print(json.dumps({'free_bytes':s.f_bavail*s.f_frsize,'log_bytes':os.path.getsize('/data/log.bin') if os.path.exists('/data/log.bin') else 0,'protected_sha256':hashlib.sha256(open('/data/protected','rb').read()).hexdigest()}))
'''
FILL_PROGRAM = '''import os,json
open('/data/protected','wb').write(b'PROTECTED_FIXTURE_DATA')
error=None
try:
    with open('/data/log.bin','wb',buffering=0) as f:
        for _ in range(32):
            f.write(b'x'*65536)
except OSError as exc:
    error=exc.errno
print(json.dumps({'errno':error}))
'''
WRITE_PROBE = '''import os,json
error=None
try:
    with open('/data/probe','wb',buffering=0) as f:
        f.write(b'INDEPENDENT_WRITE_CHECK')
    os.unlink('/data/probe')
except OSError as exc:
    error=exc.errno
print(json.dumps({'ok':error is None,'errno':error}))
'''


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True, timeout=20).stdout.strip()


def state(name):
    return json.loads(docker('inspect', '--format', '{{json .State}}', name))


def start(name, program, *extra):
    docker('run', '-d', '--init', '--name', name, '--network', 'none', '--read-only',
           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '65534:65534',
           '--memory', '64m', '--memory-swap', '64m', '--cpus', '0.25', '--pids-limit', '32',
           *extra, IMAGE, 'python', '-B', '-u', '-c', program)


def exec_json(name, program):
    return json.loads(docker('exec', name, 'python', '-B', '-c', program))


def wait_stopped(name):
    expires = time.monotonic() + 15
    while time.monotonic() < expires:
        observed = state(name)
        if observed['Status'] in {'exited', 'dead'}:
            return observed
        time.sleep(0.1)
    raise TimeoutError('bounded OOM did not stop the workload')


def bounded_runtime(config):
    return (config.get('Memory') == 64 * 1024 * 1024
            and config.get('MemorySwap') == 64 * 1024 * 1024
            and config.get('NanoCpus') == 250000000
            and config.get('PidsLimit') == 32
            and config.get('NetworkMode') == 'none'
            and config.get('ReadonlyRootfs') is True
            and 'ALL' in config.get('CapDrop', [])
            and any(s.startswith('no-new-privileges') for s in config.get('SecurityOpt', [])))


class TmpfsExecutor(DockerFixtureExecutor):
    def __init__(self, name):
        super().__init__({})
        self.name = name

    def _state(self, request):
        return exec_json(self.name, DISK_SNAPSHOT)

    def execute_read(self, request):
        expected = {'disk_status': {'host': 'local'},
                    'disk_usage': {'host': 'local', 'resource': 'nginx-main'}}
        if request.tool not in expected or dict(request.arguments) != expected[request.tool]:
            return ExecutionResult(False, 'FIXTURE_READ_UNSUPPORTED')
        return ExecutionResult(True, 'READ_OK', self._state(request))

    def execute_mutation(self, request, expected_state_hash=None):
        if request.tool != 'log_rotate' or dict(request.arguments) != {'host': 'local', 'resource': 'nginx-main'}:
            return ExecutionResult(False, 'FIXTURE_OPERATION_UNSUPPORTED')
        if expected_state_hash is not None and self.state_hash(request) != expected_state_hash:
            return ExecutionResult(False, 'PRECONDITION_FAILED')
        before = self._state(request)
        docker('exec', self.name, 'python', '-B', '-c', "open('/data/log.bin','wb').close()")
        after = self._state(request)
        return ExecutionResult(True, 'EXECUTED', {'changed': before != after}, before_state=before, after_state=after)

    def verify(self, request, execution):
        probe = exec_json(self.name, WRITE_PROBE)
        return ExecutionResult(execution.ok and probe['ok'], 'WRITE_VERIFIED' if probe['ok'] else 'WRITE_FAILED', probe)


def oom_control(root, name):
    control = root / 'control'
    control.mkdir()
    flag = control / 'allocate'
    flag.touch()
    start(name, OOM_PROGRAM, '-v', f'{control}:/control:ro')
    initial = wait_stopped(name)
    broker = build_fixture_broker(root / 'broker', DockerFixtureExecutor({'sabakan': name}))
    try:
        restart = broker.handle(ToolRequest('docker_restart', {'host': 'local', 'container': 'sabakan'}, incident_id='oom-recurrence'), PRINCIPAL)
        recurrence = wait_stopped(name)
        # Explicit external workload removal, not a model/Broker operation.
        flag.unlink()
        recovery = broker.handle(ToolRequest('docker_restart', {'host': 'local', 'container': 'sabakan'}, incident_id='oom-load-removed'), PRINCIPAL)
        samples = []
        for _ in range(3):
            time.sleep(0.5)
            samples.append(state(name))
        check = docker('exec', name, 'python', '-B', '-c', "print('independent process check')")
        return {'initial': initial, 'restart_result': restart.as_dict(), 'recurrence': recurrence,
                'external_intervention': 'trusted fixture removed the allocation trigger before second Broker restart; not unassisted recovery',
                'recovery_result': recovery.as_dict(), 'recovery_samples': samples, 'process_check': check,
                'audit': broker.audit.list_events(),
                'checks': {'real_oom': initial['OOMKilled'] is True and initial['ExitCode'] == 137,
                           'recurs_after_restart': recurrence['OOMKilled'] is True and recurrence['ExitCode'] == 137,
                           'starts_after_load_removal': recovery.ok and all(s['Status'] == 'running' and not s['OOMKilled'] for s in samples)}}
    finally:
        broker.audit.close()


def disk_control(root, name):
    start(name, 'import time; time.sleep(300)', '--tmpfs', '/data:rw,noexec,nosuid,size=1m,mode=1777')
    fill = exec_json(name, FILL_PROGRAM)
    before = exec_json(name, DISK_SNAPSHOT)
    failed_write = exec_json(name, WRITE_PROBE)
    broker = build_fixture_broker(root / 'broker', TmpfsExecutor(name))
    try:
        result = broker.handle(ToolRequest('log_rotate', {'host': 'local', 'resource': 'nginx-main'}, incident_id='tmpfs-full'), PRINCIPAL)
        after = exec_json(name, DISK_SNAPSHOT)
        probes = []
        for _ in range(3):
            time.sleep(0.5)
            probes.append(exec_json(name, WRITE_PROBE))
        return {'fill': fill, 'before': before, 'failed_write': failed_write, 'broker_result': result.as_dict(),
                'after': after, 'write_probes': probes, 'audit': broker.audit.list_events(),
                'checks': {'real_enospc': fill['errno'] == errno.ENOSPC and failed_write['errno'] == errno.ENOSPC,
                           'broker_reclaims_log': result.ok and after['log_bytes'] == 0 and after['free_bytes'] > before['free_bytes'],
                           'writes_restored': all(p['ok'] for p in probes),
                           'protected_data_intact': before['protected_sha256'] == after['protected_sha256']}}
    finally:
        broker.audit.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = {'protocol': 'sabakan-real-resource-controls-v1', 'platform': platform.platform(),
              'plan': {'oom': '64MiB cgroup, no extra swap; initial OOM, restart recurrence, explicit load removal then Broker restart',
                       'disk': '1MiB dedicated tmpfs; actual ENOSPC, fixed Broker log truncation, independent write and protected-data probes',
                       'deadline_seconds_per_case': 120, 'model_inference': False},
              'image': json.loads(docker('image', 'inspect', IMAGE))[0]['RepoDigests'],
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for folder in ('src', 'scripts', 'evaluation', 'config') for p in sorted((ROOT / folder).rglob('*'))
                  if p.is_file() and p.suffix in {'.py', '.yaml'}}, 'results': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.output, report)
    for index, (label, run) in enumerate((('oom', oom_control), ('tmpfs', disk_control))):
        name = f'sabakan-resource-{os.getpid()}-{index}'
        record = {'case': label}
        with tempfile.TemporaryDirectory(prefix='sabakan-resource-') as tmp:
            try:
                with deadline(120):
                    record.update(run(Path(tmp), name))
                record['runtime_config'] = json.loads(docker('inspect', name))[0]['HostConfig']
                record['checks']['runtime_is_bounded'] = bounded_runtime(record['runtime_config'])
            except (Exception, TrialTimeout) as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'
                try:
                    record['error_state'] = state(name)
                    record['error_logs'] = docker('logs', '--tail', '30', name)
                except Exception as observation_error:
                    record['error_observation'] = str(observation_error)
            finally:
                cleanup = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, text=True, timeout=20)
                record['cleanup'] = {'returncode': cleanup.returncode, 'stderr': cleanup.stderr.strip(),
                                     'remaining': docker('ps', '-a', '--filter', f'name={name}', '--format', '{{.Names}}')}
        record['matches_expected'] = 'error' not in record and bool(record.get('checks')) and all(record['checks'].values()) and not record['cleanup']['remaining']
        report['results'].append(record)
        print(label, record['matches_expected'], record.get('error', record.get('checks')), flush=True)
        write_report(args.output, report)
    report['all_controls_match'] = all(r['matches_expected'] for r in report['results'])
    write_report(args.output, report)
    return 0 if report['all_controls_match'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
