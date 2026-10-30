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

    def test_missing_number_recovers_from_trusted_label(self):
        page = {**self.page("DRIVER LICENSE\n4d DL 01234567 3 DOB 01/02/1990"), "ocr_confidence": 92}
        result = license_evidence.reconcile("drivers_license", [page], {})
        self.assertEqual(result["license_number"]["value"], "01234567")
        self.assertEqual(result["license_number"]["page"], 1)
        self.assertEqual(result["license_number"]["quote"], "4d DL 01234567")

    def test_missing_number_not_recovered_from_uncertain_or_wrong_label(self):
        for text in ("DRIVER LICENSE\n4d DL 01234567", "DRIVER LICENSE\nDD 01234567", "DRIVER LICENSE\nDOB 01/02/1990"):
            self.assertNotIn("license_number", license_evidence.reconcile("drivers_license", [self.page(text)], {}))

    def test_conflicting_numbers_do_not_recover(self):
        pages = [{**self.page("DRIVER LICENSE\n4d DL " + number), "ocr_confidence": 95} for number in ("01234567", "07654321")]
        self.assertNotIn("license_number", license_evidence.reconcile("drivers_license", pages, {}))

    def test_native_text_recovery_and_date_rejection(self):
        for value, expected in (("A0123456", True), ("01/02/1990", False), ("LIMITED", False)):
            page = {**self.page("DRIVER LICENSE\nLicense number: " + value), "method": "native_text"}
            result = license_evidence.reconcile("drivers_license", [page], {})
            self.assertEqual("license_number" in result, expected)

    def test_photo_label_read_as_digits_still_confirms_number(self):
        # Real Texas photo: OCR glued the small "4d DL" label onto the number.
        for line in ("44052224976 2008 04/21/1996 gdas C", "14052224976 #00804/21/1996 von", "440152224976 — 2008 04/21/1996"):
            result = license_evidence.reconcile("drivers_license", [self.page("DRIVER LICENSE\n" + line)], {"license_number": {"value": "52224976"}})
            self.assertEqual(result["license_number"]["value"], "52224976", line)

    def test_glued_label_needs_exact_number_and_date_line(self):
        cases = (("2224976", "44052224976 2008 04/21/1996"),     # shorter tail of the run
                 ("52224977", "44052224976 2008 04/21/1996"),    # one digit changed
                 ("52224976", "44052224976"),                     # no date on the line
                 ("52224976", "9944052224976 04/21/1996"))        # longer number, not a label
        for value, line in cases:
            result = license_evidence.reconcile("drivers_license", [self.page("DRIVER LICENSE\n" + line)], {"license_number": {"value": value}})
            self.assertNotIn("license_number", result, (value, line))

    # The real Texas photo (768 x 1024 from WhatsApp) read three different ways by OCR.
    REAL_LINES = ("aa ad 052224976 \u2014 300804/21/1996 9a C",          # original size: "DL" read as "0"
                  "+\" a ts 052224976  200804/21/1996 sass C",             # enlarged copy
                  "\u00a5 10.52224976  200804/21/1996 gois C")               # screenshot copy: "4d DL" read as "10."

    def card(self, line, address="DALLAS, TX 75252"):
        return self.page("DRIVER LICENSE\n" + line + "\n1 UWAZIE\n2 MICHAEL JNR UGOCHUKWU\n8 7650 MCCALLUM BLVD #1005\n" + address)

    def test_real_photo_number_is_kept_from_any_reading(self):
        for line in self.REAL_LINES:
            for answer in ("52224976", "DL 52224976", "4d DL: 52224976"):
                result = license_evidence.reconcile("drivers_license", [self.card(line)], {"license_number": {"value": answer}})
                self.assertEqual(result["license_number"]["value"], "52224976", (line, answer))

    def test_glued_run_copied_by_the_model_is_peeled_to_the_state_format(self):
        for line, answer in zip(self.REAL_LINES, ("052224976", "052224976", "10.52224976")):
            result = license_evidence.reconcile("drivers_license", [self.card(line)], {"license_number": {"value": answer}})
            self.assertEqual(result["license_number"]["value"], "52224976", (line, answer))

    def test_wrong_or_unrelated_numbers_are_still_dropped(self):
        for answer in ("52224977", "2224976", "28124600150132755256", "052224976 3"):
            result = license_evidence.reconcile("drivers_license", [self.card(self.REAL_LINES[0])], {"license_number": {"value": answer}})
            self.assertNotIn("license_number", result, answer)

    def test_unknown_state_does_not_peel_or_accept_a_glued_number(self):
        for line in self.REAL_LINES[:2]:
            result = license_evidence.reconcile("drivers_license", [self.card(line, address="SOMEWHERE")], {"license_number": {"value": "52224976"}})
            self.assertNotIn("license_number", result)

    def test_state_comes_from_address_zip_or_extracted_field(self):
        self.assertEqual(license_evidence.card_state(["DALLAS, TK75252"]), "TX")      # mangled letters, Texas ZIP
        self.assertEqual(license_evidence.card_state(["Columbus, OH 43004"]), "OH")
        self.assertEqual(license_evidence.card_state(["no address"], "tx"), "TX")
        self.assertIsNone(license_evidence.card_state(["DALLAS, TX 75252"], "CA"))     # disagreement: no state

    # Readings of the same photo from other OCR settings and versions (tesseract 5.3.x, 1024-2400 px).
    MORE_LINES = ("ad 0652224976 \u2014 300804/21/1996 9a C",       # label read as "06"
                  "460052224976 \u2014 200804/21/1996",              # label read as "4600"
                  "+\" 4d 052224976 \u00a9 2008 04/21/1996 gti C *",  # exact label, "DL" read as "0"
                  "4d 0. 52224976",                                  # number split off, no date on the line
                  "ad 0152224976",                                   # glued after a label word, no date
                  "52224976")                                        # the number alone on its line

    def test_more_ocr_readings_confirm_the_number(self):
        for line in self.MORE_LINES:
            for answer in ("52224976", "052224976", "S2224976"):
                result = license_evidence.reconcile("drivers_license", [self.card(line)], {"license_number": {"value": answer}})
                self.assertEqual(result["license_number"]["value"], "52224976", (line, answer))

    def test_more_ocr_readings_still_drop_wrong_numbers(self):
        for line in self.MORE_LINES:
            for answer in ("52224977", "2224976", "75252000"):
                result = license_evidence.reconcile("drivers_license", [self.card(line)], {"license_number": {"value": answer}})
                self.assertNotIn("license_number", result, (line, answer))

    def test_number_after_another_label_is_not_the_license(self):
        for line in ("DD 52224976", "DOB: 52224976", "4b EXP 52224976"):
            result = license_evidence.reconcile("drivers_license", [self.card(line)], {"license_number": {"value": "52224976"}})
            self.assertNotIn("license_number", result, line)

    def test_numbered_names_with_ocr_colon(self):
        text = "DRIVER LICENSE\n1: UWAZIE\n2 MICHAEL JNR UGOCHUKWU .\n8 7650 MCCALLUM BLVD #1005 \u00a5"
        result = license_evidence.reconcile("drivers_license", [self.page(text)], {})
        self.assertEqual(result["last_name"]["value"], "UWAZIE")
        self.assertEqual(result["first_name"]["value"], "MICHAEL")
        self.assertEqual(result["address"]["value"], "7650 MCCALLUM BLVD #1005")
