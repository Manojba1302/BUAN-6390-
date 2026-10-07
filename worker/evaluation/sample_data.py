"""Fictional people and the documents we print for them.

Every name, number and company here is invented. SSNs start with 000, which
the SSA never issues, so nothing in this file can belong to a real person.

Each builder returns (lines, fields): the text printed on the page and the
answer key, written the way the extraction prompt asks for values
(dates YYYY-MM-DD, amounts digits only). A field set to None is deliberately
not printed, so a model that returns a value for it has invented one.
"""
from __future__ import annotations

PEOPLE = [
    {"key": "p1", "name": "Jordan A. Sample", "employer": "Northwind Example Logistics LLC",
     "ein": "12-3456789", "ssn": "000-12-3456", "dob": ("04/12/1990", "1990-04-12"),
     "street": "123 Maple Test Ave", "city": "Dallas", "zip": "75201", "dl": "40112233",
     "bank": "Example Community Bank", "acct": "4821", "date_style": "us",
     "pay": {"gross": "3250.00", "net": "2481.36", "ytd": "55250.00", "freq": "Semimonthly"},
     "w2": {"wages": "78000.00", "fed": "9120.00"},
     "stmt": {"begin": "5210.44", "dep": "6500.00", "wd": "4875.19", "end": "6835.25"}},
    {"key": "p2", "name": "Priya Testwell", "employer": "Bluebird Demo Software Inc",
     "ein": "98-7654321", "ssn": "000-98-7654", "dob": ("11/03/1987", "1987-11-03"),
     "street": "45 Elm Placeholder St", "city": "Austin", "zip": "78701", "dl": "27788990",
     "bank": "Sample Federal Credit Union", "acct": "1907", "date_style": "long",
     "pay": {"gross": "4615.38", "net": "3390.12", "ytd": "83076.84", "freq": None},
     "w2": {"wages": "118500.00", "fed": "17775.00"},
     "stmt": {"begin": "12040.10", "dep": "9230.76", "wd": "7712.48", "end": "13558.38"}},
    {"key": "p3", "name": "Marcus Q. Fictional", "employer": "Cedar Mock Health Partners",
     "ein": "45-1122334", "ssn": "000-55-1212", "dob": ("01/28/1995", "1995-01-28"),
     "street": "9 Birch Demo Rd", "city": "Plano", "zip": "75024", "dl": "13579246",
     "bank": "Demo National Bank", "acct": "3366", "date_style": "iso",
     "pay": {"gross": "1840.00", "net": "1502.77", "ytd": "34960.00", "freq": "Biweekly"},
     "w2": {"wages": "46920.00", "fed": "3980.00"},
     "stmt": {"begin": "840.15", "dep": "3680.00", "wd": "3101.62", "end": "1418.53"}},
]

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def show_date(iso: str, style: str) -> str:
    """Print a date the way this person's documents do, to test normalising."""
    year, month, day = iso.split("-")
    if style == "us":
        return f"{month}/{day}/{year}"
    if style == "long":
        return f"{_MONTHS[int(month) - 1]} {int(day)}, {year}"
    return iso


def money(amount: str) -> str:
    """3250.00 -> $3,250.00"""
    return f"${float(amount):,.2f}"


def paystub(p: dict) -> tuple[list[str], dict]:
    pay, d = p["pay"], p["date_style"]
    start, end, paid = "2026-09-01", "2026-09-15", "2026-09-19"
    lines = [p["employer"].upper(), "Earnings Statement", "",
             f"Employee: {p['name']}", f"Pay Period: {show_date(start, d)} - {show_date(end, d)}",
             f"Pay Date: {show_date(paid, d)}"]
    lines += [f"Pay Frequency: {pay['freq']}"] if pay["freq"] else []
    lines += ["", "Description            Current        YTD",
              f"Gross Pay              {money(pay['gross'])}     {money(pay['ytd'])}",
              "Federal Income Tax     withheld", "Social Security        withheld",
              f"Net Pay                {money(pay['net'])}"]
    fields = {"employee_name": p["name"], "employer_name": p["employer"],
              "pay_period_start": start, "pay_period_end": end, "pay_date": paid,
              "pay_frequency": pay["freq"].lower() if pay["freq"] else None,
              "gross_pay": pay["gross"], "net_pay": pay["net"], "ytd_gross": pay["ytd"]}
    return lines, fields


