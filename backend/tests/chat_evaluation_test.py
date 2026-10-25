import json
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
from datetime import datetime, timezone
from app.agent import evaluation as trace, evaluation_store as store
from app.agent.evaluation_schema import Record

class EvaluationTests(unittest.TestCase):
    def test_allowlist_removes_all_text_and_identifiers(self):
        event = {"schema_version":1,"request_id":str(uuid4()),"created_at":datetime.now(timezone.utc).isoformat(),"route":"field_lookup","outcome":"answered","timings":{"total_seconds":0.1},"question":"sensitive name","answer":"private amounts","customer_id":"private","sources":[{"source_ref":trace.pseudonym("file-id"),"page":1,"content":"raw document"}]}
        safe = Record.model_validate(event).model_dump(mode="json")
        self.assertNotIn("sensitive name", json.dumps(safe))
        self.assertNotIn("private", json.dumps(safe))
        self.assertNotIn("raw document", json.dumps(safe))

    def test_request_records_route_timings_and_pseudonymous_sources(self):
        with patch.object(store,"publish") as publish:
            with trace.session("private-conversation"):
                with trace.request():
                    trace.route("rag")
                    trace.configure_model("llama3.1:8b",4096,512)
                    trace.model(0.2,1.0)
                    trace.finish({"answer":"found", "citations":[{"file_id":"private-file","page":1}]})
        event = publish.call_args.args[0]
        self.assertEqual(event["route"],"rag")
        self.assertEqual(event["outcome"],"answered")
        self.assertEqual(event["timings"]["first_token_seconds"],0.2)
        self.assertNotIn("private",json.dumps(event))
        self.assertIsNone(trace.TRACE.get())
        self.assertIsNone(trace.SESSION.get())

    def test_queue_full_does_not_raise(self):
        from queue import Full
        with patch.object(store.settings,"chat_evaluation_enabled",True), patch.object(store,"_start"), patch.object(store.PENDING,"put_nowait",side_effect=Full):
            store.publish({"request_id":"test"})

    def test_consumer_survives_storage_failure(self):
        with patch.object(store.PENDING,"get",side_effect=[{"request_id":"test"},KeyboardInterrupt]), patch.object(store.PENDING,"task_done") as done, patch.object(store,"write",side_effect=RuntimeError("down")):
            with self.assertRaises(KeyboardInterrupt):
                store._consume()
        done.assert_called_once()

    def test_public_bucket_is_rejected(self):
        client = Mock()
        client.get_bucket_policy.return_value = {"Policy":json.dumps({"Statement":[{"Effect":"Allow","Principal":"*"}]})}
        with self.assertRaises(ValueError):
            store._check_private(client)

    def test_failed_generation_still_reports_partial_timing(self):
        import ollama
        import httpx
        context = Mock()
        context.__enter__ = Mock(side_effect=httpx.ReadTimeout("timeout"))
        context.__exit__ = Mock(return_value=False)
        callback = Mock()
        with patch.object(ollama.httpx,"stream",return_value=context):
            with self.assertRaises(ollama.OllamaError):
                ollama._stream_json({"model":"test"},1,callback)
        callback.assert_called_once()
        self.assertIsNone(callback.call_args.args[0])

    def test_report_excludes_missing_first_token_from_percentiles(self):
        from scripts.summarize_chat_evaluations import report
        result = report([{"route":"field_lookup","outcome":"answered","timings":{"total_seconds":0.1}},{"route":"rag","outcome":"answered","timings":{"total_seconds":1.0,"first_token_seconds":0.4}}])
        self.assertEqual(result["latency"]["first_token_seconds"]["samples"],1)
        self.assertEqual(result["latency"]["first_token_seconds"]["p50"],0.4)
