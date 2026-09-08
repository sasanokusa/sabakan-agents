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
from scripts.evaluate_mac_research import deadline, TrialTimeout


def run_http_trial(case, condition, chat, plan, image, name, model):
    seconds = plan['deadline_seconds']
    options = plan['conditions'][condition]
    monitor_version = plan.get('http_monitor_version', 1)
    if type(monitor_version) is not int or monitor_version not in {1, 2}:
        raise ValueError('unknown HTTP monitor version')
    observation_version = plan.get('http_observation_version', 1)
    if type(observation_version) is not int or observation_version not in {1, 2}:
        raise ValueError('unknown HTTP observation version')
    verification_fault = plan.get('fixture_verification_failure', False)
    if type(verification_fault) is not bool:
        raise ValueError('fixture verification failure must be boolean')
    record = {'case_id': 'development-http-' + case.fault, 'split': 'development',
              'condition': condition, 'model': model, 'contract': case.contract(),
              'started': False, 'public_inputs': [], 'model_responses': [],
              'partial_loop_trace': {}, 'postcheck_windows': []}
    fixture = broker = monitor = None
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
    with tempfile.TemporaryDirectory(prefix='sabakan-http-trial-') as tmp:
        try:
            fixture = HttpFixture(case, tmp, name, image)
            with deadline(40):
                record['initial_state'] = fixture.setup()
            record['isolation'] = fixture.isolation
            monitor_class = HttpClosedReadMonitor if monitor_version == 2 else HttpMonitor
            executor = HttpExecutor(fixture, observation_version=observation_version)
            executor.force_verification_failure = verification_fault
            record['fixture_verification_failure'] = verification_fault
            monitor = monitor_class(executor, case)
            broker = build_fixture_broker(Path(tmp) / 'broker', monitor)
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
            def tracked_chat(messages, tools):
                monitor.record_model_input(messages)
                record['public_inputs'].append(copy.deepcopy(messages))
                response = chat(messages, tools)
                record['model_responses'].append(copy.deepcopy(response))
                return response
            def postcheck():
                try:
                    observed = fixture.postcheck()
                    record['postcheck_windows'].append(observed)
                    monitor.record_postcheck(observed['ok'])
                    return observed['ok']
                except (Exception, TrialTimeout) as exc:
                    monitor.record_postcheck(None, str(exc))
                    raise
            record['started'] = True
            trial_started = time.monotonic()
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
            if monitor:
                record['monitor'] = monitor.details(audit)
            if broker:
                broker.audit.close()
            if fixture:
                try:
                    record['cleanup'] = fixture.cleanup()
                except Exception as exc:
                    record['cleanup'] = {'complete': False, 'error': str(exc)}
    return record
