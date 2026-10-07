"""Print the fictional sample documents and their answer key.

Run:  python -m evaluation.make_samples            (writes evaluation/samples/)

For each fictional person and each document type it writes:
  - a digital PDF, which carries real text (the easy case), and
  - a "phone photo" JPG: the same page tilted, blurred and on a desk, with no
    text layer, so the vision model and OCR have to read it (the hard case).
It also writes two documents that are none of our types, whose right answer
is "unknown". labels.json is the answer key the scorer compares against.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from evaluation import sample_data

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
PAGE_SIZES = {"letter": (612, 792), "card": (486, 306)}


def render_pdf(lines: list[str], shape: str) -> bytes:
    """A one-page PDF with the lines printed top to bottom."""
    import fitz
    width, height = PAGE_SIZES[shape]
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    left, y, size = (150, 40, 11) if shape == "card" else (60, 70, 11)
    if shape == "card":
        page.draw_rect(fitz.Rect(20, 60, 135, 210), color=(0.5, 0.5, 0.5), fill=(0.85, 0.85, 0.85))
        page.insert_text((52, 140), "PHOTO", fontsize=12, fontname="helv")
    for index, line in enumerate(lines):
        bold = index == 0
        page.insert_text((left, y), line, fontsize=size + (4 if bold else 0),
                         fontname="hebo" if bold else "helv")
        y += size + (12 if bold else 7)
    return doc.tobytes()


def photo_jpg(pdf: bytes, angle: float) -> bytes:
    """The page as a phone would see it: tilted, a little soft, on a grey desk."""
    import fitz
    from PIL import Image, ImageFilter
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    page = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    page = page.rotate(angle, expand=True, fillcolor=(120, 118, 112))
    desk = Image.new("RGB", (page.width + 120, page.height + 120), (120, 118, 112))
    desk.paste(page, (60, 60))
    desk = desk.filter(ImageFilter.GaussianBlur(0.8))
    out = io.BytesIO()
    desk.save(out, format="JPEG", quality=80)
    return out.getvalue()


def _write(out_dir: Path, name: str, body: bytes) -> None:
    (out_dir / name).write_bytes(body)


def _label(file: str, doc_type: str, person: str, variant: str, fields: dict) -> dict:
    return {"file": file, "type": doc_type, "person": person, "variant": variant, "fields": fields}


def known_documents(out_dir: Path) -> list[dict]:
    """Digital and photo copies of the five types for every fictional person."""
    labels = []
    for n, person in enumerate(sample_data.PEOPLE):
        for doc_type, (builder, shape) in sample_data.BUILDERS.items():
            lines, fields = builder(person)
            pdf = render_pdf(lines, shape)
            stem = f"{person['key']}_{doc_type}"
            _write(out_dir, f"{stem}.pdf", pdf)
            _write(out_dir, f"{stem}_photo.jpg", photo_jpg(pdf, angle=2.5 - 2.5 * n))
            labels.append(_label(f"{stem}.pdf", doc_type, person["key"], "digital", fields))
            labels.append(_label(f"{stem}_photo.jpg", doc_type, person["key"], "photo", fields))
    return labels


def unknown_documents(out_dir: Path) -> list[dict]:
    """Documents that are none of our types. The only right answer is unknown."""
    labels = []
    people = sample_data.PEOPLE
    for builder, person in zip(sample_data.UNKNOWN_BUILDERS, people):
        lines, _ = builder(person)
        name = f"{person['key']}_{builder.__name__}.pdf"
        _write(out_dir, name, render_pdf(lines, "letter"))
        labels.append(_label(name, "unknown", person["key"], "digital", {}))
    lines, _ = sample_data.utility_bill(people[2])
    name = f"{people[2]['key']}_utility_bill_photo.jpg"
    _write(out_dir, name, photo_jpg(render_pdf(lines, "letter"), angle=-1.5))
    labels.append(_label(name, "unknown", people[2]["key"], "photo", {}))
    return labels


def build(out_dir: Path = SAMPLES_DIR) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = known_documents(out_dir) + unknown_documents(out_dir)
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    return labels


if __name__ == "__main__":
    made = build()
    print(f"Wrote {len(made)} sample documents and labels.json to {SAMPLES_DIR}")
