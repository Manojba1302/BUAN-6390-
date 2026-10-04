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

if __name__ == "__main__":
    unittest.main()
