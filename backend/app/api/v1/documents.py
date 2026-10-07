"""Documents: the classify pre-check, the upload, the vault and corrections."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from uuid import UUID

import doc_types
from fastapi import APIRouter, Depends, File as UploadField, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import current_customer
from app.db.models import (
    Application, ApplicationField, Asset, Employment, Customer, DocumentMarkdown, Extraction, File, FileClassification,
)
from app.db.session import get_db
from app.services import audit, classifier, queue, storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


class CorrectionIn(BaseModel):
    extraction_id: UUID
    value: str


class CorrectionBatch(BaseModel):
    corrections: list[CorrectionIn]


def _check_upload(upload: UploadFile, body: bytes, document_tag: str) -> None:
    if document_tag not in doc_types.type_ids():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown document type: {document_tag}")
    if len(body) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Files must be under {settings.max_upload_mb} MB")
    if upload.content_type and upload.content_type not in settings.allowed_types:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Upload a PDF, JPG, PNG or HEIC")


@router.post("/classify")
async def classify_only(
    file: UploadFile = UploadField(...),
    document_tag: str = Form(...),
    customer: Customer = Depends(current_customer),
) -> dict:
    """Stage 1. Nothing is stored: the file is still on the customer's device
    as far as the application is concerned, and this is only advice."""
    body = await file.read()
    _check_upload(file, body, document_tag)
    return classifier.classify(body=body, content_type=file.content_type,
                               name=file.filename or "upload", selected_type=document_tag)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = UploadField(...),
    document_tag: str = Form(...),
    application_id: UUID | None = Form(default=None),
    confirmed_mismatch: bool = Form(default=False),
    logical_path: str = Form(default="/"),
    db: Session = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> dict:
    """Store the file, then queue it. The customer pressed Upload, so their
    choice of category is what we record, even when stage 1 disagreed."""
    body = await file.read()
    _check_upload(file, body, document_tag)
    _check_application(db, application_id, customer)
    existing = db.scalar(select(File).where(
        File.customer_id == customer.customer_id, File.checksum == storage.checksum(body)))
    if existing:
        return {"file_id": str(existing.file_id), "status": existing.status,
                "duplicate_of": str(existing.file_id),
                "message": "You have already uploaded this file."}
    row = _store_file(db, customer, file, body, document_tag, application_id, logical_path)
    audit.record(db, action="document.uploaded", customer_id=customer.customer_id,
                 application_id=application_id, file_id=row.file_id,
                 payload={"document_tag": document_tag, "confirmed_mismatch": confirmed_mismatch})
    db.commit()
    _queue_file(row)
    return {"file_id": str(row.file_id), "status": row.status,
            "document_tag": row.document_tag, "original_name": row.original_name}


def _check_application(db: Session, application_id: UUID | None, customer: Customer) -> None:
    """A file can only be attached to the caller's own application."""
    if application_id is None:
        return
    app = db.get(Application, application_id)
    if app is None or app.customer_id != customer.customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")


def _store_file(db: Session, customer: Customer, upload: UploadFile, body: bytes, document_tag: str,
                application_id: UUID | None, logical_path: str) -> File:
    """Put the bytes in object storage (flat key) and add the file row."""
    row = File(
        file_id=uuid.uuid4(), customer_id=customer.customer_id, application_id=application_id,
        document_tag=document_tag, original_name=upload.filename or "upload",
        content_type=upload.content_type, size_bytes=len(body), checksum=storage.checksum(body),
        storage_key="", logical_path=logical_path or "/", status="queued",
    )
    row.storage_key = storage.storage_key(row.file_id, row.original_name)
    storage.put_object(row.storage_key, body, upload.content_type)
    db.add(row)
    return row


def _queue_file(row: File) -> None:
    """Hand the file to the worker. If the queue is down the file is still safe in storage."""
    try:
        queue.publish_extraction_job(
            customer_id=row.customer_id, application_id=row.application_id,
            file_id=row.file_id, document_tag=row.document_tag, trace_id=str(uuid.uuid4()))
    except Exception as exc:
        log.error("could not queue %s: %s", row.file_id, exc)


