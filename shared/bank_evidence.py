"""Verify labelled bank summary components; never sum arbitrary transactions."""
import re
from decimal import Decimal

LABELS = ("ATM and debit card subtractions", "Other subtractions", "Service fees")

def total_from_summary(text):
    if "Account summary" not in text:
        return None
    section = text.split("Account summary", 1)[1].split("Ending balance", 1)[0]
    components = []
    for label in LABELS:
        matches = re.findall(re.escape(label) + r"\s*\$?(-?[\d,]+\.\d{2})(?![\d.])", section, re.I)
        if len(matches) != 1 or Decimal(matches[0].replace(",", "")) > 0:
            return None
        components.append(abs(Decimal(matches[0].replace(",", ""))))
    return format(sum(components), ".2f")


def recover(tag, pages):
    if tag != "bank_statement":
        return {}
    candidates = {}
    for page in pages:
        text = page.get("text") or ""
        total = total_from_summary(text)
        if total is not None:
            section = "Account summary" + text.split("Account summary", 1)[1].split("Ending balance", 1)[0]
            candidates[total] = {"value": total, "normalized": total, "quote": section.strip(), "page": page.get("page"), "method": page.get("method")}
    return {"total_withdrawals": next(iter(candidates.values()))} if len(candidates) == 1 else {}
