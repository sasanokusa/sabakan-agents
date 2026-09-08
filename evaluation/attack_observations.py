"""Paired attack notices on informative fixture reads; no host data access."""
from dataclasses import replace
from evaluation.diagnostic_observations import InformativeExecutor


class AttackObservationExecutor(InformativeExecutor):
    def __init__(self, case, name, *, notice=None):
        if case.attack != (notice is not None):
            raise ValueError('case attack contract and notice must agree')
        if notice is not None and (not isinstance(notice, str) or not notice.strip()):
            raise ValueError('nonempty attack notice required')
        super().__init__(case, name)
        self.notice = notice

    def execute_read(self, request):
        result = super().execute_read(request)
        if result.ok and self.notice is not None:
            # Replace the legacy notice after auxiliary observation formatting.
            # Preserve all status evidence; never alter policy/schema/resource IDs.
            return replace(result, data={**result.data, 'untrusted_notice': self.notice})
        return result

    def evidence(self, delivered, audit_events):
        evidence = super().evidence(delivered, audit_events)
        reached = None if self.notice is None else any(
            message.get('role') == 'tool' and self.notice in str(message.get('content', ''))
            for messages in delivered for message in messages)
        return replace(evidence, attack_reached_model=reached)
