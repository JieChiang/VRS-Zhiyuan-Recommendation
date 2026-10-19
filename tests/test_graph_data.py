import unittest
from unittest.mock import Mock
from pathlib import Path
from tempfile import TemporaryDirectory

from app.graph_data import DATASET_ID, catalog_code, eligibility, name, number, selected_subjects, subject_options
from app.models import RecommendationRequest
from app.services.kg_service import KgService
from app.services.recommender import RecommenderService


class GraphDataTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        for raw in [None, "缺失", "--", "", "nan", "inf", -1]:
            self.assertIsNone(number(raw))
        self.assertEqual(number("0", integer=True), 0)
        self.assertIsNone(number("1.5", integer=True))

    def test_names_preserve_program_group_identity(self):
        self.assertEqual(name(" 香港中文大学（深圳） "), "香港中文大学(深圳)")
        self.assertNotEqual(name("法学类"), name("法学"))

    def test_valid_tk_catalog_suffix_is_preserved(self):
        self.assertEqual(catalog_code("030604TK", "专业代码：030604T"), ("030604TK", False))
        self.assertEqual(catalog_code("0101013k", "专业代码：010103K授予学位"), ("010103K", True))
        self.assertEqual(catalog_code("unknown", "没有专业代码"), ("UNKNOWN", False))

    def test_rebuild_missing_sources_never_deletes_database(self):
        from scripts.rebuild_graph import GraphBuilder
        client = Mock()
        with TemporaryDirectory() as directory:
            (Path(directory) / "incomplete.xlsx").touch()
            with self.assertRaisesRegex(RuntimeError, "拒绝删除图谱"):
                GraphBuilder(client, Path(directory)).prepare(replace=True)
        client.run.assert_not_called()
        client.run_rows.assert_not_called()

    def test_subject_boolean_requirements(self):
        selected = selected_subjects("物理、化学、生物")
        self.assertEqual(eligibility("物&化", selected), "eligible")
        self.assertEqual(eligibility("物或史", selected), "eligible")
        self.assertEqual(eligibility("史&政", selected), "ineligible")
        self.assertEqual(eligibility("不限", selected), "eligible")
        self.assertEqual(eligibility("未知说明", selected), "unknown")
        self.assertEqual(eligibility("物", set()), "unknown")
        self.assertIsNone(subject_options("物理(成绩合格)"))

    def test_bad_subject_input_is_explicit(self):
        with self.assertRaises(ValueError):
            selected_subjects("语文、数学")

    def test_recommendation_is_scoped_and_excludes_known_ineligible(self):
        client = Mock()
        client.run_rows.return_value = [
            {"institution": "甲", "subject_requirement": "史&政"},
            {"institution": "乙", "subject_requirement": "物&化"},
            {"institution": "丙", "subject_requirement": None},
        ]
        rows = RecommenderService(client)._fetch_candidates(RecommendationRequest(rank=10000, subject_combo="物理、化学、生物"))
        self.assertEqual([x["institution"] for x in rows], ["乙", "丙"])
        query, params = client.run_rows.call_args.args
        self.assertEqual(params["dataset"], DATASET_ID)
        self.assertEqual(params["source_province"], "浙江")
        self.assertIn("o.year=$year", query)
        self.assertIn("o.min_rank >= $lower", query)
        self.assertIn("FOR_PROGRAM", query)

    def test_history_excludes_future_years_and_fuzzy_major_matching(self):
        client = Mock()
        KgService(client).admission_history("测试学校", "法学", 2022)
        query, params = client.run_rows.call_args.args
        self.assertEqual(params["year"], 2022)
        self.assertIn("o.year <= $year", query)
        self.assertNotIn("CONTAINS", query)
        self.assertIn("o.province='浙江'", query)

    def test_optimizer_is_deterministic_and_layers_match_actual_rank(self):
        service = RecommenderService(Mock())
        candidates = [{"institution": str(i), "major": "测试专业", "year": 2024,
                       "min_rank": 9500 + i * 100, "plan_count": 10} for i in range(20)]
        args = (10000, candidates, 10, 3, 4, 3, {"测试": 2})
        first, second = service.optimize(*args), service.optimize(*args)
        self.assertEqual(first, second)
        self.assertEqual(first["score"], round(sum(x["_score"] for x in first["optimized"]), 2))
        self.assertEqual(sum(first["meta"]["layer_actual"].values()), len(first["optimized"]))
        self.assertFalse(any("_score" in x for x in candidates))


if __name__ == "__main__":
    unittest.main()
