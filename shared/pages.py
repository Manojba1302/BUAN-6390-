"""Turning an uploaded file into page text and page images.

A PDF born digital carries its own text and needs no OCR. A scan or a phone
photo does not, so it goes to the vision model as an image.
"""
from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)

MIN_CHARS_FOR_NATIVE_TEXT = 120   # below this a "text" PDF is really a scan


def is_pdf(content_type: str | None, name: str) -> bool:
    return (content_type or "").endswith("pdf") or name.lower().endswith(".pdf")


def page_count(body: bytes, content_type: str | None, name: str) -> int:
    if not is_pdf(content_type, name):
        return 1
    try:
        import fitz
        with fitz.open(stream=body, filetype="pdf") as doc:
            return doc.page_count
    except Exception as exc:
        log.warning("page count failed: %s", exc)
        return 1


def native_text(body: bytes) -> list[str]:
    """Text per page, empty strings where a page carries none."""
    try:
        import fitz
        with fitz.open(stream=body, filetype="pdf") as doc:
            return [p.get_text("text") or "" for p in doc]
    except Exception as exc:
        log.warning("native text failed: %s", exc)
        return []


def render_page(body: bytes, page_index: int = 0, long_edge: int = 1100) -> bytes:
    """One page as PNG bytes, sized for a vision model rather than for print."""
    import fitz
    with fitz.open(stream=body, filetype="pdf") as doc:
        page = doc[min(page_index, doc.page_count - 1)]
        rect = page.rect
        scale = long_edge / max(rect.width, rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return pix.tobytes("png")


def normalise_image(body: bytes, long_edge: int = 1100) -> bytes:
    """Downscale a phone photo and drop its EXIF rotation."""
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(body))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((long_edge, long_edge))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as exc:
        log.warning("image normalise failed, using original: %s", exc)
        return body


def first_page_image(body: bytes, content_type: str | None, name: str) -> bytes:
    """What stage 1 classification looks at: page one, as an image."""
    if is_pdf(content_type, name):
        return render_page(body, 0)
    return normalise_image(body)


def read_document(body: bytes, content_type: str | None, name: str) -> dict:
    """Full read for stage 2.

    Returns pages as {"text": str, "method": "native_text"|"ocr"|"vision",
    "image": bytes|None}. Pages with no usable text carry their image so the
    vision model can read them instead.
    """
    if not is_pdf(content_type, name):
        return {"pages": [{"text": "", "method": "vision",
                           "image": normalise_image(body)}]}

    texts = native_text(body)
    if not texts:
        return {"pages": [{"text": "", "method": "vision",
                           "image": render_page(body, 0)}]}

    pages = []
    for i, text in enumerate(texts):
        if len(text.strip()) >= MIN_CHARS_FOR_NATIVE_TEXT:
            pages.append({"text": text, "method": "native_text", "image": None})
        else:
            pages.append({"text": text, "method": "vision",
                          "image": render_page(body, i)})
    return {"pages": pages}
