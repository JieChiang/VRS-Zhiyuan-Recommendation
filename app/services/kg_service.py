from __future__ import annotations

from typing import Any
from app.graph_data import DATASET_ID, name, subject_requirement_info
from app.neo4j_http import Neo4jHttpClient


class KgService:
    """v2 queries: raw admission programs are distinct from catalog majors."""
    def __init__(self, client: Neo4jHttpClient):
        self.client = client

    def q(self, query, params=None):
        return self.client.run_rows(query, params or {})

    def health(self):
        return {"ok": self.q("RETURN 1 AS ok")[0]["ok"] == 1}

    def data_scope(self):
        datasets = self.q("MATCH (d:Dataset {dataset_id:$id}) RETURN properties(d) AS dataset", {"id": DATASET_ID})
        years = self.q("""MATCH (o:OfferFact {dataset_id:$id})
          RETURN o.year AS year,count(o) AS offer_count,count(o.min_rank) AS rank_count ORDER BY year DESC""", {"id": DATASET_ID})
        return {"dataset": datasets[0]["dataset"] if datasets else {}, "years": years,
                "limitations": ["原表未标注录取批次和科类", "计划表选科要求未按年区分", "无一分一段表，不自动将分数换算为位次"]}

    def search(self, keyword, limit=20):
        params = {"kw": name(keyword), "limit": max(1, min(limit, 100))}
        majors = self.q("MATCH (m:MajorL3) WHERE m.name CONTAINS $kw RETURN DISTINCT m.name AS name,'catalog' AS source_type ORDER BY name LIMIT $limit", params)
        programs = self.q("MATCH (p:AdmissionProgram) WHERE p.name CONTAINS $kw RETURN DISTINCT p.name AS name,'admission_program' AS source_type ORDER BY name LIMIT $limit", params)
        names = {x["name"] for x in majors}
        majors.extend(x for x in programs if x["name"] not in names)
        return {
            "institutions": self.q("MATCH (i:Institution) WHERE i.name CONTAINS $kw RETURN i.name AS name ORDER BY name LIMIT $limit", params),
            "majors": majors[:params["limit"]],
        }

    def _rankings(self, institution, year):
        rows = self.q("""MATCH (:Institution {norm_name:$institution})-[:HAS_RANKING]->(r:RankingFact)
          WHERE r.year <= $year RETURN r.list_type AS list_type,r.year AS year,r.rank AS rank,
          r.world_rank AS world_rank,r.score AS score,r.source_file AS source_file
          ORDER BY year DESC,list_type""", {"institution": name(institution), "year": year})
        latest = {}
        for row in rows:
            latest.setdefault(row["list_type"], row)
        return list(latest.values())

    def institution_detail(self, institution, year=2024):
        result = self.recommend_item_detail(institution, "", year)
        rows = self.q("MATCH (i:Institution {norm_name:$name}) RETURN properties(i) AS institution", {"name": name(institution)})
        return {"institution": rows[0]["institution"] if rows else {}, "ranking": result["rankings"],
                "satisfaction": result["institution_satisfaction"], "employment_flow": result["employment_flow"]}

    def major_detail(self, major):
        params = {"name": name(major)}
        base = self.q("""MATCH (m:MajorL3) WHERE m.name CONTAINS $name
          OPTIONAL MATCH (m)-[:BELONGS_TO]->(l2:MajorL2)-[:BELONGS_TO]->(l1:MajorL1)
          RETURN m.name AS major,m.code AS code,m.major_type AS major_type,m.degree AS degree,
          m.intro AS intro,l2.name AS l2_name,l1.name AS l1_name LIMIT 10""", params)
        schools = self.q("""MATCH (i:Institution)-[:OFFERS_PROGRAM]->(p:AdmissionProgram)
          OPTIONAL MATCH (p)-[:MAPS_TO]->(m:MajorL3)
          WITH i,p,m WHERE m.name CONTAINS $name OR p.name CONTAINS $name
          OPTIONAL MATCH (i)-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p)
          WHERE o.province='浙江' AND coalesce(o.conflicting,false)=false
          RETURN i.name AS institution,count(DISTINCT o) AS offer_count,min(o.min_rank) AS best_rank
          ORDER BY offer_count DESC LIMIT 20""", params)
        return {"major_matches": base, "top_schools": schools,
                "catalog_status": "available" if base else "missing",
                "source_note": "目录未覆盖的专业仍可查询原始招生记录；未补造专业代码、学位或介绍。"}

    def compare_data(self, institutions, major_keyword, year, compare_items=None):
        items = [{"institution": name(x.get("institution")), "major": name(x.get("major"))}
                 for x in compare_items or [] if x.get("institution") and x.get("major")]
        schools = sorted({x["institution"] for x in items}) if items else [name(x) for x in institutions]
        params = {"institutions": schools, "items": items, "kw": name(major_keyword), "year": year, "dataset": DATASET_ID}
        selected = """i.name IN $institutions AND ($kw='' OR p.name CONTAINS $kw)
          AND (size($items)=0 OR any(it IN $items WHERE it.institution=i.name AND it.major=p.name))"""
        trend = self.q(f"""MATCH (i:Institution)-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p:AdmissionProgram)
          WHERE {selected} AND o.dataset_id=$dataset AND o.province='浙江' AND o.year <= $year
            AND coalesce(o.conflicting,false)=false
          RETURN i.name AS institution,p.name AS major,o.year AS year,o.min_score AS avg_min_score,
          o.min_rank AS avg_min_rank,o.source_file AS source_file,o.source_row AS source_row
          ORDER BY institution,major,year""", params)
        plans = self.q(f"""MATCH (i:Institution)-[:HAS_PLAN]->(f:PlanFact)-[:FOR_PROGRAM]->(p:AdmissionProgram)
          WHERE {selected} AND f.dataset_id=$dataset AND f.province='浙江' AND f.year <= $year
          WITH i,p,f.year AS year,collect(f) AS facts
          RETURN i.name AS institution,p.name AS major,year,
          CASE WHEN size(facts)=1 THEN facts[0].plan_count ELSE null END AS avg_plan_count,
          size(facts)>1 AS plan_ambiguous""", params)
        by_key = {(r["institution"], r["major"], r["year"]): r for r in trend}
        for row in plans:
            key = row["institution"], row["major"], row["year"]
            by_key.setdefault(key, {"institution": key[0], "major": key[1], "year": key[2], "avg_min_score": None, "avg_min_rank": None}).update(row)
        inst_sat = self.q("""MATCH (i:Institution)-[:HAS_INST_SAT]->(s:InstitutionSatisfaction)
          WHERE i.name IN $institutions RETURN i.name AS institution,s.overall AS overall,
          s.environment AS environment,s.life AS life""", params)
        major_sat = self.q("""MATCH (i:Institution)-[:HAS_MAJOR_SAT]->(s:MajorSatisfaction)
          WHERE i.name IN $institutions AND ($kw='' OR s.major_name CONTAINS $kw)
          AND (size($items)=0 OR any(it IN $items WHERE it.institution=i.name AND it.major=s.major_name))
          RETURN i.name AS institution,s.major_name AS major,s.overall AS overall,
          s.employment AS employment,s.teaching AS teaching,s.condition AS condition LIMIT 100""", params)
        return {"trend": sorted(by_key.values(), key=lambda r: (r["institution"], r["major"], r["year"])),
                "institution_satisfaction": inst_sat, "major_satisfaction": major_sat,
                "source_province": "浙江", "dataset_id": DATASET_ID}

    def major_l1_list(self):
        return self.q("MATCH (m:MajorL1) RETURN m.name AS name,m.code AS code,m.norm_name AS norm_name ORDER BY code,name")

    def major_l2_list(self, l1_norm_name):
        return self.q("""MATCH (m:MajorL2)-[:BELONGS_TO]->(:MajorL1 {norm_name:$name})
          RETURN m.name AS name,m.code AS code,m.norm_name AS norm_name ORDER BY code,name""", {"name": name(l1_norm_name)})

    def major_l3_list(self, l2_norm_name):
        return self.q("""MATCH (m:MajorL3)-[:BELONGS_TO]->(:MajorL2 {norm_name:$name})
          RETURN m.name AS name,m.code AS code,m.norm_name AS norm_name,m.degree AS degree,
          m.major_type AS major_type ORDER BY code,name""", {"name": name(l2_norm_name)})

    def major_details_batch(self, majors):
        details = self.q("""MATCH (m:MajorL3) WHERE m.name IN $names
          OPTIONAL MATCH (m)-[:BELONGS_TO]->(l2:MajorL2)-[:BELONGS_TO]->(l1:MajorL1)
          OPTIONAL MATCH (i:Institution)-[:OFFERS_PROGRAM]->(:AdmissionProgram)-[:MAPS_TO]->(m)
          RETURN m.name AS major,m.code AS code,m.degree AS degree,m.major_type AS major_type,
          m.intro AS source_intro,m.source_file AS source_file,l2.name AS l2_name,l1.name AS l1_name,
          count(DISTINCT i) AS institution_count ORDER BY institution_count DESC""", {"names": [name(x) for x in majors]})
        found = {x["major"] for x in details}
        missing = [name(x) for x in majors if name(x) not in found]
        if missing:
            rows = self.q("""MATCH (i:Institution)-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p:AdmissionProgram)
              WHERE p.name IN $names AND o.dataset_id=$dataset AND coalesce(o.conflicting,false)=false
              RETURN p.name AS major,count(DISTINCT i) AS institution_count,
                head(collect(DISTINCT o.source_file)) AS source_file""", {"names": missing,"dataset":DATASET_ID})
            for row in rows:
                row.update(catalog_missing=True, source_intro="原始招生表中存在该专业；专业目录未覆盖，没有可用的培养简介、专业代码和学位信息。")
            details.extend(rows)
        return details

    def ai_context(self, question, preferences):
        """Retrieve trusted facts; browser-supplied facts never become graph evidence."""
        candidate_summary = {}
        schools = preferences.get("target_institutions", [])
        majors = preferences.get("majors", [])
        schools = [name(x) for x in schools[:10] if isinstance(x, str)] if isinstance(schools, list) else []
        majors = [name(x) for x in majors[:10] if isinstance(x, str)] if isinstance(majors, list) else []
        year = preferences.get("year", 2024)
        year = max(2019, min(year, 2024)) if type(year) is int else 2024
        rank = preferences.get("rank", 0)
        rank = rank if type(rank) is int and 0 < rank < 10000000 else 0
        params = {"schools": schools, "majors": majors, "question": question, "year": year,
                  "rank": rank, "dataset": DATASET_ID}
        mentioned_majors = self.q("""MATCH (m:MajorL3)
          WHERE m.name IN $majors OR $question CONTAINS m.name
          RETURN DISTINCT m.name AS name LIMIT 10""", params)
        majors = list(dict.fromkeys(majors + [x["name"] for x in mentioned_majors]))[:10]
        params["majors"] = majors
        matched = self.q("""MATCH (i:Institution)
          WHERE i.name IN $schools OR $question CONTAINS i.name
          RETURN i.name AS name LIMIT 10""", params)
        params["schools"] = [x["name"] for x in matched]
        # Without an institution hint, retrieve a small indexed rank window.
        if params["schools"] or rank:
            facts = self.q("""MATCH (o:OfferFact {dataset_id:$dataset,province:'浙江',year:$year})
              WHERE coalesce(o.conflicting,false)=false
                AND (size($schools)>0 OR (o.min_rank >= $rank-2000 AND o.min_rank <= $rank+2000))
              MATCH (i:Institution)-[:HAS_OFFER]->(o)-[:FOR_PROGRAM]->(p:AdmissionProgram)
              WHERE (size($schools)=0 OR i.name IN $schools)
                AND (size($majors)=0 OR any(m IN $majors WHERE p.name CONTAINS m))
              RETURN i.name AS institution,p.name AS major,o.year AS year,o.min_score AS min_score,
                o.min_rank AS min_rank,o.source_file AS source_file,o.source_sheet AS source_sheet,
                o.source_row AS source_row,o.fact_id AS fact_id
              ORDER BY CASE WHEN $rank>0 THEN abs(o.min_rank-$rank) ELSE o.min_rank END LIMIT 12""", params)
        else:
            facts = []
        if rank and not params["schools"]:
            from app.models import RecommendationRequest
            from app.services.recommender import RecommenderService
            locations = preferences.get("provinces", [])
            locations = [x for x in locations if isinstance(x, str)][:10] if isinstance(locations, list) else []
            combo = preferences.get("subject_combo", "")
            window = preferences.get("rank_window", 5000)
            window = max(50, min(window, 100000)) if type(window) is int else 5000
            rows = RecommenderService(self.client)._fetch_candidates(RecommendationRequest(
                rank=rank, year=year, majors=majors, provinces=locations,
                subject_combo=combo if isinstance(combo, str) else "", rank_window=window,
                candidate_scope="window" if preferences.get("candidate_scope") == "window" else "all"))
            from app.graph_data import selected_subjects
            confirmed = [x for x in rows if x["subject_eligibility"] == "eligible"]
            pending = [x for x in rows if x["subject_eligibility"] == "unknown"]
            facts = (confirmed if len(selected_subjects(combo or "")) == 3 else rows)[:12]
            candidate_summary = {"confirmed_count":len(confirmed), "pending_count":len(pending),
                                 "provided_fact_count":len(facts),
                                 "candidate_scope":"window" if preferences.get("candidate_scope") == "window" else "all",
                                 "note":"上下文仅节选部分候选；完整结果见推荐列表，不得把节选数量说成全部候选数量。"}
        return {"dataset_id": DATASET_ID, "source_province": "浙江", "reference_year": year,
                "available_years": [2019, 2020, 2021, 2022, 2023, 2024],
                "limitations": ["原表未标注批次和科类", "历史资料不代表当前招生计划", "无一分一段表"],
                "historical_offers": facts, "candidate_summary":candidate_summary,
                "catalog_majors": self.major_details_batch(majors) if majors else []}

    def recommend_item_detail(self, institution, major, year, fact_id=""):
        params = {"institution": name(institution), "major": name(major), "year": year,
                  "fact_id": fact_id, "dataset": DATASET_ID}
        base = self.q("""MATCH (i:Institution {norm_name:$institution})-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p:AdmissionProgram)
          WHERE p.name=$major AND o.year=$year AND o.dataset_id=$dataset AND o.province='浙江'
            AND ($fact_id='' OR o.fact_id=$fact_id) AND coalesce(o.conflicting,false)=false
          OPTIONAL MATCH (o)-[:HAS_PLAN]->(plan:PlanFact)
          RETURN i.name AS institution,p.name AS major,p.program_id AS program_id,o.fact_id AS fact_id,
          o.year AS year,coalesce(plan.level,i.level) AS level,coalesce(plan.school_nature,i.school_nature) AS school_nature,
          i.website AS website,o.min_score AS min_score,o.min_rank AS min_rank,plan.plan_count AS plan_count,
          plan.subject_requirement_raw AS subject_requirement,plan.subject_requirement_scope AS subject_requirement_scope,
          plan IS NOT NULL AS plan_matched,
          o.source_file AS source_file,o.source_sheet AS source_sheet,o.source_row AS source_row,
          plan.source_file AS plan_source,plan.source_row AS plan_source_row LIMIT 1""", params)
        inst_sat = self.q("""MATCH (:Institution {norm_name:$institution})-[:HAS_INST_SAT]->(s:InstitutionSatisfaction)
          RETURN s.overall AS overall,s.environment AS environment,s.life AS life,s.source_file AS source_file LIMIT 1""", params)
        major_sat = self.q("""MATCH (:Institution {norm_name:$institution})-[:HAS_MAJOR_SAT]->(s:MajorSatisfaction)
          WHERE s.major_name=$major RETURN s.overall AS overall,s.employment AS employment,
          s.teaching AS teaching,s.condition AS condition,s.source_file AS source_file LIMIT 1""", params)
        evaluation = self.q("""MATCH (:Institution {norm_name:$institution})-[:HAS_SUBJECT_EVAL]->(e:SubjectEvalFact)
          RETURN e.subject_name AS subject_name,e.grade AS grade,e.round AS round,e.source_file AS source_file
          ORDER BY grade LIMIT 30""", params)
        employment = self.q("""MATCH (:Institution {norm_name:$institution})-[:HAS_EMPLOYMENT]->(f:EmploymentFact)-[:HAS_REGION_FLOW]->(r:EmploymentFlowItem)
          RETURN r.name AS name,r.pct AS pct,f.source_file AS source_file ORDER BY pct DESC""", params)
        first = base[0] if base else {}
        info = subject_requirement_info(first.get("subject_requirement"), plan_matched=first.get("plan_matched") is True)
        if first:
            first.update(subject_requirement_kind=info["kind"], subject_requirement_display=info["display"])
        return {"base": first, "level_text": " ".join(str(first[x]) for x in ["level", "school_nature"] if first.get(x)) or "暂无",
                "rankings": self._rankings(institution, year), "subject_eval_items": evaluation,
                "subject_eval_text": "；".join(f"{x['subject_name']}({x['grade']})" for x in evaluation) or "暂无",
                "institution_satisfaction": inst_sat[0] if inst_sat else {},
                "major_satisfaction": major_sat[0] if major_sat else {}, "employment_flow": employment,
                "source_province": "浙江", "dataset_id": DATASET_ID}

    def admission_history(self, institution, major, year=2024):
        return self.q("""MATCH (:Institution {norm_name:$institution})-[:HAS_OFFER]->(o:OfferFact)-[:FOR_PROGRAM]->(p:AdmissionProgram {name:$major})
          WHERE o.dataset_id=$dataset AND o.province='浙江' AND o.year <= $year
            AND coalesce(o.conflicting,false)=false AND o.min_rank IS NOT NULL
          RETURN o.year AS year,o.min_rank AS min_rank,o.min_score AS min_score,
          o.source_file AS source_file,o.source_row AS source_row ORDER BY year""",
                      {"institution": name(institution), "major": name(major), "dataset": DATASET_ID, "year": year})

    def peer_insights(self, rank, provinces, majors, limit=10, year=2024, subject_combo="", rank_window=5000, candidate_scope="all"):
        from app.models import RecommendationRequest
        from app.services.recommender import RecommenderService
        rows = RecommenderService(self.client)._fetch_candidates(RecommendationRequest(
            rank=rank, provinces=provinces, majors=majors, year=year,
            subject_combo=subject_combo, rank_window=rank_window, candidate_scope=candidate_scope))
        from app.graph_data import selected_subjects
        if len(selected_subjects(subject_combo)) == 3:
            rows = [x for x in rows if x["subject_eligibility"] == "eligible"]
        by_major, by_province = {}, {}
        for row in rows:
            by_major.setdefault(row["major"], []).append(row)
            if row.get("destination_province"):
                by_province.setdefault(row["destination_province"], set()).add(row["institution"])
        majors_rows = [{"major": major, "inst_count": len({x["institution"] for x in items}),
                        "avg_rank": sum(x["min_rank"] for x in items)/len(items)} for major, items in by_major.items()]
        majors_rows.sort(key=lambda x: (-x["inst_count"], x["major"]))
        province_rows = [{"province": p, "inst_count": len(items)} for p, items in by_province.items()]
        province_rows.sort(key=lambda x: (-x["inst_count"], x["province"]))
        ranks = sorted(x["min_rank"] for x in rows)
        def percentile(fraction):
            if not ranks:
                return None
            index = (len(ranks)-1)*fraction
            lower = int(index)
            return ranks[lower] + (ranks[min(lower+1,len(ranks)-1)]-ranks[lower])*(index-lower)
        distribution = {"total_candidates": len(rows), "p25": percentile(.25),
                        "p50": percentile(.5), "p75": percentile(.75)}
        return {"popular_majors": majors_rows[:limit], "popular_provinces": province_rows[:limit],
                "rank_distribution": distribution,
                "context": {"source_province": "浙江", "year": year},
                "source_note": "这是当前筛选条件下的历史录取候选统计，不是考生实际选择或同伴行为数据。"}

    def graph_explorer_data(self, keyword="", node_type="all", limit=50):
        if node_type not in {"all", "institution", "major"}:
            raise ValueError("不支持的节点类型")
        params = {"kw": name(keyword), "limit": max(10, min(limit, 200)), "edge_limit": min(limit * 3, 400)}
        nodes, edges = {}, {}

        def node(identity, title, category, **props):
            nodes[identity] = {"id": identity, "name": title, "category": category, **props}

        def edge(source, target, label):
            edges[source, target, label] = {"source": source, "target": target, "label": label}

        seeds = self.q("""MATCH (i:Institution) WHERE $kw='' OR i.name CONTAINS $kw
          RETURN i.name AS name,i.province AS province,i.city AS city ORDER BY name LIMIT $limit""", params) if node_type in {"all", "institution"} else []
        for row in seeds:
            node("inst_" + row["name"], row["name"], "院校", province=row.get("province"), city=row.get("city"))
        params["schools"] = [row["name"] for row in seeds]
        programs = self.q("""MATCH (i:Institution)-[:OFFERS_PROGRAM]->(p:AdmissionProgram)
          WHERE (size($schools)>0 AND i.name IN $schools) OR ($kw<>'' AND p.name CONTAINS $kw)
          OPTIONAL MATCH (p)-[:MAPS_TO]->(m:MajorL3)-[:BELONGS_TO]->(l2:MajorL2)-[:BELONGS_TO]->(l1:MajorL1)
          RETURN i.name AS institution,i.province AS province,p.program_id AS program_id,p.name AS program,
          m.major_id AS major_id,m.name AS major,l2.name AS l2,l1.name AS l1,l2.norm_name AS l2_id,l1.norm_name AS l1_id
          ORDER BY institution,program LIMIT $edge_limit""", params)
        for row in programs:
            inst = "inst_" + row["institution"]; program = "program_" + row["program_id"]
            node(inst, row["institution"], "院校", province=row["province"])
            node(program, row["program"], "招生专业", institution=row["institution"], l1=row["l1"], l2=row["l2"])
            edge(inst, program, "开设招生专业")
            if row["major_id"]:
                major = "major_" + row["major_id"]
                node(major, row["major"], "专业", l1=row["l1"], l2=row["l2"])
                edge(program, major, "对应目录专业")
                if row["l2"]:
                    l2 = "l2_" + row["l2_id"]; node(l2, row["l2"], "专业类"); edge(major, l2, "所属专业类")
                    if row["l1"]:
                        l1 = "l1_" + row["l1_id"]; node(l1, row["l1"], "专业门类"); edge(l2, l1, "所属门类")
        if node_type in {"all", "major"}:
            catalog = self.q("""MATCH (m:MajorL3) WHERE $kw<>'' AND m.name CONTAINS $kw
              OPTIONAL MATCH (m)-[:BELONGS_TO]->(l2:MajorL2)-[:BELONGS_TO]->(l1:MajorL1)
              RETURN m.major_id AS id,m.name AS name,l2.name AS l2,l1.name AS l1 LIMIT $limit""", params)
            for row in catalog:
                node("major_" + row["id"], row["name"], "专业", l1=row["l1"], l2=row["l2"])
        if node_type == "all":
            params["schools"] = [n["name"] for n in nodes.values() if n["category"] == "院校"]
            regions = self.q("""MATCH (i:Institution)-[:HAS_EMPLOYMENT]->(:EmploymentFact)-[:HAS_REGION_FLOW]->(f:EmploymentFlowItem)
              WHERE i.name IN $schools RETURN i.name AS institution,f.name AS region,f.pct AS pct
              ORDER BY pct DESC LIMIT $edge_limit""", params)
            for row in regions:
                region = "region_" + row["region"]
                node(region, row["region"], "就业地区")
                edge("inst_" + row["institution"], region, f"签约占比 {row['pct']}%")
        return {"nodes": list(nodes.values()), "edges": list(edges.values()), "dataset_id": DATASET_ID}
