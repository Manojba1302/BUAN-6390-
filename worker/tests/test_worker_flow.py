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
    def __init__(self, record=RECORD, attempts=1, later=None):
        """later: what fetch_file returns after the first call (a file attached mid-read)."""
        self.calls, self.record, self.attempts, self.later = [], record, attempts, later

    @contextmanager
    def session(self):
        yield "conn"

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args[1:], kwargs))
            fetched = self.record if self.later is None or name != "fetch_file" or \
                not any(c[0] == "fetch_file" for c in self.calls[:-1]) else self.later
            return {"fetch_file": fetched, "bump_attempts": self.attempts}.get(name)
        return call

    def names(self):
        return [c[0] for c in self.calls]


@contextmanager
def _nothing():
    yield


class HandleTests(unittest.TestCase):
    def _run(self, fake, outcome="matched", fields=None, job=None, kept=None, document=None, embed=True):
        fields = {key: {"value": value, "method": "native_text"} for key, value in (("employee_name", "Example Person"), ("employer_name", "Example Employer"), ("box1_wages", "100.00"))} if fields is None else fields
        s3 = MagicMock()
        s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"%PDF")}
        rendered = {"pages": [{"text": "", "method": "vision", "image": b"png"}]}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(main, "db", fake), patch.object(main, "_s3", return_value=s3), \
             patch.object(main.config, "markdown_dir", Path(folder)), \
             patch.object(main.pipeline, "read", return_value=document or DOCUMENT) as read, \
             patch.object(main.pages, "read_document", return_value=rendered), \
             patch.object(main.pipeline, "classify", return_value={"detected": "w2", "outcome": outcome}), \
             patch.object(main.pipeline, "extract", return_value=fields) as extract, \
             patch.object(main.pipeline, "to_markdown", return_value="# md"), \
             patch.object(main.pipeline, "chunk", return_value=[] if document else ["c"]), \
             (patch.object(main.pipeline, "embed_chunks", return_value=[{"content": "c", "embedding": [0.1]}] if not document else []) if embed else _nothing()):
            if kept is not None:
                (Path(folder) / "f1.pages.json").write_text(json.dumps(kept))
            main.handle(job or {"file_id": "f1"})
            self.md_written = (Path(folder) / "f1.md").exists()
            self.pages_kept = json.loads((Path(folder) / "f1.pages.json").read_text()) if (Path(folder) / "f1.pages.json").exists() else None
        self.read = read
        return extract, self.md_written

    def test_attached_upload_is_read_then_extracted(self):
        fake = FakeDb()
        extract, md_written = self._run(fake)
        self.assertEqual(fake.names(), ["fetch_file", "bump_attempts", "set_status", "save_classification",
                                        "clear_extractions", "save_markdown", "replace_chunks", "fetch_file",
                                        "clear_extractions", "save_extraction", "save_extraction", "save_extraction",
                                        "save_markdown", "audit", "set_status", "audit"])
        self.assertTrue(md_written)
        extract.assert_called_once()
        final = fake.calls[14]
        self.assertEqual((final[1][1], final[2]), ("completed", {"pages": 1}))
        self.assertEqual(fake.calls[15][2]["payload"], {"fields": 3, "chunks": 1, "outcome": "matched"})
        self.assertEqual(self.pages_kept, [{"text": "Wage and Tax Statement", "model_text": None, "method": "native_text", "ocr_confidence": None}])

    def test_vault_upload_is_read_and_searchable_but_not_extracted(self):
        fake = FakeDb(record={**RECORD, "application_id": None})
        extract, md_written = self._run(fake)
        extract.assert_not_called()
        self.assertNotIn("save_extraction", fake.names())
        self.assertIn("replace_chunks", fake.names())
        self.assertTrue(md_written and self.pages_kept)
        self.assertEqual(fake.calls[-1][2]["payload"], {"fields": 0, "chunks": 1, "outcome": "matched"})

    def test_vault_mismatch_is_saved_as_other_not_refused(self):
        fake = FakeDb(record={**RECORD, "document_tag": "paystub", "application_id": None})
        extract, _ = self._run(fake, outcome="mismatched")
        self.assertIn(("set_tag", ("f1", "other"), {}), fake.calls)
        self.assertEqual(fake.calls[-2][1][1], "completed")
        extract.assert_not_called()

    def test_application_mismatch_is_saved_as_other_too_and_not_read_with_the_wrong_fields(self):
        fake = FakeDb(record={**RECORD, "document_tag": "paystub"}, later={**RECORD, "document_tag": "other"})
        extract, _ = self._run(fake, outcome="mismatched", fields={})
        self.assertIn(("set_tag", ("f1", "other"), {}), fake.calls)
        extract.assert_not_called()
        self.assertEqual(fake.calls[-2][1][1], "completed")

    def test_attaching_extracts_from_the_kept_text_without_reading_again(self):
        fake = FakeDb()
        kept = [{"text": "Box 1 wages 100.00", "method": "ocr", "ocr_confidence": 91.0}]
        extract, _ = self._run(fake, job={"file_id": "f1", "mode": "extract"}, kept=kept)
        self.read.assert_not_called()
        self.assertNotIn("save_classification", fake.names())
        self.assertNotIn("replace_chunks", fake.names())
        page = extract.call_args[0][0]["pages"][0]
        self.assertEqual((page["text"], page["method"], page["image"]), ("Box 1 wages 100.00", "ocr", b"png"))
        self.assertEqual(fake.calls[-1][2]["payload"], {"fields": 3, "chunks": None, "outcome": "attached"})

    def test_attaching_an_older_file_without_kept_text_reads_it_once(self):
        fake = FakeDb()
        extract, _ = self._run(fake, job={"file_id": "f1", "mode": "extract"})
        self.read.assert_called_once()
        extract.assert_called_once()

    def test_file_attached_while_it_was_being_read_is_still_extracted(self):
        fake = FakeDb(record={**RECORD, "application_id": None}, later=RECORD)
        extract, _ = self._run(fake)
        extract.assert_called_once()
        self.assertIn("save_extraction", fake.names())

    def test_photo_with_little_printed_text_is_still_extracted_from_its_image(self):
        fake = FakeDb(record={**RECORD, "document_tag": "drivers_license"})
        photo = {"pages": [{"text": "", "method": "vision", "image": b"png"}]}
        fields = {"full_name": {"value": "Example Person", "method": "vision", "page": 1, "quote": ""}}
        with patch.object(main.pipeline, "chunk", return_value=[]):
            extract, _ = self._run(fake, fields=fields, document=photo)
        extract.assert_called_once()
        self.assertEqual(fake.calls[-2][1][1], "completed")

    def test_search_index_failure_does_not_block_reading_fields(self):
        fake = FakeDb()
        with patch.object(main.pipeline, "embed_chunks", return_value=[{"content": "c", "embedding": None}]):
            extract, _ = self._run(fake, embed=False)
        extract.assert_called_once()
        self.assertEqual(fake.calls[-2][1][1], "completed")

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


