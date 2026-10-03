"""Database access for the worker.

Deliberately raw SQL rather than a second copy of the API's ORM models: one
schema, one place it is defined, and no two model files to drift apart.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, text

from worker.config import config

engine = create_engine(config.database_url, pool_pre_ping=True, future=True)


@contextmanager
def session():
    with engine.begin() as conn:
        yield conn


def fetch_file(conn, file_id: str) -> dict | None:
    row = conn.execute(text("""
        SELECT file_id, customer_id, application_id, document_tag, original_name,
               content_type, storage_key, status, attempts
        FROM file WHERE file_id = CAST(:id AS uuid)
    """), {"id": file_id}).mappings().first()
    return dict(row) if row else None


def set_status(conn, file_id: str, status: str, *, error: str | None = None,
               pages: int | None = None) -> None:
    conn.execute(text("""
        UPDATE file
           SET status = :status,
               error_detail = :error,
               page_count = COALESCE(:pages, page_count),
               processed_at = CASE WHEN :status IN ('completed','failed') THEN now() ELSE processed_at END
         WHERE file_id = CAST(:id AS uuid)
    """), {"id": file_id, "status": status, "error": error, "pages": pages})


def bump_attempts(conn, file_id: str) -> int:
    return conn.execute(text("""
        UPDATE file SET attempts = attempts + 1
         WHERE file_id = CAST(:id AS uuid)
        RETURNING attempts
    """), {"id": file_id}).scalar_one()


def save_classification(conn, file_id: str, result: dict) -> None:
    conn.execute(text("""
        INSERT INTO file_classification
            (file_id, selected_type, detected_type, outcome, evidence,
             mixed_document, model_name)
        VALUES (CAST(:id AS uuid), :selected, :detected, :outcome,
                CAST(:evidence AS jsonb), :mixed, :model)
        ON CONFLICT (file_id) DO UPDATE SET
            detected_type = EXCLUDED.detected_type,
            outcome       = EXCLUDED.outcome,
            evidence      = EXCLUDED.evidence,
            mixed_document= EXCLUDED.mixed_document,
            model_name    = EXCLUDED.model_name,
            classified_at = now()
    """), result | {"id": file_id})


def clear_extractions(conn, file_id: str) -> None:
    """Reprocessing replaces proposals but never a correction the customer made."""
    conn.execute(text("""
        DELETE FROM extraction
         WHERE file_id = CAST(:id AS uuid) AND review_state = 'proposed'
    """), {"id": file_id})


def save_extraction(conn, file_id: str, field: str, payload: dict, model: str) -> None:
    conn.execute(text("""
        INSERT INTO extraction
            (file_id, field_name, value_raw, value_normalized, page,
             evidence_quote, method, model_name)
        VALUES (CAST(:id AS uuid), :field, :raw, :norm, :page, :quote, :method, :model)
    """), {"id": file_id, "field": field, "raw": payload.get("value"),
           "norm": payload.get("normalized"), "page": payload.get("page"),
           "quote": payload.get("quote"), "method": payload.get("method"),
           "model": model})


def save_markdown(conn, file_id: str, path: str, char_count: int) -> None:
    conn.execute(text("""
        INSERT INTO document_markdown (file_id, markdown_path, char_count)
        VALUES (CAST(:id AS uuid), :path, :chars)
        ON CONFLICT (file_id) DO UPDATE
            SET markdown_path = EXCLUDED.markdown_path,
                char_count    = EXCLUDED.char_count
    """), {"id": file_id, "path": path, "chars": char_count})


def replace_chunks(conn, file_id: str, customer_id: str, chunks: list[dict]) -> None:
    conn.execute(text("DELETE FROM document_chunk WHERE file_id = CAST(:id AS uuid)"),
                 {"id": file_id})
    for chunk in chunks:
        conn.execute(text("""
            INSERT INTO document_chunk
                (file_id, customer_id, chunk_index, page, content, embedding)
            VALUES (CAST(:file_id AS uuid), CAST(:customer_id AS uuid),
                    :idx, :page, :content, CAST(:embedding AS vector))
        """), {"file_id": file_id, "customer_id": customer_id,
               "idx": chunk["index"], "page": chunk["page"],
               "content": chunk["content"],
               "embedding": "[" + ",".join(str(v) for v in chunk["embedding"]) + "]"})


def audit(conn, action: str, *, customer_id: str | None = None,
          application_id: str | None = None, file_id: str | None = None,
          payload: dict | None = None) -> None:
    import json
    conn.execute(text("""
        INSERT INTO audit_event (customer_id, application_id, file_id, actor, action, payload)
        VALUES (CAST(:customer AS uuid), CAST(:application AS uuid),
                CAST(:file AS uuid), 'worker', :action, CAST(:payload AS jsonb))
    """), {"customer": customer_id, "application": application_id, "file": file_id,
           "action": action, "payload": json.dumps(payload or {})})
