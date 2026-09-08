"""Explicit HTTP cases, preserving development/reference/evaluation identity."""
from dataclasses import dataclass
from evaluation.http_fixtures import CompoundHttpCase, FAULTS, HttpCase


@dataclass(frozen=True)
class PlannedHttpCase(HttpCase):
    case_id: str
    split: str
    symptom: str
    prior_exposure: str

    def __post_init__(self):
        if '+' in self.fault:
            CompoundHttpCase(self.fault)
        else:
            HttpCase(self.fault)
        if not self.case_id.startswith('primary-http-'):
            raise ValueError('primary HTTP case ID required')
        if not self.symptom.strip():
            raise ValueError('public symptom required')
        if (self.split, self.prior_exposure) not in {
                ('evaluation', 'unexecuted_combination_at_freeze'),
                ('reference', 'previously_used_control')}:
            raise ValueError('explicit evaluation or reference exposure required')
        if self.split == 'evaluation' and len(self.faults) != 2:
            raise ValueError('this evaluation pool admits two-fault combinations only')

    @property
    def faults(self):
        return frozenset() if self.fault == 'healthy' else frozenset(self.fault.split('+'))

    def public_incident(self):
        return {**super().public_incident(), 'symptom': self.symptom}

    def contract(self):
        return {**super().contract(), 'case_id': self.case_id, 'split': self.split,
                'component_faults': sorted(self.faults), 'prior_exposure': self.prior_exposure,
                'failure_family_holdout': False}


def http_cases(plan):
    if 'http_case_pool' in plan:
        if plan.get('failure_family_holdout') is not False or 'compound_http_faults' in plan:
            raise ValueError('explicit HTTP pool requires no family holdout or mixed pool')
        entries = plan['http_case_pool']
        if not isinstance(entries, list) or not entries:
            raise ValueError('nonempty HTTP case pool required')
        cases = {}
        for entry in entries:
            case = PlannedHttpCase(**entry)
            if case.case_id in cases:
                raise ValueError('duplicate HTTP case ID')
            cases[case.case_id] = case
        return cases
    cases = {'development-http-' + fault: HttpCase(fault) for fault in FAULTS}
    combinations = plan.get('compound_http_faults', [])
    if not isinstance(combinations, list) or any(not isinstance(value, str) for value in combinations):
        raise ValueError('compound_http_faults must be a list of canonical strings')
    if len(set(combinations)) != len(combinations):
        raise ValueError('duplicate compound HTTP cases')
    for fault in combinations:
        case = CompoundHttpCase(fault)
        cases[case.contract()['case_id']] = case
    return cases
