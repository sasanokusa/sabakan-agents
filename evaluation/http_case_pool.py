"""Explicit development compound HTTP cases, validated before model loading."""
from evaluation.http_fixtures import CompoundHttpCase, FAULTS, HttpCase


def http_cases(plan):
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
