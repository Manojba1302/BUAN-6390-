"""Persistent conversations scoped to the authenticated customer and application."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.security import current_customer
from app.db.session import get_db
from app.db.models import Customer, ChatConversation, ChatTurn
from app.services import chat_history
from app.api.v1 import chat

router = APIRouter(prefix="/chat/conversations", tags=["chat"])

class NewConversation(BaseModel):
    application_id: UUID

class Message(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

@router.get("")
def listing(application_id: UUID, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    chat._check_application(db, customer, application_id)
    rows = db.scalars(select(ChatConversation).where(ChatConversation.customer_id == customer.customer_id, ChatConversation.application_id == application_id).order_by(ChatConversation.updated_at.desc())).all()
    return [_summary(db, row) for row in rows]

def _summary(db, row):
    first = db.scalar(select(ChatTurn.question).where(ChatTurn.conversation_id == row.conversation_id).order_by(ChatTurn.created_at, ChatTurn.turn_id).limit(1))
    return {"conversation_id": str(row.conversation_id), "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(), "title": (first or "New conversation")[:80]}

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


def _send_reply(
    db: Session,
    customer: Customer,
    conversation,
    question: str,
    clarification,
    context: list[dict],
    turn_id: UUID,
) -> None:
    try:
        reply = clarification or chat.ask(
            chat.Ask(question=question, application_id=conversation.application_id),
            db,
            customer,
            context=context,
        )
        chat_history.finish(db, customer, turn_id, reply=reply)
    except HTTPException as exc:
        chat_history.finish(db, customer, turn_id, error=str(exc.detail))
        raise


@router.post("/{conversation_id}/messages")
def send(conversation_id: UUID, body: Message, db: Session = Depends(get_db), customer: Customer = Depends(current_customer)):
    if not body.question.strip():
        raise HTTPException(400, "Ask a question")
    conversation = chat_history.owned(db, customer, conversation_id, lock=True)
    context = chat_history.recent_context(db, conversation, limit=3)
    question, clarification = chat_history.follow_up(db, customer, conversation, body.question)
    row = chat_history.begin(db, conversation, body.question)
    _send_reply(
        db, customer, conversation, question,
        clarification, context, row.turn_id,
    )
    return chat_history.serialise(
        db, customer, conversation, db.get(type(row), row.turn_id)
    )
