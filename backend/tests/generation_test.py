import json
import os
import unittest
from unittest.mock import Mock, patch
from app.agent import generation


class GenerationTests(unittest.TestCase):
    def args(self):
        return dict(model="example/model:free", prompt="SYNTHETIC EVIDENCE", response_schema={"type":"object"}, options={"num_predict":512}, timeout=10)

    def response(self, lines=(), status=200):
        response = Mock(status_code=status)
        response.iter_lines.return_value = iter(lines)
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    def event(self, content):
        return "data: " + json.dumps({"choices":[{"delta":{"content":content}}]})

    def test_local_delegates_without_http(self):
        with patch.dict(os.environ, {"CHAT_PROVIDER":"ollama"}), patch.object(generation.ollama,"generate_json",return_value={"answer":"local"}) as local, patch.object(generation.httpx,"stream") as remote:
            self.assertEqual(generation.generate_json(**self.args()), {"answer":"local"})
            local.assert_called_once(); remote.assert_not_called()

    def test_remote_stream_payload_and_callbacks(self):
        context = self.response([": heartbeat", self.event('{"answer":'), self.event('"test","citations":[],"support":[]}'), 'data: [DONE]'])
        callback, metrics = Mock(), Mock()
        with patch.dict(os.environ, {"CHAT_PROVIDER":"openrouter","OPENROUTER_API_KEY":"test-only"}), patch.object(generation.httpx,"stream",return_value=context) as request, patch.object(generation.ollama,"generate_json") as local:
            result = generation.generate_json(**self.args(),on_text=callback,metrics_callback=metrics)
        self.assertEqual(result["answer"],"test"); local.assert_not_called()
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["provider"], {"require_parameters":True,"allow_fallbacks":False,"data_collection":"deny"})
        self.assertEqual(payload["response_format"]["type"],"json_schema")
        self.assertEqual(payload["max_tokens"],512)
        self.assertEqual(callback.call_count,2); metrics.assert_called_once()

    def test_missing_key_and_paid_models_never_send(self):
        for key,model in [("","example/model:free"),("test-only","example/paid")]:
            with self.subTest(model=model), patch.dict(os.environ,{"CHAT_PROVIDER":"openrouter","OPENROUTER_API_KEY":key}), patch.object(generation.httpx,"stream") as request:
                with self.assertRaises(generation.GenerationError): generation.generate_json(**{**self.args(),"model":model})
                request.assert_not_called()

    def test_http_errors_do_not_leak_or_fallback(self):
        for status in [401,402,429,500]:
            with self.subTest(status=status), patch.dict(os.environ,{"CHAT_PROVIDER":"openrouter","OPENROUTER_API_KEY":"secret-test-key"}), patch.object(generation.httpx,"stream",return_value=self.response(status=status)), patch.object(generation.ollama,"generate_json") as local:
                with self.assertRaises(generation.GenerationError) as caught: generation.generate_json(**self.args())
                self.assertNotIn("secret-test-key",str(caught.exception)); local.assert_not_called()

    def test_invalid_truncated_and_stream_errors_fail(self):
        cases = [[self.event("not json"), "data: [DONE]"], [self.event("[]"), "data: [DONE]"], [self.event('{"answer":"partial"}')], ['data: {"error":{"message":"private prompt"}}'], ['data: {"choices":[{"delta":{},"finish_reason":"length"}]}']]
        for lines in cases:
            with self.subTest(lines=lines), patch.dict(os.environ,{"CHAT_PROVIDER":"openrouter","OPENROUTER_API_KEY":"test-only"}), patch.object(generation.httpx,"stream",return_value=self.response(lines)):
                with self.assertRaises(generation.GenerationError) as caught: generation.generate_json(**self.args())
                self.assertNotIn("private prompt",str(caught.exception))

    def test_unknown_provider_does_not_silently_use_local(self):
        with patch.dict(os.environ,{"CHAT_PROVIDER":"typo"}), patch.object(generation.ollama,"generate_json") as local:
            with self.assertRaises(generation.GenerationError): generation.generate_json(**self.args())
            local.assert_not_called()

    def test_encoder_is_shared_and_local(self):
        from embedding_config import MODEL
        from app.agent import answering
        self.assertEqual(MODEL, "nomic-embed-text")
        self.assertEqual(answering.EMBED_MODEL, MODEL)
        with patch.object(answering.ollama,"embed",return_value=[0.0]*768) as embed, patch.object(generation.httpx,"stream") as remote:
            answering._embed_question("synthetic question")
            self.assertEqual(embed.call_args.kwargs["model"], MODEL)
            self.assertTrue(embed.call_args.kwargs["text"].startswith("search_query: ")); remote.assert_not_called()

    def test_timeout_is_sanitized(self):
        import httpx
        with patch.dict(os.environ,{"CHAT_PROVIDER":"openrouter","OPENROUTER_API_KEY":"test-only"}), patch.object(generation.httpx,"stream",side_effect=httpx.ReadTimeout("private prompt")):
            with self.assertRaises(generation.GenerationError) as caught: generation.generate_json(**self.args())
            self.assertNotIn("private prompt",str(caught.exception))

    def test_encoder_change_requires_migration(self):
        import subprocess, sys
        env = {**os.environ,"EMBED_MODEL":"different-encoder"}
        result = subprocess.run([sys.executable,"-c","import embedding_config"],env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("migrate and rebuild",result.stderr)
