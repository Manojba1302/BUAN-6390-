"""Fast, read-only answers from allowlisted extracted document fields."""
import re
from sqlalchemy import select
import doc_types
import money_values
from app.db.models import Extraction, File

RULES = [
    (r"\b(ssn|social security number|social security no)\b", ("ssn", "employee_ssn")),
    (r"\b(licen[cs]e number|dl number)\b", ("license_number",)),
    (r"\b(account number|account ending|last four.*account)\b", ("account_mask",)),
    (r"\b(ein|employer identification number)\b", ("employer_ein",)),
    (r"\b(bank name|institution)\b", ("institution",)),
    (r"\b(ytd|year to date)\b", ("ytd_gross",)),
    (r"\b(expir\w*|expiry|expiration|valid until)\b", ("expiry_date",)),
    (r"\b(issue date|issued|date of issue)\b", ("issue_date",)),
    (r"\b(date of birth|birth date|birthday|dob)\b", ("date_of_birth",)),
    (r"\b(pay rate|rate of pay|payrate)\b", ("pay_rate", "pay_rate_basis")),
    (r"\b(job title|position)\b", ("position",)),
    (r"\b(employers?|employeer|emplyer|employr|company name|who (?:do|did) i work (?:for|at)|where (?:do|did) i work|(?:company|organisation|organization) i work (?:for|at))\b", ("employer_name",)),
    (r"\b(gross pay|gross earnings)\b", ("gross_pay",)),
    (r"\b(net pay|take home pay)\b", ("net_pay",)),
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


def intent(question):
    text = re.sub(r"[^a-z0-9 ]", " ", question.lower())
    text = " ".join(text.split())
    if re.search(r"\b(summarize|summarise|summary|overview|explain|why|compare|difference|calculate|should|eligible|monthly income|base income)\b", text):
        return None
    fields = _question_fields(text)
    if "employer_name" in fields:
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
    return _reply(db, files, fields)


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
    prefix = "Matching documents are listed separately; they may belong to different people.\n\n" if len(files) > 1 else ""
    links = [{"file_id": str(file.file_id), "original_name": file.original_name} for file in files if str(file.file_id) not in {item["file_id"] for item in citations}]
    return {"answer": prefix + "\n\n".join(lines), "citations": citations, "evidence": evidence, "document_links": links}


def _file_lines(file, found, fields):
    owner = next((_value(found[key]) for key in ("full_name", "employee_name", "account_holder") if key in found and _value(found[key]).strip()), "Owner name unavailable")
    values = []
    for field in fields:
        if field not in (doc_types.get_type(file.document_tag) or {}).get("extract", {}):
            continue
        row = found.get(field)
        value = _value(row) if row is not None else ""
        label = field.replace("_", " ").capitalize()
        suffix = " (your saved correction)" if row is not None and row.corrected_value is not None and value else ""
        values.append(f"{label}: {value}{suffix}" if value.strip() else f"{label}: not extracted; open the document to review.")
    if file.status != "completed":
        values = [f"Document is {file.status}; extracted fields are not ready."]
    return [f"{file.original_name} — {owner}\n" + "\n".join(values or ["This document type has no matching saved field."])]


SENSITIVE = {"ssn", "employee_ssn", "license_number", "account_mask"}


def _value(row):
    value = row.corrected_value if row.corrected_value is not None else money_values.amount(row.field_name, row.value_raw or "", row.evidence_quote or "") or row.value_normalized or row.value_raw or ""
    if row.field_name in SENSITIVE and value:
        compact = re.sub(r"[^a-zA-Z0-9]", "", value)
        return "••••" + compact[-4:] if len(compact) >= 4 else "Hidden; open the document to reveal"
    return value


def _question_fields(text):
    fields = [field for pattern, keys in RULES if re.search(pattern, text) for field in keys]
    for spec in doc_types.catalogue()["types"]:
        for field in spec["extract"]:
            phrase = field.replace("_", " ")
            if re.search(r"\b" + re.escape(phrase) + r"\b", text):
                fields.append(field)
    return tuple(dict.fromkeys(fields))
