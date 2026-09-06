#!/usr/bin/env python3
"""Analyze the saved LFM traces without starting a model or a fixture.

The input report is treated as immutable evidence.  Raw assistant messages are
adapted with the same canonical adapter used by the execution loop, then
compared with the calls already persisted in ``loop.turns``.  The command only
creates a new output file and refuses to overwrite either the input or an
existing output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

# Keep parsing and progress normalization on the execution path's helpers.  In
# particular, this script must not grow a second tool-call parser that can
# disagree with the adapter used by the runner.
from evaluation.agent_loop import (  # noqa: E402
    ATTACK_GOAL_TOOL,
    MUTATION_TOOL_NAMES,
    READ_TOOL_NAMES,
    _canonical_calls_from_proposal,
    _canonical_proposal,
    _normalized_progress_value,
)


ANALYSIS_NAME = "sabakan-saved-lfm-trace-analysis-20260906"
DEFAULT_INPUT = ROOT / "evaluation" / "mac-pilot-results-v3.json"
DEFAULT_OUTPUT = ROOT / "evaluation" / "lfm-trace-analysis-20260906.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _jsonable(value: Any) -> Any:
    """Make a saved JSON value safe for deterministic signatures."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _call_value(call: Mapping[str, Any]) -> dict[str, Any]:
    """Return the adapter-owned call shape used for equality comparisons."""
    arguments = call.get("arguments")
    if isinstance(arguments, Mapping):
        arguments = dict(arguments)
    return {"tool": call.get("tool"), "arguments": _jsonable(arguments)}


def _call_matches(call: Mapping[str, Any], expected: Mapping[str, Any] | None) -> bool:
    if expected is None:
        return False
    return _call_value(call) == {
        "tool": expected.get("tool"),
        "arguments": _jsonable(expected.get("arguments")),
    }


def _raw_call_id(response: Any, call_index: int) -> str | None:
    if not isinstance(response, Mapping):
        return None
    raw_calls = response.get("tool_calls")
    if not isinstance(raw_calls, list) or call_index >= len(raw_calls):
        return None
    raw_call = raw_calls[call_index]
    return _str_or_none(raw_call.get("id")) if isinstance(raw_call, Mapping) else None


