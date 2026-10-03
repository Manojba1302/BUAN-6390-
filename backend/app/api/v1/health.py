"""Liveness, and a readiness check that names what is down."""
from __future__ import annotations

import ollama
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    checks = {"database": False, "ollama": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    checks["ollama"] = ollama.health()
    return {"ready": all(checks.values()), "checks": checks,
            "classifier_model": settings.classifier_model}
