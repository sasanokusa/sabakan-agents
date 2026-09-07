"""Resolve explicit condition rows before starting any evaluation resources."""
from collections import Counter


def validate_matrix(plan, case_ids):
    conditions = plan['conditions']
    if not conditions:
        raise ValueError('empty conditions')
    for options in conditions.values():
        if any(type(options.get(key)) is not bool
               for key in ('staged_tools', 'observation_hints')):
            raise ValueError('condition switches must be explicit booleans')
    rows = []
    for source in plan['matrix']:
        row = dict(source)
        if 'condition' not in row:
            if len(conditions) != 1:
                raise ValueError('multi-condition matrix requires explicit conditions')
            row['condition'] = next(iter(conditions))
        if row['condition'] not in conditions or row['case_id'] not in case_ids:
            raise ValueError('unknown matrix condition or case')
        if row.get('observation') not in {'baseline', 'informative', 'real_http'}:
            raise ValueError('unknown observation contract')
        row.setdefault('repetition', 0)
        if type(row['repetition']) is not int or row['repetition'] < 0:
            raise ValueError('invalid repetition')
        rows.append(row)
    keys = Counter((r['case_id'], r['condition'], r['observation'], r['repetition']) for r in rows)
    if not rows or any(count != 1 for count in keys.values()):
        raise ValueError('empty or duplicate matrix')
    if 'matrix_design' in plan:
        design = plan['matrix_design']
        axes = [design[key] for key in ('case_ids', 'conditions', 'observations')]
        if any(not axis or len(set(axis)) != len(axis) for axis in axes):
            raise ValueError('empty or duplicate design axis')
        repetitions = design['repetitions']
        if type(repetitions) is not int or repetitions < 1:
            raise ValueError('invalid design repetitions')
        expected = Counter((case, condition, observation, repetition)
                           for case in axes[0] for condition in axes[1]
                           for observation in axes[2] for repetition in range(repetitions))
        if expected != keys:
            raise ValueError('matrix differs from declared factorial design')
    return rows
