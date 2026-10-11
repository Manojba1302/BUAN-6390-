"""Complete summaries of supported saved fields; missing evidence stays unknown."""
import re
from sqlalchemy import select
from app.db.models import File
from app.services import document_answers as fields

SUMMARY_FIELDS = {
    "paystub": ("employer_name", "position", "pay_period_start", "pay_period_end", "pay_rate", "pay_rate_basis", "regular_pay", "overtime_pay", "bonus_pay", "gross_pay", "total_deductions", "federal_withholding", "net_pay", "ytd_gross"),
    "bank_statement": ("institution", "period_start", "period_end", "beginning_balance", "ending_balance", "total_deposits", "total_withdrawals"),
}


def intent(question):
    if not re.search(r"\b(summarize|summarise|summary|overview)\b", question, re.I):
        return None
    tags = {tag for pattern, tag in fields.TAGS if re.search(pattern, question, re.I)}
    if len(tags) != 1 or re.search(r"\b(compare|why|calculate|explain)\b", question, re.I):
        return None
    tag = next(iter(tags))
    return tag if tag in SUMMARY_FIELDS else None


def answer(db, customer, application_id, question):
    tag = intent(question)
    if tag is None:
        return None
    query = select(File).where(File.customer_id == customer.customer_id, File.document_tag == tag)
    if application_id is not None:
        query = query.where(File.application_id == application_id)
    files = db.scalars(query.order_by(File.uploaded_at.desc())).all()
    named = [file for file in files if file.original_name.lower() in question.lower()]
    files = named or files
    if not files:
        return None
    reply = fields._reply(db, files, SUMMARY_FIELDS[tag])
    reply["answer"] = "Summary of saved extracted fields; missing values are unknown, not zero.\n\n" + reply["answer"]
    if tag == "paystub":
        reply["answer"] += "\n\nDeductions: the summary lists saved total deductions and federal withholding when available; it is not a complete itemized breakdown. Open each source for all deduction categories. Gross pay and regular pay are distinct; missing regular pay has not been replaced with gross pay."
    return reply
