"""Audit the actual model surface, independently of recorded outcome labels."""
import json
from evaluation.agent_loop import OBSERVATION_HINT, tool_schemas_for_state


def audit_surface(trial, options):
    requests = trial.get('http_requests', [])
    if not requests:
        return {'measured': False, 'reason': 'no recorded model requests; playbook or unstarted',
                'schema_mismatches': None, 'forbidden_hint_requests': None}
    rows = []
    for index, record in enumerate(requests):
        payload = record['request']
        messages = payload['messages']
        read_observed = False
        for message in messages:
            if message.get('role') == 'tool':
                try:
                    result = json.loads(message['content'])
                except (KeyError, TypeError, ValueError):
                    continue
                if isinstance(result, dict) and result.get('code') == 'READ_OK':
                    read_observed = True
        state = 'observe' if options['staged_tools'] and not read_observed else 'remediation'
        hints = sum(m.get('role') == 'system' and m.get('content') == OBSERVATION_HINT for m in messages)
        rows.append({'request': index, 'expected_state': state,
                     'schema_matches': payload.get('tools') == list(tool_schemas_for_state(state)),
                     'hint_present': hints > 0,
                     'forbidden_hint': hints > 0 and not options['observation_hints']})
    hint_traces = [t for t in trial.get('loop', {}).get('turns', []) if t.get('harness_hint') == OBSERVATION_HINT]
    return {'measured': True, 'requests': rows,
            'schema_mismatches': sum(not r['schema_matches'] for r in rows),
            'forbidden_hint_requests': sum(r['forbidden_hint'] for r in rows),
            'hint_reached_model': any(r['hint_present'] for r in rows),
            'hint_trace_count': len(hint_traces),
            'limitation': 'Absence of a hint is not evidence of a missed opportunity; terminal traces can stop before the next request.'}
