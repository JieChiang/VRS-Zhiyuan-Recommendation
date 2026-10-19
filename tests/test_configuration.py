import io
import json
from subprocess import CompletedProcess
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient
from app.main import app
from app.services.configuration import ConfigurationChecks


class ConfigurationTests(unittest.TestCase):
    def checks(self, **overrides):
        values = dict(neo4j_url="http://localhost:7474", neo4j_user="neo4j", neo4j_password="example-only",
                      neo4j_db="neo4j", deepseek_api_key="example-only", deepseek_base_url="https://api.deepseek.com",
                      deepseek_model="deepseek-flash", tesseract_cmd="tesseract")
        return ConfigurationChecks(SimpleNamespace(**dict(values, **overrides)))

    def test_setup_endpoints_require_login(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/v1/setup/status").status_code, 401)
        self.assertEqual(client.post("/api/v1/setup/verify-model").status_code, 401)

    def test_key_missing_never_contacts_platform(self):
        with patch("app.services.configuration.urlopen") as request:
            result = self.checks(deepseek_api_key="").verify_model()
            self.assertFalse(result["configured"])
            self.assertEqual(result["state"], "missing")
            request.assert_not_called()

    def test_present_key_is_not_reported_as_verified(self):
        result = self.checks().model()
        self.assertTrue(result["configured"])
        self.assertFalse(result["verified"])
        self.assertNotIn("example-only", json.dumps(result))

    def test_model_verification_only_reads_model_list_and_is_cached(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"data": [{"id": "deepseek-flash"}]}).encode()
        checks = self.checks()
        with patch("app.services.configuration.urlopen", return_value=response) as request:
            self.assertTrue(checks.verify_model()["verified"])
            self.assertTrue(checks.verify_model()["verified"])
            self.assertEqual(request.call_count, 1)
            sent = request.call_args.args[0]
            self.assertEqual(sent.full_url, "https://api.deepseek.com/models")
            self.assertEqual(sent.get_method(), "GET")
            self.assertIsNone(sent.data)

    def test_valid_key_with_wrong_model_is_warning(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": [{"id": "other"}]}'
        with patch("app.services.configuration.urlopen", return_value=response):
            result = self.checks().verify_model()
        self.assertEqual(result["state"], "warning")
        self.assertFalse(result["verified"])

    def test_upstream_error_does_not_echo_credentials(self):
        for error in [HTTPError("https://invalid", 401, "example-only", {}, io.BytesIO()), RuntimeError("example-only")]:
            with patch("app.services.configuration.urlopen", side_effect=error):
                result = self.checks().verify_model()
            self.assertEqual(result["state"], "error")
            self.assertNotIn("example-only", json.dumps(result))

    def test_neo4j_distinguishes_empty_importing_and_ready_graphs(self):
        for rows, state, ready in [([], "warning", False), ([{"status":"snapshot_importing", "offer_count": 1}], "warning", False), ([{"status":"ready", "offer_count":116451}], "ok", True)]:
            with patch("app.services.configuration.Neo4jHttpClient") as client:
                client.return_value.run_rows.return_value = rows
                result = self.checks().neo4j()
            self.assertEqual((result["state"], result["ready"]), (state, ready))

    def test_database_failure_does_not_hide_other_component_status(self):
        checks = self.checks()
        with patch.object(checks, "neo4j", return_value={"state":"error", "ready":False}), patch.object(checks, "ocr", return_value={"state":"ok", "ready":True}), patch("app.services.configuration.urlopen") as request:
            status = checks.status()
        self.assertFalse(status["data_ready"])
        self.assertTrue(status["components"]["ocr"]["ready"])
        self.assertTrue(status["components"]["deepseek"]["configured"])
        request.assert_not_called()

    def test_ocr_checks_both_required_language_packs(self):
        for langs, ready in [("chi_sim\neng\n", True), ("eng\n", False)]:
            with patch("app.services.configuration.shutil.which", return_value="test-tesseract"), patch("app.services.configuration.subprocess.run", side_effect=[CompletedProcess([], 0, "tesseract 5.5", ""), CompletedProcess([], 0, langs, "")]):
                self.assertEqual(self.checks().ocr()["ready"], ready)

    def test_ocr_missing_and_timeout_have_actionable_safe_messages(self):
        with patch("app.services.configuration.shutil.which", return_value=None):
            self.assertEqual(self.checks().ocr()["state"], "missing")
        with patch("app.services.configuration.shutil.which", return_value="test-tesseract"), patch("app.services.configuration.subprocess.run", side_effect=RuntimeError("private-path")):
            result = self.checks().ocr()
            self.assertEqual(result["state"], "error")
            self.assertNotIn("private-path", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
