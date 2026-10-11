"""Conservative recovery from a single owner-name quote, never from employer/page text."""
import re

OWNER_FIELDS = {"w2": "employee_name", "paystub": "employee_name",
                "bank_statement": "account_holder", "drivers_license": "full_name"}
PARTS = ("address", "city", "state", "zip")
STATES = "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
STREET = r"\d+[A-Z]?\s+[A-Z0-9 .'-]+?\s+(?:STREET|ST|ROAD|RD|AVENUE|AVE|BOULEVARD|BLVD|DRIVE|DR|LANE|LN|HIGHWAY|HWY|COURT|CT|WAY|PLACE|PL|PARKWAY|PKWY|CIRCLE|CIR)\b\.?"
UNIT = r"(?:\s+(?:APT|APARTMENT|UNIT|SUITE|STE|#)\s*#?\s*[A-Z0-9-]+)?"
PATTERN = re.compile(r"(?P<address>" + STREET + UNIT + r")\s*,?\s+(?P<city>[A-Z][A-Z .'-]*?)\s*,?\s+(?P<state>" + "|".join(STATES) + r")\s+(?P<zip>\d{5}(?:-\d{4})?)\b", re.I)


def comparable(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def recover(tag, fields):
    owner = fields.get(OWNER_FIELDS.get(tag)) or {}
    name, quote = str(owner.get("value") or ""), str(owner.get("quote") or "")
    if not name or not comparable(quote).startswith(comparable(name)):
        return {}
    matches = list(PATTERN.finditer(re.sub(r"\s+", " ", quote)))
    if len(matches) != 1:
        return {}
    parts = {key: matches[0].group(key).strip() for key in PARTS}
    if any(fields.get(key, {}).get("value") and comparable(fields[key]["value"]) != comparable(parts[key]) for key in PARTS):
        return {}
    return {key: {"value": value, "normalized": value, "quote": quote,
                  "page": owner.get("page"), "method": owner.get("method"), "model_name": owner.get("model_name")}
            for key, value in parts.items() if key not in fields}


def recover_pages(tag, pages, fields):
    owner_key = OWNER_FIELDS.get(tag)
    owner = fields.get(owner_key) or {}
    name = comparable(owner.get("value") or "")
    candidates = {}
    if not name:
        return {}
    for page in pages:
        lines = (page.get("text") or "").splitlines()
        for index, line in enumerate(lines):
            if comparable(line) != name:
                continue
            quote = " ".join(lines[index:index + 5])
            recovered = recover(tag, {**fields, owner_key: {**owner, "quote": quote, "page": page.get("page"), "method": page.get("method")}})
            if recovered:
                key = tuple((part, comparable(value["value"])) for part, value in sorted(recovered.items()))
                candidates[key] = recovered
    return next(iter(candidates.values())) if len(candidates) == 1 else {}
