"""Bounded Linux RSS and cgroup-v2 RAM observations, distinct from GPU VRAM."""
import json
from pathlib import Path
import subprocess


def memory_from_state(state, *, proc_root=Path('/proc'), cgroup_root=Path('/sys/fs/cgroup')):
    result = {'container_id': state.get('Id'), 'pid': state.get('State', {}).get('Pid'),
              'rss_bytes': None, 'rss_high_water_bytes': None,
              'cgroup_current_bytes': None, 'cgroup_peak_bytes': None, 'cgroup_memory_events': None,
              'scope': 'Container init-process RSS and whole-container cgroup RAM including cache; not VRAM.'}
    pid, cid = result['pid'], result['container_id']
    if type(pid) is not int or pid <= 0 or not isinstance(cid, str) or len(cid) != 64:
        result['unavailable'] = 'container process not identified'
        return result
    try:
        membership = (proc_root / str(pid) / 'cgroup').read_text().splitlines()
        path = next(line.split(':', 2)[2] for line in membership if line.startswith('0::'))
        if cid not in path or '..' in Path(path).parts:
            result['unavailable'] = 'cgroup does not identify this container'
            return result
        for line in (proc_root / str(pid) / 'status').read_text().splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[2] == 'kB' and fields[0] in {'VmRSS:', 'VmHWM:'}:
                number = int(fields[1])
                if number >= 0:
                    result['rss_bytes' if fields[0] == 'VmRSS:' else 'rss_high_water_bytes'] = number * 1024
        directory = cgroup_root / path.lstrip('/')
        for file, key in [('memory.current', 'cgroup_current_bytes'), ('memory.peak', 'cgroup_peak_bytes')]:
            try:
                number = int((directory / file).read_text().strip())
                if number >= 0:
                    result[key] = number
            except (OSError, ValueError):
                pass
        try:
            result['cgroup_memory_events'] = {key: int(value) for key, value in
                (line.split() for line in (directory / 'memory.events').read_text().splitlines())}
        except (OSError, ValueError):
            pass
    except (OSError, ValueError, StopIteration) as exc:
        result['unavailable'] = type(exc).__name__
    return result


def sample_container_memory(name):
    observed = subprocess.run(['docker', 'inspect', '--format',
        '{"Id":{{json .Id}},"State":{{json .State}}}', name],
        capture_output=True, text=True, timeout=3)
    if observed.returncode:
        return {'unavailable': 'container inspect failed', 'returncode': observed.returncode}
    return memory_from_state(json.loads(observed.stdout))
