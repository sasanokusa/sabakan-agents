#!/usr/bin/env python3
"""Re-score a saved model run after changing benchmark scoring rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate_models import aggregate, evaluate_output, read_benchmark


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "evaluation" / "results.json")
    parser.add_argument("--benchmark", type=Path, default=ROOT / "evaluation" / "benchmark.json")
    args = parser.parse_args()
    report = json.loads(args.results.read_text(encoding="utf-8"))
    fixtures_list = read_benchmark(args.benchmark)
    fixtures = {item["id"]: item for item in fixtures_list}
    fixtures_by_name = {item.get("fixture"): item for item in fixtures_list}
    report["benchmark"] = str(args.benchmark.resolve().relative_to(ROOT))
    for model in report.get("models", []):
        if isinstance(model.get("path"), str):
            model_path = Path(model["path"])
            if model_path.is_absolute() and ROOT in model_path.parents:
                model["path"] = str(model_path.relative_to(ROOT))
        rescored = []
        for old in model.get("results", []):
            fixture = fixtures.get(old.get("incident_id")) or fixtures_by_name.get(old.get("scenario"))
            if fixture is None:
                raise ValueError(f"no benchmark fixture for saved result {old.get('incident_id') or old.get('scenario')!r}")
            result = evaluate_output(
                old.get("output", ""), fixture,
                int(old.get("prompt_tokens", 0)),
                int(old.get("completion_tokens", 0)),
                float(old.get("elapsed_seconds", 0)),
                model=str(model.get("model", "unknown")),
                response_info=old.get("response") if isinstance(old.get("response"), dict) else None,
            )
            if "response" in old:
                result["response"] = old["response"]
            rescored.append(result)
        model["results"] = rescored
        if rescored:
            model["metrics"] = aggregate(rescored)
    report["scoring"] = {
        "root_cause": "exact expected label or documented semantic alias",
        "unsafe_action": "forbidden or explicit unsafe proposal",
        "protocol": "raw output adapter -> hypothesis + tool_calls -> Broker schema/policy",
        "approval": "determined by Broker policy; model field is diagnostic only",
    }
    args.results.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rescored {args.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
