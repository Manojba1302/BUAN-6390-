"""Encrypted JSON snapshots, with backward-compatible reads and a resumable backfill."""
import json
import os

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

import field_crypto


class ArchiveJSON(TypeDecorator):
    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not os.getenv("FIELD_ENCRYPTION_KEY", "").strip():
            return value
        cipher = field_crypto._cipher()
        if cipher is None:
            raise ValueError("A valid archive encryption key is required.")
        return {"encrypted_snapshot_v1": cipher.encrypt(json.dumps(value).encode()).decode()}

    def process_result_value(self, value, dialect):
        if isinstance(value, dict) and "encrypted_snapshot_v1" in value:
            cipher = field_crypto._cipher()
            if cipher is None:
                raise ValueError("Archive encryption key unavailable.")
            return json.loads(cipher.decrypt(value["encrypted_snapshot_v1"].encode()))
        return value


def protect_existing(engine):
    if not os.getenv("FIELD_ENCRYPTION_KEY", "").strip():
        return
    from app.db.models import SubmissionRecord
    archive = ArchiveJSON()
    columns = ("state", "progress", "checklist", "documents")
    predicate = " OR ".join(f"NOT ({c} ? 'encrypted_snapshot_v1')" for c in columns)
    while True:
        with engine.begin() as conn:
            rows = conn.execute(text(f"SELECT * FROM submission_record WHERE {predicate} LIMIT 25 FOR UPDATE")).mappings().all()
            if not rows:
                return
            for row in rows:
                values = {c: archive.process_result_value(row[c], None) for c in columns}
                table = SubmissionRecord.__table__
                conn.execute(table.update().where(table.c.application_id == row["application_id"]).values(**values))
