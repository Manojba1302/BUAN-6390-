"""Tests for the model evaluation tool. No real model is called: Ollama is faked.

Run from worker/:  python -m unittest tests.test_evaluation
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import doc_types
import pages
from evaluation import compare, make_samples, run, sample_data, scoring


def perfect_classifier(**kwargs):
    """Stands in for the vision model: answers from the page text, like a good model would."""
    text = kwargs["prompt"].split("Text found on the page:")[-1] if "Text found" in kwargs["prompt"] else ""
    return {"document_type": doc_types.regex_vote(text) or "unknown", "readable": True, "evidence": []}


class ScoringTests(unittest.TestCase):
    def test_equal_values_written_differently_match(self):
        self.assertEqual(scoring.normalise("gross_pay", "$3,250.00"), scoring.normalise("gross_pay", "3250"))
        self.assertEqual(scoring.normalise("pay_date", "Sep 19, 2026"), "2026-09-19")
        self.assertEqual(scoring.normalise("pay_period_start", "09/01/2026"), "2026-09-01")
        self.assertEqual(scoring.normalise("employee_name", "JORDAN A. SAMPLE"),
                         scoring.normalise("employee_name", "Jordan A Sample"))
        self.assertEqual(scoring.normalise("account_mask", "XXXX-4821"), "4821")
        self.assertEqual(scoring.normalise("employee_ssn", "000 12 3456"), "000123456")

    def test_five_field_states(self):
        self.assertEqual(scoring.field_state("net_pay", "2481.36", "$2,481.36"), "correct")
        self.assertEqual(scoring.field_state("net_pay", "2481.36", "2418.36"), "wrong")
        self.assertEqual(scoring.field_state("net_pay", "2481.36", None), "missed")
        self.assertEqual(scoring.field_state("pay_frequency", None, "biweekly"), "invented")
        self.assertEqual(scoring.field_state("pay_frequency", None, "null"), "blank_ok")

    def test_accuracy_ignores_fields_that_are_not_printed(self):
        items = [{"type": "paystub", "variant": "digital", "extraction": {"ms": 5, "fields": {
            "net_pay": {"state": "correct"}, "gross_pay": {"state": "wrong"},
            "pay_frequency": {"state": "blank_ok"}}}}]
        summary = scoring.extraction_summary(items)
        self.assertEqual(summary["accuracy"], 50.0)


class SampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.labels = make_samples.build(cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_type_has_digital_and_photo_copies(self):
        self.assertEqual(len(self.labels), 33)
        for doc_type in doc_types.type_ids():
            variants = {l["variant"] for l in self.labels if l["type"] == doc_type}
            self.assertEqual(variants, {"digital", "photo"}, doc_type)
        self.assertTrue(all((self.dir / l["file"]).is_file() for l in self.labels))

    def test_answer_key_matches_what_is_printed(self):
        """Every expected value is really on its PDF, so a mistake is the model's, not ours."""
        for label in (l for l in self.labels if l["variant"] == "digital"):
            text = pages.native_text((self.dir / label["file"]).read_bytes())[0]
            expected_type = label["type"] if label["type"] != "unknown" else None
            self.assertEqual(doc_types.regex_vote(text), expected_type, label["file"])
            for name, value in label["fields"].items():
                if value and name not in ("account_mask", "pay_frequency") and "date" not in name \
                        and "period" not in name and "pay" not in name and "balance" not in name:
                    self.assertIn(str(value).lower().replace(".00", ""), text.lower().replace(",", ""), f"{label['file']} {name}")

    def test_photos_have_no_text_layer(self):
        photo = next(l for l in self.labels if l["variant"] == "photo")
        document = pages.read_document((self.dir / photo["file"]).read_bytes(), "image/jpeg", photo["file"])
        self.assertEqual(document["pages"][0]["method"], "vision")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.samples, self.out = Path(self.tmp.name) / "s", Path(self.tmp.name) / "r"
        self.labels = make_samples.build(self.samples)

    def tearDown(self):
        self.tmp.cleanup()

    def _main(self, extract, *extra):
        argv = ["--samples", str(self.samples), "--out", str(self.out), "--name", "t",
                "--variant", "digital", *extra]
        with patch.object(run, "missing_models", return_value=[]), \
                patch.object(run.ollama, "generate_json", side_effect=perfect_classifier), \
                patch.object(run.pipeline.ollama, "generate_json", side_effect=perfect_classifier), \
                patch.object(run.pipeline, "extract", side_effect=extract), \
                patch("builtins.print"):
            return run.main(argv)

    def _answer_key(self, document, doc_type):
        text = document["pages"][0]["text"]
        names = {p["key"]: p["name"].lower() for p in sample_data.PEOPLE}
        label = next(l for l in self.labels if l["type"] == doc_type and l["variant"] == "digital"
                     and names[l["person"]] in text.lower())
        return {k: {"value": v} for k, v in label["fields"].items()}

    def test_full_run_scores_and_writes_report(self):
        self.assertEqual(self._main(self._answer_key, "--only", "w2", "ssn_card"), 0)
        result = json.loads((self.out / "t.json").read_text())
        self.assertEqual(result["summary"]["stage2"]["accuracy"], 100.0)
        self.assertEqual(result["summary"]["extraction"]["accuracy"], 100.0)
        self.assertIn("## Summary", (self.out / "t.md").read_text())

    def test_invented_value_is_counted(self):
        def invent(document, doc_type):
            return {"pay_frequency": {"value": "weekly"}}
        self._main(invent, "--only", "paystub")
        states = json.loads((self.out / "t.json").read_text())["summary"]["extraction"]["states"]
        self.assertEqual(states.get("invented"), 1)      # only p2 has no frequency printed
        self.assertEqual(states.get("wrong"), 2)         # p1 and p3 print a different frequency
        self.assertEqual(states.get("missed"), 3 * 8)    # every other paystub field

    def test_model_failure_is_reported_not_fatal(self):
        def broken(document, doc_type):
            raise run.ollama.OllamaError("model crashed")
        self.assertEqual(self._main(broken, "--only", "w2"), 0)
        result = json.loads((self.out / "t.json").read_text())
        self.assertEqual(result["summary"]["extraction"]["errors"], 3)
        self.assertIn("model crashed", (self.out / "t.md").read_text())

    def test_missing_model_stops_with_pull_command(self):
        with patch.object(run, "missing_models", return_value=["gemma3:4b"]), patch("builtins.print") as out:
            self.assertEqual(run.main(["--samples", str(self.samples)]), 2)
        self.assertIn("ollama pull gemma3:4b", out.call_args.args[0])

    def test_compare_lists_each_run(self):
        self._main(self._answer_key, "--only", "ssn_card")
        with patch.object(compare, "RESULTS", self.out), patch("builtins.print"):
            self.assertEqual(compare.main([str(self.out / "t.json")]), 0)
        self.assertIn("| t |", (self.out / "comparison.md").read_text())


if __name__ == "__main__":
    unittest.main()
