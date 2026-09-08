"""External timed recovery of a disposable HTTP dependency, independent of reads."""
import math
import threading
import time

from evaluation.http_fixtures import HttpFixture, docker


class DelayedDependencyRecovery:
    def __init__(self, fixture, delay_seconds):
        if not isinstance(fixture, HttpFixture) or fixture.case.fault != 'dependency_down':
            raise ValueError('dependency-down HTTP fixture required')
        if type(delay_seconds) not in (int, float) or not math.isfinite(delay_seconds) or not 0 <= delay_seconds <= 180:
            raise ValueError('delay must be finite and between 0 and 180 seconds')
        self.fixture = fixture
        self.delay = delay_seconds
        self.cancel = threading.Event()
        self.thread = None
        self.record = {'attribution': 'external fixture controller, not model or Broker',
                       'delay_seconds': delay_seconds, 'status': 'not_started'}

    def start(self):
        if self.thread is not None:
            raise RuntimeError('controller already started')
        self.record.update(status='waiting', started_monotonic=time.monotonic())
        self.thread = threading.Thread(target=self._run, name='sabakan-delayed-recovery', daemon=True)
        self.thread.start()

    def _run(self):
        if self.cancel.wait(self.delay):
            self.record['status'] = 'cancelled'
            return
        self.record.update(status='starting_dependency', trigger_monotonic=time.monotonic())
        try:
            # Container start is the fault controller's action. HTTP health is
            # established separately by the observer, never by this return code.
            docker('start', self.fixture.backend)
        except Exception as exc:
            self.record.update(status='error', error_type=type(exc).__name__)
        else:
            self.record['status'] = 'container_started'
        finally:
            self.record['finished_monotonic'] = time.monotonic()

    def close(self):
        self.cancel.set()
        if self.thread is not None:
            self.thread.join(timeout=16)
            if self.thread.is_alive():
                raise RuntimeError('controller still active; do not remove its fixture yet')
