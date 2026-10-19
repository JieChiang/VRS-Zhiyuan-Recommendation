"""Real graph/API workflows, without OCR or production SQLite mutations."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app.main import app, neo4j_client
from app.graph_data import DATASET_ID, eligibility
from app.storage import LocalStorage


def main():
    start = time.monotonic()
    checks = []
    client = TestClient(app)
    def check(name, passed, detail=None):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            print("FAILED:", name, detail, flush=True)
    def request(name, path, payload=None, *, status=200, params=None):
        response = client.get(path, params=params) if payload is None else client.post(path, json=payload)
        check(name + ":http", response.status_code == status, {"status": response.status_code})
        return response.json()

    payload = {"score": 650, "rank": 11100, "year": 2024, "rank_window": 5000, "candidate_scope":"window",
               "subject_combo": "物理", "majors": ["计算机", "物理", "人工智能"],
               "provinces": ["成都", "上海"], "target_count": 80}
    # Reproduce the old predicate against current raw facts; no writes.
    raw = neo4j_client.run_rows("""MATCH (o:OfferFact {dataset_id:$dataset,province:'浙江',year:2024})
      WHERE o.min_rank>=6100 AND o.min_rank<=16100 AND coalesce(o.conflicting,false)=false
      MATCH (i:Institution)-[:HAS_OFFER]->(o)-[:FOR_PROGRAM]->(p:AdmissionProgram)
      OPTIONAL MATCH (o)-[:HAS_PLAN]->(f:PlanFact)
      RETURN i.name AS institution,i.province AS province,i.city AS city,p.name AS major,
        o.min_rank AS min_rank,f.subject_requirement_raw AS requirement,o.source_row AS source_row""", {"dataset": DATASET_ID})
    literal = [r for r in raw if any(k in r["major"] for k in payload["majors"])]
    old_geo = [r for r in literal if r["province"] in payload["provinces"]]
    old_result = [r for r in old_geo if eligibility(r["requirement"] or "", {"物理"}) != "ineligible"]
    old_funnel = {"rank_window": len(raw), "major_substring": len(literal), "province_only": len(old_geo),
                  "after_subject_filter": len(old_result), "results": old_result}
    check("old_single_law_result_reproduced", len(old_result) == 1 and old_result[0]["institution"] == "上海政法学院")

    health = request("health", "/api/v1/health")
    check("database_health", health["neo4j"]["ok"])
    scope = request("scope", "/api/v1/data/scope")
    check("scope_has_actual_2024", any(x["year"] == 2024 for x in scope["years"]))
    result = request("user_recommendation", "/api/v1/recommend/run", payload)
    rows = result["all"]
    keyset = lambda rs: {x["fact_id"] for x in rs}
    check("multiple_matching_candidates", len(rows) > 1, len(rows))
    check("chengdu_recovered", any(x["destination_city"] == "成都市" for x in rows))
    check("only_requested_cities", all(x["destination_city"] in {"成都市", "上海市"} or x["destination_province"] == "上海" for x in rows))
    check("unrelated_law_excluded", all(not x["major"].startswith("法学") for x in rows))
    check("catalog_related_major_included", any(x["major"] == "智能科学与技术" for x in rows))
    check("incomplete_subjects_not_claimed_eligible", all(x["subject_eligibility"] == "unknown" for x in rows))
    check("source_rows_preserved", all(x.get("source_file") and x.get("source_row") for x in rows))
    check("rank_window_respected", all(6100 <= x["min_rank"] <= 16100 for x in rows))
    check("layer_counts_consistent", sum(result["meta"]["layer_actual"].values()) == len(rows))
    variants = {}
    for name, changes in {
        "complete_physics_chemistry": {"subject_combo": "物理、化学、生物"},
        "complete_without_chemistry": {"subject_combo": "物理、历史、地理"},
        "city_suffix_alias": {"provinces": ["成都市", "上海市"]},
        "narrow_window": {"rank_window": 1000},
        "empty_destination": {"provinces": ["不存在的城市"]},
        "historical_year": {"year": 2022},
        "score_only_changed": {"score": 600},
        "target_school": {"target_institutions": ["西南交通大学"]},
    }.items():
        variants[name] = request(name, "/api/v1/recommend/run", {**payload, **changes})
    check("full_combination_retains_matches", keyset(variants["complete_physics_chemistry"]["all"] + variants["complete_physics_chemistry"]["pending_candidates"]) == keyset(rows))
    check("full_combination_excludes_chemistry_required", all(x["subject_requirement"] != "物&化" for x in variants["complete_without_chemistry"]["all"]))
    check("city_alias_same_results", keyset(variants["city_suffix_alias"]["all"]) == keyset(rows))
    check("narrow_window_respected", all(10100 <= x["min_rank"] <= 12100 for x in variants["narrow_window"]["all"]))
    check("unknown_destination_empty_with_explanation", not variants["empty_destination"]["all"] and variants["empty_destination"]["meta"]["warnings"])
    check("historical_year_not_copied", all(x["year"] == 2022 for x in variants["historical_year"]["all"]))
    check("rank_primary_score_not_double_filtered", keyset(variants["score_only_changed"]["all"]) == keyset(rows))
    check("target_school_tagged", variants["target_school"]["target_hits"] and all(x["institution"] == "西南交通大学" for x in variants["target_school"]["target_hits"]))

    first = next(x for x in rows if x["institution"] == "西南交通大学" and x["major"] == "人工智能")
    detail = request("exact_detail", "/api/v1/recommend/detail", params={k:first[k] for k in ["institution","major","year","fact_id"]})
    check("detail_exact_fact_and_source", detail["base"]["fact_id"] == first["fact_id"] and detail["base"]["source_row"] == first["source_row"])
    compare_items = [first, next(x for x in rows if x["institution"] == "东华大学" and x["major"] == "人工智能")]
    comparison = request("compare", "/api/v1/compare/data", {"compare_items": compare_items, "year": 2024})
    check("comparison_has_two_schools", {x["institution"] for x in comparison["trend"]} == {x["institution"] for x in compare_items})
    check("comparison_exact_programs", all(x["major"] == "人工智能" and x["year"] <= 2024 for x in comparison["trend"]))
    probabilities = request("probability", "/api/v1/recommend/probability", {"rank":11100,"items":rows,"year":2024})["probabilities"]
    check("probabilities_bounded_or_unknown", len(probabilities) == len(rows) and all(x["probability"] is None or 0 <= x["probability"] <= 100 for x in probabilities.values()))
    check("probabilities_no_future_history", all(h["year"] <= 2024 for x in probabilities.values() for h in x["history"]))
    adjusted = request("adjust", "/api/v1/recommend/adjust", {"rank":11100,"base_candidates":rows,"target_count":10})
    check("adjust_exact_count", len(adjusted["all"]) == 10 and sum(adjusted["meta"]["layer_actual"].values()) == 10)
    optimized = request("optimize", "/api/v1/recommend/optimize", {"rank":11100,"candidates":rows,"target_count":10,"user_preferences":{"人工智能":2}})
    check("optimizer_preserves_qualifications", len(optimized["optimized"]) == 10 and all(x["subject_eligibility"] == "unknown" for x in optimized["optimized"]))
    peer = request("peer", "/api/v1/kg/peer-insights", {k: payload[k] for k in ["rank","year","provinces","majors","subject_combo","rank_window","candidate_scope"]})
    check("peer_same_candidate_population", peer["rank_distribution"]["total_candidates"] == result["meta"]["filter_diagnostics"]["available_candidates"])
    search = request("search", "/api/v1/kg/search", params={"keyword":"人工智能"})
    check("search_major_found", bool(search["majors"]))
    major = request("major_detail", "/api/v1/kg/detail/major", params={"name":"人工智能"})
    check("major_detail_populated", bool(major["major_matches"] or major["top_schools"]))
    check("catalog_gap_explicit", bool(major["major_matches"]) or major["catalog_status"] == "missing")
    request("institution_detail", "/api/v1/kg/detail/institution", params={"name":"西南交通大学"})
    l1 = request("catalog_l1", "/api/v1/majors/l1")["items"]
    l2 = request("catalog_l2", "/api/v1/majors/l2", params={"l1_norm_name":next(x["norm_name"] for x in l1 if x["name"] == "工学")})["items"]
    l3 = request("catalog_l3", "/api/v1/majors/l3", params={"l2_norm_name":next(x["norm_name"] for x in l2 if x["name"] == "计算机类")})["items"]
    check("catalog_tree_real_names", any(x["name"] == "软件工程" for x in l3))
    graph = request("graph", "/api/v1/kg/explorer-data", {"keyword":"西南交通大学","limit":30})
    ids = {x["id"] for x in graph["nodes"]}
    check("graph_edges_have_endpoints", bool(ids) and all(x["source"] in ids and x["target"] in ids for x in graph["edges"]))
    for invalid in [{"rank":0}, {**payload,"subject_combo":"物理、化学、生物、历史"}]:
        request("invalid_input", "/api/v1/recommend/run", invalid, status=422)
    # Isolate save/recycle tests from the user's current strategies and recycle bin.
    with TemporaryDirectory() as temp, patch("app.main.storage", LocalStorage(Path(temp) / "workflow.db")):
        request("strategy_save", "/api/v1/session/save-strategy", {"name":"workflow-example","payload":payload})
        saved = request("strategy_list", "/api/v1/session/list-strategy")["items"]
        check("strategy_round_trip", saved[0]["payload"] == payload)
        item = {"bin_type":"S","item":first}
        request("recycle_add", "/api/v1/recycle/add", item)
        check("recycle_contains_item", len(request("recycle_list", "/api/v1/recycle/list")["items"]) == 1)
        restored = request("recycle_restore", "/api/v1/recycle/restore", item)
        check("restore_returns_original", restored["restored"] == first)
        check("restored_no_longer_in_bin", not request("recycle_after_restore", "/api/v1/recycle/list")["items"])
        request("repeat_restore", "/api/v1/recycle/restore", item, status=404)
    client.cookies.set("vrs_auth", "1")
    for route in ["/","/recommend","/compare","/majors","/trajectory","/simulate","/kg-explorer"]:
        check("page:"+route, client.get(route).status_code == 200)
    report = {"at":datetime.now(timezone.utc).isoformat(),"input":payload,"old_funnel":old_funnel,
              "new_result":result,"variant_counts":{k:len(v["all"]) for k,v in variants.items()},
              "checks":checks,"check_count":len(checks),"passed":all(x["passed"] for x in checks),
              "duration_seconds":round(time.monotonic()-start,2),"images_tested":False,
              "sqlite_test_isolated":True,"source_note":"全部院校与录取实例来自当前图谱，未改动原始数据；模型调用另见 llm_verification.json。"}
    (ROOT / "docs" / "workflow_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["passed","check_count","duration_seconds","variant_counts"]},ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
