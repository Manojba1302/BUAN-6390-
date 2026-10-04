"""Worker settings, read once."""
from __future__ import annotations

import os
from pathlib import Path


class Config:
    database_url = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://homeflow:homeflow@localhost:5432/homeflow")
    rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://homeflow:homeflow@localhost:5672/")
    queue_name = os.getenv("EXTRACTION_QUEUE", "document.extract")

    s3_endpoint = os.getenv("S3_ENDPOINT", "http://localhost:9000")
    s3_bucket = os.getenv("S3_BUCKET", "documents")
    s3_access_key = os.getenv("S3_ACCESS_KEY", "homeflow")
    s3_secret_key = os.getenv("S3_SECRET_KEY", "homeflow123")
    s3_region = os.getenv("S3_REGION", "us-east-1")

    classifier_model = os.getenv("CLASSIFIER_MODEL", "gemma3:4b")
    extractor_model = os.getenv("EXTRACTOR_MODEL", "llama3.1:8b")
    vision_model = os.getenv("VISION_MODEL", "gemma3:4b")
    embed_model = os.getenv("EMBED_MODEL", "nomic-embed-text")

    markdown_dir = Path(os.getenv("MARKDOWN_DIR", "/srv/markdown"))
    chunk_chars = int(os.getenv("CHUNK_CHARS", "1200"))
    chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "150"))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))


config = Config()

