"""The form definition and the document checklist, both served as data."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChecklistRequirement
from app.db.session import get_db

router = APIRouter(tags=["definitions"])

DICTIONARY_PATH = Path(__file__).resolve().parents[2] / "data" / "field_dictionary.json"


@lru_cache
def _dictionary() -> dict:
    return json.loads(DICTIONARY_PATH.read_text(encoding="utf-8"))


@router.get("/field-definitions")
def field_definitions() -> dict:
    """Everything the front end needs to draw the form."""
    return _dictionary()


@router.get("/checklist")
def checklist(db: Session = Depends(get_db)) -> list[dict]:
    """Which document types are required, and how many of each.

    Configuration in the database, not a number hidden in the interface.
    """
    rows = db.scalars(
        select(ChecklistRequirement).order_by(ChecklistRequirement.sort_order)
    ).all()
    return [
        {
            "document_tag": r.document_tag,
            "display_name": r.display_name,
            "required_count": r.required_count,
            "guidance": r.guidance,
        }
        for r in rows
    ]
