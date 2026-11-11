"""Queue consumer.

One message is one file. The work is idempotent: running it twice replaces
proposals and leaves corrections alone, so a retry is always safe.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
import pika
from botocore.client import Config as BotoConfig

import pages

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
    """Every file is read, identified and made searchable. Fields are pulled out only
    once the file is attached to an application, from the text kept at the first read."""
    file_id = job["file_id"]
    record = _claim(file_id)
    if record is None:
        return
    if job.get("mode") == "extract":
        document, outcome, chunks = _stored_document(file_id, record), "attached", None
    else:
        document, outcome, chunks = _read_and_index(file_id, record, auto=job.get("mode") == "auto")
    fields = _extract_if_attached(file_id, document, outcome)
    _finish(file_id, record, len(document["pages"]), outcome, len(fields), chunks)
    log.info("file %s: done (%s, %s fields)", file_id, outcome, len(fields))


def _read_and_index(file_id: str, record: dict, auto: bool = False) -> tuple[dict, str, int]:
    """Read, identify, index for search, and keep the page text for a later extraction."""
    document = _read_document(file_id, record)
    classification = _classify(file_id, document, record)
    record = _adopt_type(file_id, record, classification) if auto else _settle_type(file_id, record, classification)
    md_path, markdown = _write_markdown(file_id, document, record, {})
    chunks = pipeline.embed_chunks(pipeline.chunk(document))
    _keep_pages(file_id, document)
    with db.session() as conn:
        db.clear_extractions(conn, file_id)
        db.save_markdown(conn, file_id, str(md_path), len(markdown))
        db.replace_chunks(conn, file_id, str(record["customer_id"]), chunks)
    _check_index(file_id, document, chunks)
    return document, classification["outcome"], len(chunks)


def _settle_type(file_id: str, record: dict, classification: dict) -> dict:
    """A mismatch never blocks the upload, in the vault or in an application: the file is kept as
    Other and the type we saw stays on the classification as a suggestion the customer can accept.
    So a W-2 is never read as a pay stub, nor counted as one."""
    if classification["outcome"] != "mismatched" or record["document_tag"] == "other":
        return record
    with db.session() as conn:
        db.set_tag(conn, file_id, "other")
    log.info("file %s: saved as other (chosen %s)", file_id, record["document_tag"])
    return record | {"document_tag": "other"}


# Where a loan document goes when the customer added it without choosing a type or folder.
TAG_FOLDER = {"drivers_license": "Identification & Licenses", "ssn_card": "Identification & Licenses",
              "paystub": "Finances", "bank_statement": "Finances", "w2": "Taxes"}


def _adopt_type(file_id: str, record: dict, classification: dict) -> dict:
    """Added without a type: a loan document we recognise takes its own type and folder.
    Anything we cannot name, or a file holding several documents, stays Other."""
    found = classification["detected"]
    if record["document_tag"] != "other" or found not in TAG_FOLDER or classification.get("mixed"):
        return record
    with db.session() as conn:
        db.set_tag(conn, file_id, found)
        db.set_path(conn, file_id, "/" + TAG_FOLDER[found])
    log.info("file %s: recognised as %s", file_id, found)
    return record | {"document_tag": found}


def _extract_if_attached(file_id: str, document: dict, outcome: str) -> dict:
    """Checked again here, after the slow read, so a file attached meanwhile is not missed."""
    with db.session() as conn:
        record = db.fetch_file(conn, file_id)
    if not record or not record["application_id"] or record["document_tag"] == "other" \
            or outcome not in ("matched", "mismatched", "attached"):
        return {}                     # Other has no fields; its type can be changed and read later
    fields = _extract_fields(file_id, document, record)
    md_path, markdown = _write_markdown(file_id, document, record, fields)
    with db.session() as conn:
        db.clear_extractions(conn, file_id)
        for name, payload in fields.items():
            db.save_extraction(conn, file_id, name, payload, _model_for(payload))
        db.save_markdown(conn, file_id, str(md_path), len(markdown))
        db.audit(conn, "document.fields_extracted", customer_id=str(record["customer_id"]),
                 file_id=file_id, payload={"document_tag": record["document_tag"], "fields": len(fields)})
    return fields


def _finish(file_id: str, record: dict, pages: int, outcome: str, fields: int, chunks: int | None) -> None:
    with db.session() as conn:
        db.set_status(conn, file_id, "completed", pages=pages)
        db.audit(conn, "document.processed", customer_id=str(record["customer_id"]),
                 application_id=str(record["application_id"]) if record["application_id"] else None,
                 file_id=file_id, payload={"fields": fields, "chunks": chunks, "outcome": outcome})


def _pages_path(file_id: str):
    return config.markdown_dir / f"{file_id}.pages.json"


def _keep_pages(file_id: str, document: dict) -> None:
    """The slow part of a read is OCR; keeping its text means attaching never OCRs again."""
    kept = [{key: page.get(key) for key in ("text", "model_text", "method", "ocr_confidence")}
            for page in document["pages"]]
    config.markdown_dir.mkdir(parents=True, exist_ok=True)
    _pages_path(file_id).write_text(json.dumps(kept), encoding="utf-8")


def _stored_document(file_id: str, record: dict) -> dict:
    """Page images are rendered again (cheap); the text comes from the first read."""
    path = _pages_path(file_id)
    if not path.exists():
        return _read_document(file_id, record)
    body = _s3().get_object(Bucket=config.s3_bucket, Key=record["storage_key"])["Body"].read()
    document = pages.read_document(body, record["content_type"], record["original_name"])
    for page, kept in zip(document["pages"], json.loads(path.read_text(encoding="utf-8"))):
        page.update({key: value for key, value in kept.items() if value is not None})
    return document


def _claim(file_id: str) -> dict | None:
    """Mark the file as processing. None means drop the job (gone or retried too often)."""
    with db.session() as conn:
        record = db.fetch_file(conn, file_id)
        if record is None:
            log.warning("file %s is gone, dropping the job", file_id)
            return None
        if record.get("status") == "completed":
            log.info("file %s already completed, dropping duplicate job", file_id)
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


def _extract_fields(file_id: str, document: dict, record: dict) -> dict:
    """The customer's type picks the schema. Only the five loan documents have one."""
    fields = pipeline.extract(document, record["document_tag"])
    _validate_extraction(record["document_tag"], fields)
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


