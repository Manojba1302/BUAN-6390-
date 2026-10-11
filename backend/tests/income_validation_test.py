import unittest
from fastapi import HTTPException
from app.services.income_validation import clean_rows, employment_errors

class IncomeValidationTests(unittest.TestCase):
    def test_zero_string_is_not_complete_employment_income(self):
        self.assertIn("Base monthly employment income", employment_errors([{"employer_name": "Example", "base": "0.00"}], True))
    def test_previous_job_does_not_require_current_income(self):
        rows = [{"employer_name": "Current", "base": "1235.00"}, {"employer_name": "Previous", "base": "", "is_current": False}]
        self.assertEqual(employment_errors(rows, True), [])
        self.assertIn("At least one current job", employment_errors([rows[1]], True))
    def test_currency_formatting_and_blank_dates_save(self):
        row = clean_rows([{"base": "$1,235.00", "start_date": "", "end_date": ""}])[0]
        self.assertEqual(row["base"], "1235.00")
        self.assertIsNone(row["start_date"])
        self.assertEqual(row["bonuses"], "0.00")
    def test_negative_nan_infinity_and_text_are_rejected(self):
        for value in ("-1", "NaN", "Infinity", "lots"):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                clean_rows([{"base": value}])
    def test_reversed_dates_are_rejected(self):
        with self.assertRaises(HTTPException):
            clean_rows([{"start_date": "2026-10-01", "end_date": "2025-10-01"}])
