"""Read-only cross-combination audit against independently selected graph facts."""
from __future__ import annotations

import itertools
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

SUBJECTS = ["物理","化学","生物","政治","历史","地理","技术"]
SHORT = dict(zip(SUBJECTS,["物","化","生","政","史","地","技"]))
# Expected categories are declared here; never call production preference/eligibility helpers.
PROFILES = [
    ("计算机/物理/AI·成都上海",2024,120000,["计算机","物理","人工智能"],["成都","上海"],["计算机类","物理学类"],["计算机","物理","人工智能","大数据技术","大数据工程技术","云计算技术应用","数据科学与大数据技术"]),
    ("法学·全国",2024,60000,["法学"],[],["法学类"],["法学"]),
    ("经济学·全国",2024,50000,["经济学"],[],["经济学类"],["经济学"]),
    ("物理·全国",2024,11100,["物理"],[],["物理学类"],["物理"]),
    ("临床医学·全国",2024,30000,["临床医学"],[],["临床医学类"],["临床医学"]),
    ("英语·浙江成都",2023,80000,["英语"],["浙江","成都"],[],["英语"]),
    ("机械·广东",2022,150000,["机械"],["广东"],["机械类"],["机械"]),
    ("护理·全国",2024,220000,["护理"],[],["护理类"],["护理"]),
    ("金融·上海浙江",2024,40000,["金融"],["上海","浙江"],["金融学类","金融类"],["金融"]),
    ("师范·浙江",2024,100000,["师范"],["浙江"],[],["师范","师范类","含师范","职教师范","含职教师范","非公费师范"]),
    ("数学·全国",2024,20000,["数学"],[],["数学类"],["数学"]),
    ("药学·全国",2024,70000,["药学"],[],["药学类"],["药学"]),
    ("公共卫生与预防医学·全国",2024,90000,["公共卫生与预防医学"],[],["公共卫生与预防医学类"],["公共卫生与预防医学"]),
    ("人工智能·全国",2024,90000,["人工智能"],[],[],["人工智能"]),
    ("物理/数学/财会·成都上海",2024,120000,["物理","数学","财会"],["成都","上海"],["物理学类","数学类"],
     ["物理","数学","会计","会计学","财务管理","审计","审计学","财务会计类","大数据与会计","大数据与财务管理","大数据与审计"]),
]
QUERY = """MATCH (i:Institution)-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p:AdmissionProgram)
WHERE o.dataset_id=$dataset AND o.province='浙江' AND o.year=$year
  AND coalesce(o.conflicting,false)=false AND o.min_rank>=1
  AND (size($places)=0 OR i.province IN $places OR i.city IN $places)
OPTIONAL MATCH (o)-[:HAS_PLAN]->(plan:PlanFact)
RETURN o.fact_id AS fact_id,i.name AS institution,p.name AS major,o.year AS year,o.min_rank AS min_rank,
  plan.subject_requirement_raw AS requirement,plan IS NOT NULL AS matched"""


def state(row, selected):
    raw = row["requirement"]
    if not row["matched"]:
        return "unknown"
    if raw is None or raw.strip() in {"","不限"}:
        return "eligible"
    options = [set(part.split("&")) for part in raw.split("|")]
    if any(group <= selected for group in options):
        return "eligible"
    return "ineligible" if len(selected)==3 else "unknown"


def domain(program, terms):
    parts = re.split(r"[()、,;/]",program.replace("（","(").replace("）",")"))
    if any(parts[0].startswith(term) for term in terms) or any(part in terms for part in parts[1:]):
        return True
    if parts[0].endswith("类") or any(word in parts[0] for word in ["实验班","试验班"]):
        for part in parts[1:]:
            part = re.sub(r"^(包含专业:|包括专业:|含专业:|包含|包括|含)","",part)
            if part.removesuffix("专业").removesuffix("等") in terms:
                return True
    return False


