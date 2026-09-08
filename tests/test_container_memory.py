from pathlib import Path
import tempfile
import unittest
from evaluation.container_memory import memory_from_state


class ContainerMemoryTests(unittest.TestCase):
    def test_rss_and_cgroup_counters_keep_distinct_units_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cid = 'a' * 64
            process = root / 'proc/123'
            process.mkdir(parents=True)
            process.joinpath('cgroup').write_text('0::/docker/' + cid + '\n')
            process.joinpath('status').write_text('VmRSS:\t2 kB\nVmHWM:\t3 kB\n')
            group = root / 'groups/docker' / cid
            group.mkdir(parents=True)
            group.joinpath('memory.current').write_text('4096\n')
            group.joinpath('memory.peak').write_text('8192\n')
            group.joinpath('memory.events').write_text('oom 1\noom_kill 1\n')
            result = memory_from_state({'Id': cid, 'State': {'Pid': 123}}, proc_root=root / 'proc', cgroup_root=root / 'groups')
            self.assertEqual(result['rss_bytes'], 2048)
            self.assertEqual(result['rss_high_water_bytes'], 3072)
            self.assertEqual(result['cgroup_current_bytes'], 4096)
            self.assertEqual(result['cgroup_peak_bytes'], 8192)
            self.assertEqual(result['cgroup_memory_events']['oom_kill'], 1)
            group.joinpath('memory.peak').unlink()
            result = memory_from_state({'Id': cid, 'State': {'Pid': 123}}, proc_root=root / 'proc', cgroup_root=root / 'groups')
            self.assertIsNone(result['cgroup_peak_bytes'])
            self.assertEqual(result['cgroup_current_bytes'], 4096)

    def test_absent_or_unmatched_process_is_not_zero_memory(self):
        result = memory_from_state({'Id': 'a' * 64, 'State': {'Pid': 0}})
        self.assertIsNone(result['rss_bytes'])
        with tempfile.TemporaryDirectory() as tmp:
            process = Path(tmp) / '123'
            process.mkdir()
            process.joinpath('cgroup').write_text('0::/unrelated-container\n')
            result = memory_from_state({'Id': 'a' * 64, 'State': {'Pid': 123}}, proc_root=Path(tmp))
            self.assertIsNone(result['cgroup_current_bytes'])
            self.assertIn('does not identify', result['unavailable'])
