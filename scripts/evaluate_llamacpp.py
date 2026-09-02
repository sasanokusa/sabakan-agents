#!/usr/bin/env python3
"""Evaluate the downloaded GGUF models through one CUDA llama.cpp server at a time.

The runner deliberately keeps the model server outside of the Sabakan Broker
boundary. It sends only benchmark prompts, never executes model-produced text,
and removes the container before loading the next model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    from evaluate_models import (
        MODEL_SPECS,
        MODEL_TOOL_SCHEMAS,
        aggregate,
        build_assessment_broker,
        build_prompt,
        evaluate_output,
        read_benchmark,
    )
except ModuleNotFoundError:  # imported as ``scripts.evaluate_llamacpp`` by tests/tools
    from scripts.evaluate_models import (
        MODEL_SPECS,
        MODEL_TOOL_SCHEMAS,
        aggregate,
        build_assessment_broker,
        build_prompt,
        evaluate_output,
        read_benchmark,
    )


DEFAULT_OUTPUT = ROOT / "evaluation" / "results-v3.json"
IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda"
MODEL_CONTAINER_PATH = "/models/model.gguf"
CUDA_LIB = Path("/usr/lib/x86_64-linux-gnu/libcuda.so.580.173.02")
PTXJIT_LIB = Path("/usr/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.580.173.02")
NVVM_LIB = Path("/usr/lib/x86_64-linux-gnu/libnvidia-nvvm.so.580.173.02")
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=tuple(MODEL_SPECS), default=list(MODEL_SPECS))
    parser.add_argument("--benchmark", type=Path, default=ROOT / "evaluation" / "benchmark.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--max-tokens", "--max-new-tokens", dest="max_tokens", type=int, default=384,
        help="OpenAI max_tokens for each completion (default: 384)",
    )
    parser.add_argument("--reasoning-budget", type=int, default=96, help="bounded thinking tokens; -1 means unrestricted")
    parser.add_argument("--reasoning-mode", choices=("auto", "on", "off"), default="off")
    parser.add_argument("--context-size", type=int, default=2048)
    parser.add_argument("--gpu-layers", type=int, default=99)
    parser.add_argument("--limit", type=int, default=0, help="only run the first N fixtures; 0 means all")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    parser.add_argument("--docker-image", default=IMAGE)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def require_runtime() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("docker is required for the CUDA llama.cpp runner")
    missing = [str(path) for path in (CUDA_LIB, PTXJIT_LIB, NVVM_LIB) if not path.is_file()]
    if missing:
        raise RuntimeError("host NVIDIA driver libraries are missing: " + ", ".join(missing))


def http_json(url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object from {url}")
    return value


def docker_command(spec: dict[str, Any], name: str, port: int, image: str, context_size: int, gpu_layers: int, reasoning_budget: int, reasoning_mode: str) -> list[str]:
    model_path = Path(spec["path"]).resolve()
    return [
        "docker", "run", "-d", "--name", name,
        "--device", "/dev/nvidia0",
        "--device", "/dev/nvidiactl",
        "--device", "/dev/nvidia-uvm",
        "--device", "/dev/nvidia-uvm-tools",
        "--device", "/dev/nvidia-modeset",
        "-v", f"{CUDA_LIB}:/usr/local/cuda-12.8/compat/libcuda.so.570.124.06:ro",
        "-v", f"{PTXJIT_LIB}:/usr/local/cuda-12.8/compat/libnvidia-ptxjitcompiler.so.570.124.06:ro",
        "-v", f"{NVVM_LIB}:/usr/local/cuda-12.8/compat/libnvidia-nvvm.so.570.124.06:ro",
        "-v", f"{model_path}:{MODEL_CONTAINER_PATH}:ro",
        "-p", f"127.0.0.1:{port}:8080",
        "-e", "LD_LIBRARY_PATH=/usr/local/cuda/compat:/usr/local/cuda/lib64:/app",
        image,
        "-m", MODEL_CONTAINER_PATH,
        "--host", "0.0.0.0",
        "--port", "8080",
        "-c", str(context_size),
        "-ngl", str(gpu_layers),
        "--reasoning", reasoning_mode,
        "--reasoning-budget", str(reasoning_budget),
        "--jinja",
        "--metrics",
    ]


def start_server(spec: dict[str, Any], args: argparse.Namespace, name: str) -> tuple[float, dict[str, Any]]:
    started = time.perf_counter()
    command = docker_command(
        spec, name, args.port, args.docker_image, args.context_size, args.gpu_layers,
        args.reasoning_budget, args.reasoning_mode,
    )
    subprocess.run(["docker", "rm", "-f", name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    health_url = f"http://127.0.0.1:{args.port}/health"
    last_error: Exception | None = None
    for _ in range(180):
        try:
            http_json(health_url, None, timeout=2.0)
            models = http_json(f"http://127.0.0.1:{args.port}/v1/models", None, timeout=10.0)
            return time.perf_counter() - started, models
        except (OSError, ValueError, urllib.error.HTTPError, RuntimeError) as exc:
            last_error = exc
            time.sleep(1.0)
    logs = subprocess.run(["docker", "logs", "--tail", "200", name], check=False, text=True, capture_output=True)
    raise RuntimeError(f"llama.cpp server did not become ready: {last_error}\n{logs.stdout}\n{logs.stderr}")


def stop_server(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_chat_completion_payload(
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    max_tokens: int,
) -> dict[str, Any]:
    """Build the identical OpenAI-compatible request sent to every model."""

    return {
        "model": MODEL_CONTAINER_PATH,
        "messages": messages,
        "tools": list(tools),
        "tool_choice": "auto",
        "temperature": 0,
        "top_p": 1,
        "max_tokens": max_tokens,
        "stream": False,
    }


def generate(
    base_url: str,
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    max_tokens: int,
    timeout: float,
) -> tuple[str, int, int, float, dict[str, Any]]:
    payload = build_chat_completion_payload(messages, tools, max_tokens)
    started = time.perf_counter()
    response = http_json(f"{base_url}/v1/chat/completions", payload, timeout=timeout)
    elapsed = time.perf_counter() - started
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError(f"invalid completion response: {response}")
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        message = {}
    content = str(message.get("content") or "").strip()
    reasoning = str(message.get("reasoning_content") or "").strip()
    # Some local models expose their complete answer in reasoning_content when
    # the requested completion budget is exhausted.
    output = "\n".join(part for part in (reasoning, content) if part)
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    if not prompt_tokens:
        prompt_tokens = max(1, sum(len(message.get("content", "").split()) for message in messages))
    if not completion_tokens:
        completion_tokens = max(1, len(output.split()))
    return output, prompt_tokens, completion_tokens, elapsed, {
        "finish_reason": choices[0].get("finish_reason"),
        "reasoning_content": reasoning,
        "content": content,
        "tool_calls": message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else [],
        "timings": response.get("timings", {}),
    }


def load_info(models_response: dict[str, Any], load_seconds: float, image: str) -> dict[str, Any]:
    data = models_response.get("data", [])
    model = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    meta = model.get("meta", {}) if isinstance(model.get("meta", {}), dict) else {}
    return {
        "load_seconds": round(load_seconds, 4),
        "runtime": "llama.cpp server-cuda",
        "runtime_image": image,
        "device": "CUDA0: NVIDIA GeForce GTX 1650",
        "model_metadata": meta,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    require_runtime()
    fixtures = read_benchmark(args.benchmark, args.limit)
    selected = [MODEL_SPECS[name] for name in args.models]
    if args.dry_run:
        for spec in selected:
            print(json.dumps({"model": spec["label"], "repo": spec["repo"], "path": str(spec["path"]), "exists": Path(spec["path"]).is_file()}, ensure_ascii=False))
        return 0

    report: dict[str, Any] = {
        "benchmark": str(args.benchmark),
        "protocol": "sabakan-canonical-v3-openai-tools",
        "generated_at": time.time(),
        "runtime": {
            "image": args.docker_image,
            "context_size": args.context_size,
            "gpu_layers": args.gpu_layers,
            "max_tokens": args.max_tokens,
            "reasoning_budget": args.reasoning_budget,
            "reasoning_mode": args.reasoning_mode,
            "chat_template": "model metadata via llama.cpp Jinja",
            "tool_names": [item["function"]["name"] for item in MODEL_TOOL_SCHEMAS],
            "tool_schema_sha256": hashlib.sha256(
                json.dumps(list(MODEL_TOOL_SCHEMAS), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        "models": [],
    }
    base_url = f"http://127.0.0.1:{args.port}"
    assessor = build_assessment_broker()
    for index, spec in enumerate(selected, 1):
        name = f"sabakan-eval-{os.getpid()}-{index}"
        model_record: dict[str, Any] = {
            "model": spec["label"],
            "repo": spec["repo"],
            "path": str(Path(spec["path"]).resolve().relative_to(ROOT)),
            "status": "error",
            "results": [],
        }
        print(f"[{spec['label']}] starting CUDA server", flush=True)
        try:
            load_seconds, models_response = start_server(spec, args, name)
            model_record.update(load_info(models_response, load_seconds, args.docker_image))
            model_record["status"] = "ok"
            print(f"[{spec['label']}] ready in {load_seconds:.1f}s", flush=True)
            for fixture_index, fixture in enumerate(fixtures, 1):
                output, prompt_tokens, completion_tokens, elapsed, response_info = generate(
                    base_url, build_prompt(fixture), MODEL_TOOL_SCHEMAS, args.max_tokens, args.request_timeout
                )
                result = evaluate_output(
                    output,
                    fixture,
                    prompt_tokens,
                    completion_tokens,
                    elapsed,
                    model=spec["label"],
                    response_info=response_info,
                    assessor=assessor,
                )
                result["response"] = response_info
                model_record["results"].append(result)
                print(
                    f"[{spec['label']}] {fixture_index}/{len(fixtures)} {fixture['id']}: "
                    f"diagnosis={result['diagnosis_accuracy']} broker={result['broker_acceptance']} "
                    f"unsafe={result['unsafe_proposal_rate']} "
                    f"tokens={completion_tokens} time={elapsed:.1f}s",
                    flush=True,
                )
            model_record["metrics"] = aggregate(model_record["results"])
        except Exception as exc:
            model_record["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[{spec['label']}] ERROR {model_record['error']}", flush=True)
        finally:
            stop_server(name)
            report["models"].append(model_record)
            write_report(args.output, report)
            print(f"[{spec['label']}] unloaded; intermediate report written", flush=True)

    print(f"wrote {args.output}")
    return 0 if any(item.get("status") == "ok" for item in report["models"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
