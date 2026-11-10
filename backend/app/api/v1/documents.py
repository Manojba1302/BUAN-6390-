"""Documents: the classify pre-check, the upload, the vault and corrections."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from uuid import UUID

import money_values
import doc_types
from fastapi import APIRouter, Depends, File as UploadField, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select, delete, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import current_customer
from app.db.models import (
    Application, ApplicationField, Asset, Employment, Customer, AuditEvent, DocumentMarkdown, Extraction, File, FileClassification,
)
from app.db.models import SubmissionRecord
from app.db.session import get_db
from app.services import attachments, audit, classifier, queue, storage, saved_document_evidence, vault_folders, versions

log = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


class CorrectionIn(BaseModel):
    extraction_id: UUID | None = None
    field_name: str | None = None
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
    return await run_in_threadpool(classifier.classify, body=body, content_type=file.content_type,
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
    document_label: str | None = Form(default=None),
    auto_type: bool = Form(default=False),
) -> dict:
    """Store the file, then queue it. The customer pressed Upload, so their
    choice of category is what we record, even when stage 1 disagreed."""
    body = await file.read()
    _check_upload(file, body, document_tag)
    _check_application(db, application_id, customer)
    existing = db.scalar(select(File).where(
        File.customer_id == customer.customer_id, File.checksum == storage.checksum(body)))
    if existing:
        return _reuse_upload(db, existing, application_id, customer)
    path = vault_folders.path_for_upload(db, customer.customer_id, logical_path, document_tag)
    row = _store_file(db, customer, file, body, document_tag, application_id, path)
    db.flush()
    if application_id:
        attachments.attach(db, row, application_id)
    vault_folders.set_label(db, row.file_id, document_label)
    audit.record(db, action="document.uploaded", customer_id=customer.customer_id,
                 application_id=application_id, file_id=row.file_id,
                 payload={"document_tag": document_tag, "label": document_label, "confirmed_mismatch": confirmed_mismatch})
    db.commit()
    _queue_file(db, row, mode="auto" if auto_type and document_tag == "other" else "read")
    return {"file_id": str(row.file_id), "status": row.status,
            "document_tag": row.document_tag, "original_name": row.original_name}


def _check_application(db: Session, application_id: UUID | None, customer: Customer) -> None:
    """A file can only be attached to the caller's own application."""
    if application_id is None:
        return
    app = db.get(Application, application_id, with_for_update=True)
    if app is None or app.customer_id != customer.customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if app.status != "draft":
        raise HTTPException(409, "Documents can only be added to a draft application.")


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


def _queue_file(db: Session, row: File, mode: str = "read") -> None:
    """Hand the file to the worker. If the queue is down the file is still safe in storage."""
    try:
        queue.publish_extraction_job(
            customer_id=row.customer_id, application_id=row.application_id, file_id=row.file_id,
            document_tag=row.document_tag, trace_id=str(uuid.uuid4()), mode=mode)
    except Exception as exc:
        log.error("could not queue %s: %s", row.file_id, exc)
        row.status, row.error_detail = "failed", "Could not start document processing. Please retry."
        db.commit()


@router.get("")
def list_documents(application_id: UUID | None = None, document_tag: str | None = None,
                   db: Session = Depends(get_db),
                   customer: Customer = Depends(current_customer)) -> list[dict]:
    """The vault. Scoped to the caller, always."""
    stmt = select(File).where(File.customer_id == customer.customer_id)
    if application_id:
        app = db.get(Application, application_id)
        if app and app.customer_id == customer.customer_id and app.status == "submitted":
            frozen = db.get(SubmissionRecord, application_id)
            if frozen:
                return [d for d in frozen.documents if not document_tag or d["document_tag"] == document_tag]
    else:
        stmt = stmt.where(versions.current_only())
    if application_id:
        stmt = stmt.where(attachments.attached_to(application_id))
    if document_tag:
        stmt = stmt.where(File.document_tag == document_tag)
    rows = db.scalars(stmt.order_by(File.uploaded_at.desc())).all()
    return [_summary(db, r) for r in rows]


class FolderIn(BaseModel):
    name: str


class MoveIn(BaseModel):
    folder: str


@router.get("/folders")
def list_folders(db: Session = Depends(get_db), customer: Customer = Depends(current_customer)) -> list[dict]:
    """The vault's folders, with how many files each holds. Declared before /{file_id}."""
    return vault_folders.listing(db, customer.customer_id)


