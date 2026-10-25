"""Owned chat history. Historical replies never become new factual evidence."""
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import ChatConversation, ChatTurn, Extraction, File
from app.services import document_answers, chat_privacy


def owned(db, customer, conversation_id, lock=False):
    query = select(ChatConversation).where(ChatConversation.conversation_id == conversation_id, ChatConversation.customer_id == customer.customer_id)
    conversation = db.scalar(query.with_for_update() if lock else query)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    return conversation


def turns(db, conversation):
    return db.scalars(select(ChatTurn).where(ChatTurn.conversation_id == conversation.conversation_id).order_by(ChatTurn.created_at, ChatTurn.turn_id)).all()


def fingerprint(db, file):
    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id).order_by(Extraction.extraction_id)).all()
    data = [(str(row.extraction_id), row.field_name, row.value_raw, row.value_normalized, row.corrected_value, row.page) for row in rows]
    return hashlib.sha256(json.dumps([file.document_tag, file.status, data], default=str).encode()).hexdigest()


def source_versions(db, customer, reply):
    ids = {item["file_id"] for key in ("citations", "document_links", "evidence") for item in reply.get(key, [])}
    result = {}
    for file_id in ids:
        file = db.get(File, UUID(file_id))
        if file is not None and file.customer_id == customer.customer_id:
            result[file_id] = fingerprint(db, file)
    return result


def source_status(db, customer, application_id, versions):
    result = {}
    for file_id, old in versions.items():
        file = db.get(File, UUID(file_id))
        if file is None or file.customer_id != customer.customer_id or file.application_id != application_id:
            result[file_id] = "unavailable"
        elif fingerprint(db, file) != old:
            result[file_id] = "changed"
        else:
            result[file_id] = "current"
    return result


def serialise(db, customer, conversation, row):
    expired = row.status == "pending" and (datetime.now(timezone.utc) - row.created_at).total_seconds() > 180
    return {"turn_id": str(row.turn_id), "question": chat_privacy.redact(row.question), "reply": chat_privacy.stored(chat_privacy.scoped(db, customer, conversation.application_id, row.reply)),
            "status": "failed" if expired else row.status,
            "error": "This request did not finish. Please ask again." if expired else row.error,
            "source_status": source_status(db, customer, conversation.application_id, row.source_versions),
            "created_at": row.created_at.isoformat()}


def begin(db, conversation, question):
    pending = db.scalar(select(ChatTurn).where(ChatTurn.conversation_id == conversation.conversation_id, ChatTurn.status == "pending").order_by(ChatTurn.created_at.desc()))
    if pending and (datetime.now(timezone.utc) - pending.created_at).total_seconds() < 180:
        raise HTTPException(409, "An answer is still being prepared in this conversation")
    row = ChatTurn(conversation_id=conversation.conversation_id, question=chat_privacy.redact(question.strip()))
    db.add(row)
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    return row


def finish(db, customer, turn_id, reply=None, error=None):
    row = db.get(ChatTurn, turn_id)
    if row is None:
        raise HTTPException(410, "This conversation was deleted")
    conversation = db.get(ChatConversation, row.conversation_id)
    safe = chat_privacy.scoped(db, customer, conversation.application_id, reply) if reply else reply
    row.reply, row.error = chat_privacy.stored(safe), chat_privacy.redact(error)
    row.status = "failed" if error else "completed"
    row.source_versions = source_versions(db, customer, reply) if reply else {}
    row.completed_at = datetime.now(timezone.utc)
    db.commit()


def follow_up(db, customer, conversation, question, context_after=None):
    if not re.search(r"\b(it|its|that document|this document|same document)\b|^(?:and|also)\b", question, re.I):
        return question, None
    if any(re.search(pattern, question.lower()) for pattern, _ in document_answers.TAGS):
        return question, None
    recent = db.scalar(select(ChatTurn).where(ChatTurn.conversation_id == conversation.conversation_id, ChatTurn.status == "completed").order_by(ChatTurn.created_at.desc()).limit(1))
    if recent is None or not recent.source_versions or (context_after is not None and recent.created_at < context_after):
        return question, _clarify([])
    files = db.scalars(select(File).where(File.file_id.in_([UUID(key) for key in recent.source_versions]), File.customer_id == customer.customer_id, File.application_id == conversation.application_id)).all()
    if len(files) != 1:
        return question, _clarify(files)
    return question[:max(0, 1996 - len(files[0].original_name))] + " in " + files[0].original_name, None


def _clarify(files):
    return {"answer": "Which document do you mean? Include its filename or document type in your question.", "citations": [], "evidence": [],
            "document_links": [{"file_id": str(file.file_id), "original_name": file.original_name} for file in files]}
