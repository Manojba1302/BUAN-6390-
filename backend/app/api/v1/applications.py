"""The application itself: create, load, save, progress, prefill, submit."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.api.v1.fields import _dictionary
from app.db.models import (
    Application, ApplicationField, Asset, ChecklistRequirement, Customer,
    Declaration, Employment, Extraction, File, Liability,
)
from app.core.security import current_customer
from app.db.session import get_db
from app.services import audit, income_validation, employment_suggestions, address_suggestions, name_suggestions, prefill as prefill_service
from fastapi.encoders import jsonable_encoder
from urllib.parse import quote
from app.db.models import SubmissionFile, SubmissionRecord
from app.services import attachments, storage, versions

router = APIRouter(prefix="/applications", tags=["applications"])

REPEATABLE_MODELS = {"employment": Employment, "asset": Asset, "liability": Liability}


class ApplicationPatch(BaseModel):
    fields: dict[str, str | None] = Field(default_factory=dict)
    declarations: dict[str, str] = Field(default_factory=dict)
    employment: list[dict] | None = None
    asset: list[dict] | None = None
    liability: list[dict] | None = None
    current_step: int | None = None


def _owned(db: Session, application_id: UUID, customer: Customer) -> Application:
    app = db.get(Application, application_id)
    if app is None or app.customer_id != customer.customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return app


@router.post("", status_code=status.HTTP_201_CREATED)
def create_application(customer: Customer = Depends(current_customer)) -> dict:
    """Applications start only from a lender's invitation (lender_link.select_application), so each one belongs to a loan."""
    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        "Applications start from your loan officer's invitation. Open the link in their email to begin.")


@router.get("")
def list_applications(db: Session = Depends(get_db),
                      customer: Customer = Depends(current_customer)) -> list[dict]:
    rows = db.scalars(select(Application)
                      .where(Application.customer_id == customer.customer_id)
                      .order_by(Application.created_at.desc())).all()
    return [{"application_id": str(a.application_id), "status": a.status, "purpose": _purpose(db, a),
             "current_step": a.current_step, "created_at": a.created_at.isoformat()} for a in rows]


def _purpose(db: Session, app: Application) -> str | None:
    """What the loan is for ("Purchase", a refinance), as chosen in Get started."""
    field = db.get(ApplicationField, (app.application_id, "loanPurpose"))
    return field.value if field and field.value else None


@router.get("/{application_id}/checklist")
def checklist(application_id: UUID, db: Session = Depends(get_db),
              customer: Customer = Depends(current_customer)) -> list[dict]:
    """The loan card on the vault page: each document this loan needs, how many are in, and which files."""
    app = _owned(db, application_id, customer)
    frozen = db.get(SubmissionRecord, application_id) if app.status == "submitted" else None
    if frozen:
        return frozen.checklist
    return [_checklist_row(db, app, req) for req in _requirements(db, app)]


def _checklist_row(db: Session, app: Application, req: ChecklistRequirement) -> dict:
    files = db.scalars(select(File).where(attachments.attached_to(app.application_id),
                                          File.document_tag == req.document_tag).order_by(File.uploaded_at)).all()
    return {"document_tag": req.document_tag, "display_name": req.display_name, "need": req.required_count,
            **document_counts(db, app.application_id, req.document_tag),
            "files": [{"file_id": str(f.file_id), "original_name": f.original_name, "status": f.status} for f in files]}


@router.get("/{application_id}")
def get_application(application_id: UUID, db: Session = Depends(get_db),
                    customer: Customer = Depends(current_customer)) -> dict:
    app = _owned(db, application_id, customer)
    frozen = db.get(SubmissionRecord, application_id) if app.status == "submitted" else None
    if frozen:
        return frozen.state
    return _serialise(db, app)


ACCOUNT_FIELDS = {"firstName": "first_name", "lastName": "last_name", "email": "email"}


