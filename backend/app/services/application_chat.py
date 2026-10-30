"""Read-only chat answers from the selected application's live tracker and checklist."""
import re
from collections import Counter
from sqlalchemy import select
from app.api.v1 import applications
from app.db.models import File

PROGRESS = re.compile(r"\b(?:application|loan) (?:status|progress)\b|where (?:is|s) my (?:loan|application)|(?:what(?:s| is)|which) (?:the |my )?next step|how (?:far|much).*application|application.*(?:complete|left|remaining)", re.I)
DOCUMENTS = re.compile(r"(?:what|which).*documents?.*(?:need|missing|outstanding|left|remaining)|documents?.*(?:still need|outstanding|missing)|(?:missing|outstanding|required) documents?", re.I)

def intent(question):
    text = re.sub(r"[^a-z0-9 ]", "", question.lower())
    if DOCUMENTS.search(text):
        return "documents"
    return "progress" if PROGRESS.search(text) else None

def answer(db, customer, application_id, question):
    kind = intent(question)
    if not kind:
        return None
    if application_id is None:
        return reply("Open an application first so I can check its progress and document checklist.")
    app = applications._owned(db, application_id, customer)
    if kind == "documents":
        lines = document_lines(db, app)
    else:
        lines = progress_lines(applications.progress(application_id, db, customer))
    return reply("\n".join(lines) + "\n\nSource: this application's current saved tracker and document checklist.")

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
    lines.append("This is application completion, not lender approval. Underwriting phase and lender conditions are not connected yet.")
    return lines

def document_lines(db, app):
    missing = applications._missing_documents(db, app)
    lines = ["Your application checklist still needs:"] if missing else ["All required upload counts are met in your application checklist."]
    lines.extend(f"- {item['display_name']}: {item['need'] - item['have']} more needed ({item['have']} of {item['need']} attached)." for item in missing)
    files = db.scalars(select(File).where(File.application_id == app.application_id, File.customer_id == app.customer_id)).all()
    counts = Counter(file.status for file in files)
    if counts["failed"]:
        lines.append(f"{counts['failed']} attached file(s) failed processing. Open Documents and retry reading them.")
    pending = sum(counts[key] for key in ("uploaded", "queued", "processing"))
    if pending:
        lines.append(f"{pending} attached file(s) are still awaiting or undergoing processing.")
    lines.append("Open Documents to upload or review files. Meeting upload counts does not mean the lender has accepted them; additional lender conditions are not connected yet.")
    return lines
