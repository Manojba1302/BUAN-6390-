"""Validate editable employment data before any application changes are saved."""
from datetime import date
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException

AMOUNTS = ("base", "overtime", "bonuses", "commissions")


def amount(value):
    try:
        result = Decimal(str(value).replace(",", "").replace("$", "").strip())
        return result if result.is_finite() and 0 <= result <= Decimal("9999999999.99") else None
    except (InvalidOperation, ValueError):
        return None


def clean_rows(rows):
    cleaned = []
    for index, original in enumerate(rows, 1):
        row = dict(original)
        _clean_amounts(row, index)
        _clean_dates(row, index)
        if "is_current" in row and not isinstance(row["is_current"], bool):
            raise HTTPException(400, f"Job {index}: choose current or previous employment")
        cleaned.append(row)
    return cleaned


def _clean_amounts(row, index):
    for key in AMOUNTS:
        raw = row.get(key)
        value = Decimal("0") if raw is None or str(raw).strip() == "" else amount(raw)
        if value is None:
            raise HTTPException(400, f"Job {index}: {key} must be a valid nonnegative monthly amount")
        row[key] = str(value.quantize(Decimal("0.01")))


def _clean_dates(row, index):
    for key in ("start_date", "end_date"):
        if not row.get(key):
            row[key] = None
            continue
        try:
            row[key] = date.fromisoformat(str(row[key])).isoformat()
        except ValueError:
            raise HTTPException(400, f"Job {index}: enter a valid {key.replace('_', ' ')}")
    if row["start_date"] and row["end_date"] and row["end_date"] < row["start_date"]:
        raise HTTPException(400, f"Job {index}: end date cannot precede start date")


def employment_errors(rows, employed):
    errors = []
    current = [row for row in rows if row.get("is_current", True) is not False]
    if employed and not current:
        errors.append("At least one current job")
    for index, row in enumerate(rows, 1):
        if employed and not (row.get("employer_name") or "").strip():
            errors.append("Employer name")
        for key in AMOUNTS:
            value = amount(row.get(key) or 0)
            if value is None:
                errors.append(f"Job {index}: valid nonnegative monthly {key}")
            elif employed and row in current and key == "base" and value == 0:
                errors.append("Base monthly employment income")
    return list(dict.fromkeys(errors))
