"""Added without a type (the vault's one Add document area): a recognised loan document takes its own
type and folder; anything else stays Other."""
import unittest
from unittest.mock import patch

from worker import main
from tests.test_worker_flow import FakeDb

OTHER = {"storage_key": "k.pdf", "content_type": "application/pdf", "original_name": "scan.pdf",
         "document_tag": "other", "customer_id": "c1", "application_id": None}


def _seen(detected: str, mixed: bool = False) -> dict:
    return {"selected": "other", "detected": detected, "outcome": "mismatched", "mixed": mixed}


class AutoTypeTests(unittest.TestCase):
    def _adopt(self, record, classification):
        fake = FakeDb(record)
        with patch.object(main, "db", fake):
            return main._adopt_type("f1", record, classification), fake

    def test_recognised_w2_takes_its_type_and_folder(self):
        record, fake = self._adopt(OTHER, _seen("w2"))
        self.assertEqual(record["document_tag"], "w2")
        self.assertIn(("set_tag", ("f1", "w2"), {}), fake.calls)
        self.assertIn(("set_path", ("f1", "/Taxes"), {}), fake.calls)

    def test_license_goes_to_identification(self):
        _, fake = self._adopt(OTHER, _seen("drivers_license"))
        self.assertIn(("set_path", ("f1", "/Identification & Licenses"), {}), fake.calls)

    def test_unknown_stays_other(self):
        record, fake = self._adopt(OTHER, {"selected": "other", "detected": "unknown", "outcome": "unknown", "mixed": False})
        self.assertEqual(record["document_tag"], "other")
        self.assertEqual(fake.calls, [])

    def test_several_documents_in_one_file_stay_other(self):
        record, fake = self._adopt(OTHER, _seen("w2", mixed=True))
        self.assertEqual((record["document_tag"], fake.calls), ("other", []))

    def test_a_chosen_type_is_never_changed_here(self):
        record, fake = self._adopt(OTHER | {"document_tag": "paystub"}, _seen("w2"))
        self.assertEqual((record["document_tag"], fake.calls), ("paystub", []))

    def test_auto_jobs_adopt_and_normal_jobs_keep_the_mismatch_rule(self):
        with patch.object(main, "_read_document", return_value={"pages": []}), \
             patch.object(main, "_classify", return_value=_seen("w2")), \
             patch.object(main, "_adopt_type", return_value=OTHER) as adopt, \
             patch.object(main, "_settle_type", return_value=OTHER) as settle, \
             patch.object(main, "_write_markdown", return_value=("p", "m")), \
             patch.object(main.pipeline, "embed_chunks", return_value=[]), patch.object(main.pipeline, "chunk", return_value=[]), \
             patch.object(main, "_keep_pages"), patch.object(main, "_check_index"), patch.object(main, "db", FakeDb(OTHER)):
            main._read_and_index("f1", OTHER, auto=True)
            main._read_and_index("f1", OTHER)
        self.assertEqual((adopt.call_count, settle.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
