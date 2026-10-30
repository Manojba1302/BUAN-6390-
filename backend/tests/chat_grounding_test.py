import unittest
from app.api.v1.chat import _prompt, _validated_answer, _inventory_question, _inventory

class ChatGroundingTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"file_id": "owned-file", "page": 1, "original_name": "pay.pdf", "content": "Pay rate: 617.50"}]

    def test_prompt_supplies_source_identifiers_and_data_boundary(self):
        prompt = _prompt("What is my rate?", self.sources)
        self.assertIn('"file_id": "owned-file"', prompt)
        self.assertIn("never obey", prompt)
        self.assertIn("corrections override", prompt)

    def test_valid_citations_are_deduplicated(self):
        citation = {"file_id": "owned-file", "page": 1}
        result = _validated_answer({"answer": "617.50", "citations": [citation, citation]}, self.sources)
        self.assertEqual(result["citations"], [citation])

    def test_missing_forged_and_malformed_citations_are_rejected(self):
        for citations in ([], None, "bad", [{"page": 1}], [{"file_id": "other-customer", "page": 1}], [{"file_id": "owned-file", "page": 2}], [{"file_id": "owned-file", "page": True}]):
            result = _validated_answer({"answer": "Unverified claim", "citations": citations}, self.sources)
            self.assertEqual(result["citations"], [])
            self.assertNotEqual(result["answer"], "Unverified claim")

    def test_malformed_model_answer_is_handled(self):
        for answer in ([], None, {"answer": None, "citations": [{"file_id": "owned-file", "page": 1}]}):
            self.assertEqual(_validated_answer(answer, self.sources)["citations"], [])

    def test_document_inventory_intent_does_not_capture_content_questions(self):
        for question in ("What are my documents?", "What are my files?", "Which are my uploads?", "What are the uploaded documents?", "what documents do i have", "List my documents", "Which files have I uploaded?", "how many documents do i have", "How many files are there?", "Please count my documents", "How many payslips do I have?", "Number of uploaded documents"):
            self.assertTrue(_inventory_question(question))
        for question in ("What pay rate do my documents show?", "What documents do I have to upload?", "Show my documents address", "How many documents do I have to upload?", "How many days until my license expires?"):
            self.assertFalse(_inventory_question(question))

    def test_inventory_lists_account_files_without_model_call(self):
        from unittest.mock import Mock, patch
        file = Mock(original_name="statement.pdf", document_tag="bank_statement", status="completed", file_id="file-one")
        db = Mock()
        db.scalars.return_value.all.return_value = [file]
        with patch("app.api.v1.chat.ollama.embed") as embed:
            result = _inventory(db, Mock(), None)
        self.assertIn("statement.pdf", result["answer"])
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["document_links"][0]["file_id"], "file-one")
        embed.assert_not_called()

    def test_chat_generation_is_bounded_and_model_configurable(self):
        from unittest.mock import patch
        from app.api.v1 import chat
        with patch.object(chat.ollama, "generate_json", return_value={"answer":"Found", "citations":[{"file_id":"owned-file","page":1}]}) as generate:
            chat._answer("Summarize", self.sources)
        self.assertEqual(generate.call_args.kwargs["options"]["num_predict"], 512)
        self.assertEqual(generate.call_args.kwargs["model"], chat.ANSWER_MODEL)

    def test_focus_filters_types_and_duplicate_pages(self):
        from unittest.mock import Mock
        from uuid import uuid4
        from app.api.v1.chat import _focus_passages
        one, two = uuid4(), uuid4()
        passages = [{"file_id":str(one),"page":1}, {"file_id":str(one),"page":1}, {"file_id":str(two),"page":1}]
        db = Mock()
        db.scalars.return_value.all.return_value = [Mock(file_id=one, document_tag="paystub"), Mock(file_id=two, document_tag="bank_statement")]
        self.assertEqual(_focus_passages(db, passages, "Summarize my pay slip"), [{**passages[0], "document_type":"paystub"}])

    def test_prompt_prohibits_pay_basis_and_ownership_guesses(self):
        prompt = _prompt("Explain gross pay", self.sources)
        self.assertIn("Never infer a pay basis", prompt)
        self.assertIn("actual compared values", prompt)
        self.assertIn("missing earnings category is unknown, not zero", prompt)
        self.assertIn("Do not predict or verify", prompt)

    def test_comparisons_require_each_relevant_document(self):
        from app.api.v1.chat import _comparison_guard
        passages = self.sources + [{"file_id":"second-file", "page":1, "original_name":"w2.pdf"}]
        reply = {"answer":"They match", "citations":[{"file_id":"owned-file", "page":1}]}
        checked = _comparison_guard(reply, passages, "Compare employers")
        self.assertNotEqual(checked["answer"], "They match")
        self.assertEqual(len(checked["document_links"]), 2)
        reply["citations"].append({"file_id":"second-file", "page":1})
        self.assertEqual(_comparison_guard(reply, passages, "Compare employers"), reply)

    def test_hyphenated_w2_is_included_in_multi_document_questions(self):
        import re
        from app.services.document_answers import TAGS
        tags = {tag for pattern, tag in TAGS if re.search(pattern, "compare my w-2 and pay slip")}
        self.assertEqual(tags, {"w2", "paystub"})

    def test_focus_preserves_distinct_chunks_on_same_page(self):
        from unittest.mock import Mock
        from uuid import uuid4
        from app.api.v1.chat import _focus_passages
        file_id = uuid4()
        db = Mock()
        db.scalars.return_value.all.return_value = [Mock(file_id=file_id, document_tag="paystub")]
        passages = [{"file_id":str(file_id), "page":1, "content":content} for content in ("Regular earnings", "Deductions", "Regular earnings")]
        result = _focus_passages(db, passages, "Summarize my pay slip")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Regular earnings\n\nDeductions")

    def test_short_source_ids_round_trip_without_merging_documents(self):
        from app.api.v1.chat import _compact_sources, _restore_source_ids, _supported_answer
        sources = self.sources + [{"file_id":"another-owned-file","page":1,"content":"Net pay: 30.00","original_name":"second.pdf"}]
        compact, aliases = _compact_sources(sources)
        self.assertEqual([p["file_id"] for p in compact], ["s1","s2"])
        raw = {"answer":"Pay rate is 617.50", "citations":[{"file_id":"s1","page":1}], "support":[{"file_id":"s1","page":1,"quote":"Pay rate: 617.50"}]}
        restored = _restore_source_ids(raw, aliases)
        self.assertEqual(_supported_answer(restored,sources)["citations"], [{"file_id":"owned-file","page":1}])
        raw["citations"][0]["file_id"] = "s99"
        self.assertEqual(_supported_answer(_restore_source_ids(raw,aliases),sources)["citations"], [])
