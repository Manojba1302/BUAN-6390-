import unittest
from money_values import amount
from unittest.mock import patch
from worker import pipeline
class MoneyTests(unittest.TestCase):
    def test_extraction_preserves_quote_cents_after_refactor(self):
        document = {"pages": [{"text": "W-2", "method": "native_text"}]}
        answer = {"fields": {"box2_federal_tax": {"value": "226", "quote": "226.65"}}}
        with patch.object(pipeline.ollama, "generate_json", return_value=answer):
            fields = pipeline.extract(document, "w2")
        self.assertEqual(fields["box2_federal_tax"]["normalized"], "226.65")
        self.assertEqual(fields["box2_federal_tax"]["quote"], "226.65")

    def test_cents_preserved(self):
        self.assertEqual(amount("box1_wages","11,799.50"),"11799.50")
    def test_single_corresponding_quote_recovers_cents(self):
        self.assertEqual(amount("box2_federal_tax","226","226.65"),"226.65")
    def test_multiple_or_unrelated_quotes_do_not_replace_value(self):
        self.assertEqual(amount("box1_wages","11799","11799.50 and 226.65"),"11799.00")
        self.assertEqual(amount("box1_wages","11799","999.50"),"11799.00")
    def test_identifier_is_not_money(self):
        self.assertIsNone(amount("license_number","123456"))
if __name__ == "__main__": unittest.main()
