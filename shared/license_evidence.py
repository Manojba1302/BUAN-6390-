"""Conservative license recovery from numbered OCR labels, with exact ID support."""
import re
import address_evidence


def _entry(value, quote, page):
    return {"value": value, "normalized": value, "quote": quote[:500],
            "page": page.get("page"), "method": page.get("method", "ocr")}


def _names(text, page):
    surname = re.findall(r"^1[ \t]+([A-Z][A-Z .'-]*)$", text, re.M | re.I)
    given = re.findall(r"^2[ \t]+([A-Z][A-Z .'-]*)$", text, re.M | re.I)
    if len(surname) != 1 or len(given) != 1:
        return {}
    last, names = surname[0].strip(" ."), given[0].strip(" .")
    quote = "1 " + surname[0] + "\n2 " + given[0]
    return {key: _entry(value, quote, page) for key, value in
            (("last_name", last), ("first_name", names.split()[0]), ("full_name", last + " " + names))}


def _addresses(text, page):
    pattern = r"^8[ \t]+(" + address_evidence.STREET + address_evidence.UNIT + r")"
    matches = list(re.finditer(pattern, text, re.M | re.I))
    if len(matches) != 1:
        return {}
    match = matches[0]
    return {"address": _entry(match[1].strip(), match[0], page)}


def _page_fields(page):
    text = page.get("text") or ""
    if not re.search(r"driver'?s?\s+licen[sc]e", text, re.I):
        return {}
    return {**_names(text, page), **_addresses(text, page)}


def _supported_identifier(value, texts):
    # Never accept a matching substring within a longer OCR identifier.
    if not value or not re.fullmatch(r"[A-Z0-9-]{4,24}", value, re.I):
        return False
    label = r"(?:\b4d\s*(?:DL\s*)?|\b(?:DLN?|LIC(?:ENSE)?(?:\s+(?:NO|NUMBER))?)\s*[:#]?\s*)"
    token = "".join("[" + re.escape("".join(sorted(group))) + "]" if (group := _look_alikes(ch)) else re.escape(ch) for ch in value.upper())
    pattern = label + token + r"(?![A-Z0-9-])"
    return any(re.search(pattern, text, re.I) for text in texts)


# Characters OCR commonly confuses; one look-alike per position is still the same printed ID.
LOOK_ALIKES = ("S5$", "O0D", "I1L|", "B8", "Z2", "G6")


def _look_alikes(ch):
    return next((group for group in LOOK_ALIKES if ch in group), "")


def reconcile(tag, pages, existing):
    if tag != "drivers_license":
        return existing
    result, candidates = dict(existing), {}
    for page in pages:
        for key, entry in _page_fields(page).items():
            candidates.setdefault(key, {})[entry["value"].upper()] = entry
    for key, options in candidates.items():
        result.pop(key, None)
        if len(options) == 1:
            result[key] = next(iter(options.values()))
    identifier = result.get("license_number", {}).get("value", "")
    if not _supported_identifier(identifier, [p.get("text") or "" for p in pages]):
        result.pop("license_number", None)
    return result
