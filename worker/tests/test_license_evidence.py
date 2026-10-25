import unittest
import license_evidence


class LicenseEvidenceTests(unittest.TestCase):
    def page(self, text):
        return {"text": text, "page": 1, "method": "ocr"}

    def test_numbered_names_and_address_override_model_transcription(self):
        text = "DRIVER LICENSE\n1 RIVERA-SMITH\n2 ALEX MORGAN.\n8 246 OAK BLVD #203\n4d DL 01234567"
        fields = {key: {"value": value} for key, value in
                  (("last_name", "Morgan"), ("full_name", "Alex Morgan"), ("address", "246 OAK BLVD"), ("license_number", "01234567"))}
        result = license_evidence.reconcile("drivers_license", [self.page(text)], fields)
        self.assertEqual(result["last_name"]["value"], "RIVERA-SMITH")
        self.assertEqual(result["full_name"]["value"], "RIVERA-SMITH ALEX MORGAN")
        self.assertEqual(result["address"]["value"], "246 OAK BLVD #203")
        self.assertIn("1 RIVERA-SMITH", result["full_name"]["quote"])
        self.assertEqual(result["license_number"]["value"], "01234567")

    def test_changed_digit_and_substring_are_not_saved(self):
        for value in ("01234568", "1234567"):
            fields = {"license_number": {"value": value}}
            result = license_evidence.reconcile("drivers_license", [self.page("DRIVER LICENSE\n4d DL 01234567")], fields)
            self.assertNotIn("license_number", result)

    def test_no_ocr_does_not_confirm_identifier(self):
        result = license_evidence.reconcile("drivers_license", [self.page("")], {"license_number": {"value": "01234567"}})
        self.assertNotIn("license_number", result)

    def test_conflicting_owners_do_not_pick_first_person(self):
        pages = [self.page("DRIVER LICENSE\n1 RIVERA\n2 ALEX"), self.page("DRIVER LICENSE\n1 CHEN\n2 JAMIE")]
        result = license_evidence.reconcile("drivers_license", pages, {"full_name": {"value": "ALEX RIVERA"}})
        self.assertNotIn("full_name", result)
        self.assertNotIn("last_name", result)

    def test_other_document_types_are_unchanged(self):
        fields = {"employee_name": {"value": "Alex Rivera"}}
        self.assertIs(license_evidence.reconcile("paystub", [], fields), fields)

    def test_other_number_is_not_license_evidence(self):
        fields = {"license_number": {"value": "01234567"}}
        result = license_evidence.reconcile("drivers_license", [self.page("DRIVER LICENSE\nDD 01234567")], fields)
        self.assertNotIn("license_number", result)