def w2(p: dict) -> tuple[list[str], dict]:
    w = p["w2"]
    lines = ["Form W-2 Wage and Tax Statement 2025", "OMB No. 1545-0008",
             "Copy B To Be Filed With Employee's FEDERAL Tax Return", "",
             f"a  Employee's social security number   {p['ssn']}",
             f"b  Employer identification number (EIN)   {p['ein']}",
             f"c  Employer's name, address and ZIP code   {p['employer']}",
             f"e  Employee's first name and last name   {p['name']}", "",
             f"1  Wages, tips, other compensation   {float(w['wages']):,.2f}",
             f"2  Federal income tax withheld   {float(w['fed']):,.2f}"]
    fields = {"employee_name": p["name"], "employee_ssn": p["ssn"],
              "employer_name": p["employer"], "employer_ein": p["ein"], "tax_year": "2025",
              "box1_wages": w["wages"], "box2_federal_tax": w["fed"]}
    return lines, fields


def bank_statement(p: dict) -> tuple[list[str], dict]:
    s, d = p["stmt"], p["date_style"]
    start, end = "2026-08-01", "2026-08-31"
    lines = [p["bank"], "Checking Account Statement", "",
             f"Account holder: {p['name']}", f"Account number ending in {p['acct']}",
             f"Statement Period: {show_date(start, d)} - {show_date(end, d)}", "",
             f"Beginning Balance        {money(s['begin'])}",
             f"Total Deposits           {money(s['dep'])}",
             f"Total Withdrawals        {money(s['wd'])}",
             f"Ending Balance           {money(s['end'])}", "",
             "Date        Description              Amount",
             f"{show_date('2026-08-15', d)}  Payroll deposit  {money(s['dep'])}"]
    fields = {"account_holder": p["name"], "institution": p["bank"],
              "account_mask": f"****{p['acct']}", "period_start": start, "period_end": end,
              "beginning_balance": s["begin"], "ending_balance": s["end"],
              "total_deposits": s["dep"], "total_withdrawals": s["wd"]}
    return lines, fields


def drivers_license(p: dict) -> tuple[list[str], dict]:
    iss, exp = "2023-06-14", "2031-04-12"
    lines = ["TEXAS", "DRIVER LICENSE   SPECIMEN", f"DLN {p['dl']}   CLASS C",
             p["name"].upper(), p["street"].upper(), f"{p['city'].upper()}, TX {p['zip']}",
             f"DOB {p['dob'][0]}", f"ISS {show_date(iss, 'us')}   EXP {show_date(exp, 'us')}"]
    fields = {"full_name": p["name"], "date_of_birth": p["dob"][1], "license_number": p["dl"],
              "address": p["street"], "city": p["city"], "state": "TX", "zip": p["zip"],
              "issue_date": iss, "expiry_date": exp}
    return lines, fields


def ssn_card(p: dict) -> tuple[list[str], dict]:
    lines = ["SOCIAL SECURITY", "SPECIMEN", p["ssn"], "THIS NUMBER HAS BEEN ESTABLISHED FOR",
             p["name"].upper(), "", "SIGNATURE ____________________"]
    return lines, {"full_name": p["name"], "ssn": p["ssn"]}


def utility_bill(p: dict) -> tuple[list[str], dict]:
    """Not one of our five types: the right answer is unknown."""
    lines = ["Example City Utilities", "Electric Service Bill", "",
             f"Customer: {p['name']}", f"Service address: {p['street']}, {p['city']} TX",
             "Service from 08/03/2026 to 09/02/2026", "Usage: 812 kWh",
             "Amount due: $118.42   Due date: 09/25/2026"]
    return lines, {}


def lease_letter(p: dict) -> tuple[list[str], dict]:
    """Not one of our five types: the right answer is unknown."""
    lines = ["Oakview Demo Apartments", "Lease Renewal Notice", "",
             f"Dear {p['name']},", "Your lease for unit 4B ends on 11/30/2026.",
             "The renewal rent for a 12 month term is $1,650 per month.",
             "Please sign and return this notice by 10/31/2026.", "", "Leasing Office"]
    return lines, {}


# type id -> (builder, page shape). Cards are printed card sized.
BUILDERS = {
    "paystub": (paystub, "letter"),
    "w2": (w2, "letter"),
    "bank_statement": (bank_statement, "letter"),
    "drivers_license": (drivers_license, "card"),
    "ssn_card": (ssn_card, "card"),
}
UNKNOWN_BUILDERS = [utility_bill, lease_letter]
