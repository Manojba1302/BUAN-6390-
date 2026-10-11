import os
import unittest
from unittest.mock import patch
from sqlalchemy import select
from app.db.models import Extraction
from app.api.v1 import chat
from tests import postgres_test

@unittest.skipUnless(os.getenv("HOMEFLOW_DB_TEST") == "1", "requires isolated PostgreSQL")
class StructuredChatTests(unittest.TestCase):
    setUp = postgres_test.DatabaseTests.setUp
    tearDown = postgres_test.DatabaseTests.tearDown
    _file = postgres_test.DatabaseTests._file

    def ask(self, question):
        with patch.object(chat.ollama, "embed", side_effect=AssertionError("No model")), patch.object(chat.ollama, "generate_json", side_effect=AssertionError("No model")):
            return chat.ask(chat.Ask(question=question, application_id=self.app_row.application_id), self.db, self.customer)

    def test_employers_match_without_merging_people(self):
        self._file("w2", employer_name="EXAMPLE UNIVERSITY", employee_name="Person One")
        self._file("paystub", employer_name="Example  University", employee_name="Person Two")
        result = self.ask("Compare employer information on my W-2 and pay slip")
        self.assertIn("values match", result["answer"])
        self.assertIn("Person One", result["answer"])
        self.assertIn("Person Two", result["answer"])
        self.assertEqual(len(result["citations"]), 2)
        self.assertIn("do not establish", result["answer"])

    def test_saved_corrections_override_original(self):
        f = self._file("w2", employer_name="Old Employer")
        self._file("paystub", employer_name="New Employer")
        r = self.db.scalar(select(Extraction).where(Extraction.file_id == f.file_id))
        r.corrected_value = "New Employer"; self.db.commit()
        result = self.ask("Compare employers on W-2 and payslip")
        self.assertIn("values match", result["answer"])
        self.assertNotIn("Old Employer", result["answer"])

    def test_blank_correction_is_not_filled_from_original(self):
        f = self._file("w2", employer_name="Example")
        self._file("paystub", employer_name="Example")
        r = self.db.scalar(select(Extraction).where(Extraction.file_id == f.file_id))
        r.corrected_value = ""; self.db.commit()
        result = self.ask("Compare employers")
        self.assertIn("Not enough complete", result["answer"])
        self.assertNotIn("values match", result["answer"])

    def test_address_conflicts_are_not_selected_or_mixed(self):
        self._file("w2", employee_name="Person One", address="1 Main St", city="Dallas", state="TX", zip="75001", employer_name="Company")
        self._file("drivers_license", full_name="Person Two", address="2 Main St", city="Austin", state="TX", zip="73301")
        result = self.ask("Compare addresses across my documents")
        self.assertIn("values differ", result["answer"])
        self.assertIn("not employer addresses", result["answer"])
        self.assertIn("1 Main St", result["answer"])
        self.assertIn("2 Main St", result["answer"])
        self.assertEqual(len(result["citations"]), 2)

    def test_incomplete_address_does_not_match(self):
        self._file("w2", address="1 Main", city="Dallas")
        result = self.ask("Compare addresses")
        self.assertIn("Not enough complete", result["answer"])

    def test_pay_basis_not_inferred_from_period_gross(self):
        self._file("paystub", pay_rate="617.50", pay_rate_basis="semimonthly", gross_pay="961.88", net_pay="932.78")
        result = self.ask("Explain why my gross paycheck differs from my stated pay rate")
        self.assertIn("617.50", result["answer"])
        self.assertIn("961.88", result["answer"])
        self.assertIn("semimonthly", result["answer"])
        self.assertIn("reason cannot be determined", result["answer"])
        self.assertNotIn("1923.76", result["answer"])
