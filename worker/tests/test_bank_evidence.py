import unittest
import bank_evidence

SUMMARY = ("Your Adv SafeBalance Banking\nAccount number: 4881 3038 1596\nAccount summary\n"
           "Beginning balance on August 27, 2026\n$3.17\nDeposits and other additions\n3,111.86\n"
           "ATM and debit card subtractions\n-245.56\nOther subtractions\n-2,869.00\nService fees\n-0.00\n"
           "Ending balance on September 25, 2026\n$0.47\n")


class BankSummaryTests(unittest.TestCase):
    def page(self, text, method="native_text"):
        return {"text": text, "page": 1, "method": method}

    def test_bank_of_america_summary_rows_with_amount_on_next_line(self):
        result = bank_evidence.recover("bank_statement", [self.page(SUMMARY)])
        self.assertEqual(result["beginning_balance"]["value"], "3.17")
        self.assertEqual(result["ending_balance"]["value"], "0.47")
        self.assertEqual(result["total_deposits"]["value"], "3111.86")
        self.assertEqual(result["total_withdrawals"]["value"], "3114.56")
        self.assertIn("Ending balance on September 25, 2026", result["ending_balance"]["quote"])

    def test_same_line_amount_and_negative_balance(self):
        result = bank_evidence.summary_balances([self.page("Opening balance: $1,200.00\nClosing balance -$15.20")])
        self.assertEqual(result["beginning_balance"]["value"], "1200.00")
        self.assertEqual(result["ending_balance"]["value"], "-15.20")

    def test_conflicting_values_and_scans_are_left_to_the_model(self):
        two = self.page("Ending balance\n$10.00\nEnding balance\n$12.00")
        self.assertNotIn("ending_balance", bank_evidence.summary_balances([two]))
        self.assertEqual(bank_evidence.summary_balances([self.page(SUMMARY, method="ocr")]), {})

    def test_labels_inside_sentences_are_ignored(self):
        text = "Your ending balance may differ from 12.00 shown elsewhere."
        self.assertEqual(bank_evidence.summary_balances([self.page(text)]), {})


if __name__ == "__main__":
    unittest.main()
