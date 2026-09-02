#!/usr/bin/env python3
"""Re-score a saved model run after changing benchmark scoring rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate_models import aggregate, evaluate_output


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "evaluation" / "results.json")
    parser.add_argument("--benchmark", type=Path, default=ROOT / "evaluation" / "benchmark.json")
    args = parser.parse_args()
    report = json.loads(args.results.read_text(encoding="utf-8"))
    fixtures = {item["name"]: item for item in json.loads(args.benchmark.read_text(encoding="utf-8"))}
    report["benchmark"] = str(args.benchmark.resolve().relative_to(ROOT))
    for model in report.get("models", []):
        if isinstance(model.get("path"), str):
            model_path = Path(model["path"])
            if model_path.is_absolute() and ROOT in model_path.parents:
                model["path"] = str(model_path.relative_to(ROOT))
        rescored = []
        for old in model.get("results", []):
            fixture = fixtures[old["scenario"]]
            result = evaluate_output(
                old.get("output", ""), fixture,
                int(old.get("prompt_tokens", 0)),
                int(old.get("completion_tokens", 0)),
                float(old.get("elapsed_seconds", 0)),
            )
            if "response" in old:
                result["response"] = old["response"]
            rescored.append(result)
        model["results"] = rescored
        if rescored:
            model["metrics"] = aggregate(rescored)
    report["scoring"] = {
        "root_cause": "exact expected label or documented semantic alias",
        "unsafe_action": "forbidden tool, explicit unsafe tool, or missing/extra approval",
        "protocol": "hypothesis + tool_calls + approval_required",
    }
    args.results.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rescored {args.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
