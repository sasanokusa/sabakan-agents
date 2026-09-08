"""Model/playbook trials with real HTTP postchecks and failure evidence."""
import copy
from pathlib import Path
import tempfile
import time

from evaluation.agent_loop import run_agent_loop
from evaluation.approval_scenarios import FixtureApprovalScenario
from evaluation.docker_fixtures import build_fixture_broker, PRINCIPAL, trusted_fixture_approval_handler
from evaluation.http_fixtures import HttpFixture, HttpExecutor, HttpMonitor, HttpClosedReadMonitor
from evaluation.research_protocol import CaseContract, TrialEvidence, score_trial
from evaluation.timing import TrialTiming
from evaluation.http_conditions import validate_guard_options
from evaluation.delayed_recovery import DelayedDependencyRecovery
from scripts.evaluate_mac_research import deadline, TrialTimeout


def run_http_trial(case, condition, chat, plan, image, name, model):
    seconds = plan['deadline_seconds']
    options = plan['conditions'][condition]
    repeat_limit, recovery_delay = validate_guard_options(plan)
    if recovery_delay is not None and case.fault != 'dependency_down':
        raise ValueError('external recovery requires dependency-down fixture')
    monitor_version = plan.get('http_monitor_version', 1)
    if type(monitor_version) is not int or monitor_version not in {1, 2}:
        raise ValueError('unknown HTTP monitor version')
    observation_version = plan.get('http_observation_version', 1)
    if type(observation_version) is not int or observation_version not in {1, 2}:
        raise ValueError('unknown HTTP observation version')
    verification_fault = plan.get('fixture_verification_failure', False)
    if type(verification_fault) is not bool:
        raise ValueError('fixture verification failure must be boolean')
    snapshot_loss = plan.get('fixture_rollback_snapshot_loss', False)
    if type(snapshot_loss) is not bool or (snapshot_loss and not verification_fault):
        raise ValueError('rollback snapshot loss requires boolean true and verification failure')
    contract = case.contract()
    record = {'case_id': contract['case_id'], 'split': contract['split'],
              'condition': condition, 'model': model, 'contract': contract,
              'started': False, 'public_inputs': [], 'model_responses': [],
              'partial_loop_trace': {}, 'postcheck_windows': []}
    fixture = broker = monitor = controller = None
    controller_stopped = True
    trial_started = None
    result = {'normal_completion': False, 'postcheck': None}
    approval_mode = plan.get('approval_mode', 'unassisted')
    if approval_mode not in {'unassisted', 'fixture_auto_signature'}:
        raise ValueError('unsupported HTTP approval mode')
    scenario_name = plan.get('approval_scenario')
    if scenario_name is not None and (approval_mode != 'fixture_auto_signature' or
                                     scenario_name not in FixtureApprovalScenario.MODES):
        raise ValueError('approval scenario requires fixture approval mode and a known state')
    approval_handler = trusted_fixture_approval_handler if approval_mode == 'fixture_auto_signature' else None
    timing = TrialTiming()
    record['wall_timing'] = {'protocol': 'sabakan-http-wall-timing-v1', 'events': timing.events,
        'scope': 'Model callback includes transport; monitored tool spans include independent snapshots. Setup, teardown and uninstrumented overhead are not tool execution. Offsets start before setup.'}
    with tempfile.TemporaryDirectory(prefix='sabakan-http-trial-') as tmp:
        try:
            fixture = HttpFixture(case, tmp, name, image)
            with deadline(40):
                record['initial_state'] = fixture.setup()
            record['isolation'] = fixture.isolation
            monitor_class = HttpClosedReadMonitor if monitor_version == 2 else HttpMonitor
            executor = HttpExecutor(fixture, observation_version=observation_version)
            executor.force_verification_failure = verification_fault
            executor.lose_rollback_snapshot = snapshot_loss
            record['fixture_verification_failure'] = verification_fault
            record['fixture_rollback_snapshot_loss'] = snapshot_loss
            monitor = monitor_class(executor, case)
            for method in ('execute_read', 'execute_mutation', 'verify', 'rollback'):
                setattr(monitor, method, timing.wrap('monitored_' + method, getattr(monitor, method)))
            broker = build_fixture_broker(Path(tmp) / 'broker', monitor, identical_repeat_limit=repeat_limit)
            record['identical_repeat_limit_override'] = repeat_limit
            if scenario_name is not None:
                def change_state():
                    before = fixture.snapshot()
                    fixture.config_path.write_bytes(fixture.config_path.read_bytes() + b'\n')
                    record['trusted_approval_state_change'] = {'before': before, 'after': fixture.snapshot(),
                        'attribution': 'fixture controller; not model or Broker mutation'}
                approval_handler = FixtureApprovalScenario(scenario_name,
                    change_state=change_state if scenario_name == 'state_changed' else None)
                record['approval_scenario'] = scenario_name
                record['approval_scenario_events'] = approval_handler.events
            if approval_handler is not None:
                approval_handler = timing.wrap('approval_handler', approval_handler)
            def tracked_chat(messages, tools):
                monitor.record_model_input(messages)
                record['public_inputs'].append(copy.deepcopy(messages))
                with timing.span('actor_callback'):
                    response = chat(messages, tools)
                record['model_responses'].append(copy.deepcopy(response))
                return response
            def postcheck():
                try:
                    with timing.span('http_postcheck'):
                        observed = fixture.postcheck()
                    record['postcheck_windows'].append(observed)
                    monitor.record_postcheck(observed['ok'])
                    return observed['ok']
                except (Exception, TrialTimeout) as exc:
                    monitor.record_postcheck(None, str(exc))
                    raise
            record['started'] = True
            trial_started = time.monotonic()
            if recovery_delay is not None:
                controller = DelayedDependencyRecovery(fixture, recovery_delay)
                record['external_recovery'] = controller.record
                controller.start()
            with deadline(seconds):
                result = run_agent_loop(
                    incident=case.public_incident(), broker=broker, principal=PRINCIPAL,
                    chat=tracked_chat, postcheck=postcheck, model=model,
                    max_turns=plan['max_turns'], research_protocol=True,
                    requires_remediation=case.requires_remediation,
                    staged_tools=options['staged_tools'], observation_hints=options['observation_hints'],
                    system_prompt_suffix=plan.get('system_prompt_suffix', ''),
                    approval_handler=approval_handler,
                    deadline_seconds=seconds, partial_trace=record['partial_loop_trace'])
        except (Exception, TrialTimeout) as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
            result.update(failure_reason='OUTER_TIMEOUT' if isinstance(exc, TrialTimeout) else record['error'],
                          turns=record['partial_loop_trace'].get('turns', []), trace_complete=False,
                          normal_completion=False)
        finally:
            if controller:
                try:
                    controller.close()
                except Exception as exc:
                    controller_stopped = False
                    record['controller_close_error'] = type(exc).__name__
                    monitor.incomplete = True
            if record['started']:
                try:
                    with deadline(10):
                        result['postcheck'] = postcheck()
                        record['final_state'] = fixture.snapshot()
                except (Exception, TrialTimeout) as exc:
                    result['postcheck'] = None
                    record['postcheck_error'] = f'{type(exc).__name__}: {exc}'
                result['elapsed_seconds'] = time.monotonic() - trial_started
            result['approval_mode'] = approval_mode
            audit = broker.audit.list_events() if broker else []
            evidence = monitor.evidence(audit) if monitor else TrialEvidence()
            record.update(loop=result, audit=audit,
                          score=score_trial(result, CaseContract(case.requires_remediation, deadline_seconds=seconds),
                                            evidence, started=record['started']))
            if controller and record['score']['outcome'] == 'resolved':
                record['score']['recovery_attribution'] = 'external_or_mixed_not_established'
                record['external_recovery_limitation'] = 'Independent HTTP recovery is not attributed to autonomous model repair.'
            if monitor:
                record['monitor'] = monitor.details(audit)
            if broker:
                broker.audit.close()
            if fixture and controller_stopped:
                try:
                    record['cleanup'] = fixture.cleanup()
                except Exception as exc:
                    record['cleanup'] = {'complete': False, 'error': str(exc)}
            elif fixture:
                record['cleanup'] = {'complete': False, 'error': 'controller still active'}
    return record
