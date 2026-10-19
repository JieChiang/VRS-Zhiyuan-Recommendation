"""Read-only graph and service checks against the configured Neo4j database."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.graph_data import DATASET_ID
from app.models import RecommendationRequest
from app.neo4j_http import Neo4jHttpClient
from app.services.kg_service import KgService
from app.services.recommender import RecommenderService


def main():
    client = Neo4jHttpClient(settings.neo4j_url, settings.neo4j_user, settings.neo4j_password, settings.neo4j_db)
    service = KgService(client)
    checks = {}
    scope = service.data_scope()
    checks["dataset_ready"] = scope["dataset"].get("import_status") == "ready"
    checks["source_files_14"] = client.run_rows("MATCH (s:SourceFile) RETURN count(s) AS n")[0]["n"] == 14
    for label in ["OfferFact", "PlanFact"]:
        missing = client.run_rows(f"""MATCH (n:{label}) WHERE n.source_file IS NULL OR n.source_row IS NULL
          OR NOT EXISTS {{ MATCH (n)-[:FOR_PROGRAM]->(:AdmissionProgram) }}
          OR NOT EXISTS {{ MATCH (n)-[:FROM_SOURCE]->(:SourceFile) }}
          OR NOT EXISTS {{ MATCH (n)-[:IN_YEAR]->(:Year) }}
          RETURN count(n) AS missing""")[0]["missing"]
        checks[f"{label}_provenance_and_links"] = missing == 0
    wrong_scope = client.run_rows("""MATCH (o:OfferFact) WHERE o.dataset_id<>$id OR o.province<>'浙江'
      OR o.year<2019 OR o.year>2024 RETURN count(o) AS n""", {"id": DATASET_ID})[0]["n"]
    checks["zhejiang_year_scope"] = wrong_scope == 0
    request = RecommendationRequest(rank=11100, year=2024, subject_combo="物理、化学、生物", target_count=20, rank_window=5000)
    result = RecommenderService(client).recommend(request)
    checks["recommendation_count_and_layers"] = len(result["all"]) == 20 and sum(result["meta"]["layer_actual"].values()) == 20
    checks["recommendations_have_source"] = all(x.get("source_file") and x.get("source_row") for x in result["all"])
    checks["known_ineligible_excluded"] = all(x["subject_eligibility"] != "ineligible" for x in result["all"])
    first = result["all"][0]
    detail = service.recommend_item_detail(first["institution"], first["major"], first["year"], first["fact_id"])
    checks["exact_fact_detail"] = detail["base"].get("fact_id") == first["fact_id"]
    history = service.admission_history(first["institution"], first["major"], 2022)
    checks["historical_cutoff"] = all(x["year"] <= 2022 for x in history)
    compare = service.compare_data([first["institution"]], "", 2024, [first])
    checks["comparison_has_matching_program"] = bool(compare["trend"]) and all(x["major"] == first["major"] for x in compare["trend"])
    for keyword, kind in [("浙江大学", "all"), ("计算机", "major"), ("", "all")]:
        graph = service.graph_explorer_data(keyword, kind, 20)
        ids = {n["id"] for n in graph["nodes"]}
        checks[f"graph_endpoints:{keyword}:{kind}"] = bool(ids) and all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
    checks["catalog_hierarchy"] = bool(service.major_l1_list())
    corrected = client.run_rows("""MATCH (m:MajorL3)-[:BELONGS_TO]->(c:MajorL2)
      WHERE m.major_type='本科' AND c.code IN ['0702','1004','1007']
      RETURN c.code AS code,c.name AS category,m.category_name_raw AS original,
        m.category_correction_source AS evidence""")
    names = {'0702':'物理学类','1004':'公共卫生与预防医学类','1007':'药学类'}
    checks["corrected_catalog_code_names"] = bool(corrected) and all(r["category"]==names[r["code"]] for r in corrected)
    checks["catalog_correction_provenance"] = sum(bool(r["original"] and r["evidence"]) for r in corrected)==8
    for label, parent in [("MajorL3", "MajorL2"), ("MajorL2", "MajorL1")]:
        wrong = client.run_rows(f"""MATCH (m:{label}) OPTIONAL MATCH (m)-[:BELONGS_TO]->(p:{parent})
          WITH m,count(p) AS parents WHERE parents<>1 RETURN count(m) AS n""")[0]["n"]
        checks[f"{label}_single_parent"] = wrong == 0
    checks["peer_query"] = "rank_distribution" in service.peer_insights(11100, [], [], 10, 2024)
    report = {"checks": checks, "passed": all(checks.values()), "scope": scope}
    (ROOT / "docs" / "graph_verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