def _adapt_raw_responses(responses: Any) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Adapt saved model responses using ``evaluation.agent_loop`` helpers."""
    if not isinstance(responses, list):
        return None, {"response_count": None, "parse_error_count": None, "envelope_invalid_count": None}

    records: list[dict[str, Any]] = []
    parse_errors = 0
    envelope_invalid = 0
    for response_index, response in enumerate(responses, 1):
        adapted = _canonical_proposal(response)
        calls = _canonical_calls_from_proposal(adapted)
        if adapted.errors:
            parse_errors += 1
        if not adapted.envelope_valid:
            envelope_invalid += 1
        for call_index, call in enumerate(calls):
            records.append(
                {
                    "index": len(records) + 1,
                    "response_index": response_index,
                    "call_index": call_index + 1,
                    "turn": response_index,
                    "raw_id": _raw_call_id(response, call_index),
                    "call": _call_value(call),
                    "source_format": adapted.source_format,
                }
            )
    return records, {
        "response_count": len(responses),
        "parse_error_count": parse_errors,
        "envelope_invalid_count": envelope_invalid,
    }


def _loop_trace_records(loop: Any) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Normalize calls from the saved ``loop.turns`` trace.

    The loop trace stores OpenAI-shaped calls after the runtime has assigned a
    deterministic ``call-<turn>-<index>`` id.  They are passed back through
    the existing adapter so comparison ignores only the transport id and keeps
    tool names and decoded arguments meaningful.
    """
    if not isinstance(loop, Mapping) or not isinstance(loop.get("turns"), list):
        return None, {"assistant_turn_count": None, "parse_error_count": None, "envelope_invalid_count": None}

    records: list[dict[str, Any]] = []
    assistant_turns = 0
    parse_errors = 0
    envelope_invalid = 0
    results_by_turn: dict[int, list[Any]] = {}
    for entry in loop["turns"]:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("tool_results"), list):
            continue
        turn = entry.get("turn")
        if isinstance(turn, int):
            results_by_turn[turn] = entry["tool_results"]

    for entry in loop["turns"]:
        if not isinstance(entry, Mapping) or "assistant" not in entry:
            continue
        assistant_turns += 1
        raw_calls = entry.get("tool_calls")
        if not isinstance(raw_calls, list):
            # A saved diagnosis-only assistant turn has no call list.  It is a
            # known zero-call turn; a non-list value is an incomplete trace.
            if raw_calls is not None:
                parse_errors += 1
                envelope_invalid += 1
            continue
        response = {
            "content": entry.get("assistant") if isinstance(entry.get("assistant"), str) else "",
            "tool_calls": raw_calls,
        }
        adapted = _canonical_proposal(response)
        calls = _canonical_calls_from_proposal(adapted)
        if adapted.errors:
            parse_errors += 1
        if not adapted.envelope_valid:
            envelope_invalid += 1
        turn = entry.get("turn") if isinstance(entry.get("turn"), int) else assistant_turns
        tool_results = results_by_turn.get(turn)
        for call_index, call in enumerate(calls):
            result_item = (
                tool_results[call_index]
                if isinstance(tool_results, list)
                and call_index < len(tool_results)
                and isinstance(tool_results[call_index], Mapping)
                else None
            )
            result = result_item.get("result") if isinstance(result_item, Mapping) else None
            records.append(
                {
                    "index": len(records) + 1,
                    "turn": turn,
                    "call_index": call_index + 1,
                    "loop_id": (
                        raw_calls[call_index].get("id")
                        if isinstance(raw_calls[call_index], Mapping)
                        else None
                    ),
                    "call": _call_value(call),
                    "result": dict(result) if isinstance(result, Mapping) else None,
                    "source_format": adapted.source_format,
                }
            )
    return records, {
        "assistant_turn_count": assistant_turns,
        "parse_error_count": parse_errors,
        "envelope_invalid_count": envelope_invalid,
    }


def _result_summary(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, Mapping):
        return None
    data = result.get("data")
    data = data if isinstance(data, Mapping) else None
    return {
        "code": _str_or_none(result.get("code")),
        "ok": _bool_or_none(result.get("ok")),
        "status": _str_or_none(data.get("status")) if data is not None else None,
        "logical_resource": _str_or_none(data.get("logical_resource")) if data is not None else None,
        "error": _str_or_none(result.get("error")),
        "request_id": _str_or_none(result.get("request_id")),
    }


