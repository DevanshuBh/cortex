"""Celery application (guide step 4.5).

- ``acks_late`` + ``task_reject_on_worker_lost``: a task whose worker dies is redelivered, never lost.
- ``worker_prefetch_multiplier = 1``: one worker process never reserves several long tasks.
- Redis ``visibility_timeout`` above every hard time limit, so a slow task is not redelivered while running.
  ``visibility_timeout`` only applies to the Redis and SQS brokers; this deployment uses Redis (docs/adr/0007).
- Separate queues so a long ingestion backlog never delays questions.
"""

from __future__ import annotations

import logging
import os

from celery import Celery
from celery.signals import worker_init, worker_process_init

from cortex.config import get_settings

s = get_settings()

app = Celery("cortex", broker=s.broker_url, include=["cortex.worker.tasks"])
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_transport_options={"visibility_timeout": s.celery_visibility_timeout},
    broker_connection_retry_on_startup=True,
    task_default_queue="ask",
    task_routes={
        "cortex.ingest": {"queue": "ingest"},
        "cortex.extract": {"queue": "ingest"},
        "cortex.delete_document": {"queue": "ingest"},
        "cortex.ask": {"queue": "ask"},
    },
    task_serializer="json",
    accept_content=["json"],
    worker_send_task_events=False,
    worker_hijack_root_logger=False,
)

_hard_limits = (s.ask_time_limit, s.ingest_time_limit, s.extract_time_limit)
if s.celery_visibility_timeout <= max(_hard_limits):
    raise RuntimeError(
        f"visibility_timeout ({s.celery_visibility_timeout}s) must exceed the longest hard time limit "
        f"({max(_hard_limits)}s), or running tasks will be redelivered"
    )


@worker_init.connect
def _start_metrics(**_: object) -> None:
    """Expose worker metrics. In prefork mode children write to PROMETHEUS_MULTIPROC_DIR; the parent serves."""
    from prometheus_client import CollectorRegistry, start_http_server

    registry = None
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    try:
        start_http_server(s.worker_metrics_port, registry=registry) if registry else start_http_server(
            s.worker_metrics_port
        )
    except OSError:
        logging.getLogger(__name__).warning("metrics port %d in use; not serving", s.worker_metrics_port)


@worker_process_init.connect
def _init_process(**_: object) -> None:
    from cortex.logging_setup import configure_logging
    from cortex.observability.tracing import setup_tracing

    configure_logging()
    setup_tracing("worker")
