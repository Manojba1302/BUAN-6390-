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

if __name__=='__main__':unittest.main()