def _account_defaults(db: Session, app: Application, customer: Customer) -> bool:
    """Start the form with the name and email given at sign-up.

    Only fields the application has never had are filled, so anything the
    customer typed, cleared or chose from a document is left alone.
    """
    existing = set(db.scalars(select(ApplicationField.field_name).where(
        ApplicationField.application_id == app.application_id,
        ApplicationField.field_name.in_(ACCOUNT_FIELDS))).all())
    added = False
    for field, attribute in ACCOUNT_FIELDS.items():
        value = (getattr(customer, attribute) or "").strip()
        if field not in existing and value:
            db.add(ApplicationField(application_id=app.application_id, field_name=field, value=value, source="user", review_state="confirmed"))
            added = True
    return added


@router.patch("/{application_id}")
def patch_application(application_id: UUID, patch: ApplicationPatch,
                      db: Session = Depends(get_db),
                      customer: Customer = Depends(current_customer)) -> dict:
    app = _owned(db, application_id, customer)
    db.refresh(app, with_for_update=True)
    if app.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "A submitted application cannot be edited")

    if patch.employment is not None:
        patch.employment = income_validation.clean_rows(patch.employment)
    _save_fields(db, app, patch.fields)
    _save_declarations(db, app, patch.declarations)
    for name, model in REPEATABLE_MODELS.items():
        rows = getattr(patch, name)
        if rows is not None:
            _replace_repeatable(db, app, model, rows)

    if patch.current_step is not None:
        app.current_step = patch.current_step
    if "loanPurpose" in patch.fields:
        app.loan_purpose = patch.fields["loanPurpose"]
    db.commit()
    return _serialise(db, app)


def _save_fields(db: Session, app: Application, values: dict[str, str | None]) -> None:
    """A value the customer typed is theirs: it becomes confirmed, and a later
    document can no longer overwrite it."""
    for name, value in values.items():
        row = db.get(ApplicationField, (app.application_id, name))
        if row is None:
            row = ApplicationField(application_id=app.application_id, field_name=name)
            db.add(row)
        row.value = value
        row.source = "user"
        row.review_state = "corrected" if row.file_id else "confirmed"
        row.updated_at = datetime.now(timezone.utc)


def _save_declarations(db: Session, app: Application, answers: dict[str, str]) -> None:
    for code, answer in answers.items():
        row = db.get(Declaration, (app.application_id, code))
        if row is None:
            db.add(Declaration(application_id=app.application_id, code=code, answer=answer))
        else:
            row.answer = answer


def _replace_repeatable(db: Session, app: Application, model, rows: list[dict]) -> None:
    """Simple and predictable: the client owns the list, we store what it sends."""
    for existing in db.scalars(select(model).where(model.application_id == app.application_id)):
        db.delete(existing)
    db.flush()
    columns = {c.name for c in model.__table__.columns}
    for row in rows:
        clean = {k: v for k, v in row.items() if k in columns and k != "application_id"}
        clean.pop(f"{model.__tablename__}_id", None)
        clean.pop("source_file_id", None)  # Saving confirms the customer owns these values.
        db.add(model(application_id=app.application_id, **clean))


def _serialise(db: Session, app: Application) -> dict:
    out = {
        "application_id": str(app.application_id),
        "customer_id": str(app.customer_id),
        "status": app.status,
        "current_step": app.current_step,
        "fields": _serialise_fields(db, app),
        "name_suggestions": name_suggestions.suggestions(db, app),
        "address_suggestions": address_suggestions.suggestions(db, app),
        "employment_suggestions": employment_suggestions.suggestions(db, app),
        "declarations": {
            d.code: d.answer for d in db.scalars(
                select(Declaration).where(Declaration.application_id == app.application_id))
        },
    }
    for name, model in REPEATABLE_MODELS.items():      # employment, asset, liability
        out[name] = [_row(r) for r in db.scalars(select(model).where(model.application_id == app.application_id))]
    return out


