"""Read-only chat answers from the selected application's live tracker and checklist."""
import re
from collections import Counter
from sqlalchemy import select
from app.api.v1 import applications
from app.db.models import Application, File
from app.services import attachments, borrower_questions

PROGRESS = re.compile(r"\b(?:application|loan) (?:status|progress)\b|where (?:is|s) my (?:loan|application)|(?:what(?:s| is)|which) (?:the |my )?next step|how (?:far|much).*application|application.*(?:complete|left|remaining)", re.I)
DOCUMENTS = re.compile(r"(?:what|which).*documents?.*(?:need|missing|outstanding|left|remaining)|documents?.*(?:still need|outstanding|missing)|(?:missing|outstanding|required) documents?", re.I)

PROGRESS_NOTE = "This is application completion, not lender approval. Your loan team's requests and decisions appear under Share with your lender on the Documents step."
DOCUMENTS_NOTE = "Open Documents to upload or review files. Uploading or attaching a file does not send it to your lender: choose Send to loan team, and check Requests from your loan team for anything they still need."
PURPOSE = {"Purchase": "Home purchase", "Other": "Home equity line"}


def intent(question):
    text = re.sub(r"[^a-z0-9 ]", "", question.lower())
    found = borrower_questions.intent(text)
    if found:
        return found
    if DOCUMENTS.search(text):
        return "documents"
    return "progress" if PROGRESS.search(text) else None

def answer(db, customer, application_id, question):
    kind = intent(question)
    if not kind:
        return None
    if kind in borrower_questions.KINDS:
        return borrower_questions.answer(kind, application_id)
    if application_id is None:
        return _vault_answer(db, customer, kind)
    lines = _lines(db, customer, applications._owned(db, application_id, customer), kind)
    return reply("\n".join(lines + [_note(kind)]) + "\n\nSource: this application's current saved tracker and document checklist.")


def _lines(db, customer, app, kind):
    if kind == "documents":
        return document_lines(db, app)
    return progress_lines(applications.progress(app.application_id, db, customer))


def _note(kind):
    return DOCUMENTS_NOTE if kind == "documents" else PROGRESS_NOTE


def _vault_answer(db, customer, kind):
    """No application chosen (the vault chat): every application this customer has, newest first."""
    apps = db.scalars(select(Application).where(Application.customer_id == customer.customer_id)
                      .order_by(Application.created_at.desc())).all()
    if not apps:
        return reply("You haven't started an application yet. Choose New application at the top of your vault; "
                     "documents already in your vault can be added to it.")
    parts = [f"{name(db, app)}:\n" + "\n".join(_lines(db, customer, app, kind)) for app in apps]
    lead = [f"You have {len(apps)} applications."] if len(apps) > 1 else []
    return reply("\n\n".join(lead + parts + [_note(kind)]) + "\n\nSource: each application's current saved tracker and document checklist.")


def name(db, app):
    """What the customer sees on the vault: "Home purchase HF-1A2B3C4D"."""
    purpose = applications._purpose(db, app) or ""
    label = PURPOSE.get(purpose) or ("Refinance" if "Refinance" in purpose else "Loan application")
    return f"{label} HF-{app.application_id.hex[:8].upper()}"

def reply(text):
    return {"answer": text, "citations": [], "evidence": [], "document_links": []}

def progress_lines(state):
    lines = [f"Your application status is {state['status']}. Application completion: {state['percent']}%."]
    incomplete = [step for step in state["steps"] if not step["complete"]]
    if state["status"] == "submitted":
        lines.append("Your application has been submitted. Contact your loan team for the next processing step.")
    elif incomplete:
        lines.append("Next step: complete " + incomplete[0]["label"] + ".")
        lines.extend("- " + step["label"] + ": " + str(len(step["missing"])) + " items remaining." for step in incomplete)
    else:
        lines.append("All tracked sections are complete. Review your answers and documents, then submit your application.")
    return lines

def document_lines(db, app):
    missing = applications._missing_documents(db, app)
    lines = ["Your application checklist still needs:"] if missing else ["All required upload counts are met in your application checklist."]
    lines.extend(f"- {item['display_name']}: {item['need'] - item['have']} more needed ({item['have']} of {item['need']} read{_pending(item)})." for item in missing)
    files = db.scalars(select(File).where(attachments.attached_to(app.application_id), File.customer_id == app.customer_id)).all()
    counts = Counter(file.status for file in files)
    if counts["failed"]:
        lines.append(f"{counts['failed']} attached file(s) failed processing. Open Documents and retry reading them.")
    pending = sum(counts[key] for key in ("uploaded", "queued", "processing"))
    if pending:
        lines.append(f"{pending} attached file(s) are still awaiting or undergoing processing.")
    return lines


def _pending(item: dict) -> str:
    """Uploaded files that do not count yet, so the customer knows why."""
    notes = [f"{item[key]} {label}" for key, label in (("reading", "still being read"), ("unread", "could not be read"))
             if item.get(key)]
    return f"; {', '.join(notes)}" if notes else ""
