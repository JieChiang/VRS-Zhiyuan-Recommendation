"""Read-only audit that no unrestricted program is lost to subject filtering."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.graph_data import DATASET_ID, subject_options
from app.main import neo4j_client, recommender_service
from app.models import RecommendationRequest


def main():
    patterns = neo4j_client.run_rows("""MATCH (p:PlanFact {dataset_id:$dataset})
      RETURN p.subject_requirement_raw AS requirement,count(p) AS count ORDER BY count DESC""", {"dataset":DATASET_ID})
    check = {}
    check["all_source_requirement_patterns_supported"] = all(subject_options(x["requirement"]) is not None for x in patterns)
    raw = neo4j_client.run_rows("""MATCH (o:OfferFact {dataset_id:$dataset,province:'浙江',year:2024})-[:HAS_PLAN]->(p:PlanFact)
      WHERE coalesce(o.conflicting,false)=false AND o.min_rank>=1 AND o.min_rank<=200000
        AND p.subject_requirement_raw='不限'
      MATCH (i:Institution)-[:HAS_OFFER]->(o)-[:FOR_PROGRAM]->(m:AdmissionProgram)
      RETURN o.fact_id AS fact_id,i.name AS institution,m.name AS major,o.min_rank AS min_rank,
        p.subject_requirement_raw AS subject_requirement,o.source_file AS source_file,o.source_row AS source_row""", {"dataset":DATASET_ID})
    expected = {x["fact_id"] for x in raw}
    cohorts = []
    for combo in ["", "物理", "物理、化学、生物", "政治、历史、地理", "技术、历史、生物"]:
        stats = {}
        rows = recommender_service._fetch_candidates(RecommendationRequest(rank=100000, rank_window=100000, candidate_scope="window", year=2024, subject_combo=combo), stats)
        unlimited = [x for x in rows if x["subject_requirement_kind"] == "unrestricted"]
        retained = {x["fact_id"] for x in unlimited}
        label = combo or "未填选科"
        check[f"retained_all_unrestricted:{label}"] = retained == expected
        check[f"unrestricted_eligible:{label}"] = all(x["subject_eligibility"] == "eligible" for x in unlimited)
        cohorts.append({"subjects":label,"source_unrestricted_count":len(expected),"retained":len(retained),
                        "lost_fact_count":len(expected-retained),"all_candidates":len(rows)})
    user_result = recommender_service.recommend(RecommendationRequest(
        score=650, rank=11100, year=2024, rank_window=5000, candidate_scope="window", subject_combo="物理",
        majors=["计算机","物理","人工智能"], provinces=["成都","上海"]))
    check["original_window_case_not_regressed"] = len(user_result["all"]) >= 15
    check["original_case_has_no_unrestricted_subject_exclusions"] = user_result["meta"]["filter_diagnostics"]["subject_unrestricted"] == 0
    missing = sum(x["plan_matched"] is False for x in user_result["all"])
    check["missing_plan_kept_unknown"] = all(x["subject_eligibility"] == "unknown" for x in user_result["all"] if not x["plan_matched"])
    report = {"at":datetime.now(timezone.utc).isoformat(), "scope":"2024年浙江、非冲突、最低位次1–200000，地区和专业不限；只审计选科对候选的影响",
              "source_plan_facts":sum(x["count"] for x in patterns),
              "source_unrestricted_plan_facts":sum(x["count"] for x in patterns if subject_options(x["requirement"]) == [[]]),
              "source_blank_plan_facts":sum(x["count"] for x in patterns if x["requirement"] is None or not x["requirement"].strip()),
              "requirement_patterns":patterns,"cohorts":cohorts,"checks":check,"passed":all(check.values()),
              "original_case":{"candidate_count":len(user_result["all"]),"unrestricted_count":user_result["meta"]["filter_diagnostics"]["subject_unrestricted"],
                               "missing_plan_count":missing,"diagnostics":user_result["meta"]["filter_diagnostics"]},
              "sample_unrestricted_facts":raw[:5],"images_tested":False}
    (ROOT / "docs" / "subject_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["passed","source_plan_facts","source_unrestricted_plan_facts","source_blank_plan_facts","cohorts","original_case"]},ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
