"""Durable cleanup intents for object storage and derived markdown files."""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import File, StorageCleanup
from app.services import storage

log = logging.getLogger(__name__)


def reserve_upload(db, row):
    # The intent survives even if the uploading process dies before its transaction commits.
    with Session(db.get_bind()) as ledger:
        ledger.add(StorageCleanup(file_id=row.file_id, storage_key=row.storage_key,
                                  retry_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
        ledger.commit()
    intent = db.get(StorageCleanup, row.file_id, with_for_update=True)
    if intent is None:
        raise RuntimeError("Upload reservation expired.")
    db.delete(intent)  # removed atomically with insertion of the new file


def schedule_delete(db, row):
    db.add(StorageCleanup(file_id=row.file_id, storage_key=row.storage_key,
                          retry_at=datetime.now(timezone.utc)))


def drain(engine, limit=32):
    for _ in range(limit):
        with Session(engine) as db, db.begin():
            job = db.scalar(select(StorageCleanup).where(StorageCleanup.retry_at <= datetime.now(timezone.utc))
                            .order_by(StorageCleanup.retry_at).limit(1).with_for_update(skip_locked=True))
            if job is None:
                return
            if db.get(File, job.file_id) is None:
                try:
                    storage.delete_object(job.storage_key)
                    for suffix in (".md", ".pages.json"):
                        (Path(settings.markdown_dir) / f"{job.file_id}{suffix}").unlink(missing_ok=True)
                except Exception:
                    log.exception("Storage cleanup deferred for %s", job.file_id)
                    job.retry_at = datetime.now(timezone.utc) + timedelta(minutes=1)
                    continue
            db.delete(job)


def start(engine):
    stop = Event()
    def run():
        while not stop.wait(60):
            try:
                drain(engine)
            except Exception:
                log.exception("Storage cleanup cycle failed")
    Thread(target=run, daemon=True, name="storage-cleanup").start()
    return stop
