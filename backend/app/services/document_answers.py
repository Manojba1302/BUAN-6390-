"""Fast, read-only answers from allowlisted extracted document fields."""
import re
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
import doc_types
import money_values
from app.db.models import Extraction, File

RULES = [
    (r"\b(ssn|social security number|social security no)\b", ("ssn", "employee_ssn")),
    (r"\b(licen[cs]e number|dl number)\b", ("license_number",)),
    (r"\b(account number|account ending|last four.*account)\b", ("account_mask",)),
    (r"\b(ein|employer identification number)\b", ("employer_ein",)),
    (r"\b(bank name|institution|name of (?:my |the )?bank|which bank|what bank)\b", ("institution",)),
    (r"\b(salary|how much (?:do|did) i (?:make|earn|get paid)|what (?:do|did) i (?:make|earn))\b", ("gross_pay", "pay_rate", "pay_rate_basis", "pay_frequency", "box1_wages")),
    (r"\b(ytd|year to date)\b", ("ytd_gross",)),
    (r"\b(expir\w*|expiry|expiration|valid until)\b", ("expiry_date",)),
    (r"\b(issue date|issued|date of issue)\b", ("issue_date",)),
    (r"\b(date of birth|birth date|birthday|dob)\b", ("date_of_birth",)),
    (r"\b(pay rate|rate of pay|payrate)\b", ("pay_rate", "pay_rate_basis")),
    (r"\b(job title|position)\b", ("position",)),
    (r"\b(employers?|employeer|emplyer|employr|company name|who (?:do|did) i work (?:for|at)|where (?:do|did) i work|(?:company|organisation|organization) i work (?:for|at))\b", ("employer_name",)),
    (r"\b(gross pay|gross earnings)\b", ("gross_pay",)),
    (r"\b(net pay|take home pay|take home)\b", ("net_pay", "pay_frequency")),
    (r"\b(pay date|paid on|when.*paid)\b", ("pay_date",)),
    (r"\b(pay frequency|how often.*paid)\b", ("pay_frequency",)),
    (r"\b(opening balance|beginning balance|starting balance)\b", ("beginning_balance",)),
    (r"\b(ending balance|closing balance|bank balance|account balance|my balance)\b", ("ending_balance",)),
    (r"\b((?:total )?deposits|total credits)\b", ("total_deposits",)),
    (r"\b((?:total )?withdrawals|total debits)\b", ("total_withdrawals",)),
    (r"\b(statement period|period.*statement|statement.*period)\b", ("period_start", "period_end")),
    (r"\b(pay period)\b", ("pay_period_start", "pay_period_end")),
    (r"\b(tax year)\b", ("tax_year",)),
    (r"\b(wages|box 1)\b", ("box1_wages",)),
    (r"\b(federal tax|box 2)\b", ("box2_federal_tax",)),
    (r"\b(zip|zip code|postal code)\b", ("zip",)),
    (r"\b(city)\b", ("city",)),
    (r"\b(address|where.*live)\b", ("address", "city", "state", "zip")),
    (r"\b(name|who.*belongs|who.*belong|whose)\b", ("full_name", "employee_name", "account_holder")),
]
TAGS = [(r"\b(licen[cs]e|licen[cs]es|dl)\b", "drivers_license"),
        (r"\bw[ -]?2s?\b", "w2"), (r"\b(pay ?slips?|pay ?stubs?)\b", "paystub"),
        (r"\b(bank|statement)\b", "bank_statement"), (r"\b(social security card|ssn card)\b", "ssn_card")]


EMPLOYER_ADDRESS = re.compile(r"\b(employers?|employeer|company|work) s? ?(?:address|location)\b|\b(?:address|location) of (?:my |the )?(?:employer|company|work)\b"
                              r"|\bwhere(?: is|s| s)? (?:my |the )?(?:employers?|employeer|company|workplace|office)\b|\b(?:employers?|employeer|company|office) (?:is )?located\b")


def _has_field(db, files, field):
    rows = db.scalars(select(Extraction).where(Extraction.file_id.in_([f.file_id for f in files]), Extraction.field_name == field)).all()
    return any(_value(row).strip() for row in rows)


