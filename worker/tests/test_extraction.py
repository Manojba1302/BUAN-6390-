import unittest
from unittest.mock import patch
import ollama
from worker import pipeline

class ExtractionTests(unittest.TestCase):
    def test_image_with_ocr_still_uses_vision(self):
        document = {"pages": [{"text": "Partial OCR", "image": b"photo", "method": "ocr"}]}
        with patch.object(pipeline.ollama, "generate_json", return_value={"fields": {"full_name": {"value": "Example Name", "quote": "Example Name"}}}) as model:
            fields = pipeline.extract(document, "drivers_license")
        self.assertEqual(model.call_args.kwargs["images"], [b"photo"])
        self.assertEqual(model.call_args.kwargs["model"], pipeline.config.vision_model)
        self.assertEqual(fields["full_name"]["method"], "vision")

    def test_model_failure_is_not_empty_success(self):
        document = {"pages": [{"text": "", "image": b"photo", "method": "vision"}]}
        with patch.object(pipeline.ollama, "generate_json", side_effect=ollama.OllamaError("unavailable")):
            with self.assertRaises(ollama.OllamaError):
                pipeline.extract(document, "drivers_license")

    def test_classification_outage_fails_loudly(self):
        document = {"pages": [{"text": "", "image": b"photo", "method": "vision"}]}
        with patch.object(pipeline.ollama, "generate_json", side_effect=ollama.OllamaError("model not found")):
            with self.assertRaises(ollama.OllamaError) as raised:
                pipeline.classify(document, "w2")
        self.assertIn("model not found", str(raised.exception))

    def test_classification_falls_back_to_regex_when_model_down(self):
        text = "Form W-2 Wage and Tax Statement. Employer identification number. Wages, tips, other compensation. Federal income tax withheld. Social security wages."
        document = {"pages": [{"text": text, "image": None, "method": "native_text"}]}
        with patch.object(pipeline.ollama, "generate_json", side_effect=ollama.OllamaError("down")):
            result = pipeline.classify(document, "w2")
        self.assertEqual(result["detected"], "w2")

    def test_only_first_pages_are_classified(self):
        document = {"pages": [{"text": "", "image": b"p", "method": "vision"}] * 10}
        with patch.object(pipeline.ollama, "generate_json", return_value={"document_type": "w2"}) as model:
            pipeline.classify(document, "w2")
        self.assertEqual(model.call_count, pipeline.config.classify_pages)


if __name__ == "__main__":
    unittest.main()
