"""Application entry point."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import applications, auth, chat, documents, fields, health
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

for router in (auth.router, health.router, fields.router, applications.router,
               documents.router, chat.router):
    app.include_router(router, prefix=settings.api_prefix)


@app.on_event("startup")
def on_startup() -> None:
    from app.db.models import AuthAccount, AuthSession, PasswordReset
    from app.db.session import engine
    for table in (AuthAccount.__table__, AuthSession.__table__, PasswordReset.__table__):
        table.create(engine, checkfirst=True)
    try:
        storage.ensure_bucket()
    except Exception as exc:                 # storage down should not stop the API
        log.warning("object storage not ready: %s", exc)
    log.info("%s listening, api at %s", settings.app_name, settings.api_prefix)

