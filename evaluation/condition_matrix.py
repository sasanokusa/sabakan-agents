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
    return rows
