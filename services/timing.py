import time
import logging
from contextlib import contextmanager

@contextmanager
def log_duration(description: str):
    """
    Context manager to measure and log the duration of a block of code.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        t1 = time.perf_counter()
        duration_ms = (t1 - t0) * 1000
        lag = " (LAG!)" if duration_ms > 500 else ""
        logging.info(f"{description} | duration: {duration_ms:.0f}ms{lag}")
