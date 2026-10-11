import unittest
from unittest.mock import Mock
from app.api.v1.documents import _missing_fields
from app.db.models import Extraction
from app.services.employment_suggestions import _discard_label_only_title

class PayFieldReviewTests(unittest.TestCase):
    def test_unprinted_optional_earnings_are_not_missing_requirements(self):
        missing = _missing_fields("paystub", [])
        self.assertNotIn("overtime_pay", missing)
        self.assertNotIn("bonus_pay", missing)
        self.assertNotIn("pay_rate", missing)
        self.assertNotIn("position", missing)
        self.assertNotIn("pay_rate_basis", missing)
    def test_label_only_title_is_removed_but_corrections_are_preserved(self):
        bad = Extraction(field_name="position", value_raw="Pay Rate:")
        corrected = Extraction(field_name="position", value_raw="Pay Rate:", corrected_value="Student Assistant")
        db = Mock()
        self.assertEqual(_discard_label_only_title(db, [bad, corrected]), [corrected])
        db.delete.assert_called_once_with(bad)
