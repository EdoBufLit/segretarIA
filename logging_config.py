import logging
import os
import sys
# import structlog
from contextvars import ContextVar

# Context var for Correlation ID
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

def configure_logging():
    """
    Configures standard logging with specific format for diagnosis.
    """
    root_logger = logging.getLogger()
    has_capture_handler = any(handler.__class__.__name__ == "LogCaptureHandler" for handler in root_logger.handlers)
    is_pytest = bool(os.getenv("PYTEST_CURRENT_TEST")) or has_capture_handler
    if not is_pytest:
        # Remove existing handlers to avoid duplication if re-configured
        if root_logger.handlers:
            for handler in root_logger.handlers:
                root_logger.removeHandler(handler)

    logging.basicConfig(
        format='[%(asctime)s] STEP: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.INFO,
        force=not is_pytest
    )

    # Suppress uvicorn access logs duplicate if needed
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

def get_logger(name):
    # return structlog.get_logger(name)
    return logging.getLogger(name)