def main():
    client = TestClient(app)
    cases, failures, summary, peer_checks = [], [], [], []
    catalog = neo4j_client.run_rows("MATCH (m:MajorL3)-[:BELONGS_TO]->(c:MajorL2) RETURN m.name AS major,c.name AS category",{})
    def check_case(label, payload, raw, weights=(3,4,3)):
        selected = {SHORT[s] for s in SUBJECTS if s in payload["subject_combo"]}
        known = [r for r in raw if state(r,selected)=="eligible"]
        pending = [r for r in raw if state(r,selected)=="unknown"]
        primary = known if len(selected)==3 else known+pending
        expected = {r["fact_id"] for r in primary}
        expected_pending = {r["fact_id"] for r in pending} if len(selected)==3 else set()
        response = client.post("/api/v1/recommend/run",json=payload)
        if response.status_code!=200:
            failures.append({"case":label,"status":response.status_code})
            return {}
        result = response.json()
        actual = {r["fact_id"] for r in result["all"]}
        def layer(r):
            return "冲" if r["min_rank"]<payload["rank"]-300 else "稳" if r["min_rank"]<=payload["rank"]+300 else "保"
        allowed = {x for x,w in zip(["冲","稳","保"],weights) if w}
        permitted = {r["fact_id"] for r in primary if layer(r) in allowed}
        checks = {
            "candidate_count":result["meta"]["filter_diagnostics"]["primary_candidates"]==len(expected),
            "no_extra":actual<=permitted,
            "no_missing_below_cap":actual==permitted if len(permitted)<=payload["target_count"] else len(actual)==payload["target_count"],
            "pending_exact":{r["fact_id"] for r in result["pending_candidates"]}==expected_pending,
            "valid_layers":all(r["layer"]==layer(r) and r["layer"] in allowed for r in result["all"]),
            "unique":len(actual)==len(result["all"]),
            "grouped_order":result["all"]==result["chong"]+result["wen"]+result["bao"],
        }
        case = {"case":label,"subjects":payload["subject_combo"],"eligible":len(known),"pending":len(pending),
                "returned":len(actual),"checks":checks}
        cases.append(case)
        if not all(checks.values()):
            failures.append({**case,"missing":sorted(permitted-actual)[:8],"extra":sorted(actual-permitted)[:8],
                             "diagnostics":result["meta"]["filter_diagnostics"]})
        return result

    for title,year,rank,majors,places,categories,literals in PROFILES:
        terms = set(literals)|{r["major"] for r in catalog if r["category"] in categories}|set(categories)
        geo = list(set(places+[p+"市" if p in {"成都","上海"} else p+"省" for p in places]))
        raw = [r for r in neo4j_client.run_rows(QUERY,{"dataset":DATASET_ID,"year":year,"places":geo}) if domain(r["major"],terms)]
        payload = {"rank":rank,"year":year,"majors":majors,"provinces":places,"target_count":300,"candidate_scope":"all"}
        start = len(cases)
        for combo in itertools.combinations(SUBJECTS,3):
            check_case(title,{**payload,"subject_combo":"、".join(combo)},raw)
        current = cases[start:]
        summary.append({"profile":title,"year":year,"rank":rank,"raw_domain_facts":len(raw),"combinations":len(current),
                        "eligible_min":min(c["eligible"] for c in current),"eligible_max":max(c["eligible"] for c in current),
                        "pending_min":min(c["pending"] for c in current),"pending_max":max(c["pending"] for c in current)})
        print(json.dumps(summary[-1],ensure_ascii=False),flush=True)
        peer_payload = {k:v for k,v in payload.items() if k!="target_count"}
        peer_payload["subject_combo"] = "物理、化学、生物"
        peer = client.post("/api/v1/kg/peer-insights",json=peer_payload)
        peer_ok = peer.status_code==200 and peer.json()["rank_distribution"]["total_candidates"]==sum(state(r,{"物","化","生"})=="eligible" for r in raw)
        peer_checks.append({"profile":title,"passed":peer_ok})
        if not peer_ok:
            failures.append({"case":title,"error":"图谱分布与独立候选集数量不一致"})
        # Partial selection and disabled layer cases use the same independent cohort.
        if title=="法学·全国":
            for combo in ["","物理","物理、地理"]:
                check_case(title+"·未完整选科",{**payload,"subject_combo":combo},raw)
            for weights in [(0,1,0),(1,0,0),(0,0,1),(1,0,1),(0,1,1),(1,1,0)]:
                check_case(title+"·比例"+str(weights),{**payload,"subject_combo":"物理、化学、生物",
                           **dict(zip(["ratio_chong","ratio_wen","ratio_bao"],weights))},raw,weights)
    report = {"at":datetime.now(timezone.utc).isoformat(),"passed":not failures,"profile_count":len(PROFILES),
              "subject_combination_count":35,"api_cases":len(cases)+len(peer_checks),"recommendation_cases":len(cases),
              "assertions":sum(len(c["checks"]) for c in cases)+len(peer_checks),
              "summary":summary,"peer_checks":peer_checks,"failures":failures,"cases":cases,
              "method":"独立查询原图谱事实，预先指定目录专业类，单独计算选科集合包含关系；候选超过300时核对总量、返回数量及每条资格，未声称展示全部。"}
    (ROOT/"docs"/"combination_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["passed","api_cases","assertions","failures"]},ensure_ascii=False),flush=True)
    if failures:
        raise SystemExit(1)


if __name__=="__main__":
    main()
