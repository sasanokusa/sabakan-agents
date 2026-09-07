"""Development-only observation intervention for Issue #8.

Target status calls retain the pilot behavior. Only previously empty auxiliary
observations are replaced, using the current disposable Docker state. No
correct action, hidden case identifier, or expected outcome is returned.
"""
from dataclasses import replace
from evaluation.research_cases import MonitoredExecutor, snapshot


class InformativeExecutor(MonitoredExecutor):
    def execute_read(self, request):
        result = super().execute_read(request)
        if not result.ok or request.tool not in {
            'host_status', 'service_list', 'docker_list', 'journal_query', 'docker_logs'}:
            return result
        try:
            observed = snapshot(self.name)
        except BaseException:
            self.complete = False
            raise
        target = {'host': 'local', 'kind': self.case.kind,
                  'logical_resource': self.case.target, 'status': observed['status']}
        if request.tool == 'service_list':
            data = {'services': [target] if self.case.kind == 'service' else []}
        elif request.tool == 'docker_list':
            data = {'containers': [target] if self.case.kind == 'docker' else []}
        else:
            data = {'observed_target': target,
                           'evidence_source': 'disposable container state summary'}
        return replace(result, data=data)
