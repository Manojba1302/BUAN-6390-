"""Conservative project scope checks before retrieval or tools."""
import re
import doc_types

DOMAIN = r"printed|conditions|earnings|document|file|upload|application|mortgage|loan|pay|salary|w[ -]?2|bank|statement|licen[cs]e|income|employer|employeer|work for|work at|where do i work|job|address|ssn|social security|lease|insurance|contract|policy|passport|tax|deduction|withholding|bonus|overtime|balance|account|deposit|withdrawal|expiry|expire|birth|name|period|amount|section|clause|coverage|premium|earn|paid|company|landlord|tenant|\brent\b|pets?\b|deposit|workplace|office located|make per|make a (?:month|year|week)|how much (?:do|did) i make|take[ -]?home|paycheck|pay check|wage|monthly|per month|eligib|qualif|afford|house|home|property|down payment|credit|debt|employ|identity|\bid\b|dob|zip|city|state"
UNRELATED = r"tell (?:me )?a joke|write (?:me )?(?:a )?(?:poem|python|javascript|code)|weather|sports score|president of|capital of|ignore (?:all |previous )?instructions|system prompt"


def allowed(question):
    if re.search(UNRELATED, question, re.I):
        return False
    if re.search(DOMAIN, question, re.I) or re.search(r"\b(it|its|that|this|these|those)\b|\.(pdf|png|jpe?g)\b",question,re.I):
        return True
    keys = [key.replace("_"," ") for spec in doc_types.catalogue()["types"] for key in spec["extract"]]
    return any(re.search(r"\b"+re.escape(key)+r"\b",question,re.I) for key in keys)


def reply():
    return {"answer":"I don't know about that. I can help with your HomeFlow application and uploaded documents. Please ask a document-related question.","citations":[],"evidence":[]}
