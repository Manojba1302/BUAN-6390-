"""Object storage. One flat bucket, a unique key per file, no folders."""
import hashlib
import logging
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings

log = logging.getLogger(__name__)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> None:
    """Called once at start-up. Safe to run repeatedly."""
    s3 = _client()
    try:
        s3.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        s3.create_bucket(Bucket=settings.s3_bucket)
        log.info("created bucket %s", settings.s3_bucket)


def storage_key(file_id: UUID, original_name: str) -> str:
    """Flat key. The extension is kept only so downloads open cleanly."""
    suffix = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
    return f"{file_id}.{suffix}"


def put_object(key: str, body: bytes, content_type: str | None) -> None:
    _client().put_object(
        Bucket=settings.s3_bucket, Key=key, Body=body,
        ContentType=content_type or "application/octet-stream",
    )


def get_object(key: str) -> bytes:
    return _client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def checksum(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()
