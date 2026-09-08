"""Resolve explicit actor, approval, and guard experiment variations."""
import math
from evaluation.approval_scenarios import FixtureApprovalScenario


def http_condition(plan, condition):
    options = plan['conditions'][condition]
    actor = options.get('actor', 'playbook' if condition == 'B0' else 'model')
    if actor not in {'playbook', 'model'}:
        raise ValueError('unknown HTTP condition actor')
    selected = dict(plan)
    for name in ('approval_mode', 'approval_scenario', 'identical_repeat_limit', 'external_recovery_delay_seconds'):
        if name in options:
            selected[name] = options[name]
    mode = selected.get('approval_mode', 'unassisted')
    scenario = selected.get('approval_scenario')
    if mode not in {'unassisted', 'fixture_auto_signature'}:
        raise ValueError('unknown approval mode')
    if scenario is not None and (mode != 'fixture_auto_signature' or scenario not in FixtureApprovalScenario.MODES):
        raise ValueError('invalid approval scenario')
    validate_guard_options(selected)
    return actor, selected


def validate_guard_options(plan):
    limit = plan.get('identical_repeat_limit')
    delay = plan.get('external_recovery_delay_seconds')
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 20):
        raise ValueError('identical repeat limit must be an integer between 1 and 20')
    if delay is not None and (type(delay) not in (int, float) or not math.isfinite(delay) or not 0 <= delay <= 180):
        raise ValueError('external recovery delay must be finite and between 0 and 180 seconds')
    return limit, delay
