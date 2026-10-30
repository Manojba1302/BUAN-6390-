"""Deterministic comparisons of saved fields; no identity or payroll inference."""
import re
from sqlalchemy import select
from app.db.models import File, Extraction
from app.services import document_answers as fields

FIELDS = {
    "name": ("full_name", "employee_name", "account_holder"),
    "employer": ("employer_name",),
    "address": ("address", "city", "state", "zip"),
    "identity": ("full_name", "employee_name", "account_holder", "address", "city", "state", "zip"),
    "pay": ("pay_rate", "pay_rate_basis", "gross_pay", "net_pay", "ytd_gross"),
}

def intent(question):
    q = question.lower().replace("same document", "document")
    if re.search(r"compare|conflict|differ|same|match", q):
        if re.search(r"\bnames?\b", q) and "address" in q:
            return "identity"
        if re.search(r"\bnames?\b", q) and "employer" not in q and "company" not in q:
            return "name"
        if "address" in q:
            return "address"
        if "employer" in q or "company" in q:
            return "employer"
    if re.search(r"why|explain|differ|compare", q) and "gross" in q and re.search(r"rate|paycheck|pay check", q):
        return "pay"
    return None


def answer(db, customer, application_id, question):
    kind = intent(question)
    if kind is None:
        return None
    files = _files(db, customer, application_id, question, kind)
    if not files:
        return {"answer": "No matching documents are attached to this application.", "citations": [], "evidence": []}
    rows = db.scalars(select(Extraction).where(Extraction.file_id.in_([f.file_id for f in files]))).all()
    reply = fields._reply(db, files, FIELDS[kind])
    detail = reply["answer"].removeprefix("Matching documents are listed separately; they may belong to different people.\n\n")
    reply["answer"] = _explanation(kind, files, rows) + "\n\n" + detail
    return reply


def _files(db, customer, application_id, question, kind):
    query = select(File).where(File.customer_id == customer.customer_id)
    if application_id is not None:
        query = query.where(File.application_id == application_id)
    tags = {tag for pattern, tag in fields.TAGS if re.search(pattern, question.lower())}
    tags = tags or ({"paystub"} if kind == "pay" else {"w2", "paystub"} if kind == "employer" else {"w2", "paystub", "bank_statement", "drivers_license"})
    files = db.scalars(query.where(File.document_tag.in_(tags)).order_by(File.uploaded_at.desc())).all()
    named = [f for f in files if f.original_name.lower() in question.lower()]
    return named or files


def _values(file, rows, keys):
    found = {r.field_name: r for r in rows if r.file_id == file.file_id}
    return [fields._value(found[k]).strip() if k in found else "" for k in keys]


def _explanation(kind, files, rows):
    if kind == "identity":
        return _name_explanation(files, rows) + "\n" + _explanation("address", files, rows)
    if kind == "name":
        return _name_explanation(files, rows)
    if kind == "pay":
        return "Pay rate is the stated rate and basis; gross pay is the total for that pay period. Year-to-date pay covers the year so far. A difference does not establish extra hours, overtime or adjustments; the reason cannot be determined from these saved totals alone."
    complete = [_values(f, rows, FIELDS[kind]) for f in files if f.status == "completed"]
    known = [values for values in complete if all(values)]
    unique = {tuple(re.sub(r"\s+", " ", value.casefold()).strip() for value in values) for values in known}
    if len(known) < 2:
        finding = "Not enough complete saved information to establish a comparison."
    elif len(unique) == 1:
        finding = "The complete saved values match apart from capitalization or spacing."
    else:
        finding = "The saved values differ. Review each source below; no value has been chosen automatically."
    if len(known) < len(files):
        finding += " Some documents are missing fields or are still processing."
    scope = "These are document-holder addresses, not employer addresses. They do not establish your current residence." if kind == "address" else "Matching employer names do not establish that the documents belong to the same person or represent one job."
    return finding + " " + scope


def _name_explanation(files, rows):
    names = []
    for file in files:
        values = _values(file, rows, FIELDS["name"]) if file.status == "completed" else []
        name = next((value for value in values if value), "")
        if name:
            names.append(" ".join(name.casefold().split()))
    if len(names) < 2:
        result = "Not enough saved names to compare."
    else:
        result = "The printed names match apart from capitalization or spacing." if len(set(names)) == 1 else "The printed names differ."
    return result + " Names alone do not establish document ownership or whether these are different people."
