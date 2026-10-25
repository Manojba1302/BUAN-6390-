import unittest
import label_evidence
import license_evidence
import pay_evidence
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

    def _ssn_card_page(self):
        text = "SOCIAL SECURITY\nThis number has been established for\n123-45-6789\nALEX MORGAN\n" + "Signature line and notices printed on the card. " * 4
        return {"text": text, "image": b"photo", "method": "ocr"}

    def test_plenty_of_ocr_text_is_read_without_the_image(self):
        answer = {"full_name": "ALEX MORGAN", "ssn": "123-45-6789", "first_name": None, "last_name": None}
        with patch.object(pipeline.ollama, "generate_json", return_value=answer) as model:
            fields = pipeline.extract({"pages": [self._ssn_card_page()]}, "ssn_card")
        self.assertEqual(model.call_count, 1)
        self.assertIsNone(model.call_args.kwargs["images"])
        self.assertEqual(fields["ssn"]["method"], "ocr")
        self.assertIn("123-45-6789", fields["ssn"]["quote"])

    def test_image_is_used_only_when_ocr_text_left_fields_missing(self):
        answers = [{"full_name": "ALEX MORGAN", "ssn": None}, {"fields": {"ssn": {"value": "123-45-6789", "quote": ""}}}]
        with patch.object(pipeline.ollama, "generate_json", side_effect=answers) as model:
            fields = pipeline.extract({"pages": [self._ssn_card_page()]}, "ssn_card")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args.kwargs["images"], [b"photo"])
        self.assertEqual((fields["full_name"]["method"], fields["ssn"]["method"]), ("ocr", "vision"))

    def test_ocr_reads_the_high_resolution_copy(self):
        document = {"pages": [{"text": "", "method": "vision", "image": b"small", "ocr_image": b"large"}]}
        with patch.object(pipeline.pages, "read_document", return_value=document), patch.object(pipeline, "_ocr", return_value=("", 0.0)) as ocr:
            pipeline.read(b"x", "image/png", "card.png")
        ocr.assert_called_once_with(b"large")

    def test_model_failure_is_not_empty_success(self):
        document = {"pages": [{"text": "", "image": b"photo", "method": "vision"}]}
        with patch.object(pipeline.ollama, "generate_json", side_effect=ollama.OllamaError("unavailable")):
            with self.assertRaises(ollama.OllamaError):
                pipeline.extract(document, "drivers_license")

class NativeEvidenceTests(unittest.TestCase):
    def test_payroll_does_not_keep_invented_zeroes_or_ytd_deductions(self):
        text="Employee Name: Example Person\nRegular earnings: 961.88\nFederal withholding: 29.10\nTotal deductions: 0.00"
        out={"regular_pay":{"value":"900"},"overtime_pay":{"value":"0.00"},"bonus_pay":{"value":"0.00"},"total_deductions":{"value":"327.45"},"first_name":{"value":"Example"},"last_name":{"value":"Person"}}
        result=pipeline._recover_evidence("paystub",[{"text":text,"method":"native_text"}],out)
        self.assertEqual(result["total_deductions"]["value"],"0.00")
        self.assertEqual(result["regular_pay"]["value"],"961.88")
        for field in ("overtime_pay","bonus_pay","first_name","last_name"):
            self.assertNotIn(field,result)

    def test_explicit_name_parts_are_kept(self):
        out={"first_name":{"value":"Example"},"last_name":{"value":"Person"}}
        pipeline._drop_unlabelled_name_parts([{"text":"First name: Example\nLast name: Person","method":"native_text"}],out)
        self.assertEqual(len(out),2)

if __name__ == "__main__":
    unittest.main()


