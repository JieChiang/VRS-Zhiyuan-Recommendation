import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.graph_data import eligibility, selected_subjects, subject_requirement_info
from app.main import app
from app.models import RecommendationRequest
from app.services.preference_filters import location_aliases, major_matches, resolve_major_terms
from app.services.recommender import RecommenderService
from app.storage import LocalStorage


class PreferenceTests(unittest.TestCase):
    def test_school_requirements_may_be_a_strict_subset(self):
        selected = {"物理", "技术", "地理"}
        self.assertEqual(selected_subjects("（物理，技术，地理）"), selected)
        for requirement in ["物", "地", "技", "物&地", "物&技", "不限"]:
            self.assertEqual(eligibility(requirement, selected), "eligible", requirement)
        for requirement in ["化", "物&化", "物&化&技"]:
            self.assertEqual(eligibility(requirement, selected), "ineligible", requirement)

    def test_all_scope_does_not_apply_a_hidden_rank_window(self):
        client = Mock()
        client.run_rows.return_value = []
        service = RecommenderService(client)
        service._fetch_candidates(RecommendationRequest(rank=120000))
        params = client.run_rows.call_args.args[1]
        self.assertEqual(params["lower"], 1)
        self.assertGreater(params["upper"], 300000)
        service._fetch_candidates(RecommendationRequest(rank=120000, candidate_scope="window", rank_window=1000))
        params = client.run_rows.call_args.args[1]
        self.assertEqual((params["lower"], params["upper"]), (119000,121000))

    def test_unknown_requirements_are_separate_from_confirmed_for_full_combo(self):
        client = Mock()
        client.run_rows.return_value = [
            {"institution":"甲", "major":"计算机", "year":2024, "min_rank":130000, "subject_requirement":"物", "plan_matched":True},
            {"institution":"乙", "major":"计算机", "year":2024, "min_rank":125000, "subject_requirement":None, "plan_matched":False},
        ]
        result = RecommenderService(client).recommend(RecommendationRequest(rank=120000, subject_combo="物理、技术、地理"))
        self.assertEqual([x["institution"] for x in result["all"]], ["甲"])
        self.assertEqual([x["institution"] for x in result["pending_candidates"]], ["乙"])

    def test_computing_domain_covers_verified_supplement_not_accounting(self):
        client = Mock()
        client.run_rows.return_value = []
        terms = resolve_major_terms(client, ["计算机"])
        self.assertTrue(major_matches("大数据技术", terms))
        self.assertTrue(major_matches("大数据工程技术", terms))
        self.assertTrue(major_matches("数据科学与大数据技术(中外合作办学)", terms))
        self.assertFalse(major_matches("大数据与会计", terms))

    def test_unrestricted_accepts_every_subject_combination(self):
        for requirement in ["不限", "无", "无要求", "没有要求", "无选科要求", "不提科目要求", "选考科目不限", ""]:
            for subjects in [set(), {"物理"}, {"物理", "化学", "生物"}, {"政治", "历史", "地理"}]:
                with self.subTest(requirement=requirement, subjects=subjects):
                    self.assertEqual(eligibility(requirement, subjects), "eligible")

    def test_blank_plan_requirement_differs_from_absent_plan(self):
        self.assertEqual(subject_requirement_info(None, plan_matched=True)["kind"], "unrestricted")
        self.assertEqual(subject_requirement_info("", plan_matched=True)["display"], "不限选科")
        self.assertEqual(subject_requirement_info(None, plan_matched=False)["kind"], "unknown")
        self.assertEqual(eligibility(None, {"物理", "化学", "生物"}), "unknown")

    def test_unrestricted_rows_are_never_excluded_by_subjects(self):
        client = Mock()
        client.run_rows.return_value = [
            {"institution":"不限学校", "major":"不限专业", "subject_requirement":"不限", "plan_matched":True},
            {"institution":"空白学校", "major":"空白专业", "subject_requirement":"", "plan_matched":True},
            {"institution":"空值学校", "major":"空值专业", "subject_requirement":None, "plan_matched":True},
            {"institution":"缺计划学校", "major":"缺计划专业", "subject_requirement":None, "plan_matched":False},
            {"institution":"物化学校", "major":"物化专业", "subject_requirement":"物&化", "plan_matched":True},
        ]
        stats = {}
        rows = RecommenderService(client)._fetch_candidates(RecommendationRequest(rank=11100, subject_combo="政治、历史、地理"), stats)
        self.assertEqual(len(rows), 4)
        self.assertEqual(stats["subject_unrestricted"], 3)
        self.assertEqual([x["subject_eligibility"] for x in rows], ["eligible","eligible","eligible","unknown"])

    def test_city_alias_does_not_expand_to_entire_province(self):
        aliases = location_aliases(["成都", "上海市"])
        self.assertIn("成都市", aliases)
        self.assertIn("上海", aliases)
        self.assertNotIn("四川", aliases)
        self.assertNotIn("绵阳市", aliases)

    def test_incomplete_subjects_remain_unknown_instead_of_rejected(self):
        self.assertEqual(eligibility("物&化", {"物理"}, complete=False), "unknown")
        self.assertEqual(eligibility("物", {"物理"}, complete=False), "eligible")
        self.assertEqual(eligibility("不限", set(), complete=False), "eligible")
        self.assertEqual(eligibility("物&化", {"物理", "历史", "地理"}), "ineligible")

    def test_too_many_subjects_are_rejected(self):
        with self.assertRaises(ValueError):
            selected_subjects("物理、化学、生物、历史")

    def test_catalog_expansion_and_unrelated_direction(self):
        client = Mock()
        client.run_rows.return_value = [{"major": "软件工程", "category": "计算机类", "field": "工学"}]
        terms = resolve_major_terms(client, ["计算机", "人工智能"])
        self.assertIn("软件工程", terms)
        self.assertTrue(major_matches("软件工程(实验班)", terms))
        self.assertTrue(major_matches("工科试验班(软件工程、计算机科学与技术)", terms))
        self.assertFalse(major_matches("法学(人工智能法学方向)", terms))
        self.assertFalse(major_matches("金融学(计算机金融方向)", terms))
        self.assertTrue(major_matches("计算机类(含数据科学与大数据技术、人工智能专业)",["人工智能"]))
        self.assertTrue(major_matches("工科试验班(包含专业:软件工程、机械工程)",["软件工程"]))
        self.assertTrue(major_matches("外国语言文学类(含英语(非公费师范)翻译专业)",["英语"]))
        self.assertFalse(major_matches("法学(含人工智能法学方向)",["人工智能"]))
        self.assertTrue(major_matches("法学(人工智能法学方向)", ["法学"]))

    def test_specific_major_does_not_expand_to_entire_field(self):
        client = Mock()
        client.run_rows.return_value = [{"major": "人工智能", "category": "电子信息类", "field": "工学"}]
        self.assertEqual(resolve_major_terms(client, ["人工智能"]), ["人工智能"])

    def test_ambiguous_major_prefers_category_and_explicit_field_is_available(self):
        client = Mock()
        client.run_rows.return_value = [
            {"major":"法学","category":"法学类","field":"法学"},
            {"major":"知识产权","category":"法学类","field":"法学"},
            {"major":"社会工作","category":"社会学类","field":"法学"},
        ]
        info = []
        terms = resolve_major_terms(client, ["法学"], info)
        self.assertIn("知识产权", terms)
        self.assertNotIn("社会工作", terms)
        self.assertEqual(info[0]["level"], "专业类")
        self.assertIn("社会工作", resolve_major_terms(client, ["法学门类"]))
        self.assertNotIn("知识产权", resolve_major_terms(client, ["法学专业"]))
        exact = resolve_major_terms(client,["法学专业"])
        self.assertTrue(major_matches("法学(卓越班)",exact))
        self.assertTrue(major_matches("法学类(法学、知识产权)",exact))
        self.assertFalse(major_matches("法学类",exact))
        self.assertFalse(major_matches("法学类(知识产权)",exact))

    def test_physics_is_not_physical_therapy(self):
        client = Mock()
        client.run_rows.return_value = [
            {"major":"应用物理学","category":"物理学类","field":"理学"},
            {"major":"康复物理治疗","category":"医学技术类","field":"医学"}]
        terms = resolve_major_terms(client, ["物理"])
        self.assertTrue(major_matches("应用物理学(实验班)",terms))
        self.assertFalse(major_matches("康复物理治疗",terms))

    def test_teacher_attribute_includes_grouped_but_excludes_non_teacher(self):
        client = Mock()
        client.run_rows.return_value = []
        for keyword in ["师范","师范类","师范教育"]:
            terms = resolve_major_terms(client, [keyword])
            for program in ["英语(师范类)","中国语言文学类(含师范)","英语(非公费师范)","教育学类(创新实验班,含师范)"]:
                self.assertTrue(major_matches(program,terms), program)
            self.assertFalse(major_matches("英语(非师范,拔尖人才培养)",terms))

    def test_full_autonomous_region_names_share_the_same_aliases(self):
        for short,full in [("广西","广西壮族自治区"),("宁夏","宁夏回族自治区"),("新疆","新疆维吾尔自治区")]:
            self.assertEqual(location_aliases([short]),location_aliases([full]))

    def test_accounting_alias_keeps_modern_names_without_other_business_majors(self):
        client = Mock()
        client.run_rows.return_value = []
        terms = resolve_major_terms(client,["财会"])
        for program in ["会计学","财务管理","审计学","大数据与会计","大数据与财务管理","大数据与审计"]:
            self.assertTrue(major_matches(program,terms),program)
        for program in ["金融数学","工商管理","市场营销","计算机科学与技术"]:
            self.assertFalse(major_matches(program,terms),program)

    def test_incomplete_subject_candidate_is_labeled_with_missing_chemistry(self):
        client = Mock()
        client.run_rows.side_effect = [[], [{"institution": "学校", "major": "人工智能", "year": 2024,
                                            "min_rank": 11100, "subject_requirement": "物&化"}]]
        result = RecommenderService(client).recommend(RecommendationRequest(rank=11100, subject_combo="物理", majors=["人工智能"]))
        self.assertEqual(result["all"][0]["subject_eligibility"], "unknown")
        self.assertEqual(result["all"][0]["subject_missing"], ["化学"])
        self.assertFalse(result["meta"]["subject_selection_complete"])
        self.assertTrue(result["meta"]["warnings"])

    def test_complete_incompatible_combination_is_excluded(self):
        client = Mock()
        client.run_rows.return_value = [{"institution": "学校", "major": "计算机", "subject_requirement": "物&化"}]
        result = RecommenderService(client)._fetch_candidates(RecommendationRequest(rank=11100, subject_combo="物理、历史、地理"))
        self.assertEqual(result, [])

    def test_restore_removes_exact_item_and_rejects_repeat(self):
        with TemporaryDirectory() as directory, patch("app.main.storage", LocalStorage(Path(directory) / "test.db")):
            client = TestClient(app)
            item = {"institution": "测试学校", "major": "测试专业"}
            body = {"bin_type": "S", "item": item}
            self.assertEqual(client.post("/api/v1/recycle/add", json=body).status_code, 200)
            self.assertEqual(len(client.get("/api/v1/recycle/list").json()["items"]), 1)
            self.assertEqual(client.post("/api/v1/recycle/restore", json=body).json()["restored"], item)
            self.assertEqual(client.get("/api/v1/recycle/list").json()["items"], [])
            self.assertEqual(client.post("/api/v1/recycle/restore", json=body).status_code, 404)


if __name__ == "__main__":
    unittest.main()