def _progress_hash(call: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """Use the loop's same noise-stripping rule for saved read results."""
    payload = {
        "tool": call.get("tool"),
        "arguments": _normalized_progress_value(call.get("arguments")),
        "result": _normalized_progress_value(result),
    }
    encoded = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _public_tool_messages(public_inputs: Any) -> tuple[list[dict[str, Any]] | None, bool]:
    """Extract persisted tool messages for result-to-next-input checks."""
    if not isinstance(public_inputs, list):
        return None, False
    messages: list[dict[str, Any]] = []
    malformed = False
    for history in public_inputs:
        if not isinstance(history, list):
            malformed = True
            continue
        for item in history:
            if not isinstance(item, Mapping) or item.get("role") != "tool":
                continue
            content = item.get("content")
            if not isinstance(content, str):
                malformed = True
                continue
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                malformed = True
                continue
            if not isinstance(parsed, Mapping):
                malformed = True
                continue
            messages.append(
                {
                    "tool": item.get("name") or parsed.get("tool"),
                    "request_id": parsed.get("request_id"),
                    "payload": dict(parsed),
                }
            )
    return messages, malformed


def _forwarded_to_next_input(
    record: Mapping[str, Any],
    public_inputs: Any,
    public_tool_messages: list[dict[str, Any]] | None,
    public_inputs_malformed: bool,
) -> bool | None:
    if public_tool_messages is None:
        return None
    result = record.get("result")
    if not isinstance(result, Mapping):
        return None
    request_id = result.get("request_id")
    if not isinstance(request_id, str):
        return None
    if any(message.get("request_id") == request_id for message in public_tool_messages):
        return True
    turn = record.get("turn")
    has_next_history = isinstance(turn, int) and isinstance(public_inputs, list) and turn < len(public_inputs)
    if has_next_history and not public_inputs_malformed:
        return False
    # A missing next history is terminal for the saved trace, or the capture is
    # incomplete.  Keep the transport fact separate so callers can distinguish
    # the normal terminal case from a malformed capture.
    return False if not public_inputs_malformed else None


def _compare_calls(
    canonical: list[dict[str, Any]] | None,
    loop_calls: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if canonical is None or loop_calls is None:
        return {
            "canonical_count": None if canonical is None else len(canonical),
            "loop_count": None if loop_calls is None else len(loop_calls),
            "compared_count": None,
            "match": None,
            "mismatch_count": None,
            "mismatches": [],
        }

    canonical_values = [item["call"] for item in canonical]
    loop_values = [item["call"] for item in loop_calls]
    mismatches: list[dict[str, Any]] = []
    for index in range(max(len(canonical_values), len(loop_values))):
        left = canonical_values[index] if index < len(canonical_values) else None
        right = loop_values[index] if index < len(loop_values) else None
        if left != right:
            mismatches.append({"index": index + 1, "canonical": left, "loop": right})
    return {
        "canonical_count": len(canonical),
        "loop_count": len(loop_calls),
        "compared_count": min(len(canonical), len(loop_calls)),
        "match": not mismatches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def _first_matching(records: list[dict[str, Any]] | None, expected: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if records is None:
        return None
    for record in records:
        if _call_matches(record["call"], expected):
            return record
    return None


def _required_observation(
    contract: Mapping[str, Any] | None,
    canonical: list[dict[str, Any]] | None,
    loop_calls: list[dict[str, Any]] | None,
    public_inputs: Any,
    public_tool_messages: list[dict[str, Any]] | None,
    public_inputs_malformed: bool,
) -> dict[str, Any]:
    expected = contract.get("required_observation") if isinstance(contract, Mapping) else None
    expected = expected if isinstance(expected, Mapping) else None
    canonical_first = _first_matching(canonical, expected)
    loop_first = _first_matching(loop_calls, expected)
    result = loop_first.get("result") if isinstance(loop_first, Mapping) else None
    result_info = _result_summary(result)
    if loop_calls is None:
        reached = None
    elif loop_first is None:
        reached = False
    elif result_info is None or result_info.get("code") is None:
        reached = None
    else:
        reached = result_info.get("code") == "READ_OK" and result_info.get("ok") is True

    def call_location(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if record is None:
            return None
        return {
            "index": record.get("index"),
            "turn": record.get("turn"),
            "call_index": record.get("call_index"),
            "call": record.get("call"),
        }

    return {
        "expected": dict(expected) if expected is not None else None,
        "canonical_first": call_location(canonical_first),
        "loop_first": call_location(loop_first),
        "result": result_info,
        "reached": reached,
        "forwarded_to_next_input": (
            _forwarded_to_next_input(loop_first, public_inputs, public_tool_messages, public_inputs_malformed)
            if loop_first is not None
            else None
        ),
    }


def _observations(
    loop_calls: list[dict[str, Any]] | None,
    required: Mapping[str, Any] | None,
    public_inputs: Any,
    public_tool_messages: list[dict[str, Any]] | None,
    public_inputs_malformed: bool,
    ) -> dict[str, Any]:
    if loop_calls is None:
        return {
            "read_attempt_count": None,
            "successful_read_count": None,
            "first_successful": None,
            "same_after_first_success_count": None,
            "alternate_after_first_success_count": None,
            "non_required_successful_count": None,
            "events": [],
        }

    expected = required if isinstance(required, Mapping) else None
    read_records: list[dict[str, Any]] = []
    for record in loop_calls:
        call = record.get("call")
        result = record.get("result")
        if not isinstance(call, Mapping) or call.get("tool") not in READ_TOOL_NAMES:
            continue
        info = _result_summary(result)
        successful = isinstance(info, Mapping) and info.get("code") == "READ_OK" and info.get("ok") is True
        signature = _progress_hash(call, result) if successful and isinstance(result, Mapping) else None
        read_records.append(
            {
                "index": record.get("index"),
                "turn": record.get("turn"),
                "call_index": record.get("call_index"),
                "call": call,
                "result": info,
                "successful": successful,
                "progress_signature_sha256": signature,
                "forwarded_to_next_input": _forwarded_to_next_input(
                    record, public_inputs, public_tool_messages, public_inputs_malformed
                ),
            }
        )

    successful_records = [record for record in read_records if record["successful"]]
    first_successful = successful_records[0] if successful_records else None
    first_signature = first_successful.get("progress_signature_sha256") if first_successful else None
    same_after = sum(
        record.get("progress_signature_sha256") == first_signature
        for record in successful_records[1:]
    ) if first_successful else 0
    alternate_after = sum(
        record.get("progress_signature_sha256") != first_signature
        for record in successful_records[1:]
    ) if first_successful else 0
    non_required = sum(
        not _call_matches(record["call"], expected)
        for record in successful_records
    )
    return {
        "read_attempt_count": len(read_records),
        "successful_read_count": len(successful_records),
        "first_successful": first_successful,
        "same_after_first_success_count": same_after,
        "alternate_after_first_success_count": alternate_after,
        "non_required_successful_count": non_required,
        "events": read_records,
    }


def _mutation_info(
    trial: Mapping[str, Any],
    loop: Mapping[str, Any] | None,
    canonical: list[dict[str, Any]] | None,
    loop_calls: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    canonical_count = (
        sum(record.get("call", {}).get("tool") in MUTATION_TOOL_NAMES for record in canonical)
        if canonical is not None
        else None
    )
    loop_call_count = (
        sum(record.get("call", {}).get("tool") in MUTATION_TOOL_NAMES for record in loop_calls)
        if loop_calls is not None
        else None
    )
    loop_proposal_count = _int_or_none(loop.get("mutation_proposal_count")) if loop is not None else None
    loop_execution_count = _int_or_none(loop.get("mutation_count")) if loop is not None else None

    executor_events = trial.get("executor_events")
    if isinstance(executor_events, list):
        mutation_entries = [
            event for event in executor_events
            if isinstance(event, Mapping) and event.get("kind") == "mutation"
        ]
        executor_entry_count: int | None = len(mutation_entries)
        if all(isinstance(event.get("mutation_executed"), bool) for event in mutation_entries):
            executor_executed_count: int | None = sum(event.get("mutation_executed") is True for event in mutation_entries)
        elif not mutation_entries:
            executor_executed_count = 0
        else:
            executor_executed_count = None
    else:
        executor_entry_count = None
        executor_executed_count = None

    return {
        "canonical_proposal_count": canonical_count,
        "loop_call_count": loop_call_count,
        "loop_reported_proposal_count": loop_proposal_count,
        "execution_count": loop_execution_count if loop_execution_count is not None else executor_executed_count,
        "executor_entry_count": executor_entry_count,
        "executor_reported_execution_count": executor_executed_count,
        "canonical_loop_proposal_match": (
            canonical_count == loop_call_count == loop_proposal_count
            if canonical_count is not None and loop_call_count is not None and loop_proposal_count is not None
            else None
        ),
        "attack_goal_proposed": _bool_or_none(trial.get("attack_goal_proposed")),
        "attack_goal_executed": _bool_or_none(trial.get("attack_goal_executed")),
        "attack_goal_tool": ATTACK_GOAL_TOOL,
    }


def _stop_info(loop: Mapping[str, Any] | None) -> dict[str, Any]:
    if loop is None:
        return {
            "status": None,
            "failure_reason": None,
            "escalation_reason": None,
            "normal_completion": None,
            "guard_intervention": None,
            "loop_failure": None,
            "no_progress_reason": None,
            "terminal_stop_codes": None,
        }
    terminal_codes: list[str] = []
    turns = loop.get("turns")
    if isinstance(turns, list):
        for entry in turns:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("tool_results"), list):
                continue
            for item in entry["tool_results"]:
                result = item.get("result") if isinstance(item, Mapping) else None
                code = result.get("code") if isinstance(result, Mapping) else None
                if isinstance(code, str) and code in {
                    "TOOL_CALL_LIMIT", "LOOP_DETECTED", "INCIDENT_TIMEOUT", "MUTATION_LIMIT",
                    "CIRCUIT_OPEN", "AUTO_REMEDIATION_SUSPENDED",
                }:
                    terminal_codes.append(code)
    return {
        "status": _str_or_none(loop.get("status")),
        "failure_reason": _str_or_none(loop.get("failure_reason")),
        "escalation_reason": _str_or_none(loop.get("escalation_reason")),
        "normal_completion": _bool_or_none(loop.get("normal_completion")),
        "guard_intervention": _bool_or_none(loop.get("guard_intervention")),
        "loop_failure": _bool_or_none(loop.get("loop_failure")),
        "no_progress_reason": _str_or_none(loop.get("no_progress_reason")),
        "terminal_stop_codes": terminal_codes,
    }


def _trial_analysis(
    source_index: int,
    trial: Mapping[str, Any],
    contracts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    loop = trial.get("loop") if isinstance(trial.get("loop"), Mapping) else None
    canonical, raw_meta = _adapt_raw_responses(trial.get("model_responses"))
    loop_calls, loop_meta = _loop_trace_records(loop)
    comparison = _compare_calls(canonical, loop_calls)
    public_inputs = trial.get("public_inputs")
    public_tool_messages, public_inputs_malformed = _public_tool_messages(public_inputs)
    case_id = _str_or_none(trial.get("case_id"))
    contract = contracts.get(case_id) if case_id is not None else None
    required = _required_observation(
        contract,
        canonical,
        loop_calls,
        public_inputs,
        public_tool_messages,
        public_inputs_malformed,
    )
    required_expected = required.get("expected") if isinstance(required, Mapping) else None
    observations = _observations(
        loop_calls,
        required_expected,
        public_inputs,
        public_tool_messages,
        public_inputs_malformed,
    )
    if loop is not None:
        observations["runtime_repeated_observation_count"] = _int_or_none(
            loop.get("repeated_observation_count")
        )
        observations["runtime_observation_hint_sent"] = _bool_or_none(
            loop.get("observation_hint_sent")
        )
    else:
        observations["runtime_repeated_observation_count"] = None
        observations["runtime_observation_hint_sent"] = None
    return {
        "source_index": source_index,
        "case_id": case_id,
        "condition": _str_or_none(trial.get("condition")),
        "repetition": _int_or_none(trial.get("repetition")),
        "started": _bool_or_none(trial.get("started")),
        "required_observation": required,
        "calls": {
            **comparison,
            "raw_response_count": raw_meta["response_count"],
            "canonical_parse_error_count": raw_meta["parse_error_count"],
            "canonical_envelope_invalid_count": raw_meta["envelope_invalid_count"],
            "loop_assistant_turn_count": loop_meta["assistant_turn_count"],
            "loop_parse_error_count": loop_meta["parse_error_count"],
            "loop_envelope_invalid_count": loop_meta["envelope_invalid_count"],
        },
        "stop": _stop_info(loop),
        "mutation": _mutation_info(trial, loop, canonical, loop_calls),
        "observations": observations,
        "attack": {
            "reached_model": _bool_or_none(trial.get("attack_reached_model")),
            "goal_proposed": _bool_or_none(trial.get("attack_goal_proposed")),
            "goal_executed": _bool_or_none(trial.get("attack_goal_executed")),
        },
        "capture": {
            "public_inputs_present": isinstance(public_inputs, list),
            "public_inputs_malformed": public_inputs_malformed if isinstance(public_inputs, list) else None,
            "model_responses_present": isinstance(trial.get("model_responses"), list),
            "loop_turns_present": isinstance(loop, Mapping) and isinstance(loop.get("turns"), list),
        },
    }


def _tri_state(values: Sequence[Any]) -> dict[str, int]:
    return {
        "true": sum(value is True for value in values),
        "false": sum(value is False for value in values),
        "unknown": sum(value is None for value in values),
    }


def _known_numeric(values: Sequence[Any]) -> dict[str, Any]:
    known = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    return {
        "known_sum": sum(known),
        "known_trials": len(known),
        "unknown_trials": len(values) - len(known),
        "all_known": len(known) == len(values),
    }


def _expected_matrix(report: Mapping[str, Any], selected_model: str) -> dict[str, Any]:
    plan = report.get("plan") if isinstance(report.get("plan"), Mapping) else {}
    condition_plan = plan.get("conditions") if isinstance(plan.get("conditions"), Mapping) else {}
    if selected_model == plan.get("primary_model"):
        conditions = [
            str(condition)
            for condition, config in condition_plan.items()
            if isinstance(config, Mapping) and config.get("agent") == "LLM"
        ]
    else:
        conditions = ["B2"] if "B2" in condition_plan else []
    contracts = report.get("case_contracts")
    cases = [
        str(item.get("case_id"))
        for item in contracts
        if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
    ] if isinstance(contracts, list) else []
    repetitions = plan.get("repetitions")
    repetitions = repetitions if isinstance(repetitions, int) and repetitions >= 1 else None
    expected_cells = (
        [{"case_id": case, "condition": condition, "repetition": repetition}
         for case in cases for condition in conditions
         for repetition in range(repetitions)]
        if repetitions is not None else []
    )
    return {
        "model": selected_model,
        "conditions": conditions,
        "case_ids": cases,
        "repetitions": repetitions,
        "expected_trial_count": len(expected_cells) if repetitions is not None else None,
        "expected_cells": expected_cells,
    }


def _scope(rows: list[dict[str, Any]], matrix: Mapping[str, Any]) -> dict[str, Any]:
    expected_keys = {
        (cell["case_id"], cell["condition"], cell["repetition"])
        for cell in matrix.get("expected_cells", [])
    }
    observed: Counter[tuple[Any, Any, Any]] = Counter(
        (row.get("case_id"), row.get("condition"), row.get("repetition")) for row in rows
    )
    duplicate_cells = sorted(
        [{"case_id": key[0], "condition": key[1], "repetition": key[2], "count": count}
         for key, count in observed.items() if count > 1],
        key=lambda item: (str(item["case_id"]), str(item["condition"]), str(item["repetition"])),
    )
    observed_keys = set(observed)
    missing = [
        {"case_id": case, "condition": condition, "repetition": repetition}
        for case, condition, repetition in sorted(expected_keys - observed_keys, key=str)
    ]
    unexpected = [
        {"case_id": case, "condition": condition, "repetition": repetition, "count": observed[(case, condition, repetition)]}
        for case, condition, repetition in sorted(observed_keys - expected_keys, key=str)
    ]
    complete = (
        matrix.get("expected_trial_count") is not None
        and not missing
        and not unexpected
        and not duplicate_cells
        and len(rows) == matrix.get("expected_trial_count")
    )
    return {
        "expected_trial_count": matrix.get("expected_trial_count"),
        "observed_trial_count": len(rows),
        "complete": complete,
        "missing_cells": missing,
        "unexpected_cells": unexpected,
        "duplicate_cells": duplicate_cells,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stops = Counter(row["stop"].get("failure_reason") for row in rows)
    return {
        "trial_count": len(rows),
        "started": _tri_state([row.get("started") for row in rows]),
        "canonical_loop_match": _tri_state([row["calls"].get("match") for row in rows]),
        "required_observation_reached": _tri_state([
            row["required_observation"].get("reached") for row in rows
        ]),
        "same_observation_trial_count": sum(
            row["observations"].get("runtime_repeated_observation_count", 0) > 0
            for row in rows
            if isinstance(row["observations"].get("runtime_repeated_observation_count"), int)
        ),
        "alternate_observation_trial_count": sum(
            row["observations"].get("non_required_successful_count", 0) > 0
            for row in rows
            if isinstance(row["observations"].get("non_required_successful_count"), int)
        ),
        "same_observation_events": _known_numeric([
            row["observations"].get("runtime_repeated_observation_count") for row in rows
        ]),
        "same_as_first_success_events": _known_numeric([
            row["observations"].get("same_after_first_success_count") for row in rows
        ]),
        "alternate_observation_events": _known_numeric([
            row["observations"].get("non_required_successful_count") for row in rows
        ]),
        "alternate_after_first_success_events": _known_numeric([
            row["observations"].get("alternate_after_first_success_count") for row in rows
        ]),
        "mutation_canonical_proposals": _known_numeric([
            row["mutation"].get("canonical_proposal_count") for row in rows
        ]),
        "mutation_execution": _known_numeric([
            row["mutation"].get("execution_count") for row in rows
        ]),
        "attack_goal_proposed": _tri_state([
            row["attack"].get("goal_proposed") for row in rows
        ]),
        "attack_goal_executed": _tri_state([
            row["attack"].get("goal_executed") for row in rows
        ]),
        "stops": {str(key) if key is not None else "unknown": value for key, value in sorted(stops.items(), key=lambda item: str(item[0]))},
    }


def analyze_report(report: Mapping[str, Any], selected_model: str | None = None) -> dict[str, Any]:
    plan = report.get("plan") if isinstance(report.get("plan"), Mapping) else {}
    model = selected_model or _str_or_none(plan.get("primary_model"))
    if not model:
        raise ValueError("the report has no primary model; pass --model explicitly")
    raw_trials = report.get("trials")
    if not isinstance(raw_trials, list):
        raise ValueError("saved report has no trials list")
    contracts = {
        item["case_id"]: item
        for item in report.get("case_contracts", [])
        if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
    } if isinstance(report.get("case_contracts"), list) else {}
    selected = [
        (index, trial)
        for index, trial in enumerate(raw_trials)
        if isinstance(trial, Mapping) and trial.get("model") == model
    ]
    if not selected:
        raise ValueError(f"no trials found for model {model!r}")
    rows = [_trial_analysis(index, trial, contracts) for index, trial in selected]
    matrix = _expected_matrix(report, model)
    return {
        "analysis": ANALYSIS_NAME,
        "kind": "offline_saved_trace_analysis",
        "source_protocol": report.get("protocol"),
        "source_split": report.get("split"),
        "scope": {
            "selected_model": model,
            "selection_rule": "trial.model == selected model; default is plan.primary_model",
            **matrix,
            **_scope(rows, matrix),
        },
        "summary": _summary(rows),
        "trials": rows,
    }


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", type=str, help="model name; defaults to plan.primary_model")
    args = parser.parse_args(argv)

    input_path = args.input.resolve()
    output_path = args.output.resolve()
    if input_path == output_path:
        raise FileExistsError("analysis output must differ from the immutable input report")
    if output_path.exists():
        raise FileExistsError(f"analysis output already exists: {output_path}")
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    input_before = _sha256(input_path)
    report = json.loads(input_path.read_text(encoding="utf-8"))
    analysis = analyze_report(report, args.model)
    if _sha256(input_path) != input_before:
        raise RuntimeError("input report changed during offline analysis")

    source_paths = {
        "analysis_script": Path(__file__).resolve(),
        "canonical_adapter": ROOT / "evaluation" / "adapters" / "canonical.py",
        "agent_loop_helper": ROOT / "evaluation" / "agent_loop.py",
    }
    analysis["provenance"] = {
        "input": _relative(input_path),
        "input_sha256": input_before,
        "sources": {
            name: {"path": _relative(path), "sha256": _sha256(path)}
            for name, path in source_paths.items()
        },
        "execution": "offline JSON analysis only; no model, Docker, CUDA, VM, or external service started",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation is deliberate: an existing output is never replaced.
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(analysis, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"output": _relative(output_path), **analysis["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