class HeartbeatTests(unittest.TestCase):
    def test_connection_io_continues_during_job(self):
        from threading import Event
        released = Event()
        channel = MagicMock()
        channel.connection.process_data_events.side_effect = lambda **kwargs: released.set()
        def job(_):
            if not released.wait(2):
                raise AssertionError("Connection I/O was blocked by the job")
        with patch.object(main,"handle",side_effect=job):
            main._handle_with_heartbeats(channel,{"file_id":"synthetic"})
        channel.connection.process_data_events.assert_called()


class CompletedJobTests(unittest.TestCase):
    def test_redelivered_completed_job_does_not_rerun_models(self):
        fake=FakeDb(record={**RECORD,"status":"completed"})
        with patch.object(main,"db",fake),patch.object(main.pipeline,"read") as read:
            main.handle({"file_id":"done"})
        self.assertEqual(fake.names(),["fetch_file"])
        read.assert_not_called()


class ExtractionQualityTests(unittest.TestCase):
    def test_partial_w2_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError,"Incomplete W-2"):
            main._validate_extraction("w2", {"tax_year":{"value":"2025"}})

    def test_w2_requires_names_and_wages_but_allows_zero_wages(self):
        main._validate_extraction("w2", {key:{"value":value} for key,value in (("employee_name","Example Person"),("employer_name","Example Employer"),("box1_wages","0.00"))})
