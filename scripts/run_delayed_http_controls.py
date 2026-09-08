#!/usr/bin/env python3
"""Fixed early and settled HTTP windows for external timed recovery controls."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from evaluation.http_fixtures import HttpFixture, HttpCase
from evaluation.delayed_recovery import DelayedDependencyRecovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = {'protocol': 'sabakan-delayed-http-two-window-control-v1',
              'fidelity': 'Real timed external dependency start, no model or Broker',
              'delay_seconds': 5, 'between_windows_seconds': 2, 'trials': []}
    image = 'python@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a'
    for mode in ('delayed', 'no_progress'):
        with tempfile.TemporaryDirectory(prefix='sabakan-delay-') as root:
            fixture = HttpFixture(HttpCase('dependency_down'), root,
                                  f'sabakan-http-delay-{os.getpid()}-{mode}', image)
            controller = None
            trial = {'mode': mode}
            try:
                trial['initial'] = fixture.setup()
                if mode == 'delayed':
                    controller = DelayedDependencyRecovery(fixture, 5)
                    controller.start()
                    controller.thread.join(timeout=21)
                    controller.close()
                    trial['controller'] = controller.record
                else:
                    time.sleep(5)
                trial['early_window'] = fixture.postcheck()
                time.sleep(2)
                trial['settled_window'] = fixture.postcheck()
                trial['final'] = fixture.snapshot()
                trial['passed'] = (trial['initial']['http']['ok'] is False
                    and trial['settled_window']['ok'] == (mode == 'delayed'))
            except Exception as exc:
                trial.update(error_type=type(exc).__name__, passed=False)
            finally:
                if controller:
                    controller.close()
                trial['cleanup'] = fixture.cleanup()
            report['trials'].append(trial)
            print(mode, trial['passed'], flush=True)
    report['passed'] = all(t['passed'] and t['cleanup']['complete'] for t in report['trials'])
    with args.output.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
