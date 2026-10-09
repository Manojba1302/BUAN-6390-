"""Queue consumer.

One message is one file. The work is idempotent: running it twice replaces
proposals and leaves corrections alone, so a retry is always safe.
"""
from __future__ import annotations

import json
import logging
import time

import boto3
import pika
from botocore.client import Config as BotoConfig

from worker import db, pipeline
from worker.config import config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s worker %(message)s")
log = logging.getLogger(__name__)


def _s3():
    return boto3.client(
        "s3", endpoint_url=config.s3_endpoint,
        aws_access_key_id=config.s3_access_key,
        aws_secret_access_key=config.s3_secret_key,
        region_name=config.s3_region, config=BotoConfig(signature_version="s3v4"))


def handle(job: dict) -> None:
    """Process one file: read, classify, extract, write markdown, embed, save."""
    file_id = job["file_id"]
    record = _claim(file_id)
    if record is None:
        return
    document = _read_document(file_id, record)
    classification = _classify(file_id, document, record)
    fields = _extract_fields(file_id, document, record, classification)
    md_path, markdown = _write_markdown(file_id, document, record, fields)
    chunks = pipeline.embed_chunks(pipeline.chunk(document))
    _save_results(file_id, record, document, classification, fields, md_path, markdown, chunks)
    log.info("file %s: done, %s chunks embedded", file_id, len(chunks))


def _claim(file_id: str) -> dict | None:
    """Mark the file as processing. None means drop the job (gone or retried too often)."""
    with db.session() as conn:
        record = db.fetch_file(conn, file_id)
        if record is None:
            log.warning("file %s is gone, dropping the job", file_id)
            return None
        attempts = db.bump_attempts(conn, file_id)
        db.set_status(conn, file_id, "processing")
    if attempts > config.max_attempts:
        with db.session() as conn:
            db.set_status(conn, file_id, "failed", error="Too many attempts")
        return None
    return record


def _read_document(file_id: str, record: dict) -> dict:
    body = _s3().get_object(Bucket=config.s3_bucket, Key=record["storage_key"])["Body"].read()
    document = pipeline.read(body, record["content_type"], record["original_name"])
    log.info("file %s: %s pages read", file_id, len(document["pages"]))
    return document


def _classify(file_id: str, document: dict, record: dict) -> dict:
    classification = pipeline.classify(document, record["document_tag"])
    with db.session() as conn:
        db.save_classification(conn, file_id, classification)
    log.info("file %s: classified %s (%s)", file_id,
             classification["detected"], classification["outcome"])
    return classification


def _extract_fields(file_id: str, document: dict, record: dict, classification: dict) -> dict:
    """Only a recognised document is extracted. The customer's tag picks the schema; they confirmed it."""
    if classification["outcome"] not in ("matched", "mismatched"):
        return {}
    fields = pipeline.extract(document, record["document_tag"])
    log.info("file %s: %s fields extracted", file_id, len(fields))
    return fields


def _write_markdown(file_id: str, document: dict, record: dict, fields: dict):
    markdown = pipeline.to_markdown(document, file_name=record["original_name"],
                                    document_tag=record["document_tag"], fields=fields)
    config.markdown_dir.mkdir(parents=True, exist_ok=True)
    md_path = config.markdown_dir / f"{file_id}.md"
    md_path.write_text(markdown, encoding="utf-8")
    return md_path, markdown


def _model_for(payload: dict) -> str:
    return config.vision_model if payload["method"] == "vision" else config.extractor_model


def _save_results(file_id, record, document, classification, fields, md_path, markdown, chunks) -> None:
    """Everything the job produced, saved in one transaction."""
    with db.session() as conn:
        db.clear_extractions(conn, file_id)
        for name, payload in fields.items():
            db.save_extraction(conn, file_id, name, payload, _model_for(payload))
        db.save_markdown(conn, file_id, str(md_path), len(markdown))
        db.replace_chunks(conn, file_id, str(record["customer_id"]), chunks)
        db.set_status(conn, file_id, "completed", pages=len(document["pages"]))
        db.audit(conn, "document.processed", customer_id=str(record["customer_id"]),
                 application_id=str(record["application_id"]) if record["application_id"] else None,
                 file_id=file_id,
                 payload={"fields": len(fields), "chunks": len(chunks),
                          "outcome": classification["outcome"]})


def on_message(channel, method, _properties, body) -> None:
    try:
        job = json.loads(body)
    except json.JSONDecodeError:
        log.error("message is not JSON, dropping it")
        channel.basic_ack(method.delivery_tag)
        return

    try:
        handle(job)
        channel.basic_ack(method.delivery_tag)
    except Exception as exc:
        log.exception("job failed: %s", exc)
        try:
            with db.session() as conn:
                db.set_status(conn, job.get("file_id"), "failed", error=str(exc)[:500])
        except Exception:
            log.exception("could not record the failure")
        channel.basic_ack(method.delivery_tag)     # the row says failed; no poison loop


def main() -> None:
    while True:
        try:
            conn = pika.BlockingConnection(pika.URLParameters(config.rabbitmq_url))
            channel = conn.channel()
            channel.queue_declare(queue=config.queue_name, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=config.queue_name, on_message_callback=on_message)
            log.info("waiting for jobs on %s", config.queue_name)
            channel.start_consuming()
        except pika.exceptions.AMQPError as exc:
            log.warning("queue connection lost (%s), retrying in 5s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
