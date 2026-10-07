"""Unit tests for business rules that need no database or running services."""
import json
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import ollama

from app.api.v1.applications import _income_errors
from app.services import classifier, queue
from app.services.prefill import monthly_from_pay


class ClassifierTests(unittest.TestCase):
    def _run(self, answer=None, error=None, regex=None, text="", render_error=None):
        with patch.object(classifier.pages, "first_page_image", return_value=b"img", side_effect=render_error), \
             patch.object(classifier, "_page_one_text", return_value=text), \
             patch.object(classifier.doc_types, "regex_vote", return_value=regex), \
             patch.object(classifier.ollama, "generate_json", return_value=answer, side_effect=error):
            return classifier.classify(body=b"x", content_type="application/pdf", name="a.pdf", selected_type="w2")

    def test_matched(self):
        result = self._run({"document_type": "w2", "readable": True, "evidence": ["Wage and Tax Statement"]})
        self.assertEqual((result["outcome"], result["detected_type"]), ("matched", "w2"))
        self.assertEqual(result["evidence"], ["Wage and Tax Statement"])
        self.assertEqual(result["message"], "Looks like a w-2.")

    def test_mismatched_message_names_both_types(self):
        result = self._run({"document_type": "bank_statement", "readable": True})
        self.assertEqual(result["outcome"], "mismatched")
        self.assertIn("You chose W-2", result["message"])

    def test_unknown_label_from_model_becomes_unknown(self):
        self.assertEqual(self._run({"document_type": "passport"})["detected_type"], "unknown")

    def test_model_down_falls_back_to_regex_vote(self):
        result = self._run(error=ollama.OllamaError("down"), regex="w2")
        self.assertEqual((result["outcome"], result["detected_type"]), ("matched", "w2"))

    def test_unrenderable_file_fails_cleanly(self):
        result = self._run(render_error=ValueError("bad file"))
        self.assertEqual((result["outcome"], result["detected_type"]), ("failed", "unknown"))

    def test_evidence_is_capped_at_four(self):
        result = self._run({"document_type": "w2", "evidence": list("abcdef")})
        self.assertEqual(len(result["evidence"]), 4)


class QueueTests(unittest.TestCase):
    def test_publishes_durable_json_message_and_closes(self):
        conn = MagicMock()
        ids = dict(customer_id=uuid4(), application_id=None, file_id=uuid4())
        with patch.object(queue, "_connection", return_value=conn):
            queue.publish_extraction_job(**ids, document_tag="w2", trace_id="t1")
        kwargs = conn.channel.return_value.basic_publish.call_args.kwargs
        body = json.loads(kwargs["body"])
        self.assertEqual(body, {"customer_id": str(ids["customer_id"]), "application_id": None,
                                "file_id": str(ids["file_id"]), "document_tag": "w2", "trace_id": "t1"})
        self.assertEqual(kwargs["properties"].delivery_mode, 2)
        conn.close.assert_called_once()

    def test_connection_closed_even_when_publish_fails(self):
        conn = MagicMock()
        conn.channel.return_value.basic_publish.side_effect = RuntimeError("broker down")
        with patch.object(queue, "_connection", return_value=conn), self.assertRaises(RuntimeError):
            queue.publish_extraction_job(customer_id=uuid4(), application_id=uuid4(), file_id=uuid4(),
                                         document_tag="w2", trace_id="t")
        conn.close.assert_called_once()


class IncomeRuleTests(unittest.TestCase):
    def test_missing_employment_status(self):
        self.assertIn("Choose your employment situation in Get started", _income_errors({}, []))

    def test_self_employed_rules(self):
        errors = _income_errors({"employmentStatus": "Self-employed", "ownershipPercent": "150"}, [])
        self.assertIn("Ownership percentage must be between 0 and 100", errors)
        self.assertIn("Enter monthly income, or 0 if none", errors)
        self.assertIn("Enter a valid ownership percentage",
                      _income_errors({"employmentStatus": "Self-employed", "ownershipPercent": "abc"}, []))

    def test_negative_and_invalid_amounts(self):
        values = {"employmentStatus": "Self-employed", "ownershipPercent": "50", "selfEmploymentIncome": "-5"}
        self.assertTrue(any("nonnegative" in e for e in _income_errors(values, [])))
        values["selfEmploymentIncome"] = "lots"
        self.assertTrue(any(e.startswith("Enter a valid") for e in _income_errors(values, [])))

    def test_hidden_fields_are_ignored(self):
        self.assertEqual(_income_errors({"employmentStatus": "Employed", "pensionIncome": "-1"}, []), [])

    def test_employed_needs_employer_name_and_base(self):
        errors = _income_errors({"employmentStatus": "Employed"}, [{"employer_name": " ", "base": None}])
        self.assertEqual(errors, ["Employer name", "Base monthly employment income"])

    def test_retired_with_any_income_is_fine(self):
        self.assertEqual(_income_errors({"employmentStatus": "Retired", "pensionIncome": "$1,200"}, []), [])


class PayConversionTests(unittest.TestCase):
    def test_biweekly(self):
        self.assertEqual(monthly_from_pay(Decimal("3000"), "Biweekly")[0], Decimal("6500.00"))

    def test_no_frequency_means_no_income(self):
        self.assertEqual(monthly_from_pay(Decimal("3000"), None), (None, None))
        self.assertEqual(monthly_from_pay(Decimal("3000"), "fortnightly"), (None, None))


if __name__ == "__main__":
    unittest.main()
