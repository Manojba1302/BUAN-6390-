"""Turning what a document said into what the application holds.

Every rule here exists because getting it wrong is worse than leaving the
field blank:
  - a value the customer confirmed is never overwritten by a later document
  - pay is converted to monthly income only with a stated frequency, and the
    arithmetic is kept so it can be shown
  - several statements for one account are one asset, not one per statement
  - declarations and consents are never touched
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApplicationField, Asset, Employment, Extraction, File

log = logging.getLogger(__name__)

# document field -> application field, for the plain one-to-one cases
DIRECT_MAP: dict[tuple[str, str], str] = {
    ("drivers_license", "date_of_birth"): "dob",
    ("drivers_license", "address"): "addr1",
    ("drivers_license", "city"): "city",
    ("drivers_license", "state"): "state",
    ("drivers_license", "zip"): "zip",
    ("drivers_license", "full_name"): "legalName",
    ("ssn_card", "ssn"): "ssn",
    ("w2", "employee_ssn"): "ssn",
}

PAY_PERIODS_PER_YEAR = {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12}

NEVER_PREFILL = {"econsent"}  # declarations live in their own table and are never touched


def apply_pending(db: Session, *, application_id: UUID) -> dict:
    """Fold in every processed document for this application.

    Safe to run on every load: applying the same extraction twice writes the
    same proposal, and a value the customer confirmed is skipped either way.
    """
    files = db.scalars(select(File).where(
        File.application_id == application_id, File.status == "completed")).all()
    totals = {"applied": 0, "skipped": 0, "files": len(files)}
    for file in files:
        result = apply_file(db, file=file)
        totals["applied"] += result["applied"]
        totals["skipped"] += result["skipped"]
    return totals


def apply_file(db: Session, *, file: File) -> dict:
    """Fold one processed file's extractions into the application."""
    if file.application_id is None:
        return {"applied": 0, "skipped": 0}

    rows = db.scalars(select(Extraction).where(Extraction.file_id == file.file_id)).all()
    values = {r.field_name: r for r in rows if (r.corrected_value or r.value_raw)}
    applied = skipped = 0

    for doc_field, row in values.items():
        target = DIRECT_MAP.get((file.document_tag, doc_field))
        if not target or target in NEVER_PREFILL:
            continue
        if _set_field(db, file, target, row):
            applied += 1
        else:
            skipped += 1

    if file.document_tag in ("paystub", "w2"):
        _apply_employment(db, file, values)
    if file.document_tag == "bank_statement":
        _apply_asset(db, file, values)

    db.commit()
    return {"applied": applied, "skipped": skipped}


def _value(row: Extraction) -> str:
    return row.corrected_value or row.value_normalized or row.value_raw or ""


def _set_field(db: Session, file: File, name: str, row: Extraction) -> bool:
    """Propose a value. A confirmed or corrected one is left alone."""
    existing = db.get(ApplicationField, (file.application_id, name))
    if existing and existing.review_state in ("confirmed", "corrected") and existing.value:
        log.info("keeping customer value for %s", name)
        return False

    payload = dict(
        value=_value(row), source="extracted", file_id=file.file_id, page=row.page,
        evidence_quote=row.evidence_quote, method=row.method, review_state="proposed",
    )
    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
    else:
        db.add(ApplicationField(application_id=file.application_id, field_name=name, **payload))
    return True


def _decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(str(raw).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def monthly_from_pay(gross: Decimal, frequency: str | None) -> tuple[Decimal | None, str | None]:
    """Gross pay is not monthly income. Without a stated frequency we refuse."""
    if not frequency:
        return None, None
    periods = PAY_PERIODS_PER_YEAR.get(frequency.strip().lower())
    if not periods:
        return None, None
    monthly = (gross * periods / 12).quantize(Decimal("0.01"))
    note = f"{frequency} pay of {gross} x {periods} / 12 = {monthly} a month"
    return monthly, note


def _apply_employment(db: Session, file: File, values: dict[str, Extraction]) -> None:
    name = _value(values["employer_name"]) if "employer_name" in values else None
    if not name:
        return

    row = db.scalar(select(Employment).where(
        Employment.application_id == file.application_id,
        Employment.employer_name == name))
    if row is None:
        row = Employment(application_id=file.application_id, employer_name=name,
                         source_file_id=file.file_id)
        db.add(row)

    if row.source_file_id is None:
        return  # Preserve customer-confirmed employment.

    if "position" in values and not row.position:
        row.position = _value(values["position"])

    gross = _decimal(_value(values["gross_pay"])) if "gross_pay" in values else None
    freq = _value(values["pay_frequency"]) if "pay_frequency" in values else None
    if gross is not None:
        monthly, note = monthly_from_pay(gross, freq)
        if monthly is not None:
            row.base = monthly
            row.pay_frequency = freq
        else:
            # We know the gross but not the period. Leave income blank rather
            # than assume monthly, and let the customer say which it is.
            row.pay_frequency = None
            log.info("pay frequency not stated on %s, leaving base blank", file.file_id)


def _apply_asset(db: Session, file: File, values: dict[str, Extraction]) -> None:
    institution = _value(values["institution"]) if "institution" in values else None
    mask = _value(values["account_mask"]) if "account_mask" in values else None
    if not institution:
        return

    row = db.scalar(select(Asset).where(
        Asset.application_id == file.application_id,
        Asset.institution == institution,
        Asset.account_mask == mask))

    balance = _decimal(_value(values["ending_balance"])) if "ending_balance" in values else None
    period_end = _value(values["period_end"]) if "period_end" in values else None

    if row is None:
        db.add(Asset(application_id=file.application_id, asset_type="Checking Account",
                     institution=institution, account_mask=mask, balance=balance or 0,
                     as_of=period_end or None, source_file_id=file.file_id))
        return

    if row.source_file_id is None:
        return  # Preserve customer-confirmed assets.

    # Same account, another month. Keep the most recent balance, never add them.
    if balance is not None and (row.as_of is None or (period_end or "") >= str(row.as_of)):
        row.balance = balance
        row.as_of = period_end or row.as_of
        row.source_file_id = file.file_id