class AccountMaskGroundingTests(unittest.TestCase):
    def test_model_example_digits_are_replaced_with_printed_suffix(self):
        out={"account_mask":{"value":"****1234"}}
        result=pipeline._recover_evidence("bank_statement",[{"text":"Account number: 5555 6666 7890","method":"native_text"}],out)
        self.assertEqual(result["account_mask"]["value"],"****7890")

    def test_missing_account_number_does_not_keep_invented_suffix(self):
        out={"account_mask":{"value":"****1234"}}
        result=pipeline._recover_evidence("bank_statement",[{"text":"No account identifier printed","method":"native_text"}],out)
        self.assertNotIn("account_mask",result)


class BoundedExtractionTests(unittest.TestCase):
    def test_flat_native_values_require_source_evidence(self):
        result = pipeline._ground_answer({"gross_pay":"123.45", "bonus_pay":"0.00", "position":"Manager"}, "Gross pay: 123.45\nPosition: Assistant", False)
        self.assertEqual(set(result["fields"]), {"gross_pay"})

    def test_amount_substring_is_not_evidence(self):
        self.assertEqual(pipeline._value_quote("123.45", "Gross pay: 123.456"), "")
        self.assertEqual(pipeline._value_quote("monthly", "Pay rate: semimonthly"), "")

    def test_dates_and_wrapped_address_are_grounded(self):
        self.assertTrue(pipeline._value_quote("2026-09-15", "Advice Date: 09/15/2026"))
        self.assertTrue(pipeline._value_quote("12 MAIN ST APT 9", "12 MAIN ST\nAPT 9"))

    def test_native_continuation_does_not_call_model(self):
        with patch.object(pipeline, "_ask_model") as model:
            result = pipeline._page_classification({"method":"native_text"}, "Important disclosures", ["bank_statement"])
        model.assert_not_called()
        self.assertEqual(result[0], "unknown")

    def test_conflicting_continuation_still_detected(self):
        page={"method":"native_text", "text":"Wage and Tax Statement wages, tips 1545-0008"}
        self.assertEqual(pipeline._page_classification(page, page["text"], ["bank_statement"])[0], "w2")

    def test_null_optional_fields_do_not_force_more_pages(self):
        spec={"extract":{"employee_name":"name", "first_name":"given", "bonus_pay":"bonus"}, "optional_extract":["bonus_pay"]}
        self.assertTrue(pipeline._enough_fields(spec, {"employee_name":{}}))


class OriginalLayoutTests(unittest.TestCase):
    def test_model_layout_does_not_destroy_original_owner_address(self):
        import pages, fitz
        doc=fitz.open(); page=doc.new_page()
        page.insert_text((30,50),"Example Person\n12 MAIN ST APT 9\nDALLAS TX 75001")
        page.insert_text((280,50),"Employee ID: 987\nDepartment: Example\nLocation: Campus")
        page.insert_text((30,150),"Gross pay: 123.45\nNet pay: 100.00\nPay period: monthly")
        result=pages.read_document(doc.tobytes(),"application/pdf","fixture.pdf")["pages"][0]
        self.assertIn("model_text",result)
        recovered=pipeline._recover_evidence("paystub",[result],{"employee_name":{"value":"Example Person"}})
        self.assertEqual(recovered["address"]["value"],"12 MAIN ST APT 9")

    def test_recovery_happens_before_continuation_decision(self):
        spec={"extract":{"account_holder":"holder","account_mask":"mask","total_withdrawals":"total"}}
        page={"text":"Example Person\nAccount number: 5555 6666\nAccount summary\nATM and debit card subtractions -1.00\nOther subtractions -2.00\nService fees -0.00\nEnding balance 4.00", "method":"native_text"}
        with patch.object(pipeline.doc_types,"get_type",return_value=spec),patch.object(pipeline,"_extract_page",return_value={"fields":{"account_holder":"Example Person"}}) as model:
            result=pipeline.extract({"pages":[page,page]},"bank_statement")
        self.assertEqual(model.call_count,1)
        self.assertEqual(result["total_withdrawals"]["value"],"3.00")


