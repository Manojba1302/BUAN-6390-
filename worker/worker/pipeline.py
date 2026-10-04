"""The document pipeline: read, classify, extract, write markdown, embed.

Validate -> inspect pages -> text or image -> classify -> extract -> store.
Each stage returns what the next one needs and nothing more, so a failure in
one of them is reportable rather than mysterious.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import doc_types
import ollama
import pages

from worker.config import config

log = logging.getLogger(__name__)

MIN_OCR_CHARS = 80


# ---------------------------------------------------------------- reading
def read(body: bytes, content_type: str | None, name: str) -> dict:
    """Page text, with OCR where a PDF page carries none."""
    document = pages.read_document(body, content_type, name)
    for page in document["pages"]:
        if page["method"] == "vision" and page["image"] is not None:
            text = _ocr(page["image"])
            if len(text.strip()) >= MIN_OCR_CHARS:
                page["text"] = text
                page["method"] = "ocr"
    return document


def _ocr(image: bytes) -> str:
    try:
        import io

        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(io.BytesIO(image)))
    except Exception as exc:
        log.info("ocr unavailable or failed: %s", exc)
        return ""


# ------------------------------------------------------------ classifying
def classify(document: dict, selected_type: str) -> dict:
    """Stage 2. Every page is classified, not just the first.

    Pages that disagree mean the file holds more than one document, which we
    flag rather than tagging twelve pages as one W-2.
    """
    per_page: list[str] = []
    evidence: list[str] = []
    readable = False

    for index, page in enumerate(document["pages"][:6]):      # six is plenty
        text = page.get("text") or ""
        if len(text.strip()) >= MIN_OCR_CHARS:
            readable = True
        regex_type = doc_types.regex_vote(text)
        model_type, found = _ask_model(page, text)
        per_page.append(doc_types.reconcile(model_type, regex_type))
        if index == 0:
            evidence = found

    if not per_page:
        return _result(selected_type, doc_types.UNKNOWN, False, [], False)

    distinct = {t for t in per_page if t != doc_types.UNKNOWN}
    mixed = len(distinct) > 1
    detected = per_page[0] if not mixed else doc_types.UNKNOWN
    return _result(selected_type, detected, readable, evidence, mixed)


def _ask_model(page: dict, text: str) -> tuple[str, list[str]]:
    prompt = doc_types.classification_prompt()
    images = [page["image"]] if page.get("image") else None
    if text.strip():
        prompt += f"\n\nText found on the page:\n{text[:4000]}"
    model = config.vision_model if images else config.extractor_model

    try:
        answer = ollama.generate_json(model=model, prompt=prompt, images=images, timeout=120.0)
    except ollama.OllamaError as exc:
        log.warning("classification call failed: %s", exc)
        return doc_types.UNKNOWN, []

    detected = str(answer.get("document_type", doc_types.UNKNOWN)).strip().lower()
    if detected not in doc_types.type_ids():
        detected = doc_types.UNKNOWN
    return detected, [str(e) for e in (answer.get("evidence") or [])][:4]


def _result(selected: str, detected: str, readable: bool,
            evidence: list[str], mixed: bool) -> dict:
    import json
    return {
        "selected": selected,
        "detected": detected,
        "outcome": doc_types.decide_outcome(selected, detected, readable),
        "evidence": json.dumps(evidence),
        "mixed": mixed,
        "model": config.vision_model,
    }


# -------------------------------------------------------------- extracting
def extract(document: dict, document_tag: str) -> dict[str, dict]:
    """Fields for the tag the customer chose, with the quote they came from."""
    spec = doc_types.get_type(document_tag)
    if spec is None:
        return {}

    prompt = doc_types.extraction_prompt(document_tag)
    out: dict[str, dict] = {}

    for index, page in enumerate(document["pages"][:6], start=1):
        text = (page.get("text") or "").strip()
        images = [page["image"]] if page.get("image") else None
        if not text and not images:
            continue

        page_prompt = prompt + (f"\n\nPage {index} text:\n{text[:6000]}" if text else "")
        model = config.vision_model if images else config.extractor_model
        try:
            answer = ollama.generate_json(model=model, prompt=page_prompt,
                                          images=images, timeout=180.0)
        except ollama.OllamaError as exc:
            log.warning("extraction failed on page %s: %s", index, exc)
            raise

        for name, payload in (answer.get("fields") or {}).items():
            if name not in spec["extract"] or name in out:
                continue
            value = _clean(payload)
            if value is None:
                continue                      # a missing value stays missing
            out[name] = {
                "value": value,
                "normalized": _normalise(name, value),
                "page": index,
                "quote": str(payload.get("quote") or "")[:500] if isinstance(payload, dict) else "",
                "method": "vision" if images else page.get("method", "native_text"),
            }
    return out


def _clean(payload) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("value")
    else:
        value = payload
    if value is None:
        return None
    value = str(value).strip()
    if value.lower() in ("", "null", "none", "n/a", "not found", "unknown"):
        return None
    return value


def _normalise(field: str, value: str) -> str | None:
    """Only where the conversion is unambiguous. Otherwise leave it alone."""
    if any(k in field for k in ("date", "period_start", "period_end")):
        return _as_date(value)
    if any(k in field for k in ("pay", "balance", "wages", "tax", "deposits", "withdrawals")):
        digits = re.sub(r"[^0-9.\-]", "", value)
        return digits or None
    return None


def _as_date(value: str) -> str | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ------------------------------------------------------- markdown and RAG
def to_markdown(document: dict, *, file_name: str, document_tag: str,
                fields: dict[str, dict]) -> str:
    """One markdown file per document: what it is, what we read, and the text."""
    lines = [f"# {doc_types.display_name(document_tag)}", "",
             f"Source file: {file_name}", ""]
    if fields:
        lines += ["## Extracted fields", ""]
        lines += [f"- **{k}**: {v['value']}  (page {v['page']})" for k, v in fields.items()]
        lines.append("")
    lines += ["## Document text", ""]
    for index, page in enumerate(document["pages"], start=1):
        lines += [f"### Page {index}", "", (page.get("text") or "").strip(), ""]
    return "\n".join(lines)


def chunk(document: dict) -> list[dict]:
    """Chunks carry their page so an answer can cite one."""
    out: list[dict] = []
    index = 0
    for page_no, page in enumerate(document["pages"], start=1):
        text = (page.get("text") or "").strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(start + config.chunk_chars, len(text))
            body = text[start:end].strip()
            if body:
                out.append({"index": index, "page": page_no, "content": body})
                index += 1
            if end == len(text):
                break
            start = end - config.chunk_overlap
    return out


def embed_chunks(chunks: list[dict]) -> list[dict]:
    done = []
    for item in chunks:
        try:
            item["embedding"] = ollama.embed(model=config.embed_model, text=item["content"])
            done.append(item)
        except ollama.OllamaError as exc:
            log.warning("embedding failed for chunk %s: %s", item["index"], exc)
    return done
