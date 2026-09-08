"""Wall-clock spans without recording callback inputs, outputs or credentials."""
from contextlib import contextmanager
from functools import wraps
import time


class TrialTiming:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.origin = clock()
        self.events = []

    @contextmanager
    def span(self, phase):
        start = self.clock()
        event = {'phase': phase, 'start_offset_seconds': start - self.origin,
                 'completed': False}
        self.events.append(event)
        try:
            yield
        except BaseException as exc:
            event['error_type'] = type(exc).__name__
            raise
        else:
            event['completed'] = True
        finally:
            event['elapsed_seconds'] = self.clock() - start

    def wrap(self, phase, callback):
        @wraps(callback)
        def measured(*args, **kwargs):
            with self.span(phase):
                return callback(*args, **kwargs)
        return measured
