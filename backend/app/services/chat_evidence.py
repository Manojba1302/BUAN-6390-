"""Customer-scoped hybrid retrieval with schema-independent page text."""
import re
from uuid import UUID
from types import SimpleNamespace
from sqlalchemy import text, select
from app.db.models import Extraction, File
from app.services import document_answers
import field_crypto

SQL = """
WITH ranked AS (
 SELECT c.file_id,c.page,c.content,c.chunk_id,f.original_name,f.document_tag,
 ts_rank_cd(to_tsvector('english',c.content),websearch_to_tsquery('english',:keywords)) AS lexical,
 CASE WHEN CAST(:vector AS vector) IS NULL OR c.embedding IS NULL THEN 0
 ELSE 1-(c.embedding <=> CAST(:vector AS vector)) END AS semantic
 FROM document_chunk c JOIN file f ON f.file_id=c.file_id
 WHERE c.customer_id=CAST(:customer AS uuid) AND f.customer_id=CAST(:customer AS uuid)
 AND f.status='completed' AND (CAST(:application AS uuid) IS NULL OR f.application_id=CAST(:application AS uuid))
), lex AS (
 SELECT chunk_id,row_number() OVER(ORDER BY lexical DESC) AS r FROM ranked WHERE lexical>0
), sem AS (
 SELECT chunk_id,row_number() OVER(ORDER BY semantic DESC) AS r FROM ranked WHERE semantic>0
), fused AS (
 -- Reciprocal rank fusion: relevance across keyword and vector rankings decides the order,
 -- instead of taking one chunk from every file in turn.
 SELECT chunk_id,SUM(1.0/(60+r)) AS score
 FROM (SELECT * FROM lex WHERE r<=20 UNION ALL SELECT * FROM sem WHERE r<=20) hits GROUP BY chunk_id
), capped AS (
 SELECT ranked.*,fused.score,row_number() OVER(PARTITION BY ranked.file_id ORDER BY fused.score DESC) AS per_file
 FROM ranked JOIN fused USING(chunk_id)
)
SELECT * FROM capped WHERE per_file<=3 ORDER BY score DESC LIMIT 8
"""

def retrieve(db, customer, application_id, question, vector=None):
    parameters = {"customer":str(customer.customer_id), "application":str(application_id) if application_id else None,
                  "question":question, "keywords":_keywords(question), "vector":"["+",".join(map(str,vector))+"]" if vector else None}
    rows = db.execute(text(SQL),parameters).mappings().all()
    passages = [{"file_id":str(r["file_id"]), "page":r["page"], "content":r["content"],
                 "original_name":r["original_name"], "document_type":r["document_tag"],"lexical":float(r["lexical"]),"semantic":float(r["semantic"])} for r in rows]
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
        row = {key: field_crypto.decrypt(value) for key, value in dict(r).items()}   # raw SQL bypasses the ORM decryption
        value = document_answers._value(SimpleNamespace(**row, evidence_quote=""))
        result.append({"file_id":str(r["file_id"]),"page":r["page"],"content":f"Saved field {r['field_name']}: {value}","original_name":r["original_name"],"document_type":r["document_tag"]})
    return result


def _keywords(question):
    ignored = {"summarize","summary","explain","compare","tell","show","please","what","when","where","how","does","do","my","the","is","are","a","an","of","in","on","and","between","documents","document"}
    words = [word for word in re.findall(r"[a-z0-9]+",question.lower()) if word not in ignored]
    return " OR ".join(dict.fromkeys(words))


OTHER_DOCUMENT_WORDS = re.compile(r"\b(lease|rental|landlord|tenant|insurance|policy|contract|agreement|letter|invoice|utility|tax return|1099|deed|appraisal|gift|divorce|decree|clause|section|coverage|premium)\b", re.I)


def needs_general(db, customer, application_id, question):
    """True when the question is about an 'other' document, so saved-field shortcuts must not answer it.

    Questions about schema fields (employer, pay, balance...) keep their instant answers
    even when an unrelated document such as a lease is attached.
    """
    if any(re.search(pattern,question.lower()) for pattern,_ in document_answers.TAGS):
        return False
    query = select(File.original_name).where(File.customer_id==customer.customer_id, File.document_tag=="other")
    if application_id is not None:
        query = query.where(File.application_id==application_id)
    names = db.scalars(query).all()
    if not names:
        return False
    stems = {word for name in names for word in re.findall(r"[a-z]{4,}", name.lower().rsplit(".", 1)[0])}
    return bool(OTHER_DOCUMENT_WORDS.search(question) or stems & set(re.findall(r"[a-z]{4,}", question.lower())))