def on_message(channel, method, _properties, body) -> None:
    try:
        job = json.loads(body)
    except json.JSONDecodeError:
        log.error("message is not JSON, dropping it")
        channel.basic_ack(method.delivery_tag)
        return

    try:
        _handle_with_heartbeats(channel, job)
        channel.basic_ack(method.delivery_tag)
    except Exception as exc:
        log.exception("job failed: %s", exc)
        try:
            with db.session() as conn:
                db.set_status(conn, job.get("file_id"), "failed", error="Document processing failed. Please retry.")
        except Exception:
            log.exception("could not record the failure")
        channel.basic_ack(method.delivery_tag)     # the row says failed; no poison loop



def _handle_with_heartbeats(channel, job):
    """Keep Pika I/O on its owning thread during blocking model calls."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(handle, job)
        while not future.done():
            channel.connection.process_data_events(time_limit=1)
        future.result()


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



def _validate_extraction(tag, fields):
    """A recognized W-2 must yield usable identity and wage evidence."""
    if tag != "w2":
        return
    required = ("employee_name", "employer_name", "box1_wages")
    missing = [key for key in required if not str((fields.get(key) or {}).get("value") or "").strip()]
    if missing:
        raise RuntimeError("Incomplete W-2 extraction; could not read: " + ", ".join(missing) + ". Retry reading or upload a clearer document.")




def _check_index(file_id: str, document: dict, chunks: list[dict]) -> None:
    """Only a file with nothing to read at all fails. A photo with little printed text is still
    read from its image, and a file whose search index fell short stays usable: the API shows it
    as not searchable yet and offers Retry reading."""
    if not chunks and not any(page.get("image") for page in document["pages"]):
        raise RuntimeError("File saved, but no readable text was found. Retry with a clearer document.")
    missing = sum(1 for chunk in chunks if not chunk.get("embedding"))
    if missing:
        log.warning("file %s: %s of %s chunks not indexed for search", file_id, missing, len(chunks))


if __name__ == "__main__":
    main()
