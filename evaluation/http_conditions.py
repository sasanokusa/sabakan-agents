"""Resolve only actor and approval variations for an HTTP condition."""
from evaluation.approval_scenarios import FixtureApprovalScenario


def http_condition(plan, condition):
    options = plan['conditions'][condition]
    actor = options.get('actor', 'playbook' if condition == 'B0' else 'model')
    if actor not in {'playbook', 'model'}:
        raise ValueError('unknown HTTP condition actor')
    selected = dict(plan)
    for name in ('approval_mode', 'approval_scenario'):
        if name in options:
            selected[name] = options[name]
    mode = selected.get('approval_mode', 'unassisted')
    scenario = selected.get('approval_scenario')
    if mode not in {'unassisted', 'fixture_auto_signature'}:
        raise ValueError('unknown approval mode')
    if scenario is not None and (mode != 'fixture_auto_signature' or scenario not in FixtureApprovalScenario.MODES):
        raise ValueError('invalid approval scenario')
    return actor, selected
