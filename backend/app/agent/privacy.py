"""Chat-boundary redaction; source documents and extraction records are unchanged."""
import re
from sqlalchemy import select
from app.db.models import Extraction, File

SENSITIVE_FIELDS = {"ssn", "employee_ssn", "license_number", "account_mask", "account_number", "employee_id", "date_of_birth"}
PHONE = re.compile(r"(?<![\w-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-](\d{4})(?![\w-])")
BIRTH_DATE = re.compile(r"(?i)\b((?:dob|date of birth|birth ?date|born(?: on)?)\s*[:#]?\s*)(\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4})")


def redact(value, secrets=()):
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key:redact(item, secrets) for key,item in value.items()}
    if not isinstance(value, str):
        return value
    for secret in sorted(set(secrets), key=len, reverse=True):
        if len(secret) >= 4:
            value = re.sub(r"(?<!\w)"+re.escape(secret)+r"(?!\w)", "[REDACTED]", value, flags=re.I)
    value = re.sub(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b", "[REDACTED SSN]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED EMAIL]", value)
    value = PHONE.sub(lambda match: f"[PHONE ending {match[1]}]", value)
    value = BIRTH_DATE.sub(r"\1[DATE OF BIRTH HIDDEN]", value)
    value = re.sub(r"(?i)\b((?:ssn|social security|account|license|employee id)(?: number| no)?\s*[:#]\s*)([A-Z0-9][A-Z0-9 -]{3,})", r"\1[REDACTED]", value)
    return value


def scoped(db, customer, application_id, value):
    query = select(Extraction).join(File).where(File.customer_id == customer.customer_id, Extraction.field_name.in_(SENSITIVE_FIELDS))
    if application_id is not None:
        query = query.where(File.application_id == application_id)
    rows = db.scalars(query).all()
    secrets = [str(v).strip() for row in rows for v in (row.value_raw,row.value_normalized,row.corrected_value) if v]
    return redact(value, secrets)


def stored(reply):
    if not isinstance(reply, dict):
        return redact(reply)
    result = dict(reply)
    result["evidence"] = [{key:item[key] for key in ("file_id","page","original_name") if key in item} for item in reply.get("evidence",[]) if isinstance(item,dict)]
    return redact(result)
