#!/usr/bin/env python3
"""Run disposable Docker fixtures through the real Sabakan Broker path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from evaluation.docker_fixtures import BUSYBOX_IMAGE, run_docker_fixtures  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "fixture-results-v2.json")
    parser.add_argument("--image", default=BUSYBOX_IMAGE)
    args = parser.parse_args()
    report = run_docker_fixtures(args.output, image=args.image)
    print(f"wrote {args.output} incident_resolution_rate={report['incident_resolution_rate']}")
    return 0 if report["incident_resolution_rate"] == 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
