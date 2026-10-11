"""Income proposals stay separate from confirmed job details."""
from pathlib import Path
import re
import pay_evidence
from sqlalchemy import select
from app.db.models import Extraction, File, DocumentMarkdown
from app.services import prefill


def employer_key(value):
    return " ".join(str(value or "").split()).casefold()


def suggestions(db, application):
    files = db.scalars(select(File).where(
        File.application_id == application.application_id,
        File.customer_id == application.customer_id, File.status == "completed",
        File.document_tag.in_(["paystub", "w2"])).order_by(File.uploaded_at)).all()
    return [candidate for file in files if (candidate := _candidate(db, file))]


def _candidate(db, file):
    if file.document_tag == "paystub":
        _recover_printed_payroll(db, file)
    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id)).all()
    values = {row.field_name: row for row in rows}
    name = prefill._get(values, "employer_name")
    if not name:
        return None
    monthly, frequency, note = prefill.base_monthly(values)
    evidence = values.get("pay_rate") or values.get("gross_pay") or values.get("employer_name")
    return {"file_id": str(file.file_id), "file_name": file.original_name, "document_type": file.document_tag,
            "employer_name": name, "employee_name": prefill._get(values, "employee_name") or "",
            "base": str(monthly) if monthly is not None else None, "pay_frequency": frequency,
            "calculation": note, "position": prefill._get(values, "position") or "",
            "gross_pay": prefill._get(values, "gross_pay"), "pay_rate": prefill._get(values, "pay_rate"),
            "page": evidence.page}


def _recover_printed_payroll(db, file):
    markdown = db.get(DocumentMarkdown, file.file_id)
    if not markdown or not Path(markdown.markdown_path).is_file():
        return
    body = Path(markdown.markdown_path).read_text(encoding="utf-8").partition("## Document text")[2]
    pages = [{"page": int(match[1]), "text": match[2]} for match in
             re.finditer(r"### Page (\d+)\s*\n(.*?)(?=\n### Page |\Z)", body, re.S)]
    db.scalar(select(File).where(File.file_id == file.file_id).with_for_update())
    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id)).all()
    rows = _discard_label_only_title(db, rows)
    pages += _native_payroll_pages(file, rows)
    recovered = pay_evidence.recover(file.document_tag, pages, {row.field_name: {"value": row.corrected_value if row.corrected_value is not None else prefill._value(row)} for row in rows})
    for key, value in recovered.items():
        db.add(Extraction(file_id=file.file_id, field_name=key, value_raw=value["value"],
                          value_normalized=value["value"], evidence_quote=value["quote"], page=value["page"], method=value.get("method")))
    db.commit()


def _discard_label_only_title(db, rows):
    invalid = [row for row in rows if row.field_name == "position" and row.corrected_value is None
               and not pay_evidence.valid_title(row.value_raw)]
    for row in invalid:
        db.delete(row)
    db.flush()
    return [row for row in rows if row not in invalid]


def _native_payroll_pages(file, rows):
    if {"position", "pay_rate", "pay_rate_basis", "regular_pay", "federal_withholding"}.issubset({row.field_name for row in rows}):
        return []
    if not file.original_name.lower().endswith(".pdf"):
        return []
    from app.services import storage
    import fitz
    import logging
    try:
        with fitz.open(stream=storage.get_object(file.storage_key), filetype="pdf") as document:
            return [{"page": i + 1, "text": pay_evidence.aligned_labels(page), "method": "native_text"}
                    for i, page in enumerate(document) if i < 6]
    except Exception:
        logging.getLogger(__name__).warning("Native payroll layout unavailable for file %s", file.file_id)
        return []
