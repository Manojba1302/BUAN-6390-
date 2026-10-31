"""Versions of one vault document.

Replacing a document keeps every earlier version; each application uses the version attached to it now
(Vijay, October 2026: "both exist and only the attached document at a given point in time is viewable").
A version row says which file a file replaced. The vault lists only the newest version of each document.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocumentVersion, File


def ensure(engine) -> None:
    """Older databases predate the table (db/init/011 creates it on a fresh one)."""
    DocumentVersion.__table__.create(engine, checkfirst=True)


def current_only():
    """A condition on File: not replaced by a newer version."""
    return File.file_id.not_in(select(DocumentVersion.previous_file_id)
                               .where(DocumentVersion.previous_file_id.is_not(None)))


def previous_of(db: Session, file_id: UUID) -> UUID | None:
    row = db.get(DocumentVersion, file_id)
    return row.previous_file_id if row else None


def newer_than(db: Session, file_id: UUID) -> UUID | None:
    return db.scalar(select(DocumentVersion.file_id).where(DocumentVersion.previous_file_id == file_id))


def chain(db: Session, file_id: UUID) -> list[File]:
    """Every version of the document this file belongs to, oldest first."""
    newest = file_id
    while (newer := newer_than(db, newest)) is not None:
        newest = newer
    out, at = [], newest
    while at is not None:
        out.append(db.get(File, at))
        at = previous_of(db, at)
    return [f for f in reversed(out) if f is not None]


def number(db: Session, file_id: UUID) -> int:
    """1 for the first version, 2 for the file that replaced it, and so on."""
    count, at = 1, previous_of(db, file_id)
    while at is not None:
        count, at = count + 1, previous_of(db, at)
    return count


def record(db: Session, new_id: UUID, old_id: UUID) -> None:
    db.add(DocumentVersion(file_id=new_id, previous_file_id=old_id))
