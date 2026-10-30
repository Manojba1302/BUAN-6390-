"""Session-scoped LangGraph memory stores source references, never document text."""
from dataclasses import dataclass, field
from typing import TypedDict, Callable
from uuid import UUID
from collections import OrderedDict
from threading import RLock
import re
import time
from sqlalchemy import select
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime
from app.db.models import File, ChatTurn
from app.services import application_chat, document_answers, chat_history
from app.agent import evaluation

class State(TypedDict, total=False):
    source_ids: list[str]
    turns: int
    pending_turn_id: str

@dataclass
class Context:
    db: object
    customer: object
    conversation: object
    question: str
    answer: Callable
    resolved: str = ""
    reply: dict = field(default_factory=dict)

CHECKPOINTS = InMemorySaver()
ACTIVE = OrderedDict()
LOCK = RLock()


def _resolve(state: State, runtime: Runtime[Context]):
    ctx = runtime.context
    ctx.resolved = _clarified_question(ctx,state)
    followup = re.search(r"\b(it|its|that document|this document|same document)\b|^(?:and|also)\b",ctx.resolved,re.I)
    explicit = any(re.search(pattern,ctx.resolved,re.I) for pattern,_ in document_answers.TAGS)
    if followup and not explicit and not application_chat.intent(ctx.resolved):
        files = _files(ctx,state.get("source_ids",[]))
        if len(files) == 1:
            ctx.resolved = ctx.resolved[:max(0,1996-len(files[0].original_name))]+" in "+files[0].original_name
        else:
            ctx.reply = chat_history._clarify(files)
    return _pending(ctx)


def _clarified_question(ctx, state):
    identity = state.get("pending_turn_id")
    selection = any(re.fullmatch(pattern,ctx.question.strip(),re.I) for pattern,_ in document_answers.TAGS)
    if identity and selection:
        row = ctx.db.get(ChatTurn,UUID(identity))
        if row and row.conversation_id == ctx.conversation.conversation_id:
            return (row.question + " in " + ctx.question)[:2000]
    return ctx.question


def _pending(ctx):
    if not ctx.reply:
        return {"pending_turn_id":""}
    identity = ctx.db.scalar(select(ChatTurn.turn_id).where(ChatTurn.conversation_id==ctx.conversation.conversation_id,ChatTurn.status=="pending").order_by(ChatTurn.created_at.desc()).limit(1))
    return {"pending_turn_id":str(identity) if isinstance(identity,UUID) else ""}


def _files(ctx, ids):
    return ctx.db.scalars(select(File).where(File.file_id.in_([UUID(value) for value in ids]),File.customer_id==ctx.customer.customer_id,File.application_id==ctx.conversation.application_id)).all() if ids else []


def _answer(state: State, runtime: Runtime[Context]):
    ctx = runtime.context
    if ctx.reply:
        with evaluation.request():
            evaluation.route("clarification")
            evaluation.finish(ctx.reply)
    else:
        ctx.reply = ctx.answer(ctx.resolved)
    ids = {item["file_id"] for key in ("citations","document_links") for item in ctx.reply.get(key,[])}
    return {"source_ids":sorted(ids),"turns":state.get("turns",0)+1}


def _build():
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("resolve",_resolve)
    builder.add_node("answer",_answer)
    builder.add_edge(START,"resolve")
    builder.add_edge("resolve","answer")
    builder.add_edge("answer",END)
    return builder.compile(checkpointer=CHECKPOINTS)

GRAPH = _build()


def key(customer, conversation, cutoff=None):
    return f"{customer.customer_id}:{conversation.application_id}:{conversation.conversation_id}:{cutoff.isoformat() if cutoff else 'active'}"


def _expire():
    now = time.monotonic()
    for identity, used in list(ACTIVE.items()):
        if now-used > 1800 or len(ACTIVE)>128:
            CHECKPOINTS.delete_thread(identity)
            ACTIVE.pop(identity,None)


def run(db, customer, conversation, question, answer, cutoff=None):
    identity = key(customer,conversation,cutoff)
    context = Context(db,customer,conversation,question,answer)
    with LOCK:
        _expire()
        ACTIVE[identity] = time.monotonic()
    GRAPH.invoke({}, {"configurable":{"thread_id":identity}}, context=context)
    return context.reply


def end(customer, conversation, cutoff=None):
    identity = key(customer,conversation,cutoff)
    with LOCK:
        CHECKPOINTS.delete_thread(identity)
        ACTIVE.pop(identity,None)


def resume(db, customer, conversation, cutoff=None):
    """Restore source focus only; historical answer text is never evidence."""
    recent = next((row for row in reversed(chat_history.turns(db,conversation)) if row.status == "completed" and row.source_versions), None)
    ids = list(recent.source_versions) if recent else []
    ids = [str(file.file_id) for file in _files(Context(db,customer,conversation,"",None),ids)]
    identity = key(customer,conversation,cutoff)
    with LOCK:
        CHECKPOINTS.delete_thread(identity)
        GRAPH.update_state({"configurable":{"thread_id":identity}}, {"source_ids":ids,"turns":0,"pending_turn_id":""}, as_node="answer")
        ACTIVE[identity] = time.monotonic()
