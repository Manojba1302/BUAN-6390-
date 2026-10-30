"""Exact per-document calculations. Ambiguous operands stay unanswered."""
import re
from decimal import Decimal, InvalidOperation
from datetime import date
from sqlalchemy import select
from app.db.models import File, Extraction
from app.services import document_answers
import doc_types


def operands(question):
    q = question.lower()
    if not re.search(r"difference|subtract|days between|sum|add together", q):
        return None
    candidates = {k for spec in doc_types.catalogue()["types"] for k, description in spec["extract"].items()
                  if re.search(r"amount|balance|gross pay|net pay|yyyy-mm-dd", description, re.I)}
    selected = sorted(k for k in candidates if re.search(r"\b"+re.escape(k.replace("_"," "))+r"\b",q))
    return selected if len(selected) == 2 else None


def calculate(left, right, question):
    if "days between" in question.lower():
        try:
            return f"{abs((date.fromisoformat(right)-date.fromisoformat(left)).days)} days apart"
        except ValueError:
            return "Dates are missing or not in a supported format."
    try:
        a, b = Decimal(left.replace(",","").replace("$","")), Decimal(right.replace(",","").replace("$",""))
        if not a.is_finite() or not b.is_finite():
            raise InvalidOperation
        addition = bool(re.search(r"sum|add together",question,re.I))
        value = a+b if addition else abs(a-b)
        return f"{value:.2f} (same units as source; {'sum' if addition else 'absolute difference'})"
    except InvalidOperation:
        return "Both amounts must be present and numeric."


def answer(db, customer, application_id, question):
    keys = operands(question)
    if not keys:
        return None
    query = select(File).where(File.customer_id==customer.customer_id, File.status=="completed")
    if application_id is not None:
        query = query.where(File.application_id==application_id)
    files = db.scalars(query).all()
    files = [f for f in files if all(k in (doc_types.get_type(f.document_tag) or {}).get("extract",{}) for k in keys)]
    if not files:
        return None
    rows = db.scalars(select(Extraction).where(Extraction.file_id.in_([f.file_id for f in files]))).all()
    reply = document_answers._reply(db, files, keys)
    results = []
    for f in files:
        found = {r.field_name:r for r in rows if r.file_id==f.file_id}
        values = [document_answers._value(found[k]) if k in found else "" for k in keys]
        results.append(f"{f.original_name}: " + calculate(*values,question))
    results.extend(_pay_note(keys))
    reply["answer"] = "Calculated separately for each document; no totals across people or periods.\n" + "\n".join(results) + "\n\n" + reply["answer"]
    return reply


def _pay_note(keys):
    if set(keys) != {"pay_rate", "gross_pay"}:
        return []
    return ["Pay rate is the stated rate and basis; gross pay is the period total. The difference alone does not establish overtime, extra hours or adjustments; the reason is unknown without supporting earnings details."]
