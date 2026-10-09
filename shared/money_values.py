"""Preserve decimal amounts, recovering cents only from one corroborating quote."""
import re
from decimal import Decimal, InvalidOperation
MONEY_FIELDS = {"gross_pay","net_pay","ytd_gross","box1_wages","box2_federal_tax","beginning_balance","ending_balance","total_deposits","total_withdrawals"}
def amount(field, value, quote=""):
    if field not in MONEY_FIELDS: return None
    clean = re.sub(r"[$,\s]", "", str(value))
    if not re.fullmatch(r"-?\d+(?:\.\d{1,2})?", clean): return None
    candidates = re.findall(r"(?<![\d.])-?\d[\d,]*\.\d{2}(?!\d)", quote)
    if "." not in clean and len(candidates) == 1:
        source = candidates[0].replace(",", "")
        if Decimal(source).to_integral_value(rounding="ROUND_DOWN") == Decimal(clean): clean = source
    return format(Decimal(clean), ".2f")
