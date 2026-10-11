import unittest
from unittest.mock import patch
from worker import pipeline
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
