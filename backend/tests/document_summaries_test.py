import unittest
from unittest.mock import Mock, patch
from app.services import document_summaries as summaries

class SummaryTests(unittest.TestCase):
    def test_complete_payroll_request_routes(self):
        self.assertEqual(summaries.intent("Summarize my pay slip, separating regular pay, overtime, deductions, and net pay."), "paystub")
        self.assertIn("regular_pay", summaries.SUMMARY_FIELDS["paystub"])
        self.assertIn("overtime_pay", summaries.SUMMARY_FIELDS["paystub"])
        self.assertIn("net_pay", summaries.SUMMARY_FIELDS["paystub"])

    def test_broad_or_comparison_requests_remain_general(self):
        for question in ("Summarize all documents", "Compare a summary of my W-2 and pay slip", "Explain why my pay slip differs", "Summarize my lease"):
            self.assertIsNone(summaries.intent(question))

    def test_missing_deductions_are_explicit_not_invented(self):
        db = Mock()
        db.scalars.return_value.all.return_value = [Mock(original_name="pay.pdf")]
        with patch.object(summaries.fields, "_reply", return_value={"answer":"Net pay: 932.78", "citations":[]}):
            reply = summaries.answer(db, Mock(), None, "Summarize my pay slip")
        self.assertIn("Deductions: the summary lists saved total deductions", reply["answer"])
        self.assertIn("unknown, not zero", reply["answer"])
