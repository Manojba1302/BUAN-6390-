"""Persistent conversations scoped to the authenticated customer and application."""
import json
import queue
import threading
from uuid import UUID
from fastapi.responses import StreamingResponse
from app.db.session import SessionLocal
from app.agent import streaming
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.security import current_customer
from app.db.session import get_db
from app.db.models import Customer, ChatConversation, ChatTurn
from app.agent import evaluation, graph
from app.services import chat_history
from app.api.v1 import chat

router = APIRouter(prefix="/chat/conversations", tags=["chat"])

class NewConversation(BaseModel):
    application_id: UUID

class Message(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    context_after: datetime | None = None

@router.get("")
def listing(application_id: UUID, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    chat._check_application(db, customer, application_id)
    rows = db.scalars(select(ChatConversation).where(ChatConversation.customer_id == customer.customer_id, ChatConversation.application_id == application_id).order_by(ChatConversation.updated_at.desc())).all()
    return [item for row in rows if (item := _summary(db, row))["question_count"]]

def _summary(db, row):
    first = db.scalar(select(ChatTurn.question).where(ChatTurn.conversation_id == row.conversation_id).order_by(ChatTurn.created_at, ChatTurn.turn_id).limit(1))
    count = db.scalar(select(func.count()).select_from(ChatTurn).where(ChatTurn.conversation_id == row.conversation_id))
    return {"question_count": count, "conversation_id": str(row.conversation_id), "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(), "title": chat.chat_privacy.redact(first or "New conversation")[:80]}

@router.post("", status_code=201)
def create(body: NewConversation, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    chat._check_application(db, customer, body.application_id)
    row = ChatConversation(application_id=body.application_id, customer_id=customer.customer_id)
    db.add(row); db.commit()
    return {"conversation_id": str(row.conversation_id)}

@router.get("/{conversation_id}")
def history(conversation_id: UUID, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    conversation = chat_history.owned(db, customer, conversation_id)
    return {"conversation_id": str(conversation_id), "turns": [chat_history.serialise(db, customer, conversation, row) for row in chat_history.turns(db, conversation)]}

@router.delete("/{conversation_id}", status_code=204)
def delete(conversation_id: UUID, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    conversation = chat_history.owned(db, customer, conversation_id)
    db.delete(conversation); db.commit()

@router.post("/{conversation_id}/messages")
def send(conversation_id: UUID, body: Message, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    if not body.question.strip():
        raise HTTPException(400, "Ask a question")
    conversation = chat_history.owned(db, customer, conversation_id, lock=True)
    question = body.question
    row = chat_history.begin(db, conversation, chat.chat_privacy.scoped(db, customer, conversation.application_id, body.question))
    turn_id = row.turn_id
    try:
        reply = _generate(conversation, question, body.context_after, db, customer)
        chat_history.finish(db, customer, turn_id, reply=reply)
    except HTTPException as exc:
        chat_history.finish(db, customer, turn_id, error=str(exc.detail))
        raise
    return chat_history.serialise(db, customer, conversation, db.get(type(row), turn_id))


def _generate(conversation, question, cutoff, db, customer):
    with evaluation.session(conversation.conversation_id):
        callback = lambda resolved: chat.ask(chat.Ask(question=resolved,application_id=conversation.application_id),db,customer)
        return graph.run(db,customer,conversation,question,callback,cutoff)


@router.post("/{conversation_id}/messages/stream")
def send_stream(conversation_id: UUID, body: Message, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    """Same as send, as Server-Sent Events: "token" events carry the draft answer text while
    the model writes, then one "done" event carries the verified turn (or "error")."""
    if not body.question.strip():
        raise HTTPException(400, "Ask a question")
    conversation = chat_history.owned(db, customer, conversation_id, lock=True)
    row = chat_history.begin(db, conversation, chat.chat_privacy.scoped(db, customer, conversation.application_id, body.question))
    events = queue.Queue()
    threading.Thread(target=_stream_worker, args=(events, conversation_id, customer.customer_id, row.turn_id, body), daemon=True).start()
    return StreamingResponse(_sse(events), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _stream_worker(events, conversation_id, customer_id, turn_id, body):
    """Runs the normal answer flow in its own database session, forwarding draft text."""
    db = SessionLocal()
    sink = streaming.SINK.set(lambda text: events.put(("token", {"text": chat.chat_privacy.redact(text)})))
    try:
        customer, conversation = db.get(Customer, customer_id), db.get(ChatConversation, conversation_id)
        try:
            reply = _generate(conversation, body.question, body.context_after, db, customer)
            chat_history.finish(db, customer, turn_id, reply=reply)
        except HTTPException as exc:
            chat_history.finish(db, customer, turn_id, error=str(exc.detail))
        events.put(("done", chat_history.serialise(db, customer, conversation, db.get(ChatTurn, turn_id))))
    except Exception:
        events.put(("error", {"detail": "We could not answer that. Please try again."}))
    finally:
        streaming.SINK.reset(sink)
        db.close()
        events.put(None)


def _sse(events):
    while (item := events.get()) is not None:
        kind, data = item
        yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"


class EndSession(BaseModel):
    context_after: datetime | None = None


@router.post("/{conversation_id}/end", status_code=204)
def end_session(conversation_id: UUID, body: EndSession, db: Session=Depends(get_db), customer: Customer=Depends(current_customer)):
    conversation = chat_history.owned(db,customer,conversation_id)
    graph.end(customer,conversation,body.context_after)


@router.post("/{conversation_id}/resume", status_code=204)
def resume_session(conversation_id: UUID, body: EndSession, db: Session=Depends(get_db), customer: Customer=Depends(current_customer)):
    conversation = chat_history.owned(db,customer,conversation_id)
    graph.resume(db,customer,conversation,body.context_after)
