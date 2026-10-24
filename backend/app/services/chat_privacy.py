
"""Basic privacy controls for persisted chatbot content."""

import re
from typing import Any


SSN_PATTERN = re.compile(
    r"(?<!\d)\d{3}-?\d{2}-?\d{4}(?!\d)"
)

PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+1[\s.-]?)?"
    r"(?:\(\d{3}\)|\d{3})[\s.-]?"
    r"\d{3}[\s.-]?\d{4}(?!\d)"
)

DOB_PATTERN = re.compile(
    r"\b(?:DOB|date of birth|birth date)\s*[:=]?\s*"
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)


ACCOUNT_PATTERN = re.compile(
    r"\b(account\s*(?:number|no\.?|#)|"
    r"acct\s*(?:number|no\.?|#)?)"
    r"\s*[:=]?\s*"
    r"([0-9][0-9\s-]{3,25}[0-9])",
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    """Redact common sensitive identifiers from text."""
    text = DOB_PATTERN.sub("[DOB REDACTED]", text)
    text = ACCOUNT_PATTERN.sub(
        lambda match: f"{match.group(1)}: [ACCOUNT REDACTED]",
        text,
    )
    text = SSN_PATTERN.sub("[SSN REDACTED]", text)
    text = PHONE_PATTERN.sub("[PHONE REDACTED]", text)
    return text


def redact_data(value: Any) -> Any:
    """Recursively redact sensitive values in nested data."""
    if isinstance(value, str):
        return redact_text(value)

    if isinstance(value, dict):
        return {
            key: redact_data(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [redact_data(item) for item in value]

    return value



def _evidence_links(evidence, links):
    known = {
        item.get("file_id")
        for item in links
        if isinstance(item, dict)
    }
    for item in evidence:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        if not file_id or file_id in known:
            continue
        links.append({
            "file_id": file_id,
            "original_name": redact_text(
                str(item.get("original_name", "Document"))
            ),
        })
        known.add(file_id)
    return links


def _protect_document_links(protected):
    evidence = protected.pop("evidence", [])
    if not isinstance(evidence, list):
        return protected
    links = protected.get("document_links", [])
    if not isinstance(links, list):
        links = []
    links = _evidence_links(evidence, links)
    if links:
        protected["document_links"] = links
    return protected


def protect_chat_response(reply: dict) -> dict:
    """Prepare a chatbot reply for safe API delivery."""
    if not isinstance(reply, dict):
        raise TypeError("Chat response must be a dictionary")
    protected = redact_data(reply)
    return _protect_document_links(protected)
