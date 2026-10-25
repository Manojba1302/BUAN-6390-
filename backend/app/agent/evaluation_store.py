"""Bounded best-effort background writer to a separate private object bucket."""
import json
import logging
from queue import Queue, Full
from threading import Thread, Lock
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from app.core.config import settings
from app.agent.evaluation_schema import Record

log = logging.getLogger(__name__)
PENDING = Queue(maxsize=256)
LOCK = Lock()
WORKER = None


def publish(record):
    if not settings.chat_evaluation_enabled:
        return
    try:
        _start()
        PENDING.put_nowait(record)
    except Full:
        log.warning("chat_evaluation_dropped reason=queue_full")
    except Exception:
        log.warning("chat_evaluation_dropped reason=writer_unavailable")


def _start():
    global WORKER
    with LOCK:
        if WORKER is None or not WORKER.is_alive():
            WORKER = Thread(target=_consume, name="chat-evaluation-writer", daemon=True)
            WORKER.start()


def _consume():
    while True:
        record = PENDING.get()
        try:
            write(record)
        except Exception:
            log.warning("chat_evaluation_write_failed request_id=%s",record["request_id"])
        finally:
            PENDING.task_done()


def _client():
    return boto3.client("s3",endpoint_url=settings.s3_endpoint,aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,region_name=settings.s3_region,
        config=Config(signature_version="s3v4",connect_timeout=1,read_timeout=2,retries={"max_attempts":0}))


def ensure_bucket(client):
    bucket = settings.chat_evaluation_bucket
    if bucket == settings.s3_bucket:
        raise ValueError("Evaluation bucket must be separate from documents")
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if str(exc.response.get("Error",{}).get("Code")) not in {"404","NoSuchBucket","NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)
        days = max(1, settings.chat_evaluation_retention_days)
        client.put_bucket_lifecycle_configuration(Bucket=bucket,LifecycleConfiguration={"Rules":[{"ID":"chat-evaluation-retention","Status":"Enabled","Filter":{"Prefix":"chat/"},"Expiration":{"Days":days}}]})


def write(record):
    record = Record.model_validate(record).model_dump(mode="json")
    client = _client()
    ensure_bucket(client)
    _check_private(client)
    day = record["created_at"][:10]
    key = f"chat/date={day}/{record['request_id']}.json"
    client.put_object(Bucket=settings.chat_evaluation_bucket,Key=key,Body=json.dumps(record,allow_nan=False).encode(),ContentType="application/json")


def _check_private(client):
    try:
        policy = json.loads(client.get_bucket_policy(Bucket=settings.chat_evaluation_bucket)["Policy"])
    except ClientError as exc:
        if exc.response.get("Error",{}).get("Code") == "NoSuchBucketPolicy":
            return
        raise
    for statement in policy.get("Statement",[]):
        principal = statement.get("Principal")
        if statement.get("Effect") == "Allow" and '"*"' in json.dumps(principal):
            raise ValueError("Anonymous evaluation bucket access is not allowed")