def intent(question):
    text = re.sub(r"[^a-z0-9 ]", " ", question.lower())
    text = " ".join(text.split())
    if re.search(r"\b(summarize|summarise|summary|overview|explain|why|compare|difference|calculate|should|eligible|monthly income|base income)\b", text):
        return None
    if EMPLOYER_ADDRESS.search(text):
        return ("employer_name", "employer_address"), ["w2", "paystub"]
    fields = _question_fields(text)
    if "employer_name" in fields or "institution" in fields:
        fields = tuple(field for field in fields if field not in ("full_name", "employee_name", "account_holder"))
    if not fields:
        return None
    tags = [tag for pattern, tag in TAGS if re.search(pattern, text)]
    if not tags:
        tags = [spec["id"] for spec in doc_types.catalogue()["types"] if any(field in spec["extract"] for field in fields)]
    return fields, tags


def answer(db, customer, application_id, question):
    route = intent(question)
    if route is None:
        return None
    fields, tags = route
    query = select(File).where(File.customer_id == customer.customer_id, File.document_tag.in_(tags))
    if application_id is not None:
        query = query.where(File.application_id == application_id)
    files = db.scalars(query.order_by(File.uploaded_at.desc())).all()
    named = [file for file in files if file.original_name.lower() in question.lower()]
    files = named or files
    if not files:
        return {"answer": "No matching document is attached here. Upload or attach the document first.", "citations": [], "evidence": []}
    if "employer_address" in fields and not _has_field(db, files, "employer_address"):
        return None   # read before this field existed: let document search look in the page text instead
    reply = _reply(db, files, fields)
    reply["answer"] += monthly_note(db, files, question)
    return reply


def _reply(db, files, fields):
    rows = db.scalars(select(Extraction).where(Extraction.file_id.in_([file.file_id for file in files]))).all()
    lines, citations, evidence = [], [], []
    for file in files:
        found = {row.field_name: row for row in rows if row.file_id == file.file_id}
        lines.extend(_file_lines(file, found, fields))
        for field in fields:
            row = found.get(field)
            if file.status == "completed" and row is not None and _value(row).strip() and row.page:
                citations.append({"file_id": str(file.file_id), "page": row.page})
                evidence.append({"file_id": str(file.file_id), "page": row.page, "original_name": file.original_name, "content": _value(row) if row.field_name in SENSITIVE else row.evidence_quote or "Saved extracted field"})
    citations = list({(item["file_id"], item["page"]): item for item in citations}.values())
    owners = {_owner_key(rows, file) for file in files}
    prefix = "Matching documents are listed separately; they may belong to different people.\n\n" if len(files) > 1 and (len(owners) > 1 or "" in owners) else ""
    links = [{"file_id": str(file.file_id), "original_name": file.original_name} for file in files if str(file.file_id) not in {item["file_id"] for item in citations}]
    return {"answer": prefix + "\n\n".join(lines), "citations": citations, "evidence": evidence, "document_links": links}


def _owner_key(rows, file):
    """Printed owner name, normalised; empty when the document has none."""
    found = {row.field_name: row for row in rows if row.file_id == file.file_id}
    name = next((_value(found[key]) for key in ("full_name", "employee_name", "account_holder") if key in found and _value(found[key]).strip()), "")
    return " ".join(name.casefold().split())


PERIODS_PER_YEAR = {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12, "annual": 1, "annually": 1}


def monthly_note(db, files, question):
    """For 'per month' questions, convert a printed rate or net pay using its printed frequency only."""
    if not re.search(r"\b(month|monthly|per month|a month)\b", question, re.I):
        return ""
    stubs = [f for f in files if f.document_tag == "paystub" and f.status == "completed"]
    rows = db.scalars(select(Extraction).where(Extraction.file_id.in_([f.file_id for f in stubs]))).all() if stubs else []
    notes = [note for file in stubs for note in _monthly_lines(file, {r.field_name: r for r in rows if r.file_id == file.file_id})]
    return ("\n\nMonthly estimate (calculated from printed values, not a lender income determination):\n" + "\n".join(notes)) if notes else ""


