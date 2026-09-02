from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CanonicalProposal:
    """The only proposal representation consumed by the evaluator.

    ``approval_required`` is deliberately not part of this representation. If
    a model emits that legacy/diagnostic field, it is recorded separately as
    ``llm_approval_signal`` and never used for authorization or scoring Broker
    acceptance.
    """

    proposal: dict[str, Any]
    envelope_valid: bool
    source_format: str
    llm_approval_signal: bool | None = None
    raw_envelope: dict[str, Any] | None = None
    errors: tuple[str, ...] = ()


def _json_candidates(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    return candidates


def _select_envelope(text: str) -> dict[str, Any] | None:
    candidates = _json_candidates(text)
    if not candidates:
        return None
    envelopes = [
        item for item in candidates
        if "tool_calls" in item or "tools" in item or "hypothesis" in item or "approval_required" in item
    ]
    if envelopes:
        return envelopes[0]
    return max(candidates, key=lambda item: len(json.dumps(item, ensure_ascii=False)))


def _parse_arguments(value: Any) -> tuple[dict[str, Any], str | None]:
    if value is None:
        return {}, None
    if isinstance(value, Mapping):
        return dict(value), None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            return {"_raw_arguments": value}, f"arguments JSON parse failed: {exc.msg}"
        if isinstance(parsed, Mapping):
            return dict(parsed), None
        return {"_raw_arguments": parsed}, "arguments must decode to an object"
    return {"_raw_arguments": value}, "arguments must be an object"


def _canonical_call(value: Any) -> tuple[dict[str, Any], str | None]:
    if not isinstance(value, Mapping):
        return {"tool": "__invalid_call__", "arguments": {"_invalid_call": value}}, "tool call must be an object"

    function = value.get("function")
    function_mapping = function if isinstance(function, Mapping) else {}
    name = value.get("tool") or value.get("name") or function_mapping.get("name")
    arguments = value.get("arguments")
    if arguments is None:
        arguments = value.get("args")
    if arguments is None:
        arguments = value.get("parameters")
    if arguments is None and function_mapping:
        arguments = function_mapping.get("arguments")
    parsed_arguments, error = _parse_arguments(arguments)
    if not isinstance(name, str) or not name:
        return {"tool": "__invalid_tool__", "arguments": parsed_arguments}, "tool name must be a non-empty string"
    return {"tool": name, "arguments": parsed_arguments}, error


def _scan_calls(text: str) -> list[tuple[str, str]]:
    """Scan ``name(...)`` without evaluating model-provided expressions."""

    calls: list[tuple[str, str]] = []
    cursor = 0
    name_pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    while True:
        match = name_pattern.search(text, cursor)
        if match is None:
            break
        opening = text.find("(", match.start(), match.end())
        depth = 1
        index = opening + 1
        quote: str | None = None
        escaped = False
        while index < len(text) and depth:
            character = text[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    quote = None
            elif character in {"'", '"'}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            index += 1
        if depth == 0:
            calls.append((match.group(1), text[opening + 1 : index - 1]))
            cursor = index
        else:
            break
    return calls


def _native_arguments(text: str) -> tuple[dict[str, Any], str | None]:
    if not text.strip():
        return {}, None
    try:
        expression = ast.parse(f"f({text})", mode="eval")
    except SyntaxError as exc:
        return {"_raw_arguments": text}, f"native arguments parse failed: {exc.msg}"
    call = expression.body
    if not isinstance(call, ast.Call):
        return {"_raw_arguments": text}, "native call arguments are invalid"
    if call.args:
        return {"_positional": [ast.unparse(item) for item in call.args]}, "native calls require keyword arguments"
    arguments: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            return {"_raw_arguments": text}, "native **kwargs are not supported"
        try:
            arguments[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, SyntaxError):
            # Keep unsupported expressions as data. Broker schema validation will
            # reject them rather than the evaluator executing or guessing them.
            arguments[keyword.arg] = ast.unparse(keyword.value)
    return arguments, None


def _native_calls(text: str) -> list[dict[str, Any]]:
    start = re.search(r"<\|tool_call_start\|>", text, re.IGNORECASE)
    if start is None:
        return []
    tail = text[start.end() :]
    end = re.search(r"<\|tool_call_end\|>", tail, re.IGNORECASE)
    body = tail[: end.start()] if end is not None else tail
    calls: list[dict[str, Any]] = []
    for name, arguments_text in _scan_calls(body):
        arguments, _ = _native_arguments(arguments_text)
        calls.append({"tool": name, "arguments": arguments})
    return calls


def _openai_calls(response: Mapping[str, Any] | None) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(response, Mapping):
        return [], None
    raw_calls = response.get("tool_calls")
    if not isinstance(raw_calls, list):
        return [], None
    calls: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw_call in raw_calls:
        call, error = _canonical_call(raw_call)
        calls.append(call)
        if error:
            errors.append(error)
    return calls, "; ".join(errors) if errors else None


def adapt_output(raw_output: str, response: Mapping[str, Any] | None = None) -> CanonicalProposal:
    """Normalize JSON, OpenAI/llama.cpp, and LFM native output forms."""

    errors: list[str] = []
    response = response if isinstance(response, Mapping) else None
    openai_calls, openai_error = _openai_calls(response)
    if openai_calls:
        if openai_error:
            errors.append(openai_error)
        content = response.get("content") or response.get("reasoning_content") or ""
        hypothesis = content if isinstance(content, str) else ""
        return CanonicalProposal(
            proposal={"hypothesis": hypothesis, "tool_calls": openai_calls},
            envelope_valid=True,
            source_format="llama_cpp_tool_calls",
            errors=tuple(errors),
        )

    envelope = _select_envelope(raw_output)
    if envelope is not None and ("tool_calls" in envelope or "tools" in envelope):
        raw_calls = envelope.get("tool_calls", envelope.get("tools"))
        envelope_valid = isinstance(envelope.get("hypothesis"), str) and isinstance(raw_calls, list)
        calls: list[dict[str, Any]] = []
        if isinstance(raw_calls, list):
            for raw_call in raw_calls:
                call, error = _canonical_call(raw_call)
                calls.append(call)
                if error:
                    errors.append(error)
        else:
            errors.append("tool_calls must be an array")
        signal = envelope.get("approval_required")
        return CanonicalProposal(
            proposal={
                "hypothesis": envelope.get("hypothesis") if isinstance(envelope.get("hypothesis"), str) else "",
                "tool_calls": calls,
            },
            envelope_valid=envelope_valid,
            source_format="sabakan_json",
            llm_approval_signal=signal if isinstance(signal, bool) else None,
            raw_envelope=envelope,
            errors=tuple(errors),
        )

    native_calls = _native_calls(raw_output)
    if native_calls:
        return CanonicalProposal(
            proposal={"hypothesis": "", "tool_calls": native_calls},
            envelope_valid=True,
            source_format="lfm_native",
            errors=tuple(errors),
        )

    # With OpenAI-compatible function calling, a valid assistant message may
    # contain only natural-language content (for example, a diagnosis-only
    # incident) and no tool calls. Treat that message as the canonical empty
    # tool proposal instead of requiring the model to duplicate it as JSON.
    if response is not None and ("tool_calls" in response or "content" in response):
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            content = response.get("reasoning_content")
        if isinstance(content, str) and content.strip():
            return CanonicalProposal(
                proposal={"hypothesis": content.strip(), "tool_calls": []},
                envelope_valid=True,
                source_format="llama_cpp_message",
                errors=tuple(errors),
            )

    return CanonicalProposal(
        proposal={"hypothesis": "", "tool_calls": []},
        envelope_valid=False,
        source_format="unparsed",
        errors=("no supported proposal format found",),
    )
