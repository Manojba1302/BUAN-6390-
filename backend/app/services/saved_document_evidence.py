"""Reuse saved page text for review without guessing or overwriting user corrections."""
from pathlib import Path
import re
import address_evidence
import bank_evidence
from sqlalchemy import select
from app.db.models import DocumentMarkdown, Extraction, File


def pages(db, file):
    markdown = db.get(DocumentMarkdown, file.file_id)
    if not markdown or not Path(markdown.markdown_path).is_file():
        return []
    body = Path(markdown.markdown_path).read_text(encoding="utf-8").partition("## Document text")[2]
    return [{"page": int(match[1]), "text": match[2], "method": None} for match in
            re.finditer(r"### Page (\d+)\s*\n(.*?)(?=\n### Page |\Z)", body, re.S)]


def recover(db, file):
    if file.status != "completed":
        return
    source = pages(db, file)
    if not source:
        return
    db.scalar(select(File).where(File.file_id == file.file_id).with_for_update())
    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id)).all()
    fields = {row.field_name: {"value": row.corrected_value if row.corrected_value is not None else row.value_normalized or row.value_raw} for row in rows}
    recovered = address_evidence.recover_pages(file.document_tag, source, fields)
    recovered.update(bank_evidence.recover(file.document_tag, source))
    for key, value in recovered.items():
        _save(db, file, rows, key, value)
    db.commit()


def _save(db, file, rows, key, value):
    row = next((row for row in rows if row.field_name == key), None)
    if row is not None and (row.corrected_value is not None or key not in ("total_withdrawals", "account_mask")):
        return
    if row is None:
        row = Extraction(file_id=file.file_id, field_name=key, value_raw=value["value"], review_state="proposed")
        db.add(row)
    row.value_normalized = value["value"]
    row.evidence_quote = value["quote"]
    row.page = value["page"]
    row.method = value.get("method")
