"""Customer-scoped hybrid retrieval with schema-independent page text."""
import re
from uuid import UUID
from types import SimpleNamespace
from sqlalchemy import text, select
from app.db.models import Extraction, File
from app.services import document_answers

SQL = """
WITH ranked AS (
 SELECT c.file_id,c.page,c.content,c.chunk_id,f.original_name,f.document_tag,
 ts_rank_cd(to_tsvector('english',c.content),websearch_to_tsquery('english',:keywords)) AS lexical,
 CASE WHEN CAST(:vector AS vector) IS NULL OR c.embedding IS NULL THEN 0
 ELSE 1-(c.embedding <=> CAST(:vector AS vector)) END AS semantic
 FROM document_chunk c JOIN file f ON f.file_id=c.file_id
 WHERE c.customer_id=CAST(:customer AS uuid) AND f.customer_id=CAST(:customer AS uuid)
 AND f.status='completed' AND (CAST(:application AS uuid) IS NULL OR f.application_id=CAST(:application AS uuid))
), balanced AS (
 SELECT *,row_number() OVER(PARTITION BY file_id ORDER BY lexical DESC,semantic DESC) AS position
 FROM ranked WHERE lexical>0 OR semantic>0
)
SELECT * FROM balanced ORDER BY position,lexical DESC,semantic DESC LIMIT 8
"""

def retrieve(db, customer, application_id, question, vector=None):
    parameters = {"customer":str(customer.customer_id), "application":str(application_id) if application_id else None,
                  "question":question, "keywords":_keywords(question), "vector":"["+",".join(map(str,vector))+"]" if vector else None}
    rows = db.execute(text(SQL),parameters).mappings().all()
    passages = [{"file_id":str(r["file_id"]), "page":r["page"], "content":r["content"],
                 "original_name":r["original_name"], "document_type":r["document_tag"]} for r in rows]
    passages += _field_pages(db, parameters)
    return enrich(db, passages)


def enrich(db, passages):
    ids = [UUID(p["file_id"]) for p in passages]
    rows = db.scalars(select(Extraction).where(Extraction.file_id.in_(ids))).all() if ids else []
    return [{**p, "saved_fields":_fields(rows,p), "field_policy":"Saved corrections override original page text; blank corrections mean unknown."} for p in passages]


def _fields(rows, passage):
    result = []
    for r in rows:
        if str(r.file_id) != passage["file_id"] or r.page != passage["page"]:
            continue
        result.append({"field":r.field_name, "value":document_answers._value(r),
                       "origin":"customer_correction" if r.corrected_value is not None else "extracted_unverified",
                       "role":_role(r.field_name), "page":r.page})
    return result


def _role(field):
    if field.startswith("employer"):
        return "employer"
    if field in {"address","city","state","zip","full_name","employee_name","account_holder"}:
        return "document_holder"
    if "period" in field or field in {"tax_year","pay_date"}:
        return "document_period"
    return "document_field"


def _field_pages(db, parameters):
    sql = """SELECT e.file_id,e.page,e.field_name,e.corrected_value,e.value_raw,e.value_normalized,f.original_name,f.document_tag
    FROM extraction e JOIN file f ON f.file_id=e.file_id
    WHERE f.customer_id=CAST(:customer AS uuid) AND f.status='completed' AND e.page IS NOT NULL
    AND (CAST(:application AS uuid) IS NULL OR f.application_id=CAST(:application AS uuid))
    AND to_tsvector('english',replace(e.field_name,'_',' ')||' '||coalesce(e.corrected_value,e.value_normalized,e.value_raw,''))
    @@ websearch_to_tsquery('english',:keywords) LIMIT 8"""
    rows = db.execute(text(sql),parameters).mappings().all()
    result = []
    for r in rows:
        value = document_answers._value(SimpleNamespace(**dict(r), evidence_quote=""))
        result.append({"file_id":str(r["file_id"]),"page":r["page"],"content":f"Saved field {r['field_name']}: {value}","original_name":r["original_name"],"document_type":r["document_tag"]})
    return result


def _keywords(question):
    ignored = {"summarize","summary","explain","compare","tell","show","please","what","when","where","how","does","do","my","the","is","are","a","an","of","in","on","and","between","documents","document"}
    words = [word for word in re.findall(r"[a-z0-9]+",question.lower()) if word not in ignored]
    return " OR ".join(dict.fromkeys(words))


def needs_general(db, customer, application_id, question):
    if any(re.search(pattern,question.lower()) for pattern,_ in document_answers.TAGS):
        return False
    query = select(File.file_id).where(File.customer_id==customer.customer_id, File.document_tag=="other")
    if application_id is not None:
        query = query.where(File.application_id==application_id)
    return db.scalar(query.limit(1)) is not None
