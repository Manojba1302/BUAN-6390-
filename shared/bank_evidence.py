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
    result = {"total_withdrawals": next(iter(candidates.values()))} if len(candidates) == 1 else {}
    result.update(summary_balances(pages))
    mask = account_mask(pages)
    if mask:
        result["account_mask"] = mask
    return result


def account_mask(pages):
    candidates={}
    for page in pages:
        for match in re.finditer(r"\baccount\s+(?:number|no\.?)\s*:\s*([0-9xX*•][0-9xX*• -]{3,35})",page.get("text", ""),re.I):
            digits=re.sub(r"\D","",match[1])
            if len(digits)>=4:
                candidates[digits[-4:]]={"value":"****"+digits[-4:],"normalized":"****"+digits[-4:],"quote":digits[-4:],"page":page.get("page"),"method":page.get("method")}
    return next(iter(candidates.values())) if len(candidates)==1 else None


# Summary rows printed as a label line with the amount on the same or the next line, e.g.
# "Beginning balance on August 27, 2026\n$3.17" (Bank of America). Digital text only, where
# the printed words are exact; a scan or photo is left to the model.
SUMMARY_LABELS = {
    "beginning_balance": r"(?:beginning|opening|starting|previous) balance(?:[ \t]+(?:on|as of)[ \t]+[A-Za-z]+[ \t]+\d{1,2},[ \t]*\d{4})?",
    "ending_balance": r"(?:ending|closing|new) balance(?:[ \t]+(?:on|as of)[ \t]+[A-Za-z]+[ \t]+\d{1,2},[ \t]*\d{4})?",
    "total_deposits": r"(?:deposits and other (?:additions|credits)|total deposits(?: and (?:other )?(?:additions|credits))?)",
}


def summary_balances(pages):
    """Each summary amount that is printed exactly once (one distinct value) in digital text."""
    found = {}
    for page in pages:
        if page.get("method") != "native_text":
            continue
        text = page.get("text") or ""
        for field, label in SUMMARY_LABELS.items():
            pattern = r"(?im)^[ \t]*(" + label + r")[ \t]*:?[ \t]*(?:\n[ \t]*)?(-?\$?-?[\d,]+\.\d{2})[ \t]*$"
            for match in re.finditer(pattern, text):
                value = match[2].replace("$", "").replace(",", "")
                value = "-" + value.replace("-", "") if "-" in value else value
                found.setdefault(field, {})[value] = {"value": value, "normalized": value, "quote": match[0].strip(),
                                                      "page": page.get("page"), "method": page.get("method")}
    return {field: next(iter(options.values())) for field, options in found.items() if len(options) == 1}