def _monthly_lines(file, found):
    get = lambda key: _value(found[key]).strip() if key in found else ""
    amount = lambda key: Decimal(get(key).replace(",", "").replace("$", ""))
    basis = re.sub(r"[ -]", "", get("pay_rate_basis").lower())
    frequency = re.sub(r"[ -]", "", get("pay_frequency").lower())
    lines = []
    try:
        if basis in PERIODS_PER_YEAR and get("pay_rate"):
            monthly = amount("pay_rate") * PERIODS_PER_YEAR[basis] / 12
            lines.append(f"{file.original_name}: printed {basis} base rate {get('pay_rate')} × {PERIODS_PER_YEAR[basis]} / 12 = about {monthly:,.2f} a month before deductions.")
        elif frequency in PERIODS_PER_YEAR and get("gross_pay"):
            gross = amount("gross_pay") * PERIODS_PER_YEAR[frequency] / 12
            lines.append(f"{file.original_name}: gross pay {get('gross_pay')} paid {frequency} is about {gross:,.2f} a month before deductions, if every pay period is the same.")
        if frequency in PERIODS_PER_YEAR and get("net_pay"):
            net = amount("net_pay") * PERIODS_PER_YEAR[frequency] / 12
            lines.append(f"{file.original_name}: net pay {get('net_pay')} paid {frequency} is about {net:,.2f} a month take-home, if every pay period is the same.")
    except InvalidOperation:
        return []
    return lines


def _file_lines(file, found, fields):
    owner = next((_value(found[key]) for key in ("full_name", "employee_name", "account_holder") if key in found and _value(found[key]).strip()), "Owner name unavailable")
    values = []
    for field in fields:
        if field not in (doc_types.get_type(file.document_tag) or {}).get("extract", {}):
            continue
        row = found.get(field)
        value = _value(row) if row is not None else ""
        label = LABELS.get(field) or field.replace("_", " ").capitalize()
        suffix = " (your saved correction)" if row is not None and row.corrected_value is not None and value else ""
        values.append(f"{label}: {value}{suffix}" if value.strip() else f"{label}: not extracted; open the document to review.")
    if file.status != "completed":
        values = [f"Document is {file.status}; extracted fields are not ready."]
    return [f"{file.original_name} — {owner}\n" + "\n".join(values or ["This document type has no matching saved field."])]


SENSITIVE = {"ssn", "employee_ssn", "license_number", "account_mask"}
LABELS = {
    "ssn": "SSN", "employee_ssn": "SSN", "employer_ein": "Employer EIN", "employer_address": "Employer address", "ytd_gross": "Year-to-date gross pay",
    "box1_wages": "Wages (W-2 box 1)", "box2_federal_tax": "Federal tax withheld (W-2 box 2)", "zip": "ZIP code",
    "account_mask": "Account number", "institution": "Bank", "license_number": "License number",
    "date_of_birth": "Date of birth", "pay_rate_basis": "Pay rate basis", "pay_period_start": "Pay period start",
    "pay_period_end": "Pay period end", "period_start": "Statement period start", "period_end": "Statement period end",
}


def _value(row):
    value = row.corrected_value if row.corrected_value is not None else money_values.amount(row.field_name, row.value_raw or "", row.evidence_quote or "") or row.value_normalized or row.value_raw or ""
    if row.field_name in SENSITIVE and value:
        compact = re.sub(r"[^a-zA-Z0-9]", "", value)
        return "••••" + compact[-4:] if len(compact) >= 4 else "Hidden; open the document to reveal"
    if row.field_name == "date_of_birth" and value:
        year = re.search(r"\b(19|20)\d{2}\b", value)
        return f"••/••/{year[0]} (full date hidden; open the document to view)" if year else "Hidden; open the document to view"
    return value


def _question_fields(text):
    fields = [field for pattern, keys in RULES if re.search(pattern, text) for field in keys]
    for spec in doc_types.catalogue()["types"]:
        for field in spec["extract"]:
            phrase = field.replace("_", " ")
            if re.search(r"\b" + re.escape(phrase) + r"\b", text):
                fields.append(field)
    return tuple(dict.fromkeys(fields))
