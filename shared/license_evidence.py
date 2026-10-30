"""Conservative license recovery from numbered OCR labels, with exact ID support."""
import re
import address_evidence


def _entry(value, quote, page):
    return {"value": value, "normalized": value, "quote": quote[:500],
            "page": page.get("page"), "method": page.get("method", "ocr")}


def _names(text, page):
    # OCR sometimes adds a colon or dot after the field number ("1: UWAZIE").
    surname = re.findall(r"^1[:.]?[ \t]+([A-Z][A-Z .'-]*)$", text, re.M | re.I)
    given = re.findall(r"^2[:.]?[ \t]+([A-Z][A-Z .'-]*)$", text, re.M | re.I)
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


def supported_identifier(value, texts):
    """Whether the page text prints this number beside a license-number label."""
    return _supported_identifier(value, texts)


def _supported_identifier(value, texts):
    # Never accept a matching substring within a longer OCR identifier.
    if not value or not re.fullmatch(r"[A-Z0-9-]{4,24}", value, re.I):
        return False
    label = r"(?:\b4d\s*(?:DL\s*)?|\b(?:DLN?|LIC(?:ENSE)?(?:\s+(?:NO|NUMBER))?)\s*[:#]?\s*)"
    token = "".join("[" + re.escape("".join(sorted(group))) + "]" if (group := _look_alikes(ch)) else re.escape(ch) for ch in value.upper())
    pattern = label + token + r"(?![A-Z0-9-])"
    if any(re.search(pattern, text, re.I) for text in texts):
        return True
    return _garbled_label_supports(token, texts)


# On a photo, the tiny "4d DL" label is often read as digits glued to the number:
# "4d DL 52224976" comes back as "44052224976", "14052224976" or "440152224976".
# The number the model read is accepted only when it sits right after such a run,
# on the line that also carries a date (Texas and AAMVA cards print 3 DOB beside it).
GARBLED_LABEL = r"(?<![A-Z0-9])[14]?4[DAO04]?[D0O][L1I|]?"
LINE_DATE = r"\d{2}/\d{2}/\d{4}"


def _garbled_label_supports(token, texts):
    pattern = GARBLED_LABEL + token + r"(?![A-Z0-9-])"
    return any(re.search(LINE_DATE, line) and re.search(pattern, line, re.I)
               for text in texts for line in text.splitlines())


# How common US states print their license numbers. Used only to peel a garbled label off
# a number: with the state's exact length known, "052224976" on a Texas card can only be
# the label's "DL" read as "0" followed by the 8-digit number 52224976.
STATE_FORMATS = {
    "TX": r"\d{8}", "CA": r"[A-Z]\d{7}", "FL": r"[A-Z]\d{12}", "NY": r"\d{9}", "IL": r"[A-Z]\d{11}",
    "GA": r"\d{9}", "AZ": r"[A-Z]\d{8}|\d{9}", "OK": r"[A-Z]\d{9}|\d{9}", "LA": r"\d{9}", "NM": r"\d{9}",
    "CO": r"\d{9}", "NJ": r"[A-Z]\d{14}", "PA": r"\d{8}", "OH": r"[A-Z]{2}\d{6}", "MI": r"[A-Z]\d{12}",
    "MA": r"[A-Z]\d{8}", "AR": r"\d{9}",
}
STATE_NAMES = {"TEXAS": "TX", "CALIFORNIA": "CA", "FLORIDA": "FL", "NEW YORK": "NY", "ILLINOIS": "IL",
               "GEORGIA": "GA", "ARIZONA": "AZ", "OKLAHOMA": "OK", "LOUISIANA": "LA", "NEW MEXICO": "NM",
               "COLORADO": "CO", "NEW JERSEY": "NJ", "PENNSYLVANIA": "PA", "OHIO": "OH", "MICHIGAN": "MI",
               "MASSACHUSETTS": "MA", "ARKANSAS": "AR"}
# What the small "4d DL" label turns into when OCR glues it to the number:
# "052224976", "44052224976", "14052224976", "440152224976", "10.52224976".
GLUE = r"[14DAL0OI|.:]{1,4}"
# The same label, glued to the number, as seen across OCR versions and image sizes:
# "0652224976", "460052224976" ("4d DL" -> "06", "4600"). Up to four characters, digits included.
GLUE_WIDE = r"[0-9A-Z|.:]{1,4}"
# Labels of the card's other numbers; a number printed right after one of them is not the license number.
OTHER_LABEL = r"(?:\bDD|\bDOB|\bISS|\bEXP|\bICN|\bAUDIT|\bZIP)\W{0,3}$"
DIGIT_FOR = str.maketrans({"S": "5", "O": "0", "D": "0", "I": "1", "L": "1", "|": "1", "B": "8", "Z": "2", "G": "6"})


def card_state(texts, extracted=None):
    """The issuing state, when the card's address line, its state name and the model agree on one."""
    found = set()
    if extracted and re.fullmatch(r"[A-Z]{2}", str(extracted).strip().upper()):
        found.add(str(extracted).strip().upper())
    for text in texts:
        found.update(m for m in re.findall(r"[A-Z]{2,}[ \t]*,[ \t]*([A-Z]{2})[ \t]*\d{5}\b", text.upper()) if m in STATE_FORMATS)
        found.update(code for name, code in STATE_NAMES.items() if re.search(r"\b" + name + r"\b", text.upper()))
        # OCR often mangles the state letters ("DALLAS, TK75252") but keeps the ZIP code.
        found.update("TX" for zip_code in re.findall(r",[^\n,]{0,6}?(\d{5})\b", text) if _texas_zip(zip_code))
    return found.pop() if len(found) == 1 else None


