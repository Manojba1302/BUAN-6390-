"""Worker settings, read once."""
from __future__ import annotations

import os
from pathlib import Path
from embedding_config import MODEL as EMBEDDING_MODEL


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
    embed_model = EMBEDDING_MODEL

    markdown_dir = Path(os.getenv("MARKDOWN_DIR", "/srv/markdown"))
    chunk_chars = int(os.getenv("CHUNK_CHARS", "1200"))
    chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "150"))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "3"))

    # How long Ollama keeps the document model loaded after a call. Keeping it for a few
    # minutes avoids reloading it for every page; "0" unloads immediately (old behaviour).
    model_keep_alive = (lambda v: 0 if v.strip() == "0" else v)(os.getenv("MODEL_KEEP_ALIVE", "2m"))


config = Config()

