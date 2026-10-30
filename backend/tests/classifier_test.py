"""Model outages must not be reported as uncertain image classifications."""
import unittest
from unittest.mock import patch
from app.services import classifier
import ollama

class ClassifierTests(unittest.TestCase):
    def test_model_outage_is_explicit(self):
        with patch.object(classifier.pages,'first_page_image',return_value=b'image'), patch.object(classifier,'_page_one_text',return_value=''), patch.object(classifier.ollama,'generate_json',side_effect=ollama.OllamaError('model unavailable')):
            result=classifier.classify(body=b'photo',content_type='image/jpeg',name='photo.jpg',selected_type='drivers_license')
        self.assertEqual(result['outcome'],'failed')
        self.assertIn('vision model',result['message'])
        self.assertEqual(result['detected_type'],'unknown')

class NativeClassificationTests(unittest.TestCase):
    def test_readable_pdf_signals_do_not_need_vision(self):
        with patch.object(classifier,"_page_one_text",return_value="Printed bank statement "*20), patch.object(classifier.doc_types,"regex_vote",return_value="bank_statement"), patch.object(classifier.pages,"first_page_image") as image, patch.object(classifier.ollama,"generate_json") as model:
            result=classifier.classify(body=b"pdf",content_type="application/pdf",name="unhelpful-name.pdf",selected_type="paystub")
        self.assertEqual(result["detected_type"],"bank_statement")
        self.assertEqual(result["outcome"],"mismatched")
        self.assertEqual(result["model"],"native_text_rules")
        image.assert_not_called();model.assert_not_called()

if __name__=='__main__':unittest.main()


class ImageClassificationTests(unittest.TestCase):
    def test_photo_uses_bounded_evidence_classification(self):
        answer = {"document_type":"drivers_license", "readable":True, "evidence":["DRIVER LICENSE"], "mixed_document":False}
        with patch.object(classifier.pages,"first_page_image",return_value=b"photo"), patch.object(classifier.ollama,"generate_json",return_value=answer) as model:
            result = classifier.classify(body=b"photo",content_type="image/jpeg",name="bank-statement.jpg",selected_type="bank_statement")
        self.assertEqual(result["outcome"],"mismatched")
        self.assertEqual(result["detected_type"],"drivers_license")
        kwargs = model.call_args.kwargs
        self.assertEqual(kwargs["options"]["num_predict"],256)
        self.assertIn("unknown",kwargs["response_schema"]["properties"]["document_type"]["enum"])
        self.assertNotIn("bank-statement.jpg",kwargs["prompt"])
