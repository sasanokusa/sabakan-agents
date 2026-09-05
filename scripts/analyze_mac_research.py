#!/usr/bin/env python3
"""Analyze a ``evaluate_mac_research.py`` report without changing the input.

The pilot's repetitions are repeated executions of the same case.  They are
therefore summarized at the case level before the paired bootstrap is run.
This module deliberately uses only the report and its frozen plan; it does not
re-score or modify the result file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


BOOTSTRAP_SEED = 20260905
BOOTSTRAP_SAMPLES = 2000
PRIMARY_ABLATIONS = ("B1", "A_no_staging", "A_no_hints")


def _number(value: Any) -> float | int | None:
    """Return finite numeric values while treating all other values as missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return value


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _score(trial: Mapping[str, Any]) -> Mapping[str, Any]:
    score = trial.get("score")
    return score if isinstance(score, Mapping) else {}


def _started(trial: Mapping[str, Any]) -> bool:
    score = _score(trial)
    value = score.get("started", trial.get("started"))
    return value is True


def _requires_remediation(trial: Mapping[str, Any]) -> bool | None:
    value = _score(trial).get("requires_remediation")
    return _bool(value)


def _outcome(trial: Mapping[str, Any]) -> str | None:
    value = _score(trial).get("outcome")
    return value if isinstance(value, str) else None


def _metric(trial: Mapping[str, Any], name: str) -> Any:
    """Read a scored metric, preserving None as an explicit unknown."""
    score = _score(trial)
    if name in score:
        return score[name]
    return trial.get(name)


def _case_id(trial: Mapping[str, Any]) -> str:
    value = trial.get("case_id")
    return str(value) if value is not None else "<missing-case-id>"


def _model(trial: Mapping[str, Any]) -> str:
    value = trial.get("model")
    return str(value) if value is not None else "<missing-model>"


def _condition(trial: Mapping[str, Any]) -> str:
    value = trial.get("condition")
    return str(value) if value is not None else "<missing-condition>"


def _rate(numerator: int, denominator: int, unknown: int = 0) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "unknown": unknown,
        "rate": numerator / denominator if denominator else None,
    }


def _summary(values: Iterable[float | int]) -> dict[str, Any]:
    clean = [float(v) for v in values if _number(v) is not None]
    if not clean:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(clean),
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
    }


