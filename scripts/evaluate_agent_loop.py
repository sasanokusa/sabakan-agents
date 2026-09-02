#!/usr/bin/env python3
"""Measure Local LLM driven incident resolution through the Sabakan Broker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from evaluation.agent_loop import aggregate_agent_loop, run_agent_loop, tool_schemas_for_state  # noqa: E402
from evaluation.docker_fixtures import (  # noqa: E402
    DockerFixtureExecutor,
    PRINCIPAL,
    build_fixture_broker,
    fixture_cases,
    _remove_container,
)
from scripts.evaluate_models import diagnosis_matches  # noqa: E402

try:
    from scripts.evaluate_llamacpp import (  # noqa: E402
        IMAGE,
        MODEL_CONTAINER_PATH,
        MODEL_SPECS,
        http_json,
        require_runtime,
        start_server,
        stop_server,
    )
except ModuleNotFoundError:  # direct execution with scripts on sys.path
    from evaluate_llamacpp import (  # type: ignore[no-redef] # noqa: E402
        IMAGE,
        MODEL_CONTAINER_PATH,
        MODEL_SPECS,
        http_json,
        require_runtime,
        start_server,
        stop_server,
    )


DEFAULT_OUTPUT = ROOT / "evaluation" / "agent-loop-results-v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=tuple(MODEL_SPECS), default=list(MODEL_SPECS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--context-size", type=int, default=8192)
    parser.add_argument("--gpu-layers", type=int, default=99)
    parser.add_argument("--reasoning-budget", type=int, default=0)
    parser.add_argument("--reasoning-mode", choices=("auto", "on", "off"), default="off")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    parser.add_argument("--docker-image", default=IMAGE)
    return parser.parse_args()


def build_chat_function(base_url: str, max_tokens: int, timeout: float):
    def chat(messages: list[dict[str, Any]], tools: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        payload = {
            "model": MODEL_CONTAINER_PATH,
            "messages": messages,
            "tools": list(tools),
            "tool_choice": "auto",
            "temperature": 0,
            "top_p": 1,
            "max_tokens": max_tokens,
            "stream": False,
        }
        response = http_json(f"{base_url}/v1/chat/completions", payload, timeout=timeout)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError(f"invalid completion response: {response}")
        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        return {
            "content": content.strip() if isinstance(content, str) else "",
            "tool_calls": message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else [],
            "finish_reason": choices[0].get("finish_reason"),
            "usage": response.get("usage", {}),
            "timings": response.get("timings", {}),
            # Native markers, if a model emits them despite the OpenAI tools
            # request, are normalized by evaluation.agent_loop without exposing
            # model-specific prompt logic.
            "raw_output": content if isinstance(content, str) else "",
        }

    return chat


def _schema_hash(tools: tuple[dict[str, Any], ...]) -> str:
    return hashlib.sha256(
        json.dumps(list(tools), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _score_case(result: dict[str, Any], case: Any) -> dict[str, Any]:
    visible_content = " ".join(
        str(turn.get("assistant", ""))
        for turn in result.get("turns", [])
        if isinstance(turn, dict) and isinstance(turn.get("assistant"), str)
    )
    result["diagnosis_text"] = visible_content
    result["diagnosis_accuracy"] = diagnosis_matches(visible_content, case.expected_root_cause)
    result["root_cause_accuracy"] = result["diagnosis_accuracy"]
    expected_tools = set(case.expected_mutation_tools)
    unnecessary = sorted(
        {
            str(mutation.get("tool"))
            for mutation in result.get("mutations", [])
            if isinstance(mutation, dict) and mutation.get("tool") not in expected_tools
        }
    )
    result["unnecessary_mutations"] = unnecessary
    result["unnecessary_mutation"] = bool(unnecessary)
    result["fixture"] = case.name
    result["malicious"] = bool(case.malicious)
    return result


def main() -> int:
    args = parse_args()
    require_runtime()
    cases = fixture_cases()
    selected = [MODEL_SPECS[name] for name in args.models]
    read_tools = tool_schemas_for_state("observe")
    remediation_tools = tool_schemas_for_state("remediation")
    report: dict[str, Any] = {
        "protocol": "sabakan-agent-loop-v1",
        "fixtures": [case.incident_id for case in cases],
        "fixture_count": len(cases),
        "runtime": {
            "image": args.docker_image,
            "context_size": args.context_size,
            "gpu_layers": args.gpu_layers,
            "max_tokens": args.max_tokens,
            "reasoning_budget": args.reasoning_budget,
            "reasoning_mode": args.reasoning_mode,
            "chat_template": "model metadata via llama.cpp Jinja",
            "read_tool_schema_sha256": _schema_hash(read_tools),
            "remediation_tool_schema_sha256": _schema_hash(remediation_tools),
        },
        "models": [],
    }
    base_url = f"http://127.0.0.1:{args.port}"
    for model_index, spec in enumerate(selected, 1):
        model_name = spec["label"]
        container_name = f"sabakan-agent-loop-{os.getpid()}-{model_index}"
        model_record: dict[str, Any] = {
            "model": model_name,
            "repo": spec["repo"],
            "path": str(Path(spec["path"]).resolve().relative_to(ROOT)),
            "status": "error",
            "results": [],
        }
        print(f"[{model_name}] starting CUDA server", flush=True)
        server_args = argparse.Namespace(
            port=args.port,
            docker_image=args.docker_image,
            context_size=args.context_size,
            gpu_layers=args.gpu_layers,
            reasoning_budget=args.reasoning_budget,
            reasoning_mode=args.reasoning_mode,
        )
        try:
            load_seconds, models_response = start_server(spec, server_args, container_name)
            model_record.update(
                {
                    "status": "ok",
                    "load_seconds": round(load_seconds, 4),
                    "model_metadata": (
                        models_response.get("data", [{}])[0].get("meta", {})
                        if isinstance(models_response.get("data"), list)
                        and models_response.get("data")
                        and isinstance(models_response.get("data")[0], dict)
                        else {}
                    ),
                }
            )
            print(f"[{model_name}] ready in {load_seconds:.1f}s", flush=True)
            chat = build_chat_function(base_url, args.max_tokens, args.request_timeout)
            for fixture_index, case in enumerate(cases, 1):
                fixture_root: Path | None = None
                try:
                    with tempfile.TemporaryDirectory(prefix="sabakan-agent-case-") as directory:
                        fixture_root = Path(directory)
                        containers, log_path = case.setup(container_name + f"-{fixture_index}", fixture_root)
                        executor = DockerFixtureExecutor(containers, log_path, case.read_data)
                        broker = build_fixture_broker(fixture_root / "broker", executor)
                        incident = {
                            "id": case.incident_id,
                            "symptom": case.symptom,
                            "observations": list(case.observations),
                        }
                        result = run_agent_loop(
                            incident=incident,
                            broker=broker,
                            principal=PRINCIPAL,
                            chat=chat,
                            postcheck=lambda: case.postcheck(executor),
                            model=model_name,
                            max_tokens=args.max_tokens,
                            max_turns=20,
                        )
                        result = _score_case(result, case)
                        model_record["results"].append(result)
                        print(
                            f"[{model_name}] {fixture_index}/{len(cases)} {case.incident_id}: "
                            f"status={result['status']} diagnosis={result['diagnosis_accuracy']} "
                            f"calls={result['tool_call_count']} mutations={result['mutation_count']} "
                            f"postcheck={result['postcheck']}",
                            flush=True,
                        )
                except Exception as exc:
                    model_record["results"].append(
                        {
                            "incident_id": case.incident_id,
                            "fixture": case.name,
                            "model": model_name,
                            "status": "failed",
                            "failure_reason": f"{type(exc).__name__}: {exc}",
                            "health_restored": False,
                        }
                    )
                    print(f"[{model_name}] {case.incident_id} ERROR {type(exc).__name__}: {exc}", flush=True)
                finally:
                    _remove_container(container_name + f"-{fixture_index}")
            model_record["metrics"] = aggregate_agent_loop(model_record["results"])
        except Exception as exc:
            model_record["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[{model_name}] ERROR {model_record['error']}", flush=True)
        finally:
            stop_server(container_name)
            report["models"].append(model_record)
            report["generated_at"] = time.time()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{model_name}] unloaded; intermediate report written", flush=True)

    print(f"wrote {args.output}")
    return 0 if any(item.get("status") == "ok" for item in report["models"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
