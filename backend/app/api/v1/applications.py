"""The application itself: create, load, save, progress, prefill, submit."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.fields import _dictionary
from app.db.models import (
    Application, ApplicationField, Asset, ChecklistRequirement, Customer,
    Declaration, Employment, File, Liability,
)
from app.core.security import current_customer
from app.db.session import get_db
from app.services import audit, prefill as prefill_service

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
def create_application(db: Session = Depends(get_db),
                       customer: Customer = Depends(current_customer)) -> dict:
    app = Application(customer_id=customer.customer_id)
    db.add(app)
    db.flush()
    audit.record(db, action="application.created",
                 customer_id=customer.customer_id, application_id=app.application_id)
    db.commit()
    return {"application_id": str(app.application_id), "status": app.status}


@router.get("")
def list_applications(db: Session = Depends(get_db),
                      customer: Customer = Depends(current_customer)) -> list[dict]:
    rows = db.scalars(select(Application)
                      .where(Application.customer_id == customer.customer_id)
                      .order_by(Application.created_at.desc())).all()
    return [{"application_id": str(a.application_id), "status": a.status,
             "current_step": a.current_step, "created_at": a.created_at.isoformat()} for a in rows]


@router.get("/{application_id}")
def get_application(application_id: UUID, db: Session = Depends(get_db),
                    customer: Customer = Depends(current_customer)) -> dict:
    app = _owned(db, application_id, customer)
    prefill_service.apply_pending(db, application_id=app.application_id)
    return _serialise(db, app)


@router.patch("/{application_id}")
def patch_application(application_id: UUID, patch: ApplicationPatch,
                      db: Session = Depends(get_db),
                      customer: Customer = Depends(current_customer)) -> dict:
    app = _owned(db, application_id, customer)
    if app.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "A submitted application cannot be edited")

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
        } for f in fields
    }


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
    errors = []
    if status == "Employed" and any(not (row.get("employer_name") or "").strip() for row in employment):
        errors.append("Employer name")
    if status in REQUIRED_INCOME and not any(str(values.get(n) or "").strip() for n in REQUIRED_INCOME[status]):
        errors.append("Enter monthly income, or 0 if none")
    if status == "Employed" and employment and any(not row.get("base") for row in employment):
        errors.append("Base monthly employment income")
    return errors


def _percent(steps: list[dict]) -> int:
    done = sum(1 for s in steps if s["complete"])
    return int(done / max(len(steps), 1) * 100)


def _missing_documents(db: Session, app: Application) -> list[dict]:
    """A confirmed mismatch still counts. The classifier warns, it never blocks."""
    requirements = db.scalars(select(ChecklistRequirement)
                              .order_by(ChecklistRequirement.sort_order)).all()
    income_status = db.get(ApplicationField, (app.application_id, "employmentStatus"))
    non_employee = income_status and income_status.value in {"Self-employed", "Retired", "Not currently employed", "Other"}
    out = []
    for req in requirements:
        if non_employee and req.document_tag in {"w2", "paystub"}:
            continue
        have = db.scalars(select(File).where(
            File.application_id == app.application_id,
            File.document_tag == req.document_tag)).all()
        if len(have) < req.required_count:
            out.append({"document_tag": req.document_tag,
                        "display_name": req.display_name,
                        "have": len(have), "need": req.required_count})
    return out


@router.get("/{application_id}/prefill")
def prefill(application_id: UUID, db: Session = Depends(get_db),
            customer: Customer = Depends(current_customer)) -> dict:
    """Values a document proposed and the customer has not yet confirmed."""
    app = _owned(db, application_id, customer)
    prefill_service.apply_pending(db, application_id=app.application_id)
    rows = db.scalars(select(ApplicationField).where(
        ApplicationField.application_id == app.application_id,
        ApplicationField.review_state == "proposed")).all()
    return {
        "proposals": [{
            "field_name": r.field_name, "value": r.value,
            "file_id": str(r.file_id) if r.file_id else None,
            "page": r.page, "evidence_quote": r.evidence_quote, "method": r.method,
        } for r in rows]
    }


@router.post("/{application_id}/submit")
def submit(application_id: UUID, db: Session = Depends(get_db),
           customer: Customer = Depends(current_customer)) -> dict:
    app = _owned(db, application_id, customer)
    state = progress(application_id, db, customer)
    if not state["complete"]:
        blocking = [m for s in state["steps"] for m in s["missing"]]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": "Some answers are still missing", "missing": blocking})

    app.status = "submitted"
    app.submitted_at = datetime.now(timezone.utc)
    audit.record(db, action="application.submitted",
                 customer_id=customer.customer_id, application_id=app.application_id)
    db.commit()
    return {"application_id": str(app.application_id), "status": app.status,
            "reference": f"APP-{str(app.application_id)[:6].upper()}"}
