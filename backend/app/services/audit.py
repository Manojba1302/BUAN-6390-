"""Every change worth explaining later gets a row here."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record(db: Session, *, action: str, customer_id: UUID | None = None,
           application_id: UUID | None = None, file_id: UUID | None = None,
           actor: str = "customer", payload: dict | None = None) -> None:
    db.add(AuditEvent(
        customer_id=customer_id, application_id=application_id, file_id=file_id,
        actor=actor, action=action, payload=payload or {},
    ))
