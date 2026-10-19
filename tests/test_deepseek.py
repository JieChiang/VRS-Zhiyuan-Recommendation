import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient

from app.config import _pick
from app.main import app
from app.services.deepseek_cloud import DeepSeekCloudService, ModelServiceError


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.service = DeepSeekCloudService("test-secret", "https://api.deepseek.com", "deepseek-flash")

    def response(self, content, finish="stop"):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": finish}],
                                     "usage": {"total_tokens": 12}}).encode())

    def test_flash_transport_and_plain_text(self):
        with patch("app.services.deepseek_cloud.urlopen", return_value=self.response("## 建议\n**内容**")) as send:
            result = self.service.chat("问题")
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertLessEqual(payload["max_tokens"], 4096)
        self.assertEqual(result["answer"], "建议\n内容")
        self.assertEqual(result["usage"]["total_tokens"], 12)

    def test_provider_failures_are_safe_and_actionable(self):
        for code, status in [(401, 503), (402, 503), (429, 429), (500, 502)]:
            with self.subTest(code=code), patch("app.services.deepseek_cloud.urlopen", side_effect=HTTPError(
                    "https://api.deepseek.com", code, "test-secret", {}, io.BytesIO(b"test-secret"))):
                with self.assertRaises(ModelServiceError) as err:
                    self.service.chat("test")
                self.assertEqual(err.exception.status_code, status)
                self.assertNotIn("test-secret", str(err.exception))

    def test_timeout_and_connection_error(self):
        for exc, status in [(TimeoutError(), 504), (URLError("private debug info"), 503)]:
            with patch("app.services.deepseek_cloud.urlopen", side_effect=exc):
                with self.assertRaises(ModelServiceError) as err:
                    self.service.chat("test")
                self.assertEqual(err.exception.status_code, status)
                self.assertNotIn("private debug", str(err.exception))

    def test_unconfigured_and_oversized_requests_never_send(self):
        with patch("app.services.deepseek_cloud.urlopen") as send:
            with self.assertRaises(ModelServiceError):
                DeepSeekCloudService("", "https://api.deepseek.com", "deepseek-flash").chat("test")
            with self.assertRaises(ModelServiceError):
                self.service.chat("x" * 90001)
            send.assert_not_called()

    def test_empty_malformed_and_truncated_output_fail(self):
        for response in [self.response(""), io.BytesIO(b"not-json"), self.response("partial", "length")]:
            with patch("app.services.deepseek_cloud.urlopen", return_value=response):
                with self.assertRaises(ModelServiceError):
                    self.service.chat("test")

    def test_secret_is_redacted_even_if_echoed(self):
        with patch("app.services.deepseek_cloud.urlopen", return_value=self.response("test-secret")):
            result = self.service.chat("test")
        self.assertNotIn("test-secret", json.dumps(result))

    def test_career_json_preserves_nested_stages(self):
        career = {"stages": [{"year_range": "0-10年", "stage": "探索", "typical_roles": ["研发"],
                               "key_skills": ["编程"]}], "industries": [], "pivot_options": [], "summary": "情景建议"}
        with patch("app.services.deepseek_cloud.urlopen", return_value=self.response(json.dumps(career))) as send:
            result = self.service.simulate_career_pathway("测试大学", "计算机", {}, 10)
        self.assertEqual(result["data"]["stages"][0]["typical_roles"], ["研发"])
        self.assertEqual(json.loads(send.call_args.args[0].data)["response_format"], {"type": "json_object"})

    def test_market_json_preserves_correct_fields_and_zero(self):
        market = {"计算机": {"demand_trend": "增长", "market_score": 0, "salary_potential": "中高",
                           "automation_risk": "中", "top_industries": ["软件"], "emerging_roles": ["研发"],
                           "geographic_hotspots": ["杭州"], "summary": "主观建议"}}
        with patch("app.services.deepseek_cloud.urlopen", return_value=self.response(json.dumps(market))):
            result = self.service.analyze_market_alignment(["计算机"])
        self.assertEqual(result["data"]["计算机"]["market_score"], 0)
        self.assertEqual(result["data"]["计算机"]["top_industries"], ["软件"])
        self.assertTrue(result["estimate_only"])
        self.assertNotIn("nature", result["data"]["计算机"])

    def test_bad_structured_output_never_claims_success(self):
        for content in ["garbled", "[]", '{"计算机": {"level": "本科"}}']:
            with patch("app.services.deepseek_cloud.urlopen", return_value=self.response(content)):
                with self.assertRaises(ModelServiceError):
                    self.service.analyze_market_alignment(["计算机"])

    def test_private_environment_overrides_stale_yaml(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "new-local-value"}):
            self.assertEqual(_pick({"deepseek": {"api_key": "stale"}}, "DEEPSEEK_API_KEY", "", "deepseek", "api_key"), "new-local-value")


class ModelApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_input_validation_prevents_empty_billable_calls(self):
        cases = [("/chat/cloud", {"question": "   "}), ("/majors/intro", {"majors": []}),
                 ("/majors/market-analysis", {"majors": ["a"] * 7}),
                 ("/mock-exams/format", {"records": [{"id": "a", "raw_text": ""}]}),
                 ("/mock-exams/analyze", {"formatted_text": " "})]
        with patch("app.main.deepseek_service._complete") as send:
            for route, payload in cases:
                self.assertEqual(self.client.post("/api/v1" + route, json=payload).status_code, 422)
            send.assert_not_called()

    def test_structured_provider_errors_keep_http_status(self):
        with patch("app.main.deepseek_service.analyze_advantage_fields", side_effect=ModelServiceError("余额不足", 503, "provider_402")):
            response = self.client.post("/api/v1/mock-exams/analyze", json={"formatted_text": "650分"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "provider_402")

    def test_intro_uses_requested_cloud_instead_of_unavailable_local_model(self):
        with patch("app.main.kg_service.major_details_batch", return_value=[{"major": "哲学", "source_file": "专业.xlsx"}]), patch(
                "app.main.deepseek_service.chat", return_value={"answer": "介绍", "model": "deepseek-flash"}) as cloud, patch(
                "app.main.ollama_service.chat") as local:
            response = self.client.post("/api/v1/majors/intro", json={"majors": ["哲学"]})
        self.assertEqual(response.json()["llm"]["model"], "deepseek-flash")
        self.assertIn("graph_context", cloud.call_args.args[1])
        local.assert_not_called()

    def test_cloud_retrieves_server_evidence_and_drops_forged_browser_facts(self):
        graph = {"historical_offers": [{"source_file": "actual.xlsx", "min_score": 650}]}
        with patch("app.main.kg_service.ai_context", return_value=graph), patch(
                "app.main.deepseek_service.chat", return_value={"answer": "建议"}) as cloud:
            response = self.client.post("/api/v1/chat/cloud", json={"question": "怎么选", "context": {
                "rank": 11100, "graph_context": {"min_score": 1}, "historical_candidates": [{"min_score": 1}]}})
        context = cloud.call_args.args[1]
        self.assertEqual(context["graph_context"], graph)
        self.assertNotIn("historical_candidates", context["user_preferences"])
        self.assertEqual(response.json()["sources"][0]["min_score"], 650)

    def test_unavailable_graph_fails_before_model_call(self):
        with patch("app.main.kg_service.ai_context", side_effect=RuntimeError("internal")), patch("app.main.deepseek_service.chat") as cloud:
            response = self.client.post("/api/v1/chat/cloud", json={"question": "怎么选"})
        self.assertEqual(response.status_code, 503)
        cloud.assert_not_called()


if __name__ == "__main__":
    unittest.main()