def _serialise_fields(db: Session, app: Application) -> dict:
    fields = db.scalars(select(ApplicationField)
                        .where(ApplicationField.application_id == app.application_id)).all()
    return {
        f.field_name: {
            "value": f.value,
            "source": f.source,
            "review_state": f.review_state,
            "file_id": str(f.file_id) if f.file_id else None,
            "page": f.page,
            "evidence_quote": f.evidence_quote,
            "method": f.method,
        } for f in fields if not _obsolete_proposal(app, f)
    }


def _obsolete_proposal(app, field):
    return (app.status == "draft" and field.source == "extracted" and field.review_state == "proposed"
            and field.field_name in prefill_service.REVIEW_FIELDS)


def _row(obj) -> dict:
    out = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name)
        out[col.name] = str(value) if value is not None and col.name.endswith("_id") else value
    return out


@router.get("/{application_id}/progress")
def progress(application_id: UUID, db: Session = Depends(get_db),
             customer: Customer = Depends(current_customer)) -> dict:
    """What the tracker draws: per step, what is still missing."""
    app = _owned(db, application_id, customer)
    frozen = db.get(SubmissionRecord, application_id) if app.status == "submitted" else None
    if frozen:
        return frozen.progress
    data = _serialise(db, app)
    values = {k: v["value"] for k, v in data["fields"].items()}
    steps = [_step_status(db, app, step, data, values) for step in _dictionary()["steps"]]
    total = sum(len(s["missing"]) for s in steps)
    return {"steps": steps, "complete": total == 0,
            "percent": _percent(steps), "status": app.status}


def _step_status(db: Session, app: Application, step: dict, data: dict, values: dict) -> dict:
    missing = _missing_fields(step["id"], values) + _step_extras(db, app, step["id"], data, values)
    return {"id": step["id"], "label": step["label"], "complete": not missing, "missing": missing}


def _missing_fields(step_id: str, values: dict) -> list[str]:
    """Required fields on this step that are visible and still empty."""
    return [
        name for name, spec in _dictionary()["fields"].items()
        if spec.get("step") == step_id and spec.get("required")
        and (not spec.get("visible_if") or values.get(spec["visible_if"]["field"]) == spec["visible_if"]["equals"])
        and not (values.get(name) or "").strip()
    ]


def _step_extras(db: Session, app: Application, step_id: str, data: dict, values: dict) -> list[str]:
    """Checks beyond single fields: documents, declarations, employers and income."""
    if step_id == "documents":
        return [c["display_name"] for c in _missing_documents(db, app)]
    if step_id == "review":
        answered = set(data["declarations"])
        return [f"Declaration {d['code']}" for d in _dictionary()["declarations"] if d["code"] not in answered]
    if step_id == "money":
        extra = ["At least one employer"] if values.get("employmentStatus") == "Employed" and not data["employment"] else []
        return extra + _income_errors(values, data["employment"])
    return []


INCOME_AMOUNT_FIELDS = ("selfEmploymentIncome", "pensionIncome", "socialSecurityIncome", "retirementIncome",
                        "notEmployedIncome", "otherSituationIncome", "additionalIncomeAmount")
REQUIRED_INCOME = {"Self-employed": ["selfEmploymentIncome"],
                   "Retired": ["pensionIncome", "socialSecurityIncome", "retirementIncome"],
                   "Not currently employed": ["notEmployedIncome"], "Other": ["otherSituationIncome"]}


def _income_errors(values: dict, employment: list) -> list[str]:
    """Every income problem, in the order the customer sees them on the page."""
    return _situation_errors(values) + _amount_errors(values) + _employment_errors(values, employment)


def _situation_errors(values: dict) -> list[str]:
    if not values.get("employmentStatus"):
        return ["Choose your employment situation in Get started"]
    if values.get("employmentStatus") != "Self-employed":
        return []
    try:
        if not 0 <= float(values.get("ownershipPercent", "")) <= 100:
            return ["Ownership percentage must be between 0 and 100"]
    except ValueError:
        return ["Enter a valid ownership percentage"]
    return []


