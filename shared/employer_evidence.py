"""Keep employer addresses tied to the printed employer block."""
import re
from address_evidence import comparable, STREET, STATES


def _block(page, name):
    lines = [line.strip() for line in (page.get("text") or "").splitlines() if line.strip()]
    for index, line in enumerate(lines[:-2]):
        if comparable(line) != name:
            continue
        street, locality = lines[index + 1:index + 3]
        if not re.match(STREET, street, re.I):
            continue
        if not re.fullmatch(r"[A-Z][A-Z .'-]*,?\s+(?:" + "|".join(STATES) + r")\s+\d{5}(?:-\d{4})?", locality, re.I):
            continue
        value = street + ", " + locality
        yield {"value": value, "normalized": value, "quote": "\n".join((line, street, locality)),
               "page": page.get("page"), "method": page.get("method")}


def reconcile(tag, pages, fields):
    if tag not in ("w2", "paystub"):
        return fields
    result = dict(fields)
    name = comparable(fields.get("employer_name", {}).get("value") or "")
    candidates = {}
    for page in pages:
        if page.get("method") != "native_text" and page.get("ocr_confidence", 0) < 85:
            continue
        for entry in _block(page, name):
            candidates[comparable(entry["value"])] = entry
    result.pop("employer_address", None)
    if len(candidates) == 1:
        result["employer_address"] = next(iter(candidates.values()))
    return result
