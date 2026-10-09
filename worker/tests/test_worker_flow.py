"""Worker job flow and stage-2 classification/extraction rules (database, storage and models are faked)."""
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from worker import main, pipeline

RECORD = {"storage_key": "k.pdf", "content_type": "application/pdf", "original_name": "w2.pdf",
          "document_tag": "w2", "customer_id": "c1", "application_id": "a1"}
DOCUMENT = {"pages": [{"text": "Wage and Tax Statement", "image": None, "method": "native_text"}]}


class FakeDb:
    """Records every db.* call the worker makes, in order."""
    def __init__(self, record=RECORD, attempts=1):
        self.calls, self.record, self.attempts = [], record, attempts

    @contextmanager
    def session(self):
        yield "conn"

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args[1:], kwargs))
            return {"fetch_file": self.record, "bump_attempts": self.attempts}.get(name)
        return call

    def names(self):
        return [c[0] for c in self.calls]


class HandleTests(unittest.TestCase):
    def _run(self, fake, outcome="matched", fields=None):
        fields = {"tax_year": {"value": "2025", "method": "native_text"}} if fields is None else fields
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"%PDF")}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(main, "db", fake), patch.object(main, "_s3", return_value=s3), \
             patch.object(main.config, "markdown_dir", Path(folder)), \
             patch.object(main.pipeline, "read", return_value=DOCUMENT), \
             patch.object(main.pipeline, "classify", return_value={"detected": "w2", "outcome": outcome}), \
             patch.object(main.pipeline, "extract", return_value=fields) as extract, \
             patch.object(main.pipeline, "to_markdown", return_value="# md"), \
             patch.object(main.pipeline, "chunk", return_value=["c"]), \
             patch.object(main.pipeline, "embed_chunks", return_value=[("c", [0.1])]):
            main.handle({"file_id": "f1"})
            md_written = (Path(folder) / "f1.md").exists()
        return extract, md_written

    def test_happy_path_saves_everything_in_order(self):
        fake = FakeDb()
        extract, md_written = self._run(fake)
        self.assertEqual(fake.names(), ["fetch_file", "bump_attempts", "set_status", "save_classification",
                                        "clear_extractions", "save_extraction", "save_markdown",
                                        "replace_chunks", "set_status", "audit"])
        self.assertTrue(md_written)
        extract.assert_called_once()
        final = fake.calls[8]
        self.assertEqual((final[1][1], final[2]), ("completed", {"pages": 1}))
        audit = fake.calls[9]
        self.assertEqual(audit[2]["payload"], {"fields": 1, "chunks": 1, "outcome": "matched"})

    def test_unknown_document_is_not_extracted(self):
        fake = FakeDb()
        extract, _ = self._run(fake, outcome="unknown", fields={})
        extract.assert_not_called()
        self.assertNotIn("save_extraction", fake.names())

    def test_missing_file_drops_the_job(self):
        fake = FakeDb(record=None)
        main.db, original = fake, main.db
        try:
            main.handle({"file_id": "gone"})
        finally:
            main.db = original
        self.assertEqual(fake.names(), ["fetch_file"])

    def test_too_many_attempts_marks_failed(self):
        fake = FakeDb(attempts=99)
        with patch.object(main, "db", fake):
            main.handle({"file_id": "f1"})
        self.assertEqual(fake.calls[-1][1], ("f1", "failed"))
        self.assertEqual(fake.calls[-1][2], {"error": "Too many attempts"})


class OnMessageTests(unittest.TestCase):
    def test_bad_json_and_failures_are_acked_not_retried_forever(self):
        channel, method = MagicMock(), MagicMock(delivery_tag=7)
        main.on_message(channel, method, None, b"not json")
        fake = FakeDb()
        with patch.object(main, "handle", side_effect=RuntimeError("boom")), patch.object(main, "db", fake):
            main.on_message(channel, method, None, json.dumps({"file_id": "f1"}).encode())
        self.assertEqual(channel.basic_ack.call_count, 2)
        self.assertEqual(fake.calls[-1][1], ("f1", "failed"))


class ClassifyTests(unittest.TestCase):
    def _classify(self, pages, answers):
        with patch.object(pipeline.ollama, "generate_json", side_effect=answers):
            return pipeline.classify({"pages": pages}, "w2")

    def test_single_page_match(self):
        page = {"text": "Wage and Tax Statement " * 10, "image": None}
        result = self._classify([page], [{"document_type": "w2", "evidence": ["box 1"]}])
        self.assertEqual((result["detected"], result["outcome"], result["mixed"]), ("w2", "matched", False))
        self.assertEqual(json.loads(result["evidence"]), ["box 1"])

    def test_pages_that_disagree_are_flagged_as_mixed(self):
        pages = [{"text": "x " * 50, "image": None}, {"text": "y " * 50, "image": None}]
        result = self._classify(pages, [{"document_type": "w2"}, {"document_type": "bank_statement"}])
        self.assertEqual((result["detected"], result["mixed"]), ("unknown", True))

    def test_no_pages(self):
        self.assertEqual(self._classify([], [])["detected"], "unknown")


class ExtractTests(unittest.TestCase):
    def test_keeps_first_value_ignores_unknown_fields_and_blanks(self):
        pages = [{"text": "page one", "image": None, "method": "native_text"},
                 {"text": "page two", "image": None, "method": "ocr"}]
        answers = [{"fields": {"tax_year": {"value": "2025", "quote": "2025"}, "made_up": "x",
                               "employer_name": {"value": "N/A"}}},
                   {"fields": {"tax_year": "2024", "employer_name": "Northwind"}}]
        with patch.object(pipeline.ollama, "generate_json", side_effect=answers):
            fields = pipeline.extract({"pages": pages}, "w2")
        self.assertEqual(fields["tax_year"]["value"], "2025")
        self.assertEqual((fields["employer_name"]["value"], fields["employer_name"]["page"],
                          fields["employer_name"]["method"]), ("Northwind", 2, "ocr"))
        self.assertNotIn("made_up", fields)

    def test_unknown_tag_and_empty_pages(self):
        self.assertEqual(pipeline.extract({"pages": []}, "not_a_type"), {})
        with patch.object(pipeline.ollama, "generate_json") as model:
            self.assertEqual(pipeline.extract({"pages": [{"text": "", "image": None}]}, "w2"), {})
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
