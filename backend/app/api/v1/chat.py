"""Document chat API. The answering logic lives in app/agent/answering.py."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import current_customer
from app.db.models import Customer
from app.db.session import get_db
from app.agent import evaluation
# Re-exported so existing callers and tests keep importing them from here.
from app.agent.answering import (  # noqa: F401
    ollama, chat_evidence, chat_privacy, document_answers, EMBED_MODEL, ANSWER_MODEL, REPLY_SCHEMA, SYSTEM, DECISION,
    _ask, _answer, _policy_reply, _decision_reply, _search_answer, _fast_answer, _embed_question, _inventory_question,
    _inventory, _check_application, _supported_answer, _comparison_guard, _validated_answer, _focus_passages, _prompt,
    _compact_sources, _restore_source_ids, _comparable, _missing_reply,
)

router = APIRouter(prefix="/chat", tags=["chat"])


class Ask(BaseModel):
    question: str = Field(max_length=2000)
    application_id: UUID | None = None


@router.post("")
def ask(body: Ask, db: Session = Depends(get_db),
        customer: Customer = Depends(current_customer)) -> dict:
    with evaluation.request():
        try:
            reply = _ask(body, db, customer)
            evaluation.finish(reply)
            return reply
        except HTTPException as exc:
            evaluation.failed(exc.status_code)
            raise
