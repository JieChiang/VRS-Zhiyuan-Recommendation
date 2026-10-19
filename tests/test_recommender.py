import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from app.models import AdjustRequest, OptimizeRequest, RecommendationRequest
from app.services.recommender import RecommenderService


class RecommenderRegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.service = RecommenderService(self.client)

    def test_destination_filter_is_not_bypassed_by_institution_name(self):
        self.client.run_rows.return_value = []
        self.service.recommend(RecommendationRequest(rank=10000, provinces=["北京"]))
        query, params = self.client.run_rows.call_args.args
        self.assertIn("i.province IN $provinces", query)
        self.assertNotIn("OR i.name IS NOT NULL", query)
        self.assertEqual(params["provinces"], ["北京"])

    def test_fill_updates_all_layer_lists_and_counts(self):
        rows = [{"institution": f"学校{i}", "major": "测试专业", "year": 2024,
                 "min_rank": 11000 + i} for i in range(12)]
        result = self.service._split_layers(rows, 10000, 10, 3, 4, 3)
        self.assertEqual(len(result["all"]), 10)
        self.assertEqual(len(result["bao"]), 10)
        self.assertEqual(result["meta"]["layer_actual"], {"冲": 0, "稳": 0, "保": 10})
        self.assertEqual(result["all"], result["chong"] + result["wen"] + result["bao"])

    def test_fill_does_not_repeat_same_fallback_item(self):
        def row(name):
            return {"institution": name, "major": "专业", "year": 2024, "min_rank": 12000}
        rows = [row(f"学校{i}") for i in range(3)] + [row("补充"), row("补充"), row("其他")]
        result = self.service._split_layers(rows, 10000, 10, 3, 4, 3)
        self.assertEqual(sum(x["institution"] == "补充" for x in result["all"]), 1)

    def test_missing_candidates_stay_empty(self):
        result = self.service._split_layers([], 10000, 80, 3, 4, 3)
        self.assertEqual(result["all"], [])
        self.assertEqual(sum(result["meta"]["layer_actual"].values()), 0)

    def test_zero_weight_is_preserved(self):
        for model in [RecommendationRequest, AdjustRequest, OptimizeRequest]:
            request = model(rank=10000, ratio_chong=0, ratio_wen=10, ratio_bao=0)
            self.assertEqual(request.ratio_chong, 0)
            self.assertEqual(request.ratio_bao, 0)

    def test_disabled_layers_are_never_used_for_filling(self):
        rows = [{"institution":f"学校{i}","major":"专业","year":2024,"min_rank":r}
                for i,r in enumerate([9000,9700,10000,10300,11000])]
        for weights,allowed in [((0,1,0),{"稳"}),((1,0,1),{"冲","保"}),((0,0,1),{"保"})]:
            result = self.service._split_layers(rows,10000,10,*weights)
            self.assertTrue(all(x["layer"] in allowed for x in result["all"]))
            self.assertEqual(len(result["all"]),sum(self.service._classify_layer(r["min_rank"],10000) in allowed for r in rows))
        result = self.service._split_layers(rows,10000,10,0,1,0)
        self.assertEqual([r["min_rank"] for r in result["all"]],[9700,10000,10300])
        self.assertEqual(result["meta"]["disabled_layers"],["冲","保"])

    def test_duplicates_are_removed_before_layer_quotas(self):
        row = {"institution":"学校","major":"专业","year":2024,"min_rank":10000}
        result = self.service._split_layers([row,row,row],10000,10,3,4,3)
        self.assertEqual(len(result["all"]),1)

    def test_filled_mixed_layers_remain_grouped(self):
        rows = [{"institution":str(r),"major":"专业","year":2024,"min_rank":r}
                for r in [10000,9000,11000,8000,7000,6000]]
        result = self.service._split_layers(rows,10000,10,3,4,3)
        self.assertEqual(result["all"],result["chong"]+result["wen"]+result["bao"])

    def test_rounded_layer_targets_sum_to_requested_count(self):
        for count in range(10, 301):
            for weights in [(1, 1, 0), (3, 4, 3), (0, 1, 0), (1, 1, 1)]:
                targets = self.service._layer_targets(count, *weights)
                self.assertEqual(sum(targets), count)
                self.assertTrue(all(n >= 0 for n in targets))
                for weight, n in zip(weights, targets):
                    if weight == 0:
                        self.assertEqual(n, 0)

    def test_invalid_ratio_is_rejected_for_all_entry_points(self):
        for model in [RecommendationRequest, AdjustRequest, OptimizeRequest]:
            for ratios in [(0, 0, 0), (-1, 4, 3)]:
                with self.subTest(model=model.__name__, ratios=ratios), self.assertRaises(ValidationError):
                    model(rank=10000, ratio_chong=ratios[0], ratio_wen=ratios[1], ratio_bao=ratios[2])

    def test_optional_score_and_negative_score(self):
        self.assertIsNone(RecommendationRequest(rank=1).score)
        with self.assertRaises(ValidationError):
            RecommendationRequest(rank=1, score=-1)

    def test_constant_history_with_large_gap_does_not_overflow(self):
        history = [{"year": y, "min_rank": 10000} for y in [2022, 2023, 2024]]
        for rank, expected in [(1000000, 0), (1, 100), (10000, 50)]:
            with self.subTest(rank=rank):
                self.assertEqual(self.service.calculate_probability(rank, history)["probability"], expected)

    def test_risk_labels_follow_probability(self):
        history = [{"year": 2023, "min_rank": 9900}, {"year": 2024, "min_rank": 10100}]
        self.assertEqual(self.service.calculate_probability(100, history)["risk_level"], "低风险(保)")
        self.assertEqual(self.service.calculate_probability(100000, history)["risk_level"], "高风险(冲)")

    def test_recent_rank_uses_year_order(self):
        history = [{"year": 2024, "min_rank": 9000}, {"year": 2022, "min_rank": 12000}]
        result = self.service.calculate_probability(10000, history)
        self.assertEqual(result["stats"]["recent_rank"], 9000)
        self.assertEqual(result["stats"]["trend"], "上升")

    def test_invalid_history_returns_unknown(self):
        history = [{}, {"min_rank": ""}, {"min_rank": None}, {"min_rank": float("inf")}, {"min_rank": -1}]
        self.assertIsNone(self.service.calculate_probability(10000, history)["probability"])


if __name__ == "__main__":
    unittest.main()