class DocumentModelMemoryTests(unittest.TestCase):
    def test_document_memory_release_is_explicit(self):
        payload=ollama._generation_payload("test", "prompt", None, 0, None, None, 0)
        self.assertEqual(payload["keep_alive"],0)

    def test_existing_callers_keep_server_retention_default(self):
        payload=ollama._generation_payload("test", "prompt", None, 0, None, None, None)
        self.assertNotIn("keep_alive",payload)


class FileVarietyRegressionTests(unittest.TestCase):
    """Cases found by running digital, scanned, photographed and low-resolution files."""

    def test_current_ytd_table_rows_give_current_amounts(self):
        page = {"text": "Description Current YTD\nGross Pay 3,846.15 65,384.55\nNet Pay 2,911.40 49,493.80", "page": 1, "method": "native_text"}
        found = pay_evidence.recover("paystub", [page], {})
        self.assertEqual((found["gross_pay"]["value"], found["net_pay"]["value"], found["ytd_gross"]["value"]), ("3846.15", "2911.40", "65384.55"))

    def test_two_amounts_without_a_current_ytd_header_stay_unknown(self):
        page = {"text": "Gross Pay 3,846.15 65,384.55", "page": 1, "method": "native_text"}
        self.assertNotIn("gross_pay", pay_evidence.recover("paystub", [page], {}))

    def test_dotted_leader_rows_are_read(self):
        page = {"text": "Gross Earnings ........ $2,250.00", "page": 1, "method": "native_text"}
        self.assertEqual(pay_evidence.recover("paystub", [page], {})["gross_pay"]["value"], "2250.00")

    def test_license_number_survives_ocr_look_alike_characters(self):
        page = {"text": "DRIVER LICENSE\nDL $5309182", "page": 1, "method": "ocr"}
        kept = license_evidence.reconcile("drivers_license", [page], {"license_number": {"value": "S5309182"}})
        self.assertEqual(kept["license_number"]["value"], "S5309182")
        dropped = license_evidence.reconcile("drivers_license", [page], {"license_number": {"value": "X9999999"}})
        self.assertNotIn("license_number", dropped)

    def test_clear_printed_value_overrules_an_unprinted_or_ytd_answer(self):
        page = {"text": "a Employee's social security number 987-65-4321\nDescription Current YTD\nNet Pay 2,911.40 49,493.80", "page": 1, "method": "ocr", "ocr_confidence": 94}
        ssn = label_evidence.verify("w2", [page], {"employee_ssn": {"value": "111-22-3333"}})["employee_ssn"]
        self.assertEqual((ssn["value"], ssn["page"]), ("987-65-4321", 1))
        self.assertEqual(label_evidence.verify("paystub", [page], {"net_pay": {"value": "49,493.80"}})["net_pay"]["value"], "2,911.40")

    def test_low_confidence_ocr_never_overrules_the_model(self):
        page = {"text": "Ending Balance $38,402.18", "page": 1, "method": "ocr", "ocr_confidence": 67}
        out = {"ending_balance": {"value": "9,402.18"}}
        self.assertEqual(label_evidence.verify("bank_statement", [page], out), out)

    def test_digital_text_fills_a_missing_labelled_value_but_ocr_does_not(self):
        text = "Summary\nEnding Balance $9,402.18"
        digital = label_evidence.verify("bank_statement", [{"text": text, "page": 1, "method": "native_text"}], {})
        self.assertEqual(digital["ending_balance"]["value"], "9,402.18")
        self.assertEqual(label_evidence.verify("bank_statement", [{"text": text, "page": 1, "method": "ocr", "ocr_confidence": 95}], {}), {})

    def test_ocr_text_is_rebuilt_by_line_with_mean_confidence(self):
        data = {"text": ["Net", "Pay", "", "2.00"], "conf": [90, 80, -1, 70], "block_num": [1, 1, 1, 2], "par_num": [1, 1, 1, 1], "line_num": [1, 1, 1, 1]}
        self.assertEqual(pipeline._ocr_text(data), ("Net Pay\n\n2.00\n", 80.0))

