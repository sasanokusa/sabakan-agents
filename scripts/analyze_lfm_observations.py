#!/usr/bin/env python3
"""Descriptive, paired analysis of the fixed LFM development comparison."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

AUXILIARY = {'host_status', 'service_list', 'docker_list', 'journal_query', 'docker_logs'}


def raw_tool_names(request):
    choices = request.get('response', {}).get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get('message')
    if not isinstance(message, dict):
        return None
    calls = message.get('tool_calls')
    if calls is None:
        return []
    if not isinstance(calls, list):
        return None
    return [call.get('function', {}).get('name') if isinstance(call, dict) else None for call in calls]


def summarize_trial(trial):
    loop, score = trial.get('loop', {}), trial.get('score', {})
    delivered_ids = set()
    for history in trial.get('public_inputs', []):
        for message in history:
            if message.get('role') != 'tool':
                continue
            try:
                result = json.loads(message['content'])
            except (KeyError, TypeError, ValueError):
                continue
            if isinstance(result, dict) and result.get('request_id'):
                delivered_ids.add(result['request_id'])
    auxiliary = [e for e in trial.get('executor_events', [])
                 if e.get('kind') == 'read' and e.get('tool') in AUXILIARY and e.get('ok') is True]
    usage = [r.get('response', {}).get('usage') for r in trial.get('http_requests', [])]
    complete_usage = bool(usage) and all(isinstance(u, dict) and isinstance(u.get('total_tokens'), int) for u in usage)
    handoffs = Counter()
    canonical_matches = []
    requests = trial.get('http_requests', [])
    for turn in loop.get('turns', []):
        for result in turn.get('tool_results', []):
            request_id = result.get('result', {}).get('request_id')
            if request_id in delivered_ids:
                handoffs['forwarded'] += 1
            elif turn.get('turn', 0) >= len(requests):
                handoffs['terminal_not_forwarded'] += 1
            else:
                handoffs['unexplained_not_forwarded'] += 1
        if 'canonical_proposal' not in turn:
            continue
        try:
            message = requests[turn['turn'] - 1]['response']['choices'][0]['message']
            calls = message.get('tool_calls') or []
            if not calls:
                continue  # text/native formats need a separate parser audit
            raw_calls = [{'tool': call['function']['name'],
                          'arguments': json.loads(call['function']['arguments'])} for call in calls]
            canonical_matches.append(raw_calls == turn['canonical_proposal']['normalized']['tool_calls'])
        except (KeyError, IndexError, TypeError, ValueError):
            canonical_matches.append(None)
    return {
        'case_id': trial['case_id'], 'observation': trial['observation'],
        'started': trial.get('started', False), 'outcome': score.get('outcome'),
        'error': trial.get('error'), 'failure_reason': loop.get('failure_reason'),
        'normal_completion': loop.get('normal_completion'),
        'necessary_observation_completed': score.get('necessary_observation_completed'),
        'repeated_observation_count': loop.get('repeated_observation_count'),
        'tool_call_count': loop.get('tool_call_count'), 'mutation_count': loop.get('mutation_count'),
        'auxiliary_successful_reads': len(auxiliary),
        'auxiliary_results_delivered': sum(e.get('request_id') in delivered_ids for e in auxiliary),
        'http_requests': len(trial.get('http_requests', [])),
        'http_errors': sum('error' in r for r in trial.get('http_requests', [])),
        'parse_failures': trial.get('attack_goal_parse_failure_count'),
        'loop_trace_available': isinstance(loop.get('turns'), list),
        'schema_error_count': loop.get('schema_error_count'),
        'resource_error_count': loop.get('resource_error_count'),
        'raw_canonical_matches': canonical_matches,
        'tool_result_handoffs': dict(handoffs),
        'total_tokens': sum(u['total_tokens'] for u in usage) if complete_usage else None,
        'elapsed_seconds': score.get('elapsed_seconds'),
        'raw_tool_names': [raw_tool_names(request) for request in trial.get('http_requests', [])],
    }


def analyze(report):
    if report.get('status') not in {'completed', 'runtime_error'}:
        raise ValueError('the run is still active; do not analyze a partial matrix')
    planned = Counter((r['case_id'], r['observation']) for r in report['plan']['matrix'])
    actual = Counter((r['case_id'], r['observation']) for r in report['trials'])
    rows = [summarize_trial(t) for t in report['trials']]
    pairs = []
    for case in sorted({r['case_id'] for r in rows}):
        pair = {r['observation']: r for r in rows if r['case_id'] == case}
        if set(pair) == {'baseline', 'informative'}:
            initial_requests = {t['observation']: t['http_requests'][0]['request']
                for t in report['trials'] if t['case_id'] == case and t.get('http_requests')}
            pairs.append({'case_id': case, **pair,
                          'initial_requests_identical': initial_requests['baseline'] == initial_requests['informative']
                          if set(initial_requests) == {'baseline', 'informative'} else None,
                          'intervention_delivered': pair['informative']['auxiliary_results_delivered'] > 0})
    measured_memory = []
    for sample in report.get('gpu_samples', []):
        try:
            if sample['device']['returncode'] == 0:
                measured_memory.append(int(sample['device']['stdout']))
        except (KeyError, ValueError, TypeError):
            pass
    return {
        'protocol': report['protocol'], 'runtime_status': report['status'],
        'matrix_complete': actual == planned,
        'missing_rows': list((planned - actual).elements()),
        'extra_rows': list((actual - planned).elements()),
        'started_trials': sum(r['started'] for r in rows),
        'outcomes': dict(Counter(r['outcome'] if r['outcome'] is not None else 'unstarted' for r in rows)),
        'pairs': pairs,
        'device_memory_peak_sampled_mib': max(measured_memory) if measured_memory else None,
        'device_memory_valid_samples': len(measured_memory),
        'chat_template_sha256': hashlib.sha256(report['/props']['chat_template'].encode()).hexdigest()
        if isinstance(report.get('/props', {}).get('chat_template'), str) else None,
        'limitations': [
            'Development cases, one repetition per condition; no statistical or holdout claim.',
            'If no auxiliary result reached the model, the information intervention was not exercised.',
            'CUDA runtime and existing background processes differ from the Mac pilot.',
            'Device-wide memory includes background workloads; sampling can miss instantaneous peaks.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = analyze(json.loads(args.input.read_text()))
    report['input_sha256'] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    report['analyzer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
