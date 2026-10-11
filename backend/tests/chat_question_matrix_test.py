"""Schema coverage and natural-language regression questions; synthetic data only."""
import unittest
import doc_types
from app.services.document_answers import intent, _value
from app.db.models import Extraction

CASES = [
    ("What is my SSN number?", "employee_ssn"),
    ("Show my social security number", "ssn"),
    ("What is my DL number?", "license_number"),
    ("Which bank is on my statement? institution name", "institution"),
    ("What is the account number?", "account_mask"),
    ("What is the employer EIN?", "employer_ein"),
    ("What are my year-to-date earnings?", "ytd_gross"),
    ("When is the expiry date in my driving license?", "expiry_date"),
    ("What job title is printed on my payslip?", "position"),
    ("How much is my take home pay?", "net_pay"),
    ("What is my postal code?", "zip"),
    ("What is the rate of pay?", "pay_rate"),
]

class QuestionMatrixTests(unittest.TestCase):
    def test_natural_language_questions(self):
        for question, expected in CASES:
            with self.subTest(question=question):
                self.assertIn(expected, intent(question)[0])

    def test_every_catalogue_field_with_four_question_forms(self):
        import json
        from pathlib import Path
        cases = json.loads((Path(__file__).parent / "fixtures/chat_questions.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(document=case["document_type"], question=case["question"]):
                self.assertIn(case["expected_field"], intent(case["question"])[0])

    def test_identifiers_are_masked_in_answers_and_corrections(self):
        row = Extraction(field_name="employee_ssn", value_raw="123-45-6789")
        self.assertEqual(_value(row), "••••6789")
        row.corrected_value = "987-65-4321"
        self.assertEqual(_value(row), "••••4321")
        row.corrected_value = ""
        self.assertEqual(_value(row), "")
