"""Publishing to the extraction queue.

The message carries exactly what the worker needs to find the file and
nothing the worker could get wrong by trusting it.
"""
import json
import logging
from uuid import UUID

import pika

from app.core.config import settings

log = logging.getLogger(__name__)


def _connection() -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))


def publish_extraction_job(
    *, customer_id: UUID, application_id: UUID | None, file_id: UUID,
    document_tag: str, trace_id: str, mode: str = "read",
) -> None:
    """Durable publish. A failure here leaves the file queued for retry.
    mode "read" reads and identifies the file; "extract" pulls fields from the text kept at that read."""
    body = _message_body(customer_id, application_id, file_id, document_tag, trace_id, mode)
    conn = _connection()
    try:
        channel = conn.channel()
        channel.queue_declare(queue=settings.extraction_queue, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=settings.extraction_queue,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        log.info("queued file %s (%s, %s)", file_id, document_tag, mode)
    finally:
        conn.close()


def _message_body(customer_id: UUID, application_id: UUID | None, file_id: UUID,
                  document_tag: str, trace_id: str, mode: str = "read") -> bytes:
    return json.dumps({
        "customer_id": str(customer_id),
        "application_id": str(application_id) if application_id else None,
        "file_id": str(file_id),
        "document_tag": document_tag,
        "trace_id": trace_id,
        "mode": mode,
    }).encode()
