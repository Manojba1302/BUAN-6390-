import unittest
from money_values import amount
class MoneyTests(unittest.TestCase):
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
