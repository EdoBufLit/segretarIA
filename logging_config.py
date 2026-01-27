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
    logging.basicConfig(
        format='[%(asctime)s] STEP: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.INFO,
        force=True
    )

    # Suppress uvicorn access logs duplicate if needed, though basicConfig might catch them
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

def get_logger(name):
    # return structlog.get_logger(name)
    return logging.getLogger(name)
