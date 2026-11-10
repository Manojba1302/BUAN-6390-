"""Borrower questions the chat can answer before HomeFlow holds a loan file (November 2026).

Vijay's borrower scenarios: Closing Disclosure timing, cash to close, Loan Estimate changes, the monthly
payment, uploading a document, and who the loan officer and processor are. HomeFlow does not yet hold
closing dates, Loan Estimates, Closing Disclosures, loan terms or file assignments, so these answers are
fixed: they explain the general rule where there is one, say plainly what is not available yet, read no
loan data and never estimate a figure. When the loan file exists, each kind becomes a tool that reads it.
"""
import re

INTENTS = (
    ("closing_disclosure", re.compile(r"closing disclosure|\bwhen (?:will|do|can|would) i (?:get|receive|see) (?:my |the )?cd\b")),
    ("cash_to_close", re.compile(r"cash (?:do i need )?(?:to|at|for) (?:bring to )?clos|bring to (?:the )?closing|cash to close|closing costs?|due at closing")),
    ("loan_estimate_change", re.compile(r"(?:loan estimate|\ble\b).{0,40}(?:chang|differ|went up|go up|increas|revis)"
                                        r"|(?:chang|revis).{0,40}(?:loan estimate|\ble\b)|revised (?:loan )?estimate")),
    ("monthly_payment", re.compile(r"\bmy (?:monthly|mortgage) payment|monthly payment (?:with|including)|\bpiti\b|payment with (?:taxes|escrow)")),
    ("upload", re.compile(r"\b(?:can|could|may) i (?:upload|send|attach|add|submit)\b|\bhow (?:do|can|should) i (?:upload|send|attach|add|submit)\b"
                          r"|\bwhere (?:do|can|should) i (?:upload|send|add|submit)\b")),
    ("contacts", re.compile(r"loan officer|\bprocessor\b|who (?:is|s|are) (?:on )?my loan team|who (?:is|s) (?:handling|working on) my (?:loan|application)"
                            r"|(?:reach|contact|call|email) (?:my |the )?(?:lender|loan)")),
)
KINDS = {kind for kind, _ in INTENTS}
GENERAL = "\n\nSource: federal disclosure rules (general information, not your loan file)."
NOT_YET = "HomeFlow doesn't have {what} yet, so I can't {verb}, and I won't guess. Your loan team will share it."

ANSWERS = {
    "closing_disclosure": "Your Closing Disclosure must reach you at least 3 business days before your closing date. "
        "For this rule, business days are every day except Sundays and federal public holidays.\n\n"
        "Your closing date isn't scheduled in HomeFlow yet, so I can't tell you the day. "
        "Your loan team will send the Closing Disclosure and confirm the date." + GENERAL,
    "cash_to_close": "Your cash to close is shown on your Loan Estimate, and the final amount is on your Closing Disclosure. "
        "It depends on your down payment, closing costs and any credits.\n\n"
        + NOT_YET.format(what="your Loan Estimate or Closing Disclosure", verb="give you an amount"),
    "loan_estimate_change": "A Loan Estimate can be revised for a few reasons, for example:\n"
        "- a changed circumstance, such as new information about your income or the property's value, or an event outside anyone's control\n"
        "- a change you asked for, such as a different loan amount or program\n"
        "- locking your interest rate\n\n"
        "The lender must send the revised estimate within 3 business days of learning about the change.\n\n"
        "HomeFlow doesn't have your Loan Estimates or the recorded reason yet, so I can't say why yours changed. "
        "Your loan team can tell you." + GENERAL,
    "monthly_payment": "Your monthly payment depends on your interest rate, loan amount and term, plus escrow for property taxes, "
        "homeowners insurance and any mortgage insurance. These come from your Loan Estimate.\n\n"
        + NOT_YET.format(what="your loan terms", verb="calculate it"),
    "contacts": "No loan officer or processor is assigned to your file in HomeFlow yet. "
        "Once they are, I can tell you who they are and how to reach them.",
}
UPLOAD_VAULT = ("Yes. You can upload a pay stub or any other document: PDF, JPG, PNG or HEIC, up to 20 MB each.\n\n"
                "Choose Upload a document below. If you're not sure what a file is, leave the type as Other: HomeFlow reads it, "
                "works out what it is and files it in your vault. If an application still needs it, HomeFlow asks before adding it.")
UPLOAD_APPLICATION = ("Yes. Choose Upload a document below to open this application's Documents step, pick the document type, "
                      "then choose your file: PDF, JPG, PNG or HEIC, up to 20 MB each. "
                      "HomeFlow checks the file matches the type you chose before saving it.")
UPLOAD_ACTION = {"kind": "upload", "label": "Upload a document"}


def intent(text: str) -> str | None:
    """`text` is the question lower-cased with punctuation removed, as application_chat prepares it."""
    return next((kind for kind, pattern in INTENTS if pattern.search(text)), None)


def answer(kind: str, application_id) -> dict:
    if kind == "upload":
        text = UPLOAD_APPLICATION if application_id else UPLOAD_VAULT
        return {"answer": text, "citations": [], "evidence": [], "document_links": [], "actions": [UPLOAD_ACTION]}
    return {"answer": ANSWERS[kind], "citations": [], "evidence": [], "document_links": []}
