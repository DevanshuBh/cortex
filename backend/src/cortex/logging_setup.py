"""Structured JSON logs (one object per line) with the tenant and task attached when known."""

from __future__ import annotations

import logging
import sys

import structlog

from cortex.config import get_settings


def configure_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=shared,
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "neo4j", "urllib3", "botocore", "sentence_transformers", "celery.redirected"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
