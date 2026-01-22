import logging
import sys
import structlog
from contextvars import ContextVar

# Context var for Correlation ID
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

def configure_logging():
    """
    Configures structured logging with structlog and standard logging.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=shared_processors + [
            structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure Standard Library Logging
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Suppress uvicorn access logs duplicate
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

def get_logger(name):
    return structlog.get_logger(name)