def _trial_responses(trial: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    responses = trial.get("model_responses")
    if not isinstance(responses, list):
        return None
    return [r for r in responses if isinstance(r, Mapping)]


def _response_usage(trial: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    """Return measured per-response usage, with no estimates from loop totals."""
    measured = trial.get("measured_usage")
    if isinstance(measured, list):
        # A list of explicit nulls means the harness measured no usage.  Do not
        # replace it with loop counters or infer a token count from text.
        return [u for u in measured if isinstance(u, Mapping)]
    responses = _trial_responses(trial)
    if responses is None:
        return None
    usage = [r.get("usage") for r in responses if isinstance(r.get("usage"), Mapping)]
    return usage


def _response_slot_count(trial: Mapping[str, Any]) -> int | None:
    responses = trial.get("model_responses")
    return len(responses) if isinstance(responses, list) else None


def _response_timings(trial: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    responses = _trial_responses(trial)
    if responses is None:
        return None
    return [r["timings"] for r in responses if isinstance(r.get("timings"), Mapping)]


def _call_count(trial: Mapping[str, Any]) -> int | None:
    inputs = trial.get("public_inputs")
    if isinstance(inputs, list):
        return len(inputs)
    responses = _trial_responses(trial)
    if responses is None:
        return None
    return len(responses)


def _tool_call_count(trial: Mapping[str, Any]) -> int | None:
    loop = trial.get("loop")
    if isinstance(loop, Mapping):
        value = _number(loop.get("tool_call_count"))
        if isinstance(value, (int, float)) and int(value) == value:
            return int(value)
    count = 0
    found = False
    if isinstance(loop, Mapping) and isinstance(loop.get("turns"), list):
        for turn in loop["turns"]:
            if isinstance(turn, Mapping) and isinstance(turn.get("tool_calls"), list):
                found = True
                count += len(turn["tool_calls"])
    return count if found else None


def _attack_present(trial: Mapping[str, Any]) -> bool | None:
    value = _metric(trial, "attack_present")
    if isinstance(value, bool):
        return value
    # Case ids generated by research_cases end with -attack or -clean.  This
    # is only a fallback for small hand-built reports; a score remains primary.
    case = _case_id(trial)
    if case.endswith("-attack"):
        return True
    if case.endswith("-clean"):
        return False
    return None


def _attack_reached(trial: Mapping[str, Any]) -> bool | None:
    value = _metric(trial, "attack_reached_model")
    return _bool(value)


def _goal_value(trial: Mapping[str, Any], field: str, tool_name: str) -> bool | None:
    value = trial.get(field)
    if isinstance(value, bool):
        return value
    # The evaluator records these booleans directly.  A missing field is an
    # unknown measurement; response text and audit traces are not substituted.
    return None


def _elapsed(trial: Mapping[str, Any]) -> float | None:
    value = _metric(trial, "elapsed_seconds")
    return float(value) if _number(value) is not None else None


def _elapsed_bucket(trial: Mapping[str, Any]) -> str | None:
    """Classify elapsed time without mixing remediation and healthy checks."""
    outcome = _outcome(trial)
    if outcome == "resolved":
        return "resolution"
    if outcome == "appropriate_non_intervention":
        return "nonintervention"
    if outcome in {"unresolved", "escalated"}:
        return "unresolved_or_escalated"
    return None


def _nonintervention_indicator(trial: Mapping[str, Any]) -> float | None:
    """Score normal cases only when the required observation was measured."""
    if _requires_remediation(trial) is not False:
        return None
    observation = _metric(trial, "necessary_observation_completed")
    if observation is None:
        return None
    if not isinstance(observation, bool):
        return None
    outcome = _outcome(trial)
    return float(outcome == "appropriate_non_intervention") if outcome is not None else None


def _response_metrics(trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    call_values: list[int] = []
    tool_values: list[int] = []
    token_values: dict[str, list[float | int]] = {k: [] for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    timing_values: dict[str, list[float | int]] = defaultdict(list)
    unknown_calls = 0
    unknown_tool_calls = 0
    usage_call_count = 0
    timing_call_count = 0
    response_slots = 0
    response_list_unknown_trials = 0
    responses_without_usage = 0
    partial_response_coverage_trials = 0
    complete_response_coverage_trials = 0
    complete_token_cost_responses = 0
    partial_token_cost_responses = 0
    for trial in trials:
        calls = _call_count(trial)
        if calls is None:
            unknown_calls += 1
        else:
            call_values.append(calls)
        tool_calls = _tool_call_count(trial)
        if tool_calls is None:
            unknown_tool_calls += 1
        else:
            tool_values.append(tool_calls)
        usage = _response_usage(trial)
        response_count = _response_slot_count(trial)
        if response_count is None:
            response_list_unknown_trials += 1
        else:
            response_slots += response_count
            usage_count = len(usage or [])
            responses_without_usage += max(response_count - usage_count, 0)
            if 0 < usage_count < response_count:
                partial_response_coverage_trials += 1
            elif response_count > 0 and usage_count == response_count:
                complete_response_coverage_trials += 1
        if usage:
            usage_call_count += len(usage)
            for item in usage:
                present = 0
                for name in token_values:
                    value = _number(item.get(name))
                    if value is not None:
                        present += 1
                        token_values[name].append(value)
                if present == len(token_values):
                    complete_token_cost_responses += 1
                else:
                    partial_token_cost_responses += 1
        timings = _response_timings(trial)
        if timings:
            timing_call_count += len(timings)
            for item in timings:
                for name, value in item.items():
                    value = _number(value)
                    if value is not None:
                        timing_values[name].append(value)
    return {
        "calls": {**_summary(call_values), "unknown_trials": unknown_calls, "total": sum(call_values)},
        "tool_calls": {**_summary(tool_values), "unknown_trials": unknown_tool_calls, "total": sum(tool_values)},
        "measured_tokens": {
            name: {
                **_summary(values),
                "sum": sum(values) if values else None,
                "unknown_responses": (response_slots - len(values)) if not response_list_unknown_trials else None,
            }
            for name, values in token_values.items()
        },
        "measured_usage_calls": usage_call_count,
        "token_response_coverage": {
            "response_slots": response_slots if not response_list_unknown_trials else None,
            "measured_usage_responses": usage_call_count,
            "responses_without_measured_usage": responses_without_usage,
            "response_list_unknown_trials": response_list_unknown_trials,
            "partial_response_coverage_trials": partial_response_coverage_trials,
            "complete_response_coverage_trials": complete_response_coverage_trials,
            "complete_token_cost_responses": complete_token_cost_responses,
            "partial_token_cost_responses": partial_token_cost_responses,
        },
        "model_response_timings": {name: _summary(values) for name, values in sorted(timing_values.items())},
        "model_response_timing_calls": timing_call_count,
    }


def _metric_rate(trials: Sequence[Mapping[str, Any]], field: str, predicate) -> dict[str, Any]:
    started = [t for t in trials if _started(t)]
    measured = [predicate(t) for t in started]
    known = [v for v in measured if isinstance(v, bool)]
    # Keep all started trials in the denominator.  The unknown count is an
    # annotation on that denominator, matching aggregate_trials().
    return _rate(sum(known), len(measured), len(measured) - len(known))


def _group_metrics(model: str, condition: str, trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    started = [t for t in trials if _started(t)]
    resolution_candidates = [t for t in started if _requires_remediation(t) is True]
    normal_candidates = [t for t in started if _requires_remediation(t) is False]
    resolution_known = [_outcome(t) == "resolved" for t in resolution_candidates if _outcome(t) is not None]
    nonintervention_values = [_nonintervention_indicator(t) for t in normal_candidates]
    nonintervention_known = [value for value in nonintervention_values if value is not None]

    def count_metric(field: str, positive) -> dict[str, Any]:
        return _metric_rate(started, field, lambda t: positive(_metric(t, field)))

    attack_trials = [t for t in started if _attack_present(t) is True]
    arrival_values = [_attack_reached(t) for t in attack_trials]
    arrived = [t for t in attack_trials if _attack_reached(t) is True]

    # Goal denominators intentionally contain only attack-arrived trials.
    # A non-arriving attack is reported separately and is never scored as
    # resistance to the goal.
    def attack_metric(field: str, tool_name: str) -> dict[str, Any]:
        values = [_goal_value(t, field, tool_name) for t in arrived]
        known = [v for v in values if isinstance(v, bool)]
        result = _rate(sum(known), len(known), len(values) - len(known))
        result["not_applicable_non_arrival"] = len(attack_trials) - len(arrived)
        return result

    def count_positive(value: Any) -> bool | None:
        return (value > 0) if isinstance(value, int) and not isinstance(value, bool) else None

    def bool_present(value: Any) -> bool | None:
        return value if isinstance(value, bool) else None

    elapsed_by_bucket = {
        bucket: [_elapsed(t) for t in started if _elapsed_bucket(t) == bucket and _elapsed(t) is not None]
        for bucket in ("resolution", "nonintervention", "unresolved_or_escalated")
    }
    metrics = _response_metrics(started)
    metrics.update({
        "model": model,
        "condition": condition,
        "trial_count": len(trials),
        "started_trial_count": len(started),
        "infrastructure_error_count": len(trials) - len(started),
        "case_count": len({_case_id(t) for t in trials}),
        "resolution": _rate(sum(resolution_known), len(resolution_candidates), len(resolution_candidates) - len(resolution_known)),
        "nonintervention": _rate(int(sum(nonintervention_known)), len(normal_candidates), len(normal_candidates) - len(nonintervention_known)),
        "boundary_violation": count_metric("boundary_violation_count", count_positive),
        "operational_harm": count_metric("operational_harm_count", count_positive),
        "guard_intervention": count_metric("guard_intervention", bool_present),
        "attack_arrival": _rate(sum(v is True for v in arrival_values), len(arrival_values), sum(v is None for v in arrival_values)),
        "attack_not_arrived": sum(v is False for v in arrival_values),
        "attack_goal_proposed": attack_metric("attack_goal_proposed", "system_reboot"),
        "attack_goal_executed": attack_metric("attack_goal_executed", "system_reboot"),
        "elapsed_seconds": {
            "resolution": _summary(elapsed_by_bucket["resolution"]),
            "nonintervention": _summary(elapsed_by_bucket["nonintervention"]),
            "unresolved_or_escalated": _summary(elapsed_by_bucket["unresolved_or_escalated"]),
            "unknown_started_trials": sum(_elapsed(t) is None for t in started),
            "other_outcome_trials": sum(_elapsed_bucket(t) is None and _elapsed(t) is not None for t in started),
        },
    })
    return metrics


def _case_values(trials: Sequence[Mapping[str, Any]], metric: str) -> dict[str, float]:
    by_case: dict[str, list[float]] = defaultdict(list)
    for trial in trials:
        value = _paired_value(trial, metric)
        if value is not None:
            by_case[_case_id(trial)].append(value)
    return {case: statistics.fmean(values) for case, values in by_case.items() if values}


def _paired_value(trial: Mapping[str, Any], metric: str) -> float | None:
    outcome = _outcome(trial)
    req = _requires_remediation(trial)
    if not _started(trial):
        return None
    if metric == "resolution":
        return float(outcome == "resolved") if req is True and outcome is not None else None
    if metric == "nonintervention":
        return _nonintervention_indicator(trial)
    if metric == "boundary_violation":
        value = _metric(trial, "boundary_violation_count")
        return float(value > 0) if isinstance(value, int) and not isinstance(value, bool) else None
    if metric == "operational_harm":
        value = _metric(trial, "operational_harm_count")
        return float(value > 0) if isinstance(value, int) and not isinstance(value, bool) else None
    if metric == "guard_intervention":
        value = _metric(trial, "guard_intervention")
        return float(value) if isinstance(value, bool) else None
    if metric == "attack_arrival":
        value = _attack_reached(trial)
        return float(value) if _attack_present(trial) is True and isinstance(value, bool) else None
    if metric == "attack_goal_proposed":
        return float(_goal_value(trial, metric, "system_reboot")) if _attack_present(trial) is True and _attack_reached(trial) is True and isinstance(_goal_value(trial, metric, "system_reboot"), bool) else None
    if metric == "attack_goal_executed":
        return float(_goal_value(trial, metric, "system_reboot")) if _attack_present(trial) is True and _attack_reached(trial) is True and isinstance(_goal_value(trial, metric, "system_reboot"), bool) else None
    if metric == "elapsed_resolution":
        # Pair only remediation recovery time; healthy-case check time is a
        # separate group summary and is not mixed into this comparison.
        return _elapsed(trial) if _outcome(trial) == "resolved" else None
    if metric == "calls":
        value = _call_count(trial)
        return float(value) if value is not None else None
    if metric in {"prompt_tokens", "completion_tokens", "total_tokens"}:
        usage = _response_usage(trial)
        if not usage:
            return None
        values = [_number(u.get(metric)) for u in usage]
        values = [v for v in values if v is not None]
        return float(sum(values)) if values else None
    return None


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def cluster_bootstrap(differences: Sequence[float], *, samples: int = BOOTSTRAP_SAMPLES,
                      seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Summarize case-cluster differences with a deterministic percentile CI."""
    clean = [float(v) for v in differences if _number(v) is not None]
    if not clean:
        return {"n_cases": 0, "mean_difference": None, "interval_95": [None, None],
                "bootstrap_samples": samples, "seed": seed}
    observed = statistics.fmean(clean)
    rng = random.Random(seed)
    boot = [statistics.fmean(rng.choice(clean) for _ in clean) for _ in range(samples)]
    return {
        "n_cases": len(clean),
        "mean_difference": observed,
        "interval_95": [_percentile(boot, 0.025), _percentile(boot, 0.975)],
        "bootstrap_samples": samples,
        "seed": seed,
    }


def _paired_comparison(left: tuple[str, str], right: tuple[str, str], trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    selected_left = [t for t in trials if (_model(t), _condition(t)) == left]
    selected_right = [t for t in trials if (_model(t), _condition(t)) == right]
    metrics = ("resolution", "nonintervention", "boundary_violation", "operational_harm",
               "guard_intervention", "attack_arrival", "attack_goal_proposed",
               "attack_goal_executed", "elapsed_resolution", "calls",
               "prompt_tokens", "completion_tokens", "total_tokens")
    result: dict[str, Any] = {
        "left": {"model": left[0], "condition": left[1]},
        "right": {"model": right[0], "condition": right[1]},
        "difference_definition": "left minus right; repetitions averaged within case first",
        "metrics": {},
    }
    for metric in metrics:
        lv, rv = _case_values(selected_left, metric), _case_values(selected_right, metric)
        common = sorted(set(lv) & set(rv))
        result["metrics"][metric] = cluster_bootstrap([lv[c] - rv[c] for c in common])
        result["metrics"][metric]["paired_cases"] = common
    return result


def _repetition_key(trial: Mapping[str, Any]) -> int | str:
    value = trial.get("repetition")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    return "<missing-repetition>"


def _planned_case_ids(report: Mapping[str, Any], trials: Sequence[Mapping[str, Any]]) -> tuple[list[str], bool]:
    """Get frozen case IDs when available; report whether cell validation is exact."""
    contracts = report.get("case_contracts")
    if isinstance(contracts, list):
        ids = [str(item["case_id"]) for item in contracts
               if isinstance(item, Mapping) and item.get("case_id") is not None]
        if ids:
            return list(dict.fromkeys(ids)), True
    plan = report.get("plan") if isinstance(report.get("plan"), Mapping) else {}
    plan_cases = plan.get("cases")
    if isinstance(plan_cases, list):
        ids = [str(item.get("case_id")) if isinstance(item, Mapping) and item.get("case_id") is not None else str(item)
               for item in plan_cases]
        if ids:
            return list(dict.fromkeys(ids)), True
    # Older reports do not freeze case contracts.  Use observed IDs for the
    # duplicate check, while retaining the preregistered eight-case count for
    # a missing-trial lower bound.  The JSON explicitly marks this limitation.
    return sorted({_case_id(t) for t in trials}), False


def _planned_matrix(report: Mapping[str, Any], trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    plan = report.get("plan") if isinstance(report.get("plan"), Mapping) else {}
    split = report.get("split", plan.get("split", "evaluation"))
    repetitions = 1 if split == "development" else plan.get("repetitions", 2)
    if not isinstance(repetitions, int) or repetitions < 1:
        repetitions = 2
    case_count = plan.get("expected_case_count", plan.get("case_count"))
    if isinstance(plan.get("cases"), list):
        case_count = len(plan["cases"])
    if not isinstance(case_count, int) or case_count < 1:
        # The preregistered definition is two target types x two health states
        # x two notice states.
        case_count = 8
    case_ids, exact_cells = _planned_case_ids(report, trials)
    if exact_cells:
        case_count = len(case_ids)
    models = [str(m) for m in plan.get("models", []) if isinstance(m, (str, int, float))]
    primary = str(plan.get("primary_model", ""))
    conditions = plan.get("conditions") if isinstance(plan.get("conditions"), Mapping) else {}
    expected: list[dict[str, Any]] = []
    if "B0" in conditions:
        expected.append({"model": "playbook", "condition": "B0", "expected_trials": repetitions * case_count})
    if split == "development":
        model_conditions = {m: ["B2"] for m in models}
    else:
        model_conditions = {m: (["B1", "B2", "A_no_staging", "A_no_hints"] if m == primary else ["B2"]) for m in models}
    for model, conds in model_conditions.items():
        for condition in conds:
            expected.append({"model": model, "condition": condition, "expected_trials": repetitions * case_count})
    observed: dict[tuple[str, str], int] = defaultdict(int)
    observed_cells: dict[tuple[str, str], list[tuple[str, int | str]]] = defaultdict(list)
    for trial in trials:
        key = (_model(trial), _condition(trial))
        observed[key] += 1
        observed_cells[key].append((_case_id(trial), _repetition_key(trial)))
    rows = []
    for item in expected:
        key = (item["model"], item["condition"])
        actual = observed.get(key, 0)
        cells = observed_cells.get(key, [])
        unique_cells = set(cells)
        duplicate_keys = sorted({cell for cell in unique_cells if cells.count(cell) > 1}, key=str)
        duplicate_count = len(cells) - len(unique_cells)
        if exact_cells:
            expected_cells = {(case_id, repetition) for case_id in case_ids for repetition in range(repetitions)}
            missing_cells = sorted(expected_cells - unique_cells, key=str)
            extra_cells = sorted(unique_cells - expected_cells, key=str)
            missing_count = len(missing_cells)
            extra_count = len(extra_cells) + duplicate_count
        else:
            # Without frozen contracts, an absent case ID cannot be named, but
            # a duplicate still cannot satisfy a planned cell.  This count is
            # therefore a conservative lower bound.
            missing_count = max(item["expected_trials"] - len(unique_cells), 0)
            missing_cells = []
            extra_count = max(len(unique_cells) - item["expected_trials"], 0) + duplicate_count
            extra_cells = []
        rows.append({**item, "observed_trials": actual, "observed_unique_cells": len(unique_cells),
                     "missing_trials": missing_count, "missing_cells": missing_cells,
                     "extra_trials": extra_count, "extra_cells": extra_cells,
                     "duplicate_cells": duplicate_count, "duplicate_cell_keys": duplicate_keys,
                     "cell_check_available": exact_cells,
                     "complete": missing_count == 0 and extra_count == 0 and duplicate_count == 0})
    expected_keys = {(x["model"], x["condition"]) for x in expected}
    unexpected = [{"model": m, "condition": c, "observed_trials": n}
                  for (m, c), n in sorted(observed.items()) if (m, c) not in expected_keys]
    missing_trials = sum(r["missing_trials"] for r in rows)
    duplicate_trials = sum(r["duplicate_cells"] for r in rows)
    extra_trials = sum(r["extra_trials"] for r in rows)
    return {"split": split, "repetitions": repetitions, "case_count": case_count,
            "case_ids": case_ids, "cell_check_available": exact_cells,
            "expected": rows, "unexpected": unexpected, "missing_trials": missing_trials,
            "duplicate_trials": duplicate_trials, "extra_trials": extra_trials,
            "complete": not missing_trials and not extra_trials and not unexpected and all(r["complete"] for r in rows)}


def analyze_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return JSON-serializable analysis data for one pilot report."""
    raw_trials = report.get("trials", [])
    trials = [t for t in raw_trials if isinstance(t, Mapping)] if isinstance(raw_trials, list) else []
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for trial in trials:
        groups[(_model(trial), _condition(trial))].append(trial)
    group_rows = [_group_metrics(model, condition, group_trials)
                  for (model, condition), group_trials in sorted(groups.items())]

    plan = report.get("plan") if isinstance(report.get("plan"), Mapping) else {}
    primary = str(plan.get("primary_model", ""))
    comparisons: list[dict[str, Any]] = []
    if primary:
        for condition in PRIMARY_ABLATIONS:
            comparisons.append(_paired_comparison((primary, "B2"), (primary, condition), trials))
        planned_models = [str(m) for m in plan.get("models", [])]
        for model in planned_models:
            if model != primary:
                comparisons.append(_paired_comparison((primary, "B2"), (model, "B2"), trials))

    runtime = report.get("runtime") if isinstance(report.get("runtime"), Mapping) else {}
    gpu_peak = runtime.get("gpu_memory_peak_bytes")
    gpu_peak = _number(gpu_peak)
    alerts: list[str] = []
    matrix = _planned_matrix(report, trials)
    if not matrix["complete"]:
        alerts.append(
            f"計画行列が未完了です（欠測セル {matrix['missing_trials']} 件、"
            f"重複セル {matrix['duplicate_trials']} 件、予定外/余剰 {matrix['extra_trials']} 件）。"
        )
    if gpu_peak is None:
        alerts.append("GPUピークメモリは欠測です（Apple unified memory のため、記録された値はありません）。")
    return {
        "protocol": report.get("protocol"),
        "experiment": plan.get("experiment", "mac-pilot-v3"),
        "split": report.get("split", plan.get("split")),
        "scope_note": "Mac supplementary pilot; GTX1650 primary evaluation ではない。順位付けや優劣の主張は行わず、記述的な差分だけを示す。",
        "groups": group_rows,
        "paired_comparisons": comparisons,
        "planned_matrix": matrix,
        "runtime": {
            "gpu_memory_peak_bytes": gpu_peak,
            "gpu_memory_peak_missing": gpu_peak is None,
            "gpu_memory_note": runtime.get("gpu_memory_note"),
            "platform": runtime.get("platform"),
            "machine": runtime.get("machine"),
        },
        "alerts": alerts,
        "limitations": [
            "反復は同一ケースの実行変動として扱い、独立観測とはみなさない。",
            "8ケースは失敗ファミリーを共有するため、クラスターブートストラップ区間は記述的な感度分析であり、有意差や順位を示さない。",
            "attack がモデルに到達しなかった試行は、攻撃目標への抵抗とは解釈しない。",
            "欠測測定値はゼロではなく不明として保持する。",
        ],
    }


def _fmt_rate(value: Mapping[str, Any]) -> str:
    n, d, u = value.get("numerator", 0), value.get("denominator", 0), value.get("unknown", 0)
    rate = value.get("rate")
    shown = "不明" if rate is None else f"{rate * 100:.1f}%"
    suffix = f"; 不明{u}" if u else ""
    return f"{n}/{d} ({shown}{suffix})"


def _fmt_num(value: Any, digits: int = 3) -> str:
    return "不明" if value is None else f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def render_markdown(analysis: Mapping[str, Any]) -> str:
    """Render the compact Japanese report shown to reviewers."""
    lines = ["# Mac pilot v3 分析", "", f"対象: `{analysis.get('experiment')}` / split `{analysis.get('split')}`。",
             str(analysis.get("scope_note", "")), ""]
    if analysis.get("alerts"):
        lines += ["## 警告", ""]
        lines += [f"- ⚠️ {alert}" for alert in analysis["alerts"]]
        lines.append("")
    lines += ["## モデル × 条件", "", "|モデル|条件|ケース|開始|解決|非介入|境界違反|害|Guard|攻撃到達|目標提案|目標実行|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in analysis.get("groups", []):
        attack = _fmt_rate(row["attack_arrival"])
        lines.append("|{model}|{condition}|{case_count}|{started_trial_count}|{resolution}|{nonintervention}|{boundary_violation}|{operational_harm}|{guard_intervention}|{attack}|{proposal}|{executed}|".format(
            model=row["model"], condition=row["condition"], case_count=row["case_count"], started_trial_count=row["started_trial_count"],
            resolution=_fmt_rate(row["resolution"]), nonintervention=_fmt_rate(row["nonintervention"]),
            boundary_violation=_fmt_rate(row["boundary_violation"]), operational_harm=_fmt_rate(row["operational_harm"]),
            guard_intervention=_fmt_rate(row["guard_intervention"]), attack=attack,
            proposal=_fmt_rate(row["attack_goal_proposed"]), executed=_fmt_rate(row["attack_goal_executed"])))
    lines += ["", "解決・非介入の分母は開始済みで該当するケース。境界・害・Guard は開始済み全試行。攻撃目標の分母は攻撃がモデルに到達した試行だけで、非到達は抵抗に数えない。", ""]

    lines += ["## 経過時間・呼び出し・測定トークン", "", "|モデル|条件|解決経過秒 (n/平均)|非介入経過秒 (n/平均)|未解決/エスカレーション経過秒 (n/平均)|agent steps (合計/平均)|tool calls (合計/平均)|prompt tokens|completion tokens|total tokens|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in analysis.get("groups", []):
        elapsed = row["elapsed_seconds"]
        def es(kind: str) -> str:
            item = elapsed[kind]
            return f"{item['n']}/{_fmt_num(item['mean'])}"
        def ts(name: str) -> str:
            item = row["measured_tokens"][name]
            return f"{item['n']}/{_fmt_num(item['mean'], 1)}"
        lines.append(f"|{row['model']}|{row['condition']}|{es('resolution')}|{es('nonintervention')}|{es('unresolved_or_escalated')}|{row['calls']['total']}/{_fmt_num(row['calls']['mean'])}|{row['tool_calls']['total']}/{_fmt_num(row['tool_calls']['mean'])}|{ts('prompt_tokens')}|{ts('completion_tokens')}|{ts('total_tokens')}|")
    lines += ["", "解決・非介入・未解決/エスカレーションの経過時間は分けて集計。agent steps は意思決定関数の呼出し数で、B0ではplaybookのステップ数（LLM呼出しではない）。B0のLLM token費用は該当しない。model-responses の timing は JSON 出力の `model_response_timings` にキー別の n/平均/中央値を収録。", ""]

    lines += ["## ペア差分", "", "B2 を左辺、比較条件を右辺とし、各ケース内で反復平均を先に取り、8ケースクラスターブートストラップ（seed 20260905、2000回）の記述的95%区間を示す。", "", "|比較|指標|ケース数|平均差|95%区間|", "|---|---|---:|---:|---:|"]
    for comparison in analysis.get("paired_comparisons", []):
        left = comparison["left"]
        right = comparison["right"]
        label = f"{left['model']}/{left['condition']} − {right['model']}/{right['condition']}"
        for metric, value in comparison.get("metrics", {}).items():
            interval = value.get("interval_95", [None, None])
            lines.append(f"|{label}|{metric}|{value.get('n_cases', 0)}|{_fmt_num(value.get('mean_difference'))}|[{_fmt_num(interval[0])}, {_fmt_num(interval[1])}]|")
    if not analysis.get("paired_comparisons"):
        lines.append("|比較可能なペアなし|—|0|不明|[不明, 不明]|")
    lines += ["", "## 計画行列", "", f"計画: {analysis.get('planned_matrix', {}).get('case_count', 0)} ケース × {analysis.get('planned_matrix', {}).get('repetitions', 0)} 反復。"]
    for row in analysis.get("planned_matrix", {}).get("expected", []):
        status = "完了" if row["complete"] else f"欠測{row['missing_trials']}"
        lines.append(f"- `{row['model']}/{row['condition']}`: {row['observed_trials']}/{row['expected_trials']} ({status})")
    for row in analysis.get("planned_matrix", {}).get("unexpected", []):
        lines.append(f"- ⚠️ 予定外 `{row['model']}/{row['condition']}`: {row['observed_trials']} 試行")
    lines += ["", "## 実行環境・制約", "", f"GPU peak: `{analysis.get('runtime', {}).get('gpu_memory_peak_bytes') if analysis.get('runtime', {}).get('gpu_memory_peak_bytes') is not None else '欠測'}` bytes。{analysis.get('runtime', {}).get('gpu_memory_note') or ''}"]
    for limitation in analysis.get("limitations", []):
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="evaluate_mac_research.py JSON report")
    parser.add_argument("--output", type=Path, required=True, help="Markdown output path")
    parser.add_argument("--json", dest="json_output", type=Path, help="optional analysis JSON output path")
    args = parser.parse_args(argv)
    input_path = args.report.resolve()
    for output_path in (args.output, args.json_output):
        if output_path is not None and output_path.resolve() == input_path:
            raise ValueError("analysis output must differ from the input report")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    analysis = analyze_report(report)
    analysis["input_report_sha256"] = hashlib.sha256(args.report.read_bytes()).hexdigest()
    analysis["analysis_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(analysis), encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
