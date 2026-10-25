"""Cross-check model answers against values printed next to their label in the page text.

A vision answer is not quoted from the text, so a misread or invented value would otherwise be
saved as is. When exactly one value sits beside a field's label on the page and the model's
answer either is not printed anywhere or is the later (year-to-date) number on that same row,
the printed value wins and carries its line as the quote. On digital text, where the words are
exact, a labelled value also fills a field the model left empty; on a scan or photo it does not.
Only digital text and OCR read with high confidence can overrule the model, since a blurry or
tiny image misreads the printed value too. Two different labelled values leave the answer alone.
"""
import re

AMOUNT = r"\$?\s?([\d,]+\.\d{2})"
DATE = r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})"
SSN = r"(\d{3}-\d{2}-\d{4})"
LABELS = {
    "w2": {"employee_ssn": (r"social security|\bssn\b", SSN), "box1_wages": (r"wages,? tips", AMOUNT),
           "box2_federal_tax": (r"federal income tax withheld", AMOUNT)},
    "ssn_card": {"ssn": (r"social security|\bssn\b", SSN)},
    "paystub": {"gross_pay": (r"gross (?:pay|earnings)", AMOUNT), "net_pay": (r"net pay", AMOUNT),
                "total_deductions": (r"total deductions", AMOUNT), "federal_withholding": (r"federal (?:income tax|withholding)", AMOUNT)},
    "bank_statement": {"beginning_balance": (r"(?:beginning|opening|starting) balance", AMOUNT),
                       "ending_balance": (r"(?:ending|closing) balance", AMOUNT),
                       "total_deposits": (r"total (?:deposits|credits)", AMOUNT), "total_withdrawals": (r"total (?:withdrawals|debits)", AMOUNT)},
    "drivers_license": {"expiry_date": (r"\b(?:exp|expires|expiration)\b", DATE), "issue_date": (r"\b(?:iss|issued)\b", DATE),
                        "date_of_birth": (r"\b(?:dob|date of birth)\b", DATE)},
}


def comparable(value):
    text = str(value or "").strip().lower().replace("$", "").replace(",", "")
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    return f"{match[3]}-{int(match[1]):02d}-{int(match[2]):02d}" if match else re.sub(r"\s+", " ", text)


def _printed(label, pattern, pages):
    """Each distinct value printed right after the label, with its line, page and later row values."""
    found = {}
    for page in pages:
        for line in (page.get("text") or "").splitlines():
            for hit in re.finditer(label, line, re.I):
                rest = line[hit.end():]
                first = re.match(r"[^\d$\n]{0,40}?" + pattern, rest)   # a few label words may sit between
                if first:
                    later = [comparable(v) for v in re.findall(pattern, rest[first.end():])]
                    found.setdefault(comparable(first[1]), (first[1], line.strip(), page, later))
    return found


def _entry(printed):
    shown, line, page, _ = printed
    return {"value": shown.replace("$", "").strip(), "normalized": comparable(shown), "quote": line[:500],
            "page": page.get("page"), "method": page.get("method", "ocr")}


def _replace(existing, printed, all_text):
    """The printed value when the model's answer is missing from digital text, unprinted, or that row's YTD."""
    if existing is None:
        return _entry(printed) if printed[2].get("method") == "native_text" else None
    value = comparable(existing.get("value"))
    if value == comparable(printed[0]):
        return None
    return _entry(printed) if value in printed[3] or value not in comparable(all_text) else None


# Below this mean Tesseract confidence the OCR text itself is too unreliable to overrule the model.
MIN_OCR_CONFIDENCE = 85


def _trusted(page):
    return page.get("method") == "native_text" or (page.get("method") == "ocr" and page.get("ocr_confidence", 0) >= MIN_OCR_CONFIDENCE)


def verify(tag, pages, out):
    result = dict(out)
    pages = [page for page in pages if _trusted(page)]
    all_text = "\n".join(page.get("text") or "" for page in pages)
    for field, (label, pattern) in LABELS.get(tag, {}).items():
        printed = _printed(label, pattern, pages)
        if len(printed) == 1:
            replacement = _replace(result.get(field), next(iter(printed.values())), all_text)
            if replacement:
                result[field] = replacement
    return result
