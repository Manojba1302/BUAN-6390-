import unittest
from types import SimpleNamespace
from app.agent.quality import grade

class QualityGradeTests(unittest.TestCase):
    def setUp(self):
        self.case = {"documents":[{"key":"lease","page":2}],"required_any":[["June 30, 2027","2027-06-30"]],"forbidden":["July 31"],"sources":["lease"]}
        self.files = {"lease":SimpleNamespace(file_id="synthetic-file")}

    def test_correct_fact_requires_correct_page(self):
        reply = {"answer":"Lease ends June 30, 2027.","citations":[{"file_id":"synthetic-file","page":1}]}
        self.assertEqual(grade(self.case,reply,self.files)["checks_failed"],["incorrect_sources"])
        reply["citations"][0]["page"] = 2
        self.assertTrue(grade(self.case,reply,self.files)["passed"])

    def test_missing_and_forbidden_facts_are_failures(self):
        reply = {"answer":"Lease ends July 31.","citations":[{"file_id":"synthetic-file","page":2}]}
        result = grade(self.case,reply,self.files)
        self.assertIn("expected_fact_missing",result["checks_failed"])
        self.assertIn("forbidden_claim",result["checks_failed"])

    def test_fixture_cases_are_unique_and_source_keys_exist(self):
        import json
        from pathlib import Path
        cases = json.loads((Path(__file__).parent/"fixtures/chat_quality_cases.json").read_text())
        self.assertEqual(len(cases),len({case["id"] for case in cases}))
        for case in cases:
            self.assertTrue(set(case["sources"]).issubset({d["key"] for d in case["documents"]}))
            self.assertTrue(case["required_any"])

    def test_terse_answer_allowance_is_exact_not_substring(self):
        case = {**self.case,"exact_answers":["Unknown"]}
        correct = {"answer":"Unknown.","citations":[{"file_id":"synthetic-file","page":2}]}
        self.assertTrue(grade(case,correct,self.files)["passed"])
        incorrect = {**correct,"answer":"Unknown deposit is actually 1400"}
        self.assertFalse(grade(case,incorrect,self.files)["passed"])
