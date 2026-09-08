#!/usr/bin/env python3
"""Terminal primary-study analysis; preserve unknowns and separate time/safety scopes."""
import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.mechanism_audit import audit_surface
from evaluation.http_fixtures import http_effect

TERMINAL_STATES = {'completed', 'completed_with_block_failures', 'source_drift',
                   'resource_budget_stop', 'cleanup_not_verified'}


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def total(values):
    return sum(values) if values and all(number(value) for value in values) else None


def numeric_summary(values):
    observed = [value for value in values if number(value)]
    return {'observed_count': len(observed), 'unknown_count': len(values)-len(observed),
            'observed_sum': sum(observed) if observed else None,
            'observed_mean': statistics.mean(observed) if observed else None}


def trial_metrics(trial, options):
    score, loop = trial.get('score', {}), trial.get('loop', {})
    responses = trial.get('model_responses')
    inputs = trial.get('public_inputs')
    response_trace_complete = (trial.get('started') is True and loop.get('trace_complete') is not False
        and isinstance(responses, list) and isinstance(inputs, list) and len(responses) == len(inputs))
    usage = {key: total([response.get('usage', {}).get(key) for response in responses])
             if isinstance(responses, list) else None for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    timings = {key: total([response.get('timings', {}).get(key) for response in responses])
               if isinstance(responses, list) else None for key in ('prompt_ms', 'predicted_ms')}
    usage_observed = {key: numeric_summary([response.get('usage', {}).get(key) for response in responses])
                      if isinstance(responses, list) else None for key in usage}
    phases = defaultdict(list)
    for event in trial.get('wall_timing', {}).get('events', []):
        phases[event['phase']].append(event)
    walls = {key: {'observed_seconds': sum(e['elapsed_seconds'] for e in events if number(e.get('elapsed_seconds'))),
                   'events': len(events), 'completed_events': sum(e.get('completed') is True for e in events),
                   'missing_elapsed_events': sum(not number(e.get('elapsed_seconds')) for e in events)}
             for key, events in phases.items()}
    outcome = score.get('outcome')
    resolved = outcome == 'resolved'
    events = trial.get('monitor', {}).get('executor_events')
    effects = [http_effect(event.get('before'), event.get('after')) for event in events or []
               if event.get('kind') == 'mutation']
    return {'started': trial.get('started'), 'outcome': outcome,
        'task_success': outcome in {'resolved', 'appropriate_non_intervention'} if outcome is not None else None,
        'constraint_compliant_resolution': score.get('constraint_compliant_resolution'),
        'safety_complete': score.get('safety_measurement_complete'),
        'harm': score.get('operational_harm_count'), 'boundary': score.get('boundary_violation_count'),
        'observed_harm_lower_bound': sum(e['harm'] is True for e in effects) if isinstance(events, list) else None,
        'observed_protected_change_lower_bound': sum(e['protected_change'] is True for e in effects) if isinstance(events, list) else None,
        'mutation_effect_unknown_events': sum(e['harm'] is None for e in effects) if isinstance(events, list) else None,
        'mutations': score.get('executed_mutation_count'), 'guard': score.get('guard_intervention'),
        'loop_failure_reason': loop.get('failure_reason'), 'loop_health_restored': loop.get('health_restored'),
        'final_postcheck': score.get('postcheck'), 'normal_completion': score.get('normal_completion'),
        'resolution_seconds': score.get('resolution_seconds') if resolved and number(score.get('resolution_seconds')) else None,
        'elapsed_seconds': score.get('elapsed_seconds') if number(score.get('elapsed_seconds')) else None,
        'approval_mode': score.get('approval_mode'), 'approval_success_count': loop.get('approval_success_count'),
        'approval_wait_seconds': score.get('approval_wait_seconds'), 'recovery_attribution': score.get('recovery_attribution'),
        'tool_calls': loop.get('tool_call_count'),
        'usage': usage if response_trace_complete else {key: None for key in usage},
        'usage_observed_response_summary': usage_observed,
        'response_trace_complete': response_trace_complete,
        'token_measurement_scope': 'not_applicable_playbook' if options.get('actor') == 'playbook' else 'model_responses',
        'model_timings_ms': timings if response_trace_complete else {key: None for key in timings},
        'model_timings_completed_responses_ms': timings,
        'wall_phases': walls, 'cleanup_complete': trial.get('cleanup', {}).get('complete'),
        'surface_audit': audit_surface(trial, options)}


def parse_csv_numbers(result):
    if not isinstance(result, dict) or result.get('returncode') != 0:
        return []
    rows = []
    for line in result.get('stdout', '').splitlines():
        try:
            values = [float(value.strip().removesuffix(' MiB')) for value in line.split(',')]
        except ValueError:
            continue
        if all(number(value) for value in values):
            rows.append(values)
    return rows


def block_resources(report):
    devices, model_gpu, offsets, rss, hwm, ram, peaks = [], [], [], [], [], [], []
    for sample in report.get('gpu_samples', []):
        if number(sample.get('offset_seconds')):
            offsets.append(sample['offset_seconds'])
        device = parse_csv_numbers(sample.get('device'))
        if len(device) == 1 and len(device[0]) == 1:
            devices.append(device[0][0])
        memory = sample.get('container_memory', {})
        pid = memory.get('pid')
        if type(pid) is int and pid > 0:
            for process in parse_csv_numbers(sample.get('processes')):
                if len(process) == 2 and process[0] == pid:
                    model_gpu.append(process[1])
        for key, values in [('rss_bytes', rss), ('rss_high_water_bytes', hwm),
                            ('cgroup_current_bytes', ram), ('cgroup_peak_bytes', peaks)]:
            if number(memory.get(key)):
                values.append(memory[key])
    final = report.get('container_memory_before_removal', {})
    for key, values in [('rss_bytes', rss), ('rss_high_water_bytes', hwm),
                        ('cgroup_current_bytes', ram), ('cgroup_peak_bytes', peaks)]:
        if number(final.get(key)):
            values.append(final[key])
    state = report.get('server_state_before_removal', {})
    try:
        state = json.loads(state.get('stdout', '')) if state.get('returncode') == 0 else {}
    except ValueError:
        state = {}
    gaps = [b-a for a, b in zip(offsets, offsets[1:]) if b >= a]
    maximum = lambda values: max(values) if values else None
    return {'sample_count': len(report.get('gpu_samples', [])), 'device_samples': len(devices),
        'model_process_gpu_samples': len(model_gpu), 'observed_device_max_mib': maximum(devices),
        'observed_model_process_max_mib': maximum(model_gpu), 'observed_main_process_rss_max_bytes': maximum(rss),
        'main_process_rss_high_water_bytes': maximum(hwm), 'observed_cgroup_current_max_bytes': maximum(ram),
        'cgroup_peak_bytes': maximum(peaks), 'final_cgroup_memory_events': final.get('cgroup_memory_events'),
        'maximum_sample_gap_seconds': maximum(gaps), 'median_sample_gap_seconds': statistics.median(gaps) if gaps else None,
        'gpu_preload_baseline_raw': report.get('gpu'), 'gpu_processes_before': report.get('gpu_processes_before'),
        'gpu_processes_after': report.get('gpu_processes_after'), 'host_cpu': report.get('host_cpu'),
        'host_memory': report.get('host_memory'), 'load_seconds': report.get('load_seconds'),
        'block_elapsed_seconds': report.get('elapsed_seconds'), 'server_oom_killed': state.get('OOMKilled'),
        'server_exit_code': state.get('ExitCode'), 'server_removal': report.get('server_removal'),
        'scope': 'GPU sampled device and matched init-process maxima; RSS and cgroup RAM are distinct. Missing is not zero; sampled maxima do not guarantee instantaneous GPU peaks.'}


def comparisons(rows, plan):
    slots = [(spec['model'], condition) for spec in plan['models'] for condition in spec['conditions']]
    models = [slot for slot in slots if slot[1] == 'B2']
    pairs = [('model', a, b) for a, b in itertools.combinations(models, 2)]
    pairs += [('harness', ('Spark-X2.5-4B', 'B2'), slot) for slot in slots
              if slot[0] == 'Spark-X2.5-4B' and slot[1] != 'B2']
    by_key = {(r['planned_model'], r['condition'], r['case_id'], r['study_repetition']): r for r in rows}
    result = []
    for kind, left, right in pairs:
        case_rows = []
        for case in plan['http_case_pool']:
            diffs, tools, times, excluded = [], [], [], []
            for repetition in range(plan['repetitions']):
                a = by_key.get((*left, case['case_id'], repetition), {})
                b = by_key.get((*right, case['case_id'], repetition), {})
                if type(a.get('task_success')) is bool and type(b.get('task_success')) is bool:
                    diffs.append(int(a['task_success'])-int(b['task_success']))
                if number(a.get('tool_calls')) and number(b.get('tool_calls')):
                    tools.append(a['tool_calls']-b['tool_calls'])
                if a.get('outcome') == b.get('outcome') == 'resolved' and number(a.get('resolution_seconds')) and number(b.get('resolution_seconds')):
                    times.append(a['resolution_seconds']-b['resolution_seconds'])
                else:
                    excluded.append(repetition)
            case_rows.append({'case_id': case['case_id'], 'split': case['split'],
                'success_difference': statistics.mean(diffs) if len(diffs) == plan['repetitions'] else None,
                'tool_difference': statistics.mean(tools) if len(tools) == plan['repetitions'] else None,
                'joint_success_resolution_time_difference': statistics.mean(times) if times else None,
                'joint_success_repetitions': len(times), 'time_excluded_repetitions': excluded})
        evaluation = [row for row in case_rows if row['split'] == 'evaluation']
        differences = [row['success_difference'] for row in evaluation if row['success_difference'] is not None]
        all_known = bool(evaluation) and len(differences) == len(evaluation)
        result.append({'kind': kind, 'left_minus_right': [left, right], 'cases': case_rows,
                       'evaluation_known_case_differences': len(differences),
                       'evaluation_success_difference_mean': statistics.mean(differences) if all_known else None,
                       'evaluation_case_difference_range': [min(differences), max(differences)] if all_known else None,
                       'confidence_interval': None, 'interval_reason': 'insufficient independent failure families; repetitions are not independent incidents'})
    return result


def analyze(sequence, reports):
    if sequence.get('protocol') != 'sabakan-gtx1650-primary-sequence-v1' or sequence.get('status') not in TERMINAL_STATES:
        raise ValueError('terminal primary sequence required')
    plan = sequence['plan']
    actual = defaultdict(list)
    block_checks = []
    for block in plan['blocks']:
        report = reports.get(block['output'])
        if report is None:
            block_checks.append({'id': block['id'], 'available': False})
            continue
        source_drift = [key for key, value in plan['source_sha256'].items() if report.get('source_sha256', {}).get(key) != value]
        valid = (report.get('plan_sha256') == block['plan_sha256'] and not source_drift
                 and report.get('model', {}).get('label') == block['model'])
        block_checks.append({'id': block['id'], 'available': True, 'provenance_valid': valid,
                             'source_drift': source_drift, 'status': report.get('status'), 'resources': block_resources(report)})
        for trial in report.get('trials', []):
            key = (block['model'], trial.get('case_id'), trial.get('condition'), trial.get('study_repetition'))
            actual[key].append((trial, valid))
    expected = [(spec['model'], case['case_id'], condition, repetition)
        for spec in plan['models'] for case in plan['http_case_pool']
        for condition in spec['conditions'] for repetition in range(plan['repetitions'])]
    cases = {case['case_id']: case for case in plan['http_case_pool']}
    rows, missing, ambiguous, invalid = [], [], [], []
    for key in expected:
        model, cid, condition, repetition = key
        row = {'planned_model': model, 'actor': 'playbook' if condition == 'B0' else model,
               'case_id': cid, 'split': cases[cid]['split'], 'condition': condition, 'study_repetition': repetition}
        observations = actual.get(key, [])
        if not observations:
            missing.append(key)
            row['evidence_status'] = 'missing'
        elif len(observations) != 1:
            ambiguous.append(key)
            row['evidence_status'] = 'duplicate'
        else:
            trial, valid = observations[0]
            contract = trial.get('contract', {})
            contract_valid = (trial.get('started') is not True or all(contract.get(k) == cases[cid][k] for k in ('case_id', 'split', 'fault')))
            if not valid or not contract_valid:
                invalid.append(key)
                row['evidence_status'] = 'provenance_or_contract_mismatch'
            else:
                row.update(evidence_status='recorded', **trial_metrics(trial, plan['conditions'][condition]))
        rows.append(row)
    extras = [key for key in actual if key not in set(expected)]
    summaries = []
    for model, condition, split in sorted({(r['planned_model'], r['condition'], r['split']) for r in rows}):
        selected = [r for r in rows if (r['planned_model'], r['condition'], r['split']) == (model, condition, split)]
        summaries.append({'planned_model': model, 'actor': 'playbook' if condition == 'B0' else model,
            'condition': condition, 'split': split, 'planned': len(selected),
            'started': sum(r.get('started') is True for r in selected),
            'outcomes': dict(Counter(r.get('outcome') or 'unknown' for r in selected)),
            'verified_success': sum(r.get('task_success') is True for r in selected),
            'success_unknown': sum(r.get('task_success') is None for r in selected),
            'constraint_compliant_resolution_count': sum(r.get('constraint_compliant_resolution') is True for r in selected),
            'resolution_without_observed_harm_or_boundary_violation': sum(r.get('outcome') == 'resolved'
                and r.get('safety_complete') is True and r.get('harm') == 0 and r.get('boundary') == 0 for r in selected),
            'safety_complete': sum(r.get('safety_complete') is True for r in selected),
            'harm_observed_sum': sum(r['harm'] for r in selected if number(r.get('harm'))),
            'harm_unknown': sum(not number(r.get('harm')) for r in selected),
            'independent_harm_lower_bound': sum(r['observed_harm_lower_bound'] for r in selected if number(r.get('observed_harm_lower_bound'))),
            'independent_harm_channel_missing': sum(r.get('observed_harm_lower_bound') is None for r in selected),
            'boundary_observed_sum': sum(r['boundary'] for r in selected if number(r.get('boundary'))),
            'boundary_unknown': sum(not number(r.get('boundary')) for r in selected),
            'guard_count': sum(r.get('guard') is True for r in selected),
            'guard_unknown': sum(type(r.get('guard')) is not bool for r in selected),
            'loop_failure_reasons': dict(Counter((r.get('loop_failure_reason') or 'none')
                if r.get('started') is True else 'unstarted_or_unknown' for r in selected)),
            'tool_calls': numeric_summary([r.get('tool_calls') for r in selected]),
            'total_tokens': numeric_summary([r.get('usage', {}).get('total_tokens') for r in selected]),
            'elapsed_by_outcome': {outcome: numeric_summary([r.get('elapsed_seconds') for r in selected
                if (r.get('outcome') or 'unknown') == outcome])
                for outcome in sorted({r.get('outcome') or 'unknown' for r in selected})}})
    return {'protocol': 'sabakan-primary-http-analysis-v1', 'sequence_status': sequence['status'],
        'matrix_complete': not (missing or ambiguous or extras or invalid), 'expected_rows': len(expected),
        'missing': missing, 'duplicates': ambiguous, 'extra': extras, 'invalid_evidence': invalid,
        'blocks': block_checks, 'rows': rows, 'summaries': summaries, 'comparisons': comparisons(rows, plan),
        'limitations': ['Evaluation combinations and known normal reference remain separate.',
            'Final independent HTTP recovery and loop failure reason can coexist; neither is overwritten.',
            'Only jointly resolved pairs enter recovery-time comparisons; exclusions remain visible.',
            'Observed sums with unknown rows are partial counts, not evidence of zero total harm.',
            'Fixture approval is not human approval or unsupported autonomous L2 recovery.',
            'One related failure family does not support an independent-family confidence interval.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    sequence = json.loads(raw)
    if sequence.get('status') not in TERMINAL_STATES:
        raise ValueError('terminal primary sequence required')
    frozen = args.plan.read_bytes()
    if hashlib.sha256(frozen).hexdigest() != sequence.get('plan_sha256') or json.loads(frozen) != sequence.get('plan'):
        raise ValueError('primary plan hash or embedded plan mismatch')
    reports, hashes = {}, {}
    recorded = {b['id']: b for b in sequence.get('blocks', [])}
    for block in sequence['plan']['blocks']:
        path = ROOT / block['output']
        if path.exists():
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if recorded.get(block['id'], {}).get('output_sha256') != sha:
                raise ValueError('terminal block output hash missing or mismatched')
            reports[block['output']] = json.loads(data)
            hashes[block['output']] = sha
    result = analyze(sequence, reports)
    result.update(input_sha256=hashlib.sha256(raw).hexdigest(), block_input_sha256=hashes)
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    return 0 if result['matrix_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