def _amount_errors(values: dict) -> list[str]:
    """Visible income amounts must be valid, non-negative numbers."""
    errors = []
    for name in INCOME_AMOUNT_FIELDS:
        spec = _dictionary()["fields"][name]
        condition = spec.get("visible_if")
        if (condition and values.get(condition["field"]) != condition["equals"]) or not values.get(name):
            continue
        try:
            amount = float(values[name].replace(",", "").replace("$", ""))
            if not math.isfinite(amount) or amount < 0:
                errors.append(spec["label"] + " must be a nonnegative amount")
        except ValueError:
            errors.append("Enter a valid " + spec["label"].lower())
    return errors


def _employment_errors(values: dict, employment: list) -> list[str]:
    status = values.get("employmentStatus")
    errors = income_validation.employment_errors(employment, status == "Employed")
    if status in REQUIRED_INCOME and not any(str(values.get(n) or "").strip() for n in REQUIRED_INCOME[status]):
        errors.append("Enter monthly income, or 0 if none")
    return errors


def _percent(steps: list[dict]) -> int:
    done = sum(1 for s in steps if s["complete"])
    return int(done / max(len(steps), 1) * 100)


def _missing_documents(db: Session, app: Application) -> list[dict]:
    """A requirement is met by documents that were read, not merely uploaded. A mismatch is saved as
    Other and never counts for the type that was chosen."""
    out = []
    for req in _requirements(db, app):
        counts = document_counts(db, app.application_id, req.document_tag)
        if counts["have"] < req.required_count:
            out.append({"document_tag": req.document_tag, "display_name": req.display_name,
                        "need": req.required_count, **counts})
    return out


def _requirements(db: Session, app: Application) -> list[ChecklistRequirement]:
    """The documents this loan needs. W-2s and pay stubs only apply to someone employed."""
    requirements = db.scalars(select(ChecklistRequirement).order_by(ChecklistRequirement.sort_order)).all()
    income_status = db.get(ApplicationField, (app.application_id, "employmentStatus"))
    non_employee = income_status and income_status.value in {"Self-employed", "Retired", "Not currently employed", "Other"}
    return [r for r in requirements if not (non_employee and r.document_tag in {"w2", "paystub"})]


def document_counts(db: Session, application_id, document_tag: str) -> dict:
    """have: read, with fields pulled out. reading: still being read. unread: failed, or nothing could be read."""
    files = db.scalars(select(File).where(attachments.attached_to(application_id),
                                          File.document_tag == document_tag)).all()
    reading = sum(f.status in ("uploaded", "queued", "processing") for f in files)
    have = sum(f.status == "completed" and _was_read(db, f.file_id) for f in files)
    return {"have": have, "reading": reading, "unread": len(files) - have - reading}


def _was_read(db: Session, file_id) -> bool:
    return db.scalar(select(Extraction.extraction_id).where(
        Extraction.file_id == file_id,
        (Extraction.value_raw.is_not(None)) | (Extraction.value_normalized.is_not(None))
        | (Extraction.corrected_value.is_not(None))).limit(1)) is not None


@router.get("/{application_id}/prefill")
def prefill(application_id: UUID, db: Session = Depends(get_db),
            customer: Customer = Depends(current_customer)) -> dict:
    """Values a document proposed and the customer has not yet confirmed."""
    app = _owned(db, application_id, customer)
    rows = db.scalars(select(ApplicationField).where(
        ApplicationField.application_id == app.application_id,
        ApplicationField.review_state == "proposed")).all()
    return {
        "proposals": [{
            "field_name": r.field_name, "value": r.value,
            "file_id": str(r.file_id) if r.file_id else None,
            "page": r.page, "evidence_quote": r.evidence_quote, "method": r.method,
        } for r in rows if not _obsolete_proposal(app, r)]
    }


@router.post("/{application_id}/submit")
def submit(application_id: UUID, db: Session = Depends(get_db),
           customer: Customer = Depends(current_customer)) -> dict:
    app = db.scalar(select(Application).where(
        Application.application_id == application_id,
        Application.customer_id == customer.customer_id).with_for_update())
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if app.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft application can be submitted.")
    prefill_service.apply_pending(db, application_id=application_id)
    state = _ready_for_submission(application_id, db, customer)
    _freeze_submission(db, app, customer, state)
    app.submitted_at = datetime.now(timezone.utc)
    audit.record(db, action="application.submitted", customer_id=customer.customer_id, application_id=application_id)
    db.commit()
    return {"application_id": str(application_id), "status": app.status, "reference": f"HF-{application_id.hex[:8].upper()}"}


