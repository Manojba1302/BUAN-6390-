import unittest
from unittest.mock import Mock
from app.services.document_answers import intent, _file_lines, _value
from app.db.models import Extraction

class DocumentAnswerTests(unittest.TestCase):
    def test_expiry_synonyms_route_to_license_field(self):
        for question in ("When does my driving license expire?", "What is the expiry date on my licence?", "License expiration date"):
            fields, tags = intent(question)
            self.assertIn("expiry_date", fields)
            self.assertEqual(tags, ["drivers_license"])

    def test_explanations_and_calculations_remain_document_search(self):
        for question in ("Explain my bank balance", "Calculate my monthly income", "Compare the names in my documents"):
            self.assertIsNone(intent(question))

    def test_manual_correction_and_intentional_blank_take_priority(self):
        row = Extraction(field_name="expiry_date", value_raw="2027-01-01", corrected_value="2028-01-01")
        self.assertEqual(_value(row), "2028-01-01")
        row.corrected_value = ""
        self.assertEqual(_value(row), "")

    def test_missing_field_is_explicit_and_owner_is_separate(self):
        file = Mock(original_name="license.pdf", document_tag="drivers_license", status="completed")
        result = _file_lines(file, {"full_name": Extraction(field_name="full_name", value_raw="Another Person")}, ("expiry_date",))
        self.assertIn("Another Person", result[0])
        self.assertIn("not extracted", result[0])

    def test_pay_rate_does_not_use_gross(self):
        fields, tags = intent("What is the pay rate on my payslip?")
        self.assertEqual(fields, ("pay_rate", "pay_rate_basis"))
        self.assertEqual(tags, ["paystub"])


import os
from sqlalchemy import select
from app.db.models import Application
from app.api.v1 import chat
from tests import postgres_test
from unittest.mock import patch

@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires isolated PostgreSQL")
class DirectAnswerDatabaseTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp
    tearDown = postgres_test.DatabaseTests.tearDown
    _file = postgres_test.DatabaseTests._file

    def test_expiry_answer_returns_each_owner_and_preserves_correction(self):
        first = self._file("drivers_license", full_name="Person One", expiry_date="2027-01-01")
        self._file("drivers_license", full_name="Person Two", expiry_date="2029-02-01")
        row = self.db.scalar(select(Extraction).where(Extraction.file_id == first.file_id, Extraction.field_name == "expiry_date"))
        row.corrected_value = "2028-01-01"
        self.db.commit()
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("must not call model")):
            response = self.client.post("/api/v1/chat", json={"question": "When does my driving license expire?", "application_id": str(self.app_row.application_id)})
        self.assertEqual(response.status_code, 200)
        answer = response.json()
        self.assertIn("Person One", answer["answer"])
        self.assertIn("Person Two", answer["answer"])
        self.assertIn("2028-01-01", answer["answer"])
        self.assertNotIn("2027-01-01", answer["answer"])
        self.assertEqual(len(answer["citations"]), 2)

    def test_field_route_excludes_other_application_and_reports_missing(self):
        file = self._file("drivers_license", full_name="Other Application Owner", expiry_date="2030-01-01")
        other = Application(customer_id=self.customer.customer_id)
        self.db.add(other); self.db.flush(); file.application_id = other.application_id; self.db.commit()
        own = self._file("drivers_license", full_name="Current Application Owner")
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("must not call model")):
            response = self.client.post("/api/v1/chat", json={"question": "When does my license expire?", "application_id": str(self.app_row.application_id)})
        self.assertIn("not extracted", response.json()["answer"])
        self.assertNotIn("Other Application Owner", response.json()["answer"])
        self.assertEqual(response.json()["citations"], [])

    def test_count_questions_use_database_and_filter_document_type(self):
        self._file("paystub", employer_name="Example")
        self._file("w2", employer_name="Example")
        self._file("drivers_license", full_name="Example Person")
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("must not call model")):
            for question, expected in (("how many documents do i have", 3), ("How many payslips do I have?", 1), ("How many W2s do I have?", 1)):
                result = self.client.post("/api/v1/chat", json={"question": question, "application_id": str(self.app_row.application_id)})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(len(result.json()["document_links"]), expected)
                self.assertEqual(result.json()["citations"], [])

    def test_ssn_question_is_fast_masked_and_sourced(self):
        self._file("w2", employee_name="Example Person", employee_ssn="123-45-6789")
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("must not call model")):
            result = self.client.post("/api/v1/chat", json={"question": "what is my ssn number", "application_id": str(self.app_row.application_id)})
        self.assertEqual(result.status_code, 200)
        self.assertIn("6789", result.json()["answer"])
        self.assertNotIn("123-45-6789", result.text)
        self.assertEqual(len(result.json()["citations"]), 1)


class SummaryRoutingTests(unittest.TestCase):
    def test_summary_with_field_names_uses_general_pipeline(self):
        for question in ("Summarize my pay slip, separating regular pay, overtime, deductions, and net pay", "Give an overview of my gross pay", "A summary of my bank balance"):
            self.assertIsNone(intent(question))


class EmployerRoutingTests(unittest.TestCase):
    def test_employer_typo_and_phrases_use_saved_fields(self):
        for question in ("who is my employeer", "who is my emplyer", "who do I work for", "where do I work", "company I work at", "Who are my employers?"):
            self.assertEqual(intent(question)[0], ("employer_name",))

    def test_employee_and_complex_questions_are_not_employer_lookup(self):
        self.assertIsNone(intent("What is my employee number?"))
        self.assertIsNone(intent("Explain why my employeer paid less"))
        self.assertIsNone(intent("Summarize the company I work at"))


class BankFieldsTests(unittest.TestCase):
    def test_unqualified_deposits_and_withdrawals_are_not_omitted(self):
        keys, tags = intent("What are the opening balance, closing balance, deposits, and withdrawals on my bank statement?")
        self.assertTrue({"beginning_balance", "ending_balance", "total_deposits", "total_withdrawals"}.issubset(keys))
