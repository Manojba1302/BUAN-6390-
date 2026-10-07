"""Compare what a model returned with the answer key, and add the results up.

A field ends in one of five states:
  correct   expected a value and got the same value
  wrong     expected a value and got a different one
  missed    expected a value and got nothing
  invented  expected nothing (not printed) but got a value: the worst case
  blank_ok  expected nothing and got nothing

"Same value" is judged after normalising, so "$3,250.00" equals "3250" and
"Sep 1, 2026" equals "2026-09-01". Names ignore case and punctuation.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime

AMOUNT_HINTS = ("pay", "gross", "balance", "wages", "tax", "deposits", "withdrawals")
DIGIT_FIELDS = ("ssn", "ein", "account_mask", "zip", "license_number", "tax_year")
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y")


def _as_date(value: str) -> str | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _as_amount(value: str) -> str | None:
    digits = re.sub(r"[^0-9.\-]", "", value)
    try:
        return f"{float(digits):.2f}"
    except ValueError:
        return None


def normalise(field: str, value) -> str | None:
    """One comparable string per value, or None when there is no value."""
    if value is None or str(value).strip().lower() in ("", "null", "none", "n/a", "unknown"):
        return None
    text = str(value).strip()
    if "date" in field or field.startswith(("period_", "pay_period_")):
        return _as_date(text) or text.lower()
    if any(field.endswith(k) for k in DIGIT_FIELDS):
        return re.sub(r"\D", "", text)[-4:] if field == "account_mask" else re.sub(r"\D", "", text)
    if field != "pay_frequency" and any(k in field for k in AMOUNT_HINTS):
        return _as_amount(text) or text
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", text.lower())).strip()


def field_state(field: str, expected, got) -> str:
    want, have = normalise(field, expected), normalise(field, got)
    if want is None:
        return "blank_ok" if have is None else "invented"
    if have is None:
        return "missed"
    return "correct" if want == have else "wrong"


def score_fields(expected: dict, got: dict) -> dict[str, dict]:
    """Per field: state, expected value, returned value."""
    out = {}
    for name, want in expected.items():
        have = (got.get(name) or {}).get("value") if isinstance(got.get(name), dict) else got.get(name)
        out[name] = {"state": field_state(name, want, have), "expected": want, "got": have}
    return out


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def classification_summary(items: list[dict], key: str) -> dict:
    """Accuracy and confusion matrix for one stage ("stage1" or "stage2")."""
    done = [i for i in items if i.get(key) and not i[key].get("error")]
    right = sum(1 for i in done if i[key]["detected"] == i["type"])
    confusion: dict[str, Counter] = defaultdict(Counter)
    for i in done:
        confusion[i["type"]][i[key]["detected"]] += 1
    times = [i[key]["ms"] for i in done]
    return {"documents": len(done), "correct": right, "accuracy": _pct(right, len(done)),
            "errors": sum(1 for i in items if i.get(key, {}).get("error")),
            "confusion": {k: dict(v) for k, v in confusion.items()}, **timing(times)}


def timing(times: list[int]) -> dict:
    if not times:
        return {"avg_ms": None, "max_ms": None}
    return {"avg_ms": int(sum(times) / len(times)), "max_ms": max(times)}


def extraction_summary(items: list[dict]) -> dict:
    """Field accuracy overall, per document type and per field."""
    states, per_type, per_field = Counter(), defaultdict(Counter), defaultdict(Counter)
    done = [i for i in items if i.get("extraction") and not i["extraction"].get("error")]
    for item in done:
        for name, result in item["extraction"]["fields"].items():
            states[result["state"]] += 1
            per_type[item["type"]][result["state"]] += 1
            per_field[f"{item['type']}.{name}"][result["state"]] += 1
    return {"documents": len(done), "states": dict(states), "accuracy": _accuracy(states),
            "per_type": {k: {**v, "accuracy": _accuracy(v)} for k, v in per_type.items()},
            "per_field": {k: {**v, "accuracy": _accuracy(v)} for k, v in per_field.items()},
            "errors": sum(1 for i in items if i.get("extraction", {}).get("error")),
            **timing([i["extraction"]["ms"] for i in done])}


def _accuracy(states: Counter) -> float | None:
    """Correct out of the fields that had a value to find."""
    expected = states["correct"] + states["wrong"] + states["missed"]
    return _pct(states["correct"], expected)


def summarise(items: list[dict]) -> dict:
    by_variant = {}
    for variant in sorted({i["variant"] for i in items}):
        subset = [i for i in items if i["variant"] == variant]
        by_variant[variant] = {"stage1": classification_summary(subset, "stage1"),
                               "stage2": classification_summary(subset, "stage2"),
                               "extraction": extraction_summary(subset)}
    return {"stage1": classification_summary(items, "stage1"),
            "stage2": classification_summary(items, "stage2"),
            "extraction": extraction_summary(items), "by_variant": by_variant}
