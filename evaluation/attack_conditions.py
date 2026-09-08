"""Select explicit development attack observations without relabeling old goals."""
from functools import partial
from evaluation.attack_observations import AttackObservationExecutor
from evaluation.diagnostic_observations import InformativeExecutor
from evaluation.research_cases import MonitoredExecutor


def availability_executor(plan, row, cases):
    if 'attack_notices' not in plan:
        return InformativeExecutor if row['observation'] == 'informative' else MonitoredExecutor
    notices = plan['attack_notices']
    if not isinstance(notices, dict) or set(notices) - set(cases):
        raise ValueError('attack notices must map known cases')
    if row['observation'] != 'informative':
        raise ValueError('explicit attack notices require informative observations')
    case = cases[row['case_id']]
    notice = notices.get(case.case_id)
    if case.attack != (notice is not None):
        raise ValueError('attack case and explicit notice must agree')
    if notice is not None and (not isinstance(notice, str) or not notice.strip()):
        raise ValueError('nonempty attack notice required')
    return partial(AttackObservationExecutor, notice=notice)


def preserve_legacy_goal_scope(record):
    record['legacy_system_reboot_goal_metrics'] = {
        key: record.pop(key) for key in list(record) if key.startswith('attack_goal_')}
    record['custom_attack_goal_measured'] = False
    record['attack_goal_scope'] = 'Legacy goal metrics concern system_reboot only; custom goal requires separate analysis. Independent mutation and harm observations retain their own scope.'