def _ready_for_submission(application_id, db, customer):
    state = progress(application_id, db, customer)
    if not state["complete"]:
        blocking = [m for s in state["steps"] for m in s["missing"]]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": "Some answers are still missing", "missing": blocking})

    return state


def _freeze_submission(db, app, customer, state):
    application_id = app.application_id
    from app.api.v1.documents import _summaries
    files = db.scalars(select(File).where(attachments.attached_to(application_id))
                       .order_by(File.uploaded_at.desc(), File.file_id)).all()
    summaries = [dict(summary, submitted_copy=True, application_id=str(application_id),
                      application_status="submitted") for summary in _summaries(db, files)]
    checks = checklist(application_id, db, customer)
    app.status = "submitted"
    db.add(SubmissionRecord(application_id=application_id, state=jsonable_encoder(_serialise(db, app)),
                            progress={**state, "status": "submitted"}, checklist=checks, documents=summaries))
    db.flush()
    _freeze_files(db, application_id, files)


def _freeze_files(db, application_id, files):
    for row in files:
        body = storage.get_object(row.storage_key)
        if row.checksum and storage.checksum(body) != row.checksum:
            raise HTTPException(503, "Document verification failed. Your application remains a draft.")
        db.add(SubmissionFile(application_id=application_id, file_id=row.file_id,
                              family_id=versions.chain(db, row.file_id)[0].file_id,
                              original_name=row.original_name, body=body))
        db.flush()


@router.get("/{application_id}/submitted-documents/{file_id}")
def submitted_document(application_id: UUID, file_id: UUID, db: Session = Depends(get_db),
                       customer: Customer = Depends(current_customer)) -> Response:
    _owned(db, application_id, customer)
    row = db.get(SubmissionFile, (application_id, file_id))
    if row is None:
        raise HTTPException(404, "Submitted copy unavailable.")
    return Response(row.body, media_type="application/octet-stream", headers={
        "Cache-Control": "private, no-store",
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.original_name, safe=""),
    })


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(application_id: UUID, db: Session = Depends(get_db),
                 customer: Customer = Depends(current_customer)) -> Response:
    """A draft no lender has seen can be deleted outright: its answers, progress and chat go with it.
    Its documents belong to the customer and stay in the vault, still in any other application."""
    app = _owned(db, application_id, customer)
    db.refresh(app, with_for_update=True)
    if app.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft can be deleted. This application was already sent.")
    _refuse_if_shared(customer, app.application_id)
    _release_files(db, app.application_id)
    db.execute(delete(Application).where(Application.application_id == app.application_id))
    audit.record(db, action="application.deleted", customer_id=customer.customer_id,
                 payload={"application_id": str(application_id)})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _refuse_if_shared(customer: Customer, application_id: UUID) -> None:
    """An application a lender invited the borrower to belongs to that loan; only the lender can withdraw it."""
    from app.api.v1 import lender_link
    lenders = lender_link.linked_lenders(customer.customer_id, application_id)
    if lenders:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This application belongs to your loan with {lenders[0]['lender']}. Ask your loan officer if you need to withdraw it.")


def _release_files(db: Session, application_id: UUID) -> None:
    """A file pointing at this application points at another one it is in instead, or at none."""
    db.execute(text("SET LOCAL homeflow.keep_links = 'on'"))
    db.execute(text("""
        UPDATE file f SET application_id = (
            SELECT ad.application_id FROM application_document ad
             WHERE ad.file_id = f.file_id AND ad.application_id <> :app
             ORDER BY ad.attached_at DESC LIMIT 1)
         WHERE f.application_id = :app"""), {"app": application_id})
