import unittest
import pay_evidence

class PayEvidenceTests(unittest.TestCase):
    def test_labelled_rate_and_title_are_distinct_from_gross(self):
        text = "Job Title: Student Assistant\nPay Rate: $617.50 Semimonthly\nGross Pay: $961.88"
        fields = pay_evidence.recover("paystub", [{"text": text, "page": 1}], {})
        self.assertEqual(fields["pay_rate"]["value"], "617.50")
        self.assertEqual(fields["pay_rate_basis"]["value"], "semimonthly")
        self.assertEqual(fields["position"]["value"], "Student Assistant")
    def test_gross_only_and_conflicting_rates_are_not_contractual_rates(self):
        self.assertEqual(pay_evidence.recover("paystub", [{"text": "Gross Pay: $961.88 Semimonthly"}], {}), {})
        result = pay_evidence.recover("paystub", [{"text": "Pay Rate: $617.50 Semimonthly\nPay Rate: $700.00 Semimonthly"}], {})
        self.assertNotIn("pay_rate", result)
    def test_existing_corrections_are_preserved(self):
        result = pay_evidence.recover("paystub", [{"text": "Pay Rate: $617.50 Semimonthly"}], {"pay_rate": {}})
        self.assertNotIn("pay_rate", result)

    def test_empty_title_does_not_capture_next_field_label(self):
        for text in ("Job Title: Pay Rate:", "Job Title:\nPay Rate:"):
            self.assertNotIn("position", pay_evidence.recover("paystub", [{"text": text}], {}))

    def test_pdf_column_order_recovers_title_and_rate_by_row(self):
        import fitz
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((30, 50), "Job Title:")
            page.insert_text((30, 70), "Pay Rate:")
            page.insert_text((150, 50), "Student Assistant")
            page.insert_text((150, 70), "$617.50 Semimonthly")
            result = pay_evidence.recover("paystub", [{"text": pay_evidence.aligned_labels(page), "page": 1}], {})
            self.assertEqual(result["position"]["value"], "Student Assistant")
            self.assertEqual(result["pay_rate"]["value"], "617.50")
            self.assertEqual(result["pay_rate_basis"]["value"], "semimonthly")

    def test_current_categories_and_explicit_zero_are_recovered(self):
        fields = pay_evidence.recover("paystub", [{"page":2,"text":"Regular earnings: $961.88\nOvertime: 0.00\nTotal deductions: 29.10\nFederal withholding: 29.10"}], {})
        self.assertEqual(fields["regular_pay"]["value"], "961.88")
        self.assertEqual(fields["overtime_pay"]["value"], "0.00")
        self.assertEqual(fields["total_deductions"]["page"], 2)

    def test_ytd_multi_column_and_conflicting_amounts_remain_unknown(self):
        text = "YTD Regular pay: 9999.00\nRegular pay: 100.00 9999.00\nOvertime: 12.00\nOvertime: 14.00"
        result = pay_evidence.recover("paystub", [{"text":text}], {})
        self.assertNotIn("regular_pay", result)
        self.assertNotIn("overtime_pay", result)

    def test_saved_blank_category_is_not_overwritten(self):
        result = pay_evidence.recover("paystub", [{"text":"Regular pay: 961.88"}], {"regular_pay":{"value":""}})
        self.assertNotIn("regular_pay", result)

    def test_pdf_current_column_is_separate_from_ytd(self):
        import fitz
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((150,50), "Current")
            page.insert_text((250,50), "YTD")
            page.insert_text((30,65), "Regular (T)")
            page.insert_text((180,65), "961.88")
            page.insert_text((270,65), "13748.14")
            result = pay_evidence.recover("paystub", [{"text":pay_evidence.aligned_labels(page),"page":1}], {})
            self.assertEqual(result["regular_pay"]["value"], "961.88")
            self.assertNotIn("overtime_pay", result)

    def test_earnings_subheading_excludes_hours_and_ytd(self):
        import fitz
        with fitz.open() as doc:
            p = doc.new_page()
            for x,y,value in [(180,50,"Current"),(340,50,"YTD"),(185,60,"Hours"),(240,60,"Earnings"),(340,60,"Hours"),(390,60,"Earnings"),(30,70,"Regular (T)"),(185,70,"67.50"),(240+fitz.get_text_length("Earnings",fontsize=11)-fitz.get_text_length("961.88",fontsize=11),70,"961.88"),(340,70,"1021.50"),(380,70,"13689.64")]:
                p.insert_text((x,y),value)
            # Explicit amount alignment is required, not a guess from the largest number.
            result = pay_evidence.aligned_labels(p)
            self.assertIn("Regular earnings: 961.88", result)
            self.assertNotIn("Regular earnings: 67.50", result)
            self.assertNotIn("Regular earnings: 13689.64", result)
