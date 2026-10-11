"""Read explicit labelled rate/title only; earnings totals never become contractual rates."""
import re
from decimal import Decimal, InvalidOperation

RATE = re.compile(r"Pay\s+Rate\s*:\s*\$?([\d,]+\.\d{2})\s+(Semi[ -]?monthly|Bi[ -]?weekly|Weekly|Monthly|Annual(?:ly)?|Hourly)\b", re.I)
TITLE = re.compile(r"Job[ \t]+Title[ \t]*:[ \t]*([^\r\n]+?)(?=\s+Pay\s+Rate\s*:|\r?\n|$)", re.I)


def recover(tag, pages, existing):
    if tag != "paystub":
        return {}
    candidates = {}
    for page in pages:
        text = page.get("text") or ""
        for match in RATE.finditer(text):
            basis = re.sub(r"[ -]", "", match[2].lower()).replace("annually", "annual")
            _add(candidates, "pay_rate", match[1].replace(",", ""), match[0], page)
            _add(candidates, "pay_rate_basis", basis, match[0], page)
        for match in TITLE.finditer(text):
            if valid_title(match[1]):
                _add(candidates, "position", match[1].strip(), match[0], page)
    _recover_amounts(candidates, pages)
    _check_rate_pair(candidates, existing)
    return {key: next(iter(options.values())) for key, options in candidates.items()
            if key not in existing and len(options) == 1}


def _add(candidates, key, value, quote, page):
    candidates.setdefault(key, {})[value] = {"value": value, "normalized": value,
        "quote": quote, "page": page.get("page"), "method": page.get("method")}


def _check_rate_pair(candidates, existing):
    keys = ("pay_rate", "pay_rate_basis")
    compatible = all(len(candidates.get(key, {})) == 1 for key in keys)
    for key in keys:
        if key not in existing or not compatible:
            continue
        old = str(existing[key].get("value") or "").replace(",", "").strip()
        new = next(iter(candidates[key]))
        try:
            compatible = Decimal(old) == Decimal(new) if key == "pay_rate" else old.lower() == new
        except InvalidOperation:
            compatible = False
    if not compatible:
        for key in keys:
            candidates.pop(key, None)


def valid_title(value):
    text = str(value or "").strip()
    return bool(text) and not re.search(r"^(?:pay\s*rate|job\s*title|gross\s*pay|department|location)\s*:", text, re.I)


def aligned_labels(page):
    """Recover label/value rows by PDF coordinates, rather than content-stream order."""
    words = page.get_text("words")
    lines = []
    for label in ("Job Title:", "Pay Rate:"):
        for rect in page.search_for(label):
            center = (rect.y0 + rect.y1) / 2
            row = sorted((w for w in words if w[0] >= rect.x1 - 1
                          and abs((w[1] + w[3]) / 2 - center) < 2), key=lambda w: w[0])
            values = []
            for word in row:
                if word[0] > rect.x1 + 220 or word[4].endswith(":"):
                    break
                values.append(word[4])
            if values:
                lines.append(label + " " + " ".join(values))
    lines.extend(_aligned_amounts(page, words))
    return "\n".join(lines)


AMOUNT_LABELS = {
    "regular_pay": r"regular (?:pay|earnings)",
    "overtime_pay": r"overtime(?: (?:pay|earnings))?",
    "bonus_pay": r"bonus(?: pay)?",
    "total_deductions": r"total deductions",
    "federal_withholding": r"(?:federal (?:income tax|withholding)|fed withholding)",
}


def _recover_amounts(candidates, pages):
    """Only single-amount labelled rows; ambiguous tables and YTD stay unknown."""
    for page in pages:
        for line in (page.get("text") or "").splitlines():
            for key, label in AMOUNT_LABELS.items():
                pattern = r"^\s*(?:current(?: period)?\s+)?" + label + r"\s*:\s*\$?([\d,]+\.\d{2})\s*$"
                match = re.fullmatch(pattern, line, re.I)
                if match:
                    _add(candidates, key, match[1].replace(",", ""), line.strip(), page)


TABLE_LABELS = {"Regular (T)":"Regular earnings", "Regular Pay":"Regular earnings", "Overtime":"Overtime", "Fed Withholdng":"Federal withholding", "Federal Withholding":"Federal withholding"}


def _aligned_amounts(page, words):
    lines = []
    for printed, canonical in TABLE_LABELS.items():
        for rect in page.search_for(printed):
            value = _current_amount(words, rect)
            if value is not None:
                lines.append(f"{canonical}: {value}")
    return lines


def _current_amount(words, rect):
    center = (rect.y0 + rect.y1) / 2
    headers = [w for w in words if w[4].lower() == "current" and w[0] > rect.x1 and 0 < center - (w[1]+w[3])/2 < 25]
    if not headers:
        return None
    header = min(headers, key=lambda w: w[0])
    ytd = [w for w in words if w[4].lower() == "ytd" and w[0] > header[2] and abs(w[1]-header[1]) < 3]
    if not ytd:
        return None
    right = min(w[0] for w in ytd)
    amounts = [w[4] for w in words if w[0] >= header[0]-5 and w[2] < right and abs((w[1]+w[3])/2-center) < 2 and re.fullmatch(r"[\d,]+\.\d{2}", w[4])]
    if len(amounts) == 1:
        return amounts[0]
    return _earnings_amount(words, header, right, center)


def _earnings_amount(words, header, right, center):
    columns = [w for w in words if w[4].lower() == "earnings" and header[0] < w[0] < right and header[1] < w[1] < center]
    if len(columns) != 1:
        return None
    values = [w[4] for w in words if abs(w[2]-columns[0][2]) < 3 and abs((w[1]+w[3])/2-center) < 2 and re.fullmatch(r"[\d,]+\.\d{2}",w[4])]
    return values[0] if len(values) == 1 else None
