"""Allowlisted Markdown templates populated only from confirmed application data."""
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from sqlalchemy import select
from fastapi import HTTPException
from app.db.models import Application, ApplicationField, Asset, Declaration, Employment, File, Liability

ROOT = Path(__file__).resolve().parents[1]/"templates"
DICTIONARY = Path(__file__).resolve().parents[1]/"data"/"field_dictionary.json"
TEMPLATES = {"application-summary":{"name":"Application summary (sample)","version":"poc-2","path":ROOT/"application-summary.md"}}
FIELD_MAP = {
    "first_name":"firstName","last_name":"lastName","email":"email","phone":"phone","date_of_birth":"dob",
    "citizenship":"citizenship","marital_status":"maritalStatus","dependents":"dependents","housing":"housing",
    "years_at_address":"yearsAt","loan_purpose":"loanPurpose","property_value":"propertyValue","down_payment":"downPayment",
    "property_state":"propertyState","property_type":"propertyType","property_use":"propertyUse","year_built":"yearBuilt",
    "estate_held":"estateHeld","title_manner":"titleManner","employment_status":"employmentStatus","econsent":"econsent",
}
COMPOSITE = {"current_address":("addr1","city","state","zip"),"property_address":("propAddr1","propCity","propState","propZip")}
MONEY = {"property_value","down_payment","loan_amount"}
OPTIONAL_BLOCKS = {"asset_list","liability_list"}
BLOCKS = {"employment_list","asset_list","liability_list","declaration_list","document_list"}
META = {"application_reference","generated_date"}
ALLOWED = set(FIELD_MAP)|set(COMPOSITE)|BLOCKS|META|{"ssn_last_four","loan_amount"}
DOCUMENT_LABELS = {"w2":"W-2","paystub":"Pay stub","bank_statement":"Bank statement","drivers_license":"Driver's license",
                   "ssn_card":"Social Security card","other":"Other document"}
STATUS_LABELS = {"completed":"read","queued":"waiting to be read","processing":"being read","failed":"could not be read"}
CHOICE_LABELS = {"agree":"Agreed","disagree":"Declined"}


def owned(db,customer,application_id):
    application = db.get(Application,application_id)
    if application is None or application.customer_id != customer.customer_id:
        raise HTTPException(404,"Application not found")
    return application


def populate(db,customer,application_id,template_id):
    application = owned(db,customer,application_id)
    template = TEMPLATES.get(template_id)
    if template is None:
        raise HTTPException(404,"Template not found")
    # Customer-confirmed and customer-corrected answers; unreviewed document proposals stay out.
    rows = db.scalars(select(ApplicationField).where(ApplicationField.application_id==application.application_id,ApplicationField.review_state.in_(("confirmed","corrected")))).all()
    values = scalar_values({row.field_name:row.value for row in rows})
    values.update(block_values(db,application))
    values.update(application_reference="HF-"+str(application_id)[:8].upper(),generated_date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    return fill(template_id,template["path"].read_text(encoding="utf-8"),values)


def scalar_values(confirmed):
    values = {key:format_value(key,confirmed.get(field)) for key,field in FIELD_MAP.items()}
    for key,parts in COMPOSITE.items():
        values[key] = ", ".join(text for text in (format_value(key,confirmed.get(part)) for part in parts) if text)
    digits = re.sub(r"\D","",confirmed.get("ssn") or "")
    values["ssn_last_four"] = "***-**-"+digits[-4:] if len(digits) >= 4 else ""
    values["loan_amount"] = _loan_amount(confirmed.get("propertyValue"),confirmed.get("downPayment"))
    return values


def _loan_amount(value,down):
    try:
        amount = _decimal(value)-(_decimal(down) if down else Decimal(0))
    except (InvalidOperation,TypeError):
        return ""
    return f"${amount:,.2f}" if amount >= 0 else ""


def _decimal(text):
    amount = Decimal(str(text).replace(",","").replace("$","").strip())
    if not amount.is_finite():
        raise InvalidOperation
    return amount


def format_value(key,value):
    if value is None or not str(value).strip():
        return ""
    text = " ".join(str(value).split())[:500]
    if key == "econsent":
        return CHOICE_LABELS.get(text.lower(), text)
    if key in MONEY:
        try:
            amount = _decimal(text)
            return f"${amount:,.2f}" if amount >= 0 else ""
        except InvalidOperation:
            return ""
    return text


def _money(amount):
    return f"${Decimal(amount or 0):,.2f}"


def block_values(db,application):
    key = application.application_id
    rows = lambda model: db.scalars(select(model).where(model.application_id==key)).all()
    files = db.scalars(select(File).where(File.application_id==key).order_by(File.uploaded_at)).all()
    return {"employment_list":"\n".join(_job_line(job) for job in rows(Employment)),
            "asset_list":"\n".join(_asset_line(asset) for asset in rows(Asset)),
            "liability_list":"\n".join(f"- {d.liability_type or 'Debt'} with {d.creditor or 'unnamed creditor'}: balance {_money(d.balance)}, "
                                       f"{_money(d.monthly_payment)} a month" for d in rows(Liability)),
            "declaration_list":_declaration_lines(rows(Declaration)),
            "document_list":"\n".join(f"- {f.original_name} ({DOCUMENT_LABELS.get(f.document_tag, f.document_tag.replace('_',' '))}, "
                                      f"{STATUS_LABELS.get(f.status, f.status)})" for f in files)}


def _job_line(job):
    status = "Current job" if job.is_current else "Previous job"
    monthly = sum((Decimal(v or 0) for v in (job.base,job.overtime,job.bonuses,job.commissions)),Decimal(0))
    since = f", since {job.start_date.isoformat()}" if job.start_date else ""
    return f"- {status}: {job.employer_name or 'Employer not entered'}{' - ' + job.position if job.position else ''}{since}. Monthly income {_money(monthly)}"


def _asset_line(asset):
    ending = re.sub(r"\D","",str(asset.account_mask or ""))[-4:]
    return f"- {asset.asset_type or 'Account'} at {asset.institution or 'unnamed institution'}{' ending ' + ending if ending else ''}: {_money(asset.balance)}"


def _declaration_lines(rows):
    answers = {row.code:row.answer for row in rows if row.answer}
    questions = json.loads(DICTIONARY.read_text(encoding="utf-8"))["declarations"]
    return "\n".join(f"- {q['code']}. {q['text']} {answers[q['code']].capitalize()}" for q in questions if q["code"] in answers)


def fill(template_id,template,values):
    keys = list(dict.fromkeys(re.findall(r"{{\s*([a-z_]+)\s*}}",template)))
    if any(key not in ALLOWED for key in keys):
        raise ValueError("Template contains an unsupported field")
    missing = [key for key in keys if not values.get(key) and key not in OPTIONAL_BLOCKS]
    markdown = re.sub(r"{{\s*([a-z_]+)\s*}}",lambda match:values.get(match[1]) or _placeholder(match[1]),template)
    return {"template_id":template_id,"version":TEMPLATES[template_id]["version"],"markdown":markdown,"missing_fields":missing,"sample":True}


def _placeholder(key):
    return "None entered" if key in OPTIONAL_BLOCKS else "[MISSING: "+key.replace("_list","").replace("_"," ")+"]"