def _texas_zip(zip_code):
    prefix = int(zip_code[:3])
    return 750 <= prefix <= 799 or prefix in (733, 885)


def clean_identifier(value):
    """The number alone, without a label the model copied ("DL 52224976", "4d DL: 52224976")."""
    text = str(value or "").strip().upper()
    text = re.sub(r"^(?:4D\b[\s.:#]*)?(?:(?:DLN?|LIC(?:ENSE)?|NO|NUMBER)\b[\s.:#]*)*", "", text)
    return re.sub(r"[\s.]+", "", text)   # license numbers carry no spaces or dots


def _token(value):
    return "".join("[" + re.escape("".join(sorted(group))) + "]" if (group := _look_alikes(ch)) else re.escape(ch) for ch in value)


# A short word OCR made of the "4d" label ("4d", "ad", "id", "is", "DL") before the glued run.
LABEL_WORD = r"(?:\b[4AIT1][DLS]|\bDLN?)[ \t.:]+"


def _glued_supports(value, texts):
    """The number sits right after a short garbled label: on the card's date-of-birth line,
    or after a word that is what OCR made of the "4d" label."""
    glued = r"(?<![A-Z0-9])" + GLUE_WIDE + _token(value) + r"(?![A-Z0-9-])"
    for line in (line for text in texts for line in text.splitlines()):
        if re.search(glued, line, re.I) and (re.search(LINE_DATE, line) or re.search(LABEL_WORD + glued, line, re.I)):
            return True
    return False


def _standalone_supports(value, texts):
    """OCR printed the same number as a word of its own, not after another number's label.

    The model read the image and OCR read the text independently; both giving one number that
    fits the state's format is agreement, even when OCR split or lost the small label."""
    pattern = re.compile(r"(?<![A-Z0-9])" + _token(value) + r"(?![A-Z0-9-])", re.I)
    for line in (line for text in texts for line in text.splitlines()):
        if any(not re.search(OTHER_LABEL, line[:hit.start()], re.I) for hit in pattern.finditer(line)):
            return True
    return False


def _format_supports(number, texts, fmt):
    return bool(re.fullmatch(fmt, number)) and (_glued_supports(number, texts) or _standalone_supports(number, texts))


def _as_state_digits(number, fmt):
    """A digits-only state format turns look-alike letters the model read ("S2224976") into digits."""
    digits = number.translate(DIGIT_FOR)
    return digits if "A-Z" not in fmt and digits.isdigit() else number


def confirm(value, texts, state=None):
    """The license number to save, or None when the page text does not back it up.

    Exact label support wins. On a photo, where OCR mangles the small label, the number is
    accepted only when it fits the issuing state's format and OCR prints it either right after
    the mangled label on the date-of-birth line, or as a word of its own that no other label
    (DD, DOB, ISS, EXP) introduces. When the model copied the mangled run itself, the label part
    is peeled off the same way.
    """
    number, fmt = clean_identifier(value), STATE_FORMATS.get(state or "")
    if not re.fullmatch(r"[A-Z0-9-]{4,24}", number):
        return None
    number = _as_state_digits(number, fmt) if fmt else number
    if _supported_identifier(number, texts) and (not fmt or re.fullmatch(fmt, number)):
        return number
    if not fmt:
        return None
    if _format_supports(number, texts, fmt):
        return number
    for cut in range(1, 5):
        head, core = number[:cut], number[cut:]
        if re.fullmatch(GLUE_WIDE, head, re.I) and _format_supports(core, texts, fmt):
            return core
    return None


# Characters OCR commonly confuses; one look-alike per position is still the same printed ID.
LOOK_ALIKES = ("S5$", "O0D", "I1L|", "B8", "Z2", "G6")


def _look_alikes(ch):
    return next((group for group in LOOK_ALIKES if ch in group), "")


def _recover_identifier(pages):
    """Recover only an unambiguous, explicitly labelled and reliable reading."""
    candidates = {}
    label = r"(?:\b4d[ \t]+(?:DL[ \t]+)?|\bDL(?:N|[ \t]+NUMBER)?[ \t]*[:#]?[ \t]+|\bLICEN[SC]E[ \t]+(?:NO\.?|NUMBER)[ \t]*[:#]?[ \t]*)"
    for page in pages:
        text = page.get("text") or ""
        if not re.search(r"driver'?s?\s+licen[sc]e", text, re.I):
            continue
        for match in re.finditer(label + r"([A-Z0-9][A-Z0-9-]{3,23})(?![A-Z0-9/.-])", text, re.I):
            value = match[1].upper()
            if not any(ch.isdigit() for ch in value):
                continue
            trusted = page.get("method") == "native_text" or page.get("ocr_confidence", 0) >= 85
            candidates.setdefault(value, []).append(_entry(value, match[0], page) if trusted else None)
    if len(candidates) != 1:
        return None
    return next((entry for entry in next(iter(candidates.values())) if entry), None)


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
    if not result.get("license_number", {}).get("value"):
        recovered = _recover_identifier(pages)
        if recovered:
            result["license_number"] = recovered
    return _confirm_identifier(result, [p.get("text") or "" for p in pages])


def _confirm_identifier(result, texts):
    """Keep the license number only when the page text backs it up, label peeled off."""
    entry = result.get("license_number")
    number = confirm(entry.get("value"), texts, card_state(texts, result.get("state", {}).get("value"))) if entry else None
    if number:
        result["license_number"] = {**entry, "value": number, "normalized": number}
    else:
        result.pop("license_number", None)
    return result
