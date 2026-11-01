import unittest
from unittest.mock import patch
from worker import pipeline, main
import ollama

class GeneralTextTests(unittest.TestCase):
    def test_embedding_failure_preserves_page_text(self):
        chunks=[{"index":0,"page":7,"content":"Unfamiliar insurance policy ends on June 30."}]
        with patch.object(ollama,"embed",side_effect=ollama.OllamaError("offline")):
            result=pipeline.embed_chunks(chunks)
        self.assertEqual(result[0]["page"],7)
        self.assertIsNone(result[0]["embedding"])
        self.assertIn("insurance",result[0]["content"])

    def test_unknown_schema_keeps_all_page_text(self):
        doc={"pages":[{"text":"Insurance policy coverage","method":"native_text"} for _ in range(8)]}
        with patch.object(ollama,"generate_json",side_effect=AssertionError("No schema model call")):
            self.assertEqual(pipeline.extract(doc,"other"),{})
        self.assertEqual(len(pipeline.chunk(doc)),8)
        self.assertIn("### Page 8",pipeline.to_markdown(doc,file_name="policy.pdf",document_tag="other",fields={}))

    def test_only_a_file_with_nothing_to_read_fails(self):
        empty = {"pages": [{"text": "", "method": "native_text", "image": None}]}
        with self.assertRaisesRegex(RuntimeError, "no readable text"):
            main._check_index("f1", empty, [])
        photo = {"pages": [{"text": "", "method": "vision", "image": b"png"}]}
        main._check_index("f1", photo, [])                       # read from the image instead

    def test_search_index_shortfall_keeps_the_file_usable(self):
        text = {"pages": [{"text": "kept", "method": "native_text", "image": None}]}
        with self.assertLogs("worker.main", "WARNING") as logged:
            main._check_index("f1", text, [{"content": "kept", "embedding": None}])
        self.assertIn("not indexed", logged.output[0])
        main._check_index("f1", text, [{"content": "kept", "embedding": [0.1]}])

    def test_classification_checks_pages_after_six(self):
        doc={"pages":[{"text":str(i),"method":"native_text"} for i in range(8)]}
        with patch.object(pipeline, "_classify_pages", return_value=(["w2"], [], True)) as classify:
            pipeline.classify(doc, "w2")
        self.assertEqual(len(classify.call_args.args[0]), 8)

    def test_long_files_are_identified_from_the_first_twenty_pages(self):
        doc={"pages":[{"text":str(i),"method":"ocr","image":b"png"} for i in range(40)]}
        with patch.object(pipeline, "_classify_pages", return_value=(["bank_statement"], [], True)) as classify:
            pipeline.classify(doc, "bank_statement")
        self.assertEqual(len(classify.call_args.args[0]), pipeline.MAX_PAGES)
