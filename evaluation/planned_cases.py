"""Explicit new alert instances, without claiming new failure families."""
from dataclasses import dataclass

from evaluation.research_cases import ResearchCase


@dataclass(frozen=True)
class PlannedCase(ResearchCase):
    symptom: str

    def public_incident(self):
        return {'id': 'incident-001', 'symptom': self.symptom,
                'observations': ['host alias is local',
                    f"affected {'service' if self.kind == 'service' else 'container'} is {self.target}"]}


def planned_cases(plan):
    """Use an explicit pool only; reject legacy IDs and ambiguous contracts."""
    if plan.get('failure_family_holdout') is not False:
        raise ValueError('availability fixtures cannot establish failure-family holdout')
    result = {}
    for entry in plan['case_pool']:
        if not entry['case_id'].startswith('followup-') or entry['case_id'] in result:
            raise ValueError('case IDs must be unique and separate from legacy pools')
        if entry['kind'] not in {'service', 'docker'} or type(entry['unhealthy']) is not bool:
            raise ValueError('invalid case state')
        if not isinstance(entry['symptom'], str) or not entry['symptom'].strip():
            raise ValueError('explicit public symptom required')
        if entry.get('split') != 'evaluation' or entry.get('attack') is not False:
            raise ValueError('this pool supports clean evaluation alerts only')
        result[entry['case_id']] = PlannedCase(**entry)
    if not result:
        raise ValueError('empty case pool')
    return result
