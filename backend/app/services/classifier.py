"""Stage 1 classification: the fast check while the file is still being chosen.

Three rules this module exists to enforce:
  1. The model sees the page, never the filename and never the category the
     customer selected. Feeding it either trains it to agree with them.
  2. The comparison between what they said and what the page is happens in
     code, below, not inside the prompt.
  3. Nothing here is persisted. Stage 2, in the worker, is the record of truth.
"""
from __future__ import annotations

import logging
import time

import doc_types
import ollama
import pages

from app.core.config import settings

log = logging.getLogger(__name__)


def classify(*, body: bytes, content_type: str | None, name: str, selected_type: str) -> dict:
    started = time.perf_counter()
    try:
        image = pages.first_page_image(body, content_type, name)
    except Exception as exc:
        log.warning("could not render page 1 of %s: %s", name, exc)
        return _result(selected_type, doc_types.UNKNOWN, False, [], started, failed=True)

    text = _page_one_text(body, content_type, name)
    regex_type = doc_types.regex_vote(text)

    try:
        answer = ollama.generate_json(
            model=settings.classifier_model,
            prompt=doc_types.classification_prompt(),
            images=[image],
            timeout=settings.classifier_timeout_seconds,
        )
    except ollama.OllamaError as exc:
        log.warning("stage 1 model call failed: %s", exc)
        # The model being down must not block an upload. Fall back to the
        # regex vote, and say unknown rather than guessing.
        detected = regex_type or doc_types.UNKNOWN
        return _result(selected_type, detected, True, [], started)

    detected = str(answer.get("document_type", doc_types.UNKNOWN)).strip().lower()
    if detected not in doc_types.type_ids():
        detected = doc_types.UNKNOWN

    readable = bool(answer.get("readable", True))
    evidence = [str(e) for e in (answer.get("evidence") or [])][:4]
    final = doc_types.reconcile(detected, regex_type)
    return _result(selected_type, final, readable, evidence, started,
                   mixed=bool(answer.get("mixed_document", False)))


def _page_one_text(body: bytes, content_type: str | None, name: str) -> str:
    if not pages.is_pdf(content_type, name):
        return ""
    texts = pages.native_text(body)
    return texts[0] if texts else ""


def _result(selected: str, detected: str, readable: bool, evidence: list[str],
            started: float, *, mixed: bool = False, failed: bool = False) -> dict:
    outcome = "failed" if failed else doc_types.decide_outcome(selected, detected, readable)
    return {
        "selected_type": selected,
        "detected_type": detected,
        "outcome": outcome,
        "readable": readable,
        "evidence": evidence,
        "mixed_document": mixed,
        "model": settings.classifier_model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "message": _message(outcome, selected, detected),
    }


def _message(outcome: str, selected: str, detected: str) -> str:
    """The customer-facing sentence. One per outcome, no jargon."""
    sel = doc_types.display_name(selected)
    det = doc_types.display_name(detected)
    if outcome == "matched":
        return f"Looks like a {sel.lower()}."
    if outcome == "mismatched":
        return f"You chose {sel}, but this looks like a {det.lower()}."
    if outcome == "unknown":
        return "We could not tell what this document is."
    if outcome == "unreadable":
        return "We could not read enough of this page."
    return "Something went wrong checking this file."
