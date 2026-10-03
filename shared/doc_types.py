"""Loader for document_types.json, shared by the API and the worker.

Both containers mount this folder read only at /srv/shared, so there is one
definition of what a W-2 looks like rather than two that drift apart.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

SHARED_DIR = Path(os.getenv("SHARED_DIR", "/srv/shared"))
UNKNOWN = "unknown"


@lru_cache
def catalogue() -> dict:
    return json.loads((SHARED_DIR / "document_types.json").read_text(encoding="utf-8"))


@lru_cache
def type_ids() -> tuple[str, ...]:
    return tuple(t["id"] for t in catalogue()["types"])


def get_type(type_id: str) -> dict | None:
    return next((t for t in catalogue()["types"] if t["id"] == type_id), None)


def display_name(type_id: str) -> str:
    t = get_type(type_id)
    return t["display_name"] if t else type_id


def classification_prompt() -> str:
    lines = [f"- {t['id']}: {t['definition']}" for t in catalogue()["types"]]
    lines.append("- unknown: anything else, or a page you cannot identify with confidence")
    return catalogue()["classification_prompt"].replace("{{TYPE_LIST}}", "\n".join(lines))


def extraction_prompt(type_id: str) -> str:
    spec = get_type(type_id)
    if not spec:
        raise ValueError(f"unknown document type: {type_id}")
    fields = [f"- {name}: {desc}" for name, desc in spec["extract"].items()]
    return (catalogue()["extraction_prompt"]
            .replace("{{DISPLAY_NAME}}", spec["display_name"])
            .replace("{{FIELD_LIST}}", "\n".join(fields)))


def regex_vote(text: str) -> str | None:
    """A second opinion that owes nothing to the model.

    Returns the single type whose printed signals appear in the page text, or
    None when nothing reaches its threshold or two types tie.
    """
    if not text:
        return None
    hits: dict[str, int] = {}
    for spec in catalogue()["types"]:
        n = sum(1 for pattern in spec.get("regex", []) if re.search(pattern, text))
        if n >= spec.get("regex_min_hits", 2):
            hits[spec["id"]] = n
    if not hits:
        return None
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def decide_outcome(selected: str, detected: str, readable: bool) -> str:
    """The comparison happens here, in code, never inside the model."""
    if not readable:
        return "unreadable"
    if detected == UNKNOWN:
        return "unknown"
    if detected == selected:
        return "matched"
    return "mismatched"


def reconcile(model_type: str, regex_type: str | None) -> str:
    """Model and regex disagreeing is a reason to say unknown, not to pick one."""
    if regex_type is None:
        return model_type
    if model_type == UNKNOWN:
        return regex_type
    return model_type if model_type == regex_type else UNKNOWN
