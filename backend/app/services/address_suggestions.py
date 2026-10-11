"""Keep document mailing addresses separate from confirmed residential and property addresses."""
import address_evidence
import doc_types
from sqlalchemy import select
from app.db.models import Extraction, File
from app.services.name_suggestions import _value
from app.services import saved_document_evidence


def suggestions(db, application):
    files = db.scalars(select(File).where(
        File.application_id == application.application_id,
        File.customer_id == application.customer_id,
        File.status == "completed").order_by(File.uploaded_at, File.file_id)).all()
    return [candidate for file in files if (candidate := _candidate(db, file))]


def _candidate(db, file):
    saved_document_evidence.recover(db, file)
    _recover_saved_evidence(db, file)
    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id)).all()
    fields = {row.field_name: row for row in rows}
    parts = {key: _value(fields, key) for key in ("address", "city", "state", "zip")}
    if not any(parts.values()):
        return None
    evidence = next(fields[key] for key in parts if parts[key])
    return {"file_id": str(file.file_id), "file_name": file.original_name,
            "document_type": doc_types.display_name(file.document_tag), "page": evidence.page,
            "label": ", ".join(value for value in parts.values() if value), **parts}


def _recover_saved_evidence(db, file):
    db.scalar(select(File).where(File.file_id == file.file_id).with_for_update())
    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id)).all()
    evidence = {row.field_name: {"value": _value({row.field_name: row}, row.field_name),
                "quote": row.evidence_quote, "page": row.page, "method": row.method, "model_name": row.model_name} for row in rows}
    recovered = address_evidence.recover(file.document_tag, evidence)
    for name, payload in recovered.items():
        db.add(Extraction(file_id=file.file_id, field_name=name, value_raw=payload["value"],
                          value_normalized=payload["value"], page=payload["page"],
                          evidence_quote=payload["quote"], method=payload["method"], model_name=payload["model_name"], review_state="proposed"))
    db.commit()
