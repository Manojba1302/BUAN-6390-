import unittest
from unittest.mock import Mock
from app.db.models import Extraction
from app.services.saved_document_evidence import _save
import bank_evidence
import money_values

TEXT = "Account summary\nATM and debit card subtractions\n-245.56\nOther subtractions\n-2,869.00\nService fees\n-0.00\nEnding balance\n$0.47"

class BankEvidenceTests(unittest.TestCase):
    def test_summary_components_are_added_exactly(self):
        self.assertEqual(bank_evidence.total_from_summary(TEXT), "3114.56")
        self.assertEqual(money_values.amount("total_withdrawals", "3265", TEXT), "3114.56")

    def test_missing_duplicate_and_positive_components_are_not_guessed(self):
        for text in (TEXT.replace("Service fees", "Other fees"), TEXT.replace("-245.56", "245.56"), TEXT.replace("Other subtractions", "Other subtractions -2.00 Other subtractions"), "-245.56 -2,869.00 -0.00"):
            self.assertIsNone(bank_evidence.total_from_summary(text))

    def test_saved_user_corrections_are_preserved(self):
        row = Extraction(field_name="total_withdrawals", value_raw="3265", corrected_value="3200.00")
        _save(Mock(), Mock(), [row], "total_withdrawals", {"value": "3114.56"})
        self.assertEqual(row.corrected_value, "3200.00")
        self.assertEqual(row.value_raw, "3265")

    def test_recovery_retains_original_model_reading(self):
        row = Extraction(field_name="total_withdrawals", value_raw="3265")
        payload = bank_evidence.recover("bank_statement", [{"text": TEXT, "page": 1}])["total_withdrawals"]
        _save(Mock(), Mock(), [row], "total_withdrawals", payload)
        self.assertEqual(row.value_raw, "3265")
        self.assertEqual(row.value_normalized, "3114.56")