@router.get("")
def list_documents(application_id: UUID | None = None, document_tag: str | None = None,
                   db: Session = Depends(get_db),
                   customer: Customer = Depends(current_customer)) -> list[dict]:
    """The vault. Scoped to the caller, always."""
    stmt = select(File).where(File.customer_id == customer.customer_id)
    if application_id:
        stmt = stmt.where(File.application_id == application_id)
    if document_tag:
        stmt = stmt.where(File.document_tag == document_tag)
    rows = db.scalars(stmt.order_by(File.uploaded_at.desc())).all()
    return [_summary(db, r) for r in rows]


@router.get("/{file_id}")
def get_document(file_id: UUID, db: Session = Depends(get_db),
                 customer: Customer = Depends(current_customer)) -> dict:
    row = _owned_file(db, file_id, customer)
    detail = _summary(db, row)
    detail["extractions"] = [{
        "extraction_id": str(e.extraction_id), "field_name": e.field_name,
        "value": e.corrected_value or e.value_normalized or e.value_raw,
        "value_raw": e.value_raw, "corrected_value": e.corrected_value,
        "page": e.page, "evidence_quote": e.evidence_quote, "method": e.method,
        "review_state": e.review_state,
    } for e in db.scalars(select(Extraction).where(Extraction.file_id == file_id))]
    detail["missing_fields"] = _missing_fields(detail["document_tag"], detail["extractions"])
    return detail


def _missing_fields(document_tag: str, found: list[dict]) -> list[str]:
    """Named explicitly so the screen can separate them from blanks."""
    spec = doc_types.get_type(document_tag)
    if not spec:
        return []
    have = {e["field_name"] for e in found if e["value"]}
    return [name for name in spec["extract"] if name not in have]


