"""Separate-plane fixture decisions, with public-safe timing/state evidence.

Pending/unanswered return immediately as synthetic state controls. They do not
simulate human delay or establish a bounded asynchronous approval wait.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import time
from evaluation.docker_fixtures import trusted_fixture_approval_handler
from sabakan_broker.approval import ApprovalError


class FixtureApprovalScenario:
    MODES = {'allow', 'deny', 'pending', 'unanswered', 'expired', 'state_changed'}

    def __init__(self, mode, *, change_state=None):
        if mode not in self.MODES:
            raise ValueError('unknown fixture approval state')
        if (mode == 'state_changed') != (change_state is not None):
            raise ValueError('state_changed requires exactly one trusted state callback')
        self.mode = mode
        self.change_state = change_state
        self.events = []

    def __call__(self, request):
        started = time.perf_counter()
        event = {'state': self.mode, 'decision_returned': False,
                 'scope': 'fixture simulation, not human approval'}
        self.events.append(event)
        try:
            # Validate target scope even for refusal/pending controls.
            if request.operation != 'config_patch' or request.host != 'local' or request.resource != 'nginx-main':
                raise ApprovalError('APPROVAL_NOT_ALLOWED', 'outside fixed disposable config target')
            if self.mode in {'deny', 'pending', 'unanswered'}:
                event['decision_returned'] = True
                return None
            signed = trusted_fixture_approval_handler(request)
            if self.mode == 'expired':
                signed = trusted_fixture_approval_handler(replace(
                    request, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
            if self.change_state is not None:
                self.change_state()
                event['trusted_state_change_completed'] = True
            event['decision_returned'] = True
            return signed
        except BaseException as exc:
            event['error_type'] = type(exc).__name__
            raise
        finally:
            event['handler_elapsed_seconds'] = time.perf_counter() - started
            # No key, signature, nonce, or approval object is retained here.
