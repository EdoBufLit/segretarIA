import logging
import sys
# import structlog
from contextvars import ContextVar

# Context var for Correlation ID
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

def configure_logging():
    """
    Configures standard logging with specific format for diagnosis.
    """
    # Remove existing handlers to avoid duplication if re-configured
    root_logger = logging.getLogger()
    if root_logger.handlers:
        for handler in root_logger.handlers:
            root_logger.removeHandler(handler)

    logging.basicConfig(
        format='[%(asctime)s] STEP: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.INFO,
        force=True
    )

    # Suppress uvicorn access logs duplicate if needed
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

def get_logger(name):
    # return structlog.get_logger(name)
    return logging.getLogger(name)
