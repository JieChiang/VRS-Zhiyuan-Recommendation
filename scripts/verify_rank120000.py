"""Independent raw-graph audit for the user's 532/120000 example."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app.main import app, neo4j_client
from app.graph_data import DATASET_ID


QUERY = """MATCH (i:Institution)-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p:AdmissionProgram)
WHERE o.dataset_id=$dataset AND o.province='浙江' AND o.year=2024
  AND (i.province IN ['上海','上海市'] OR i.city IN ['成都','成都市'])
OPTIONAL MATCH (o)-[:HAS_PLAN]->(plan:PlanFact)
RETURN o.fact_id AS fact_id,i.name AS institution,i.city AS city,p.name AS major,
  o.min_rank AS min_rank,o.min_score AS min_score,coalesce(o.conflicting,false) AS conflicting,
  plan.subject_requirement_raw AS requirement,plan IS NOT NULL AS plan_matched,
  o.source_file AS source_file,o.source_sheet AS source_sheet,o.source_row AS source_row,
  plan.source_file AS plan_source,plan.source_row AS plan_row
ORDER BY min_rank"""


def main():
    payload = {"score":532,"rank":120000,"year":2024,"subject_combo":"物理、技术、地理",
               "majors":["计算机","物理","人工智能"],"provinces":["成都","上海"],"target_count":80}
    raw = neo4j_client.run_rows(QUERY, {"dataset":DATASET_ID})
    # Independent explicit domain checklist for this input; do not invoke the recommender's matcher.
    prefixes = ("计算机","人工智能","软件","信息安全","数字媒体技术","移动应用开发","大数据技术",
                "大数据工程技术","数据科学与大数据技术","物联网工程技术","网络工程","智能科学与技术","电子与计算机工程",
                "物理学","应用物理学","核物理","材料物理","工程物理","地球物理学","声学",
                "云计算","嵌入式","动漫制作","虚拟现实应用技术","空间信息与数字技术","空间科学与技术")
    known, pending, excluded, conflict = [], [], [], []
    for row in raw:
        base = re.split(r"[（(]",row["major"])[0]
        if not base.startswith(prefixes):
            continue
        if row["conflicting"]:
            conflict.append(row)
            continue
        requirement = row["requirement"]
        if requirement is None and not row["plan_matched"]:
            pending.append(row)
        elif requirement in {None,"","不限"} or set(requirement.split("&")) <= {"物","技","地"}:
            known.append(row)
        else:
            excluded.append(row)
    client = TestClient(app)
    response = client.post("/api/v1/recommend/run",json=payload)
    result = response.json()
    expected = {x["fact_id"] for x in known}
    actual = {x["fact_id"] for x in result.get("all",[])}
    expected_pending = {x["fact_id"] for x in pending}
    actual_pending = {x["fact_id"] for x in result.get("pending_candidates",[])}
    filtered_query = """MATCH (i:Institution)-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p:AdmissionProgram)
MATCH (o)-[:HAS_PLAN]->(plan:PlanFact)
WHERE o.dataset_id=$dataset AND o.province='浙江' AND o.year=2024
  AND coalesce(o.conflicting,false)=false AND o.min_rank IS NOT NULL
  AND (i.province IN ['上海','上海市'] OR i.city IN ['成都','成都市'])
  AND any(prefix IN $prefixes WHERE split(p.name,'(')[0] STARTS WITH prefix)
  AND (coalesce(trim(plan.subject_requirement_raw),'') IN ['','不限']
       OR all(subject IN split(plan.subject_requirement_raw,'&') WHERE subject IN ['物','技','地']))
RETURN o.fact_id AS fact_id,i.name AS institution,p.name AS major,o.min_rank AS min_rank,
  o.min_score AS min_score,plan.subject_requirement_raw AS subject_requirement,
  o.source_file AS source_file,o.source_row AS source_row
ORDER BY min_rank"""
    direct = neo4j_client.run_rows(filtered_query,{"dataset":DATASET_ID,"prefixes":list(prefixes)})
    checks = {"http_ok":response.status_code==200,
              "default_scope_is_all":result["meta"]["candidate_scope"]=="all",
              "graph_and_assistant_match":actual==expected,
              "standalone_cypher_matches_assistant":{x["fact_id"] for x in direct}==actual,
              "no_missing_graph_fact":not expected-actual,
              "no_ineligible_extra":not actual-expected,
              "pending_kept_separate":actual_pending==expected_pending,
              "every_school_requirement_is_subset":all(x["subject_eligibility"]=="eligible" for x in result["all"]),
              "single_physics_requirement_retained":any(x["subject_requirement"]=="物" for x in result["all"]),
              "higher_historical_rank_safety_candidates_retained":any(x["min_rank"]>220000 for x in result["all"]),
              "modern_big_data_name_retained":any(x["major"]=="大数据技术" for x in result["all"]),
              "accounting_not_misclassified":not any("会计" in x["major"] for x in result["all"])}
    window_counts = {}
    for window in [1000,5000,10000,30000,100000]:
        d=client.post("/api/v1/recommend/run",json={**payload,"candidate_scope":"window","rank_window":window}).json()
        window_counts[str(window)]={"confirmed":len(d["all"]),"pending":len(d["pending_candidates"])}
    checks["old_small_window_reproduced"] = window_counts["1000"]["confirmed"]==0
    peer=client.post("/api/v1/kg/peer-insights",json={k:payload[k] for k in ["rank","year","subject_combo","majors","provinces"]}).json()
    checks["peer_same_confirmed_population"]=peer["rank_distribution"]["total_candidates"]==len(known)
    report={"at":datetime.now(timezone.utc).isoformat(),"input":payload,"graph_query":QUERY,
            "graph_city_fact_count":len(raw),"confirmed_count":len(known),"pending_count":len(pending),
            "subject_excluded_count":len(excluded),"conflicting_fact_count":len(conflict),
            "missing_fact_ids":sorted(expected-actual),"unexpected_fact_ids":sorted(actual-expected),
            "window_counts":window_counts,"checks":checks,"passed":all(checks.values()),
            "confirmed":result["all"],"pending":result["pending_candidates"],"conflicting_facts":conflict}
    (ROOT/"docs"/"rank120000_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (ROOT/"docs"/"rank120000_query.cypher").write_text(filtered_query.replace('$dataset', "'"+DATASET_ID+"'").replace('$prefixes',json.dumps(prefixes,ensure_ascii=False)),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["passed","confirmed_count","pending_count","subject_excluded_count","conflicting_fact_count","missing_fact_ids","unexpected_fact_ids","window_counts","checks"]},ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
