"""Metadata-only evaluation traces; no customer text or raw identifiers."""
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
import time
from uuid import uuid4
from app.core.config import settings

TRACE = ContextVar("chat_evaluation_trace", default=None)
SESSION = ContextVar("chat_evaluation_session", default=None)
KEY = settings.chat_evaluation_hmac_key.encode() or os.urandom(32)


def pseudonym(value):
    return hmac.new(KEY, str(value).encode(), hashlib.sha256).hexdigest()


@contextmanager
def session(value):
    token = SESSION.set(pseudonym(value))
    try:
        yield
    finally:
        SESSION.reset(token)


@contextmanager
def request():
    trace = {"schema_version":1,"request_id":str(uuid4()),"created_at":datetime.now(timezone.utc).isoformat(),"route":"unknown","outcome":"error","timings":{},"retrieved":[],"sources":[]}
    if SESSION.get():
        trace["session_ref"] = SESSION.get()
    token, start = TRACE.set(trace), time.monotonic()
    try:
        yield trace
    finally:
        trace["timings"]["total_seconds"] = round(time.monotonic()-start,4)
        TRACE.reset(token)
        from app.agent.evaluation_store import publish
        publish(trace)


def route(value):
    if TRACE.get() is not None:
        TRACE.get()["route"] = value


@contextmanager
def timed(stage):
    start = time.monotonic()
    try:
        yield
    finally:
        if TRACE.get() is not None:
            TRACE.get()["timings"][stage] = round(time.monotonic()-start,4)


def configure_model(name, context, maximum):
    if TRACE.get() is not None:
        TRACE.get().update(model_name=name, context_tokens=context, max_output_tokens=maximum)


def model(first, total):
    if TRACE.get() is not None:
        TRACE.get()["timings"].update(first_token_seconds=round(first,4) if first is not None else None, generation_seconds=round(total,4))


def retrieved(passages):
    if TRACE.get() is not None:
        TRACE.get()["retrieved"] = [{"source_ref":pseudonym(p["file_id"]),"page":p.get("page"),"lexical":p.get("lexical"),"semantic":p.get("semantic")} for p in passages]


def finish(reply):
    trace = TRACE.get()
    if trace is None:
        return
    trace["sources"] = [{"source_ref":pseudonym(c["file_id"]),"page":c.get("page")} for c in reply.get("citations",[])]
    answer = reply.get("answer", "").lower()
    trace["outcome"] = "answered" if trace["sources"] or trace["route"] == "inventory" else "no_evidence"
    if "which document" in answer:
        trace["outcome"] = "clarification"
    elif "could not substantiate" in answer or "could not verify" in answer:
        trace["outcome"] = "unsupported"
    elif trace["route"] == "future_pay":
        trace["outcome"] = "uncertain"
    elif trace["route"] == "scope":
        trace["outcome"] = "out_of_scope"


def failed(status_code):
    if TRACE.get() is not None:
        TRACE.get()["outcome"] = "unavailable" if status_code == 503 else "error"