@router.get("/{file_id}/content")
def content(file_id: UUID, db: Session = Depends(get_db),
            customer: Customer = Depends(current_customer)) -> Response:
    row = _owned_file(db, file_id, customer)
    return Response(content=storage.get_object(row.storage_key),
                    media_type=row.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{row.original_name}"'})


@router.get("/{file_id}/status")
def document_status(file_id: UUID, db: Session = Depends(get_db),
                    customer: Customer = Depends(current_customer)) -> dict:
    row = _owned_file(db, file_id, customer)
    cls = db.get(FileClassification, file_id)
    return {"file_id": str(file_id), "status": row.status, "error": row.error_detail,
            "classification": _classification(cls)}


@router.patch("/{file_id}/extractions")
def correct(file_id: UUID, batch: CorrectionBatch, db: Session = Depends(get_db),
            customer: Customer = Depends(current_customer)) -> dict:
    """A correction never destroys what the model read."""
    row = _owned_file(db, file_id, customer)
    changed = 0
    for item in batch.corrections:
        ext = db.get(Extraction, item.extraction_id)
        if ext is None or ext.file_id != file_id:
            continue
        ext.corrected_value = item.value
        ext.review_state = "corrected"
        changed += 1

    audit.record(db, action="extraction.corrected", customer_id=customer.customer_id,
                 application_id=row.application_id, file_id=file_id,
                 payload={"count": changed})
    db.commit()

    from app.services import prefill          # local import avoids a cycle
    prefill.apply_file(db, file=row)
    return {"corrected": changed}


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink(file_id: UUID, db: Session = Depends(get_db),
           customer: Customer = Depends(current_customer)) -> Response:
    """Unlink from the application. The file stays in the vault, as the
    customer's own copy, which is the whole point of having one."""
    row = _owned_file(db, file_id, customer)
    _editable_link(db, row)
    _clear_proposals(db, row)
    row.application_id = None
    audit.record(db, action="document.unlinked", customer_id=customer.customer_id,
                 file_id=file_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class LinkIn(BaseModel):
    application_id: UUID


def _editable_link(db: Session, row: File) -> None:
    if row.application_id:
        app = db.get(Application, row.application_id)
        if app and app.status != "draft":
            raise HTTPException(409, "Submitted application documents cannot be removed.")


def _clear_proposals(db: Session, row: File) -> None:
    """Remove unconfirmed proposals only; customer-owned values survive."""
    if not row.application_id:
        return
    db.execute(delete(ApplicationField).where(
        ApplicationField.application_id == row.application_id,
        ApplicationField.file_id == row.file_id,
        ApplicationField.review_state == "proposed"))
    for model in (Employment, Asset):
        db.execute(delete(model).where(model.application_id == row.application_id,
                                       model.source_file_id == row.file_id))


@router.post("/{file_id}/link")
def link_document(file_id: UUID, body: LinkIn, db: Session = Depends(get_db),
                  customer: Customer = Depends(current_customer)) -> dict:
    row = _owned_file(db, file_id, customer)
    app = db.get(Application, body.application_id)
    if not app or app.customer_id != customer.customer_id:
        raise HTTPException(404, "Application not found")
    if app.status != "draft":
        raise HTTPException(409, "Documents can only be added to a draft application.")
    if row.application_id and row.application_id != app.application_id:
        raise HTTPException(409, "This document is already linked to another application.")
    row.application_id = app.application_id
    audit.record(db, action="document.linked", customer_id=customer.customer_id,
                 application_id=app.application_id, file_id=file_id)
    db.commit()
    from app.services import prefill
    if row.status == "completed":
        prefill.apply_file(db, file=row)
    return {"file_id": str(file_id), "application_id": str(app.application_id)}


@router.delete("/{file_id}/permanent", status_code=204)
def delete_permanently(file_id: UUID, db: Session = Depends(get_db),
                       customer: Customer = Depends(current_customer)) -> Response:
    row = _owned_file(db, file_id, customer)
    _editable_link(db, row)
    if row.status in ("queued", "processing"):
        raise HTTPException(409, "Wait for document processing to finish before deleting.")
    _clear_proposals(db, row)
    _detach_confirmed_values(db, file_id)
    _delete_markdown(db, file_id)
    storage.delete_object(row.storage_key)
    audit.record(db, action="document.deleted", customer_id=customer.customer_id,
                 application_id=row.application_id, file_id=file_id)
    db.delete(row)  # PostgreSQL cascades classification, extraction, markdown and vectors.
    db.commit()
    return Response(status_code=204)


def _detach_confirmed_values(db: Session, file_id: UUID) -> None:
    """Retained customer-confirmed values no longer refer to deleted evidence."""
    for field in db.scalars(select(ApplicationField).where(ApplicationField.file_id == file_id)):
        field.file_id = None
        field.evidence_quote = None
        field.page = None
        field.method = None


def _delete_markdown(db: Session, file_id: UUID) -> None:
    md = db.get(DocumentMarkdown, file_id)
    if not md:
        return
    directory = Path(settings.markdown_dir).resolve()
    path = Path(md.markdown_path).resolve()
    if path.parent != directory or path.name != f"{file_id}.md":
        raise HTTPException(500, "Document storage path is invalid.")
    path.unlink(missing_ok=True)


def _owned_file(db: Session, file_id: UUID, customer: Customer) -> File:
    row = db.get(File, file_id)
    if row is None or row.customer_id != customer.customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return row


def _classification(cls: FileClassification | None) -> dict | None:
    if cls is None:
        return None
    return {"selected_type": cls.selected_type, "detected_type": cls.detected_type,
            "outcome": cls.outcome, "evidence": cls.evidence,
            "mixed_document": cls.mixed_document, "model": cls.model_name}


def _summary(db: Session, row: File) -> dict:
    cls = db.get(FileClassification, row.file_id)
    md = db.get(DocumentMarkdown, row.file_id)
    found = [{"field_name": e.field_name, "value": e.corrected_value or e.value_normalized or e.value_raw}
             for e in db.scalars(select(Extraction).where(Extraction.file_id == row.file_id))]
    missing = _missing_fields(row.document_tag, found)
    return {
        "extracted_field_count": sum(bool(e["value"]) for e in found),
        "missing_field_count": len(missing),
        "file_id": str(row.file_id), "document_tag": row.document_tag,
        "display_name": doc_types.display_name(row.document_tag),
        "original_name": row.original_name, "content_type": row.content_type,
        "size_bytes": row.size_bytes, "page_count": row.page_count,
        "logical_path": row.logical_path, "status": row.status,
        "error": row.error_detail,
        "application_id": str(row.application_id) if row.application_id else None,
        "application_status": (db.get(Application, row.application_id).status if row.application_id and db.get(Application, row.application_id) else None),
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
        "classification": _classification(cls),
        "has_markdown": md is not None,
    }
