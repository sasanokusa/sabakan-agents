import unittest
from unittest.mock import patch

from scripts.run_resource_fault_controls import TmpfsExecutor, bounded_runtime
from sabakan_broker.models import ToolRequest


class ResourceFaultControlTests(unittest.TestCase):
    def test_runtime_check_rejects_each_missing_bound(self):
        config = dict(Memory=67108864, MemorySwap=67108864, NanoCpus=250000000,
                      PidsLimit=32, NetworkMode='none', ReadonlyRootfs=True,
                      CapDrop=['ALL'], SecurityOpt=['no-new-privileges'])
        self.assertTrue(bounded_runtime(config))
        for key in config:
            altered = dict(config)
            del altered[key]
            self.assertFalse(bounded_runtime(altered), key)

    def test_out_of_scope_requests_do_not_reach_docker(self):
        executor = TmpfsExecutor('fixture')
        with patch('scripts.run_resource_fault_controls.exec_json') as execute:
            for request in (
                ToolRequest('disk_status', {'host': 'remote'}),
                ToolRequest('disk_usage', {'host': 'local', 'resource': 'other'}),
                ToolRequest('journal_query', {'host': 'local'}),
            ):
                self.assertFalse(executor.execute_read(request).ok)
            self.assertFalse(executor.execute_mutation(
                ToolRequest('log_rotate', {'host': 'local', 'resource': 'other'})).ok)
            execute.assert_not_called()
