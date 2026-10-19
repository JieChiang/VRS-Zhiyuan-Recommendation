import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class PageElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.nav_links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "data-page" in attrs:
            self.nav_links.append(attrs.get("href"))


class PageRegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_pages_require_login(self):
        for route in ["/", "/recommend", "/compare", "/majors", "/trajectory", "/simulate", "/kg-explorer"]:
            with self.subTest(route=route):
                response = self.client.get(route, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], "/login")

    def test_all_pages_render_one_shared_navigation_without_duplicate_ids(self):
        self.client.cookies.set("vrs_auth", "1")
        for route in ["/", "/recommend", "/compare", "/majors", "/trajectory", "/simulate", "/kg-explorer"]:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                parser = PageElements()
                parser.feed(response.text)
                self.assertEqual(len(parser.ids), len(set(parser.ids)))
                self.assertEqual(len(parser.nav_links), 7)
                self.assertIn("mainContent", parser.ids)

    def test_invalid_input_fails_before_database_query(self):
        with patch("app.main.recommender_service.recommend") as recommend:
            for payload in [{"rank": 0}, {"rank": 1, "ratio_chong": 0, "ratio_wen": 0, "ratio_bao": 0}]:
                self.assertEqual(self.client.post("/api/v1/recommend/run", json=payload).status_code, 422)
            recommend.assert_not_called()

    def test_health_reports_database_failure(self):
        with patch("app.main.kg_service.health", side_effect=RuntimeError("test database unavailable")):
            response = self.client.get("/api/v1/health")
            self.assertEqual(response.status_code, 500)
            self.assertIn("Neo4j", response.json()["detail"])

    def test_enrichment_uses_graph_without_model_guesses(self):
        with patch("app.main.neo4j_client.run_rows", return_value=[{"name": "测试学校", "level": "本科", "nature": None}]), patch("app.main.ollama_service.query_institution_info_batch") as model:
            response = self.client.post("/api/v1/recommend/enrich", json={"items": [{"name": "测试学校"}]})
            self.assertEqual(response.json()["source"], "neo4j")
            self.assertEqual(response.json()["data"]["测试学校"]["nature"], "")
            model.assert_not_called()

    def test_static_assets_have_change_version(self):
        self.client.cookies.set("vrs_auth", "1")
        response = self.client.get("/")
        self.assertRegex(response.text, r"/static/common\.js\?v=\d+")


if __name__ == "__main__":
    unittest.main()
