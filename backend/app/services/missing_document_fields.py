"""Report schema fields without saved extraction values; never infer document omissions."""
import re
from sqlalchemy import select
from app.db.models import File, Extraction
from app.services import document_answers
import doc_types


def matches(question):
    return bool(re.search(r"(?:what|which).*(?:missing|not (?:find|found|extract)|couldn.t (?:find|extract)|unable to (?:find|extract))|(?:missing|unextracted) (?:information|details|fields)", question, re.I))


def answer(db, customer, application_id, question):
    if not matches(question):
        return None
    query = select(File).where(File.customer_id == customer.customer_id)
    if application_id is not None:
        query = query.where(File.application_id == application_id)
    files = db.scalars(query.order_by(File.uploaded_at.desc())).all()
    tags = {tag for pattern,tag in document_answers.TAGS if re.search(pattern,question,re.I)}
    files = [f for f in files if not tags or f.document_tag in tags]
    if not files:
        return {"answer":"No matching documents are attached to this application.","citations":[],"evidence":[]}
    rows = db.scalars(select(Extraction).where(Extraction.file_id.in_([f.file_id for f in files]))).all()
    lines = [describe(f,rows) for f in files]
    return {"answer":"Missing saved extraction fields are listed below. This does not mean the information is absent from the original document. Saved corrections take precedence.\n\n" + "\n\n".join(lines), "citations":[],"evidence":[],"document_links":[{"file_id":str(f.file_id),"original_name":f.original_name} for f in files]}


def describe(file, rows):
    if file.status != "completed":
        return f"{file.original_name}: {file.status}; extraction is not ready."
    spec = doc_types.get_type(file.document_tag)
    if not spec or not spec.get("extract"):
        return f"{file.original_name}: no field schema is available; missing information cannot be assessed from saved fields."
    found = {r.field_name:r for r in rows if r.file_id == file.file_id}
    missing = [key.replace("_"," ") for key in spec["extract"] if key not in found or not document_answers._value(found[key]).strip()]
    return file.original_name + (": no saved value for " + ", ".join(missing) + "." if missing else ": all configured extraction fields have saved values; this is not a completeness or accuracy verification.")
