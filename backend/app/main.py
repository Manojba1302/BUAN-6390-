"""Application entry point."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import applications, auth, google_auth, chat, conversations, template_documents, documents, fields, health
from app.api.v1 import lender_link
from app.core.config import settings
from app.services import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (lender_link.router, auth.router, google_auth.router, health.router, fields.router, applications.router,
               documents.router, chat.router, conversations.router, template_documents.router):
    app.include_router(router, prefix=settings.api_prefix)


@app.on_event("startup")
def on_startup() -> None:
    _initialize_database()
    from app.services import prefill_jobs
    from app.db.session import engine
    app.state.prefill_stop = prefill_jobs.start(engine)
    try:
        storage.ensure_bucket()
    except Exception as exc:                 # storage down should not stop the API
        log.warning("object storage not ready: %s", exc)
    log.info("%s listening, api at %s", settings.app_name, settings.api_prefix)


@app.on_event("shutdown")
def stop_cleanup():
    app.state.cleanup_stop.set()
    app.state.prefill_stop.set()


def _initialize_database():
    from app.db.models import AuthAccount, AuthSession, PasswordReset, GoogleIdentity, GoogleChallenge
    from app.db.session import engine
    for table in (AuthAccount.__table__, AuthSession.__table__, PasswordReset.__table__, GoogleIdentity.__table__, GoogleChallenge.__table__):
        table.create(engine, checkfirst=True)
    _fix_checklist_spelling(engine)
    from app.services import attachments
    from app.db.models import SubmissionRecord, SubmissionFile
    SubmissionRecord.__table__.create(engine, checkfirst=True)
    SubmissionFile.__table__.create(engine, checkfirst=True)
    from app.db.models import StorageCleanup
    from app.services import storage_cleanup
    StorageCleanup.__table__.create(engine, checkfirst=True)
    app.state.cleanup_stop = storage_cleanup.start(engine)
    from app.db.archive import protect_existing
    protect_existing(engine)
    attachments.ensure(engine)               # one document in several applications
    from app.services import versions
    versions.ensure(engine)                  # replace keeps earlier versions
    from app.services import chat_history
    chat_history.ensure(engine)              # a vault chat needs no application


def _fix_checklist_spelling(engine) -> None:
    """Databases seeded before the US-spelling fix still say "licence"; correct them once, idempotently."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE checklist_requirement SET guidance = replace(guidance, 'licence', 'license') "
                              "WHERE guidance LIKE '%licence%'"))
    except Exception as exc:                 # a missing table should not stop the API
        log.warning("checklist spelling fix skipped: %s", exc)

