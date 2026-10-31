"""Which applications a vault document is attached to.

One document can be in several applications (Vijay, October 2026), so the link lives in
application_document. file.application_id still holds the latest application the document
was attached to, so the worker and older code keep seeing a link; it is kept in step here.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationDocument, File

log = logging.getLogger(__name__)


def attached_to(application_id):
    """A condition on File: the document is attached to this application."""
    return File.file_id.in_(select(ApplicationDocument.file_id)
                            .where(ApplicationDocument.application_id == application_id))


def is_attached(db: Session, file_id: UUID, application_id: UUID | None) -> bool:
    return application_id is not None and db.get(ApplicationDocument, (application_id, file_id)) is not None


def applications_of(db: Session, file_id: UUID) -> list[Application]:
    """Oldest attachment first."""
    return list(db.scalars(select(Application).join(
        ApplicationDocument, ApplicationDocument.application_id == Application.application_id)
        .where(ApplicationDocument.file_id == file_id).order_by(ApplicationDocument.attached_at)))


def attach(db: Session, row: File, application_id: UUID) -> None:
    """Setting file.application_id adds the link too (database trigger); the insert covers a file
    that already pointed at this application without a link."""
    db.execute(text("SET LOCAL homeflow.keep_links = 'on'"))   # attaching here keeps it in the others
    row.application_id = application_id
    db.flush()
    db.execute(text("INSERT INTO application_document (application_id, file_id) VALUES (:a, :f) "
                    "ON CONFLICT DO NOTHING"), {"a": application_id, "f": row.file_id})


def detach(db: Session, row: File, application_id: UUID) -> None:
    link = db.get(ApplicationDocument, (application_id, row.file_id))
    if link is not None:
        db.delete(link)
        db.flush()
    remaining = applications_of(db, row.file_id)
    row.application_id = remaining[-1].application_id if remaining else None


def ensure(engine) -> None:
    """Create the table on older databases and copy each file's existing link into it, once.
    Safe on every start: a link is copied only while file.application_id still points at it."""
    ApplicationDocument.__table__.create(engine, checkfirst=True)
    with engine.begin() as conn:
        conn.execute(text(TRIGGER))
        added = conn.execute(text("""
            INSERT INTO application_document (application_id, file_id)
            SELECT f.application_id, f.file_id FROM file f
             WHERE f.application_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM application_document d WHERE d.file_id = f.file_id)""")).rowcount
    if added:
        log.info("linked %s existing documents to their applications", added)


# Keeps the links in step for code that sets file.application_id directly (db/init/010 has the same).
TRIGGER = """CREATE OR REPLACE FUNCTION link_file_application() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Changing file.application_id directly means "moved" (older code) unless the attach step
    -- has said in this transaction that the other applications keep the document.
    IF TG_OP = 'UPDATE' AND OLD.application_id IS NOT NULL
       AND OLD.application_id IS DISTINCT FROM NEW.application_id
       AND coalesce(current_setting('homeflow.keep_links', true), '') <> 'on' THEN
        DELETE FROM application_document
         WHERE application_id = OLD.application_id AND file_id = NEW.file_id;
    END IF;
    IF NEW.application_id IS NOT NULL THEN
        INSERT INTO application_document (application_id, file_id)
        VALUES (NEW.application_id, NEW.file_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS file_application_link ON file;
CREATE TRIGGER file_application_link AFTER INSERT OR UPDATE OF application_id ON file
    FOR EACH ROW EXECUTE FUNCTION link_file_application();"""
