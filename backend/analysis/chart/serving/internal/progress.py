"""Immediate, credential-free serving stage timings for Actions logs."""

import json
import time
from contextlib import contextmanager


def report(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


@contextmanager
def stage(name, **fields):
    started = time.perf_counter()
    report("stage_start", stage=name, **fields)
    try:
        yield
    except Exception as exc:
        report("stage_failed", stage=name, seconds=round(time.perf_counter() - started, 3),
               error_type=type(exc).__name__, **fields)
        raise
    else:
        report("stage_complete", stage=name, seconds=round(time.perf_counter() - started, 3), **fields)
