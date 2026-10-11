"""Document identities are suggestions, never account identity or automatic name updates."""
import doc_types
from sqlalchemy import select
from app.db.models import Extraction, File


def suggestions(db, application):
    files = db.scalars(select(File).where(
        File.application_id == application.application_id,
        File.customer_id == application.customer_id,
        File.status == "completed").order_by(File.uploaded_at, File.file_id)).all()
    return [candidate for file in files if (candidate := _candidate(db, file))]


def _candidate(db, file):
    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id)).all()
    fields = {row.field_name: row for row in rows}
    first, last = _value(fields, "first_name"), _value(fields, "last_name")
    full = next((_value(fields, key) for key in ("full_name", "employee_name", "name")
                 if _value(fields, key)), "")
    label = " ".join(part for part in (first, last) if part) or full
    if not label:
        return None
    evidence = fields.get("first_name") or fields.get("full_name") or fields.get("employee_name") or fields.get("name") or fields.get("last_name")
    return {"file_id": str(file.file_id), "file_name": file.original_name,
            "document_type": doc_types.display_name(file.document_tag), "page": evidence.page,
            "label": label, "full_name": full, "first_name": first, "last_name": last}


def _value(fields, name):
    row = fields.get(name)
    if row is None:
        return ""
    return str(row.corrected_value if row.corrected_value is not None else
               (row.value_normalized or row.value_raw or "")).strip()