@router.post("/folders", status_code=status.HTTP_201_CREATED)
def add_folder(body: FolderIn, db: Session = Depends(get_db),
               customer: Customer = Depends(current_customer)) -> dict:
    name = vault_folders.create(db, customer.customer_id, body.name)
    return {"name": name, "default": False, "count": 0}


@router.delete("/folders/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(name: str, db: Session = Depends(get_db),
                  customer: Customer = Depends(current_customer)) -> Response:
    """Only folders the customer made. Their files move back to their usual folder."""
    vault_folders.remove(db, customer.customer_id, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{file_id}/folder")
def move_document(file_id: UUID, body: MoveIn, db: Session = Depends(get_db),
                  customer: Customer = Depends(current_customer)) -> dict:
    row = _owned_file(db, file_id, customer)
    folder = vault_folders.resolve(db, customer.customer_id, body.folder)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    row.logical_path = "/" + folder
    audit.record(db, action="document.moved", customer_id=customer.customer_id,
                 application_id=row.application_id, file_id=file_id, payload={"folder": folder})
    db.commit()
    return _summary(db, row)


@router.get("/{file_id}")
def get_document(file_id: UUID, db: Session = Depends(get_db),
                 customer: Customer = Depends(current_customer)) -> dict:
    row = _owned_file(db, file_id, customer)
    saved_document_evidence.recover(db, row)
    detail = _summary(db, row)
    detail["extractions"] = [{
        "extraction_id": str(e.extraction_id), "field_name": e.field_name,
        "value": e.corrected_value if e.corrected_value is not None else (money_values.amount(e.field_name, e.value_raw or "", e.evidence_quote or "") or e.value_normalized or e.value_raw),
        "value_raw": e.value_raw, "corrected_value": e.corrected_value,
        "page": e.page, "evidence_quote": e.evidence_quote, "method": e.method,
        "review_state": e.review_state,
    } for e in db.scalars(select(Extraction).where(Extraction.file_id == file_id))]
    detail["missing_fields"] = _missing_fields(detail["document_tag"], detail["extractions"]) if row.application_id else []
    detail["can_retry"] = _retry_allowed(db, row)
    return detail


def _missing_fields(document_tag: str, found: list[dict]) -> list[str]:
    """Named explicitly so the screen can separate them from blanks."""
    spec = doc_types.get_type(document_tag)
    if not spec:
        return []
    have = {e["field_name"] for e in found if e["value"]}
    full_name_found = bool(have & {"full_name", "employee_name", "name"})
    return [name for name in spec["extract"] if name not in have and name not in spec.get("optional_extract", []) and not (full_name_found and name in ("first_name", "last_name"))]


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
        ext = _correction_extraction(db, row, item)
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


def _correction_extraction(db: Session, row: File, item: CorrectionIn) -> Extraction | None:
    if item.extraction_id:
        return db.get(Extraction, item.extraction_id)
    if item.field_name not in ("first_name", "last_name"):
        return None
    if item.field_name not in (doc_types.get_type(row.document_tag) or {}).get("extract", {}):
        raise HTTPException(400, "Name field not supported for this type")
    ext = db.scalar(select(Extraction).where(
        Extraction.file_id == row.file_id, Extraction.field_name == item.field_name))
    if ext is None:
        ext = Extraction(file_id=row.file_id, field_name=item.field_name, method=None)
        db.add(ext)
    return ext


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink(file_id: UUID, application_id: UUID | None = None, db: Session = Depends(get_db),
           customer: Customer = Depends(current_customer)) -> Response:
    """Remove from one application (the latest one when none is named). The file stays in the
    vault and in any other application it is attached to."""
    row = _owned_file(db, file_id, customer)
    target = application_id or row.application_id
    if not attachments.is_attached(db, row.file_id, target):
        raise HTTPException(404, "This document is not in that application.")
    _editable_link(db, target)
    _clear_proposals(db, row, target)
    attachments.detach(db, row, target)
    audit.record(db, action="document.unlinked", customer_id=customer.customer_id,
                 application_id=target, file_id=file_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class LinkIn(BaseModel):
    application_id: UUID


def _editable_link(db: Session, application_id: UUID | None) -> None:
    app = db.get(Application, application_id, with_for_update=True) if application_id else None
    if app and app.status != "draft":
        raise HTTPException(409, "Submitted application documents cannot be removed.")


def _clear_proposals(db: Session, row: File, application_id: UUID | None) -> None:
    """Remove this file's unconfirmed proposals from one application; customer-owned values survive."""
    if not application_id:
        return
    db.execute(delete(ApplicationField).where(
        ApplicationField.application_id == application_id,
        ApplicationField.file_id == row.file_id,
        ApplicationField.review_state == "proposed"))
    for model in (Employment, Asset):
        db.execute(delete(model).where(model.application_id == application_id,
                                       model.source_file_id == row.file_id))


@router.post("/{file_id}/link")
def link_document(file_id: UUID, body: LinkIn, db: Session = Depends(get_db),
                  customer: Customer = Depends(current_customer)) -> dict:
    row = _owned_file(db, file_id, customer)
    app = db.get(Application, body.application_id, with_for_update=True)
    if not app or app.customer_id != customer.customer_id:
        raise HTTPException(404, "Application not found")
    if app.status != "draft":
        raise HTTPException(409, "Documents can only be added to a draft application.")
    attachments.attach(db, row, app.application_id)     # the same document may be in other applications too
    audit.record(db, action="document.linked", customer_id=customer.customer_id,
                 application_id=app.application_id, file_id=file_id)
    db.commit()
    _after_attach(db, row, app.application_id)
    return {"file_id": str(file_id), "application_id": str(app.application_id), "status": row.status}


def _after_attach(db: Session, row: File, application_id: UUID) -> None:
    """Fields are pulled out when a loan document joins an application, from the text
    kept when it was first read. A file still being read is checked by the worker itself."""
    from app.services import prefill
    if row.status != "completed":
        return
    if not _needs_extraction(db, row):
        prefill.apply_file(db, file=row, application_id=application_id)
        return
    row.status, row.error_detail, row.attempts = "queued", None, 0
    db.commit()
    _queue_file(db, row, mode="extract")


def _needs_extraction(db: Session, row: File) -> bool:
    spec = doc_types.get_type(row.document_tag)
    if not spec or not spec.get("extract"):
        return False
    completed = db.scalar(select(AuditEvent.event_id).where(
        AuditEvent.file_id == row.file_id,
        AuditEvent.action == "document.fields_extracted",
        AuditEvent.payload["document_tag"].astext == row.document_tag).limit(1))
    return completed is None



class TypeIn(BaseModel):
    document_tag: str
    label: str | None = None


@router.patch("/{file_id}/type")
def change_type(file_id: UUID, body: TypeIn, db: Session = Depends(get_db),
                customer: Customer = Depends(current_customer)) -> dict:
    """Only a document saved as Other changes type; one picked from the list stays fixed."""
    row = _owned_file(db, file_id, customer)
    if row.document_tag != "other":
        raise HTTPException(409, "Only a document saved as Other can change type.")
    if body.document_tag not in doc_types.type_ids():
        raise HTTPException(400, f"Unknown document type: {body.document_tag}")
    if row.status in ("queued", "processing"):
        raise HTTPException(409, "Wait until the document has been read.")
    attached = [app.application_id for app in attachments.applications_of(db, row.file_id)]
    for application_id in attached:
        _editable_link(db, application_id)
    row.document_tag = body.document_tag
    _retype_label(db, row, body.label)
    audit.record(db, action="document.retyped", customer_id=customer.customer_id, application_id=row.application_id,
                 file_id=file_id, payload={"document_tag": body.document_tag, "label": body.label})
    db.commit()
    if attached:
        _after_attach(db, row, attached[-1])
    return _summary(db, row)


def _retype_label(db: Session, row: File, label: str | None) -> None:
    if row.document_tag == "other" and label and label.strip():
        vault_folders.set_label(db, row.file_id, label)
    elif row.document_tag != "other":
        vault_folders.clear_label(db, row.file_id)


@router.delete("/{file_id}/permanent", status_code=204)
def delete_permanently(file_id: UUID, db: Session = Depends(get_db),
                       customer: Customer = Depends(current_customer)) -> Response:
    """Delete the document and every earlier version, so no one can see any of them (Vijay, Oct 2026)."""
    row = _owned_file(db, file_id, customer)
    every = versions.chain(db, row.file_id)
    if any(f.status in ("queued", "processing") for f in every):
        raise HTTPException(409, "Wait for document processing to finish before deleting.")
    for version in every:
        for app in attachments.applications_of(db, version.file_id):
            db.refresh(app, with_for_update=True)
            if app.status != "draft" and not db.get(SubmissionRecord, app.application_id):
                raise HTTPException(409, "This earlier submission needs an archived copy before deletion.")
    for version in reversed(every):
        _delete_one(db, version, customer)
    db.commit()
    return Response(status_code=204)


def _delete_one(db: Session, row: File, customer: Customer) -> None:
    for app in attachments.applications_of(db, row.file_id):
        db.refresh(app, with_for_update=True)
        if app.status != "draft":
            if not db.get(SubmissionRecord, app.application_id):
                raise HTTPException(409, "This earlier submission needs an archived copy before deletion.")
            continue
        _clear_proposals(db, row, app.application_id)
    _detach_confirmed_values(db, row.file_id)
    _delete_markdown(db, row.file_id)
    storage.delete_object(row.storage_key)
    audit.record(db, action="document.deleted", customer_id=customer.customer_id,
                 application_id=row.application_id, file_id=row.file_id)
    db.delete(row)  # PostgreSQL cascades classification, extraction, markdown, vectors and links.
    db.flush()


@router.post("/{file_id}/replace", status_code=status.HTTP_201_CREATED)
async def replace(file_id: UUID, file: UploadFile = UploadField(...), db: Session = Depends(get_db),
                  customer: Customer = Depends(current_customer)) -> dict:
    """Create a vault version and move draft applications to it."""
    old = _replaceable(db, file_id, customer)
    body = await file.read()
    _check_upload(file, body, old.document_tag)
    if db.scalar(select(File.file_id).where(File.customer_id == customer.customer_id, File.checksum == storage.checksum(body))):
        raise HTTPException(409, "That file is already in your vault. Choose the new version of the document.")
    new = _store_file(db, customer, file, body, old.document_tag, None, old.logical_path)
    db.flush()
    versions.record(db, new.file_id, old.file_id)
    vault_folders.set_label(db, new.file_id, vault_folders.label_of(db, old.file_id))
    moved = _move_attachments(db, old, new)
    audit.record(db, action="document.replaced", customer_id=customer.customer_id, application_id=new.application_id,
                 file_id=new.file_id, payload={"previous_file_id": str(old.file_id), "applications": moved})
    db.commit()
    _queue_file(db, new)
    return _summary(db, new)


def _replaceable(db: Session, file_id: UUID, customer: Customer) -> File:
    row = _owned_file(db, file_id, customer)
    if versions.newer_than(db, row.file_id):
        raise HTTPException(409, "A newer version of this document exists. Replace that one instead.")
    if row.status in ("queued", "processing"):
        raise HTTPException(409, "Wait until the document has been read.")
    return row


def _move_attachments(db: Session, old: File, new: File) -> list[str]:
    """Keep each submission pinned to its original version."""
    moved = []
    for app in attachments.applications_of(db, old.file_id):
        db.refresh(app, with_for_update=True)
        if app.status != "draft":
            continue
        _clear_proposals(db, old, app.application_id)
        attachments.attach(db, new, app.application_id)
        attachments.detach(db, old, app.application_id)
        moved.append(str(app.application_id))
    return moved


@router.get("/{file_id}/versions")
def list_versions(file_id: UUID, db: Session = Depends(get_db),
                  customer: Customer = Depends(current_customer)) -> list[dict]:
    """Every version of the document, oldest first. Earlier versions stay viewable by the customer."""
    every = versions.chain(db, _owned_file(db, file_id, customer).file_id)
    return [{"file_id": str(f.file_id), "version": i + 1, "original_name": f.original_name,
             "size_bytes": f.size_bytes, "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
             "current": i == len(every) - 1} for i, f in enumerate(every)]


def _detach_confirmed_values(db: Session, file_id: UUID) -> None:
    """Retained customer-confirmed values no longer refer to deleted evidence."""
    for field in db.scalars(select(ApplicationField).where(ApplicationField.file_id == file_id)):
        field.file_id = None
        field.evidence_quote = None
        field.page = None
        field.method = None


def _delete_markdown(db: Session, file_id: UUID) -> None:
    (Path(settings.markdown_dir) / f"{file_id}.pages.json").unlink(missing_ok=True)   # text kept for extraction
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
    missing = _missing_fields(row.document_tag, found) if row.application_id else []   # fields come at attach
    return {
        "extracted_field_count": sum(bool(e["value"]) for e in found),
        "missing_field_count": len(missing),
        "file_id": str(row.file_id), "document_tag": row.document_tag,
        "display_name": doc_types.display_name(row.document_tag),
        "original_name": row.original_name, "content_type": row.content_type,
        "size_bytes": row.size_bytes, "page_count": row.page_count, "logical_path": row.logical_path, "status": row.status,
        "folder": vault_folders.folder_of(row.logical_path, row.document_tag), "error": row.error_detail, "label": vault_folders.label_of(db, row.file_id),
        "application_id": str(row.application_id) if row.application_id else None,
        "application_status": (db.get(Application, row.application_id).status if row.application_id and db.get(Application, row.application_id) else None),
        "applications": [{"application_id": str(a.application_id), "status": a.status} for a in attachments.applications_of(db, row.file_id)],
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
        "classification": _classification(cls), "has_markdown": md is not None, "searchable": not _unindexed(db, row),
        "version": versions.number(db, row.file_id),
    }


@router.post("/{file_id}/retry", status_code=204)
def retry_document(file_id: UUID, db: Session=Depends(get_db), customer: Customer=Depends(current_customer)):
    row = db.scalar(select(File).where(File.file_id==file_id,File.customer_id==customer.customer_id).with_for_update())
    if row is None:
        raise HTTPException(404,"Document not found")
    if not _retry_allowed(db, row):
        raise HTTPException(409,"Only failed or incomplete documents can be read again")
    row.status, row.error_detail, row.attempts = "queued", None, 0
    db.commit()
    try:
        queue.publish_extraction_job(customer_id=row.customer_id,application_id=row.application_id,file_id=row.file_id,document_tag=row.document_tag,trace_id=str(uuid.uuid4()))
    except Exception:
        row.status, row.error_detail = "failed", "Could not queue processing"
        db.commit()
        raise HTTPException(503,"Could not restart document processing")


# The fields that make a read useful. A completed read missing any of them can be read again
# from the saved file, which is the only way to re-read it: uploading the same file reuses it.
KEY_FIELDS = {
    "w2": ("employee_name", "employer_name", "box1_wages"),
    "paystub": ("employee_name", "employer_name", "gross_pay", "pay_date"),
    "bank_statement": ("account_holder", "ending_balance", "period_end"),
    "drivers_license": ("full_name", "date_of_birth", "license_number", "expiry_date"),
    "ssn_card": ("full_name", "ssn"),
}


def _unindexed(db, row) -> bool:
    """Read, but part of its text did not make it into the search index (the model was busy or down)."""
    return row.status == "completed" and bool(db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM document_chunk WHERE file_id = :f AND embedding IS NULL) "
        "OR (EXISTS (SELECT 1 FROM document_markdown WHERE file_id = :f) "
        "AND NOT EXISTS (SELECT 1 FROM document_chunk WHERE file_id = :f))"), {"f": row.file_id}))


def _retry_allowed(db, row):
    if row.status == "failed" or _unindexed(db, row):
        return True
    if row.status != "completed" or row.document_tag not in KEY_FIELDS or not row.application_id:
        return False
    rows = db.scalars(select(Extraction).where(Extraction.file_id == row.file_id)).all()
    have = {e.field_name for e in rows if (e.corrected_value if e.corrected_value is not None else e.value_normalized or e.value_raw)}
    return not set(KEY_FIELDS[row.document_tag]).issubset(have)


def _reuse_upload(db, existing, application_id, customer):
    # Pressing Upload for this application also authorizes reusing an owned vault copy.
    if versions.newer_than(db, existing.file_id):
        raise HTTPException(409, "This file is an earlier version of a document in your vault. Open that document to see its versions.")
    if application_id and not attachments.is_attached(db, existing.file_id, application_id):
        link_document(existing.file_id, LinkIn(application_id=application_id), db, customer)
    return {"file_id": str(existing.file_id), "status": existing.status,
            "duplicate_of": str(existing.file_id),
            "application_id": str(application_id if application_id else existing.application_id) if (application_id or existing.application_id) else None,
            "message": "Your existing file has been reused; no duplicate was uploaded."}
