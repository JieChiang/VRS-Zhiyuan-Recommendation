"""Rebuild the application graph exclusively from data/*.xlsx, in bounded batches.

python scripts/rebuild_graph.py --sample 3  # inspect a few rows, no database writes
python scripts/rebuild_graph.py --replace   # explicitly replace the configured project graph
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.graph_data import DATASET_ID, catalog_code, excel_records, key, name, number, subject_options, text
from app.neo4j_http import Neo4jHttpClient


class GraphBuilder:
    def __init__(self, client: Neo4jHttpClient, data: Path, batch_size: int = 500):
        self.client, self.data, self.batch_size = client, data, batch_size
        self.stats = Counter()
        self.subjects = Counter()
        self.issues = []
        self.buffers = defaultdict(list)
        self.queries = {}
        self.seen = defaultdict(set)
        self.file_ids = {}

    def run(self, query, params=None):
        return self.client.run_rows(query, params or {})

    def issue(self, message):
        self.stats["issues"] += 1
        if len(self.issues) < 100:
            self.issues.append(message)

    def emit(self, kind, query, row):
        identity = row.get("id")
        if identity and identity in self.seen[kind]:
            self.stats[f"{kind}_duplicates"] += 1
            return
        if identity:
            self.seen[kind].add(identity)
        self.queries[kind] = query
        self.buffers[kind].append(row)
        self.stats[kind] += 1
        if len(self.buffers[kind]) >= self.batch_size:
            self.flush(kind)

    def flush(self, kind=None):
        for item in [kind] if kind else list(self.buffers):
            rows = self.buffers[item]
            if rows:
                self.client.run(self.queries[item], {"rows": rows})
                rows.clear()

    def records(self, path):
        source = self.file_ids[path.name]
        for sheet, rownum, row in excel_records(path):
            self.stats[f"source_rows:{path.name}:{sheet}"] += 1
            yield row, {"source_id": source, "source_file": path.name, "source_sheet": sheet, "source_row": rownum}

    def institution(self, school, props=None):
        school = name(school)
        if not school:
            return ""
        props = {k: v for k, v in (props or {}).items() if v not in (None, "")}
        self.emit("institution_updates", """UNWIND $rows AS r
          MERGE (i:Institution {norm_name:r.school}) SET i.name=r.school, i += r.props""",
                  {"school": school, "props": props})
        return school

    def validate_sources(self):
        files = sorted(self.data.glob("*.xlsx"))
        if not files:
            raise RuntimeError("data 目录中没有 Excel 原始数据，拒绝删除图谱")
        required = {
            "大学专业基础信息.xlsx": {"三级专业名称", "三级专业代码", "一级专业名称", "二级专业名称"},
            "专业分数线.xlsx": {"院校名称", "专业名称"},
            "招生计划.xlsx": {"院校名称", "专业名称", "选考科目"},
            "院校满意度.xlsx": {"院校名称", "综合满意度"},
            "专业满意度.xlsx": {"院校名称", "专业名称", "综合满意度"},
            "院校就业流向.xlsx": {"院校名称", "毕业生签约地区流向"},
            "第四轮全国高校学科评估结果.xlsx": {"一级学科", "等级", "院校代码及名称"},
        }
        missing = set(required) - {p.name for p in files}
        if missing:
            raise RuntimeError(f"缺少必要原始资料，拒绝删除图谱：{sorted(missing)}")
        if not any("排名" in p.name or "软科" in p.name for p in files):
            raise RuntimeError("缺少排名资料，拒绝删除图谱")
        # Verify every workbook header before the explicit destructive stage.
        for path in files:
            sample = next(excel_records(path, 1), None)
            if sample is None or not required.get(path.name, set()) <= set(sample[2]):
                raise RuntimeError(f"原始资料为空或列名不匹配，拒绝删除图谱：{path.name}")
        return files

    def prepare(self, replace=False):
        files = self.validate_sources()
        existing = self.run("MATCH (n) RETURN count(n) AS count")[0]["count"]
        if existing and not replace:
            raise RuntimeError("目标库非空；重建须显式传入 --replace")
        if replace:
            for query in ["MATCH ()-[r]->() WITH r LIMIT 10000 DELETE r RETURN count(*) AS count", "MATCH (n) WITH n LIMIT 10000 DELETE n RETURN count(*) AS count"]:
                while self.run(query)[0]["count"]:
                    pass
            for row in self.run("SHOW CONSTRAINTS YIELD name RETURN name"):
                escaped = row["name"].replace("`", "``")
                self.client.run(f"DROP CONSTRAINT `{escaped}` IF EXISTS")
            for row in self.run("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name"):
                escaped = row["name"].replace("`", "``")
                self.client.run(f"DROP INDEX `{escaped}` IF EXISTS")
        for label, field in [("Institution", "norm_name"), ("MajorL1", "norm_name"), ("MajorL2", "norm_name"), ("MajorL3", "major_id"), ("AdmissionProgram", "program_id"), ("OfferFact", "fact_id"), ("PlanFact", "fact_id"), ("SourceFile", "source_id"), ("Dataset", "dataset_id"), ("Year", "value"), ("Province", "name"), ("RankingFact", "fact_id"), ("SubjectEvalFact", "fact_id"), ("InstitutionSatisfaction", "fact_id"), ("MajorSatisfaction", "fact_id"), ("EmploymentFact", "fact_id"), ("EmploymentFlowItem", "fact_id"), ("EmployerTypeItem", "fact_id"), ("InstitutionProfile", "fact_id")]:
            self.client.run(f"CREATE CONSTRAINT vrs_{label}_{field} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{field} IS UNIQUE")
        for label, fields in [("OfferFact", "dataset_id,province,year,min_rank"), ("OfferFact", "program_id,year"), ("PlanFact", "program_id,year"), ("MajorL3", "name"), ("AdmissionProgram", "name"), ("Institution", "name")]:
            expression = ",".join("n." + field for field in fields.split(","))
            self.client.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON ({expression})")
        self.client.run("""MERGE (d:Dataset {dataset_id:$id}) SET d.name='浙江高考志愿参考数据',
          d.province='浙江', d.category='原表未标注', d.batch='原表未标注', d.schema_version=2,
          d.scope_source='用户确认生源为浙江', d.import_status='building', d.built_at=$now
          MERGE (p:Province {name:'浙江'}) MERGE (d)-[:FOR_APPLICANTS_IN]->(p)""",
                        {"id": DATASET_ID, "now": datetime.now(timezone.utc).isoformat()})
        for path in files:
            with path.open("rb") as handle:
                sha = hashlib.file_digest(handle, "sha256").hexdigest()
            self.file_ids[path.name] = sha
            self.client.run("""MATCH (d:Dataset {dataset_id:$dataset})
              MERGE (s:SourceFile {source_id:$id}) SET s.name=$name,s.sha256=$id,s.relative_path=$path
              MERGE (d)-[:HAS_SOURCE]->(s)""", {"dataset": DATASET_ID, "id": sha, "name": path.name, "path": f"data/{path.name}"})

    def catalog(self):
        for row, source in self.records(self.data / "大学专业基础信息.xlsx"):
            major_name = name(row.get("三级专业名称"))
            if not major_name:
                continue
            raw_code = text(row.get("三级专业代码")).upper()
            code, corrected = catalog_code(raw_code, row.get("专业描述"))
            if corrected:
                self.issue(f"专业代码依据同一行描述修复：{major_name} {raw_code} → {code}")
            elif not re.fullmatch(r"\d{6}[TK]{0,2}", code):
                self.issue(f"保留未规范代码：{major_name} {raw_code}")
            kind = text(row.get("类型"))
            major_id = key(kind, code, major_name)
            props = {**source, "name": major_name, "norm_name": major_name, "code": code,
                     "code_raw": raw_code, "major_type": kind, "degree": text(row.get("授予学位")),
                     "intro": text(row.get("专业描述")), "similar_majors_raw": text(row.get("相近专业"))}
            l1 = name(row.get("一级专业名称")); l2 = name(row.get("二级专业名称"))
            self.emit("catalog", """UNWIND $rows AS r
              MERGE (m:MajorL3 {major_id:r.id}) SET m += r.props
              MERGE (a:MajorL1 {norm_name:r.l1_key}) SET a.name=r.l1,a.code=r.c1,a.major_type=r.kind
              MERGE (b:MajorL2 {norm_name:r.l2_key}) SET b.name=r.l2,b.code=r.c2,b.major_type=r.kind
              MERGE (m)-[:BELONGS_TO]->(b) MERGE (b)-[:BELONGS_TO]->(a)
              WITH m,r MATCH (s:SourceFile {source_id:r.props.source_id}) MERGE (m)-[:FROM_SOURCE]->(s)""",
                      {"id": major_id, "props": props, "l1": l1 or "未分类", "l2": l2 or "未分类", "c1": text(row.get("一级专业代码")), "c2": text(row.get("二级专业代码")), "kind": kind, "l1_key": key(kind,text(row.get("一级专业代码")),l1), "l2_key": key(kind,text(row.get("二级专业代码")),l2)})
        self.flush()

    def rankings(self):
        for path in sorted(self.data.glob("*.xlsx")):
            if "排名" not in path.name and "软科" not in path.name:
                continue
            year = int(re.search(r"20\d{2}", path.name)[0])
            for row, source in self.records(path):
                school = name(row.get("院校名称") or row.get("学校名称"))
                if not school:
                    continue
                province = name(row.get("所在省市") or row.get("省市") or row.get("省份") or row.get("所在省份") or row.get("地区"))
                props = {"province": province, "school_type": text(row.get("院校类型") or row.get("学校类型") or row.get("类型")), "level": text(row.get("办学层次") or row.get("办学类型")), "school_nature": text(row.get("办学性质")), "metadata_source": path.name}
                for field, column in [("is_985", "985"), ("is_211", "211"), ("is_shuangyiliu", "双一流"), ("is_qiangji", "强基计划")]:
                    if text(row.get(column)):
                        props[field] = text(row[column])
                self.institution(school, props)
                rank = text(row.get("排名") or row.get(f"{year}排名"))
                if not rank:
                    self.emit("institution_profiles", self.fact_query("InstitutionProfile", "HAS_PROFILE"), {"id": key(source["source_id"], source["source_sheet"], school), "school": school, "props": {**source, "year": year, "raw_json": json.dumps(row, ensure_ascii=False, default=str)}})
                    continue
                list_type = text(row.get("榜") or row.get("榜单")) or "软科"
                if year == 2022 and "总榜" not in source["source_sheet"]:
                    list_type = f"软科-{source['source_sheet']}"
                self.emit("rankings", self.fact_query("RankingFact", "HAS_RANKING", year=True), {"id": key(school, year, list_type), "school": school, "props": {**source, "year": year, "list_type": list_type, "rank": rank, "world_rank": text(row.get("世界排名")), "score": number(row.get("总得分") if "总得分" in row else row.get("综合得分") if "综合得分" in row else row.get("总分") if "总分" in row else row.get("分数"))}})
        self.flush()

    @staticmethod
    def fact_query(label, relationship, year=False):
        query = f"""UNWIND $rows AS r
          MERGE (i:Institution {{norm_name:r.school}}) ON CREATE SET i.name=r.school
          MERGE (f:{label} {{fact_id:r.id}}) SET f += r.props
          MERGE (i)-[:{relationship}]->(f)
          WITH f,r MATCH (s:SourceFile {{source_id:r.props.source_id}}) MERGE (f)-[:FROM_SOURCE]->(s)"""
        if year:
            query += " WITH f,r MERGE (y:Year {value:r.props.year}) MERGE (f)-[:IN_YEAR]->(y)"
        return query

    def satisfaction_and_evaluation(self):
        for row, source in self.records(self.data / "院校满意度.xlsx"):
            school = self.institution(row.get("院校名称"), {"province": name(row.get("院校所在地"))})
            if not school: continue
            self.emit("institution_satisfaction", self.fact_query("InstitutionSatisfaction", "HAS_INST_SAT"), {"id": key(school, source["source_id"]), "school": school, "props": {**source, "overall": number(row.get("综合满意度")), "environment": number(row.get("环境满意度")), "life": number(row.get("生活满意度")), "overall_votes": number(row.get("综合满意度投票人数"), True), "vote_columns_note": "环境与生活投票列名存在交叉，未自动解释"}})
        for row, source in self.records(self.data / "专业满意度.xlsx"):
            school = name(row.get("院校名称")); major = name(row.get("专业名称"))
            if not school or not major: continue
            props = {**source, "major_name": major, "level": text(row.get("层次"))}
            for field, col in [("overall", "综合满意度"), ("employment", "就业满意度"), ("teaching", "教学质量满意度"), ("condition", "办学条件满意度")]:
                props[field] = number(row.get(col)); props[field + "_votes"] = number(row.get(col + "投票人数"), True)
            self.emit("major_satisfaction", self.fact_query("MajorSatisfaction", "HAS_MAJOR_SAT"), {"id": key(school, major, props["level"], *[props.get(f) for f in ["overall", "employment", "teaching", "condition"]]), "school": school, "props": props})
        for row, source in self.records(self.data / "第四轮全国高校学科评估结果.xlsx"):
            school_raw = text(row.get("院校代码及名称")); match = re.match(r"(\d{5})\s*(.+)", school_raw)
            school = name(match[2] if match else school_raw)
            if not school: continue
            subject = text(row.get("一级学科")); sm = re.match(r"(\d+)\s*(.+)", subject)
            self.emit("subject_evaluations", self.fact_query("SubjectEvalFact", "HAS_SUBJECT_EVAL"), {"id": key(school, subject, text(row.get("等级"))), "school": school, "props": {**source, "round": 4, "school_code": match[1] if match else "", "subject_code": sm[1] if sm else "", "subject_name": sm[2] if sm else subject, "grade": text(row.get("等级"))}})
        self.flush()

    def employment(self):
        for row, source in self.records(self.data / "院校就业流向.xlsx"):
            school = self.institution(row.get("院校名称"), {"province": name(row.get("省份")), "city": name(row.get("城市"))})
            if not school: continue
            fact_id = key(school, source["source_id"])
            self.emit("employment", self.fact_query("EmploymentFact", "HAS_EMPLOYMENT"), {"id": fact_id, "school": school, "props": {**source, "region_flow_raw": text(row.get("毕业生签约地区流向")), "employer_type_raw": text(row.get("毕业生签约单位性质")), "main_employers": text(row.get("主要签约单位")), "main_employers_note": text(row.get("主要签约单位说明")), "year_note": "原表未提供统计年份"}})
            for column, label, relation in [("毕业生签约地区流向", "EmploymentFlowItem", "HAS_REGION_FLOW"), ("毕业生签约单位性质", "EmployerTypeItem", "HAS_EMPLOYER_TYPE")]:
                for item_name, pct in re.findall(r"([^:：、;；\n,，%]+)[:：]\s*(\d+(?:\.\d+)?)\s*%", text(row.get(column))):
                    self.emit(label, f"""UNWIND $rows AS r MERGE (f:EmploymentFact {{fact_id:r.parent}})
                      MERGE (v:{label} {{fact_id:r.id}}) SET v.name=r.name,v.pct=r.pct
                      MERGE (f)-[:{relation}]->(v)""", {"id": key(fact_id, label, name(item_name)), "parent": fact_id, "name": text(item_name), "pct": float(pct)})
            # Parent facts must exist before the child-item batch can be committed.
            if len(self.buffers["employment"]) >= self.batch_size - 1:
                self.flush("employment")
        self.flush("employment")
        self.flush()

    def programs_and_facts(self, filename, is_plan):
        fact_label = "PlanFact" if is_plan else "OfferFact"
        relationship = "HAS_PLAN" if is_plan else "HAS_OFFER"
        query = f"""UNWIND $rows AS r
          MERGE (i:Institution {{norm_name:r.school}}) ON CREATE SET i.name=r.school
          MERGE (p:AdmissionProgram {{program_id:r.program_id}}) SET p.name=r.major,p.institution=r.school
          MERGE (i)-[:OFFERS_PROGRAM]->(p)
          MERGE (f:{fact_label} {{fact_id:r.id}}) SET f += r.props, f.program_id=r.program_id
          MERGE (i)-[:{relationship}]->(f) MERGE (f)-[:FOR_PROGRAM]->(p)
          MERGE (y:Year {{value:r.props.year}}) MERGE (f)-[:IN_YEAR]->(y)
          MERGE (province:Province {{name:r.props.province}}) MERGE (f)-[:IN_PROVINCE]->(province)
          WITH f,r MATCH (s:SourceFile {{source_id:r.props.source_id}}) MERGE (f)-[:FROM_SOURCE]->(s)
          WITH f MERGE (d:Dataset {{dataset_id:'{DATASET_ID}'}}) MERGE (f)-[:IN_DATASET]->(d)"""
        for row, source in self.records(self.data / filename):
            school = name(row.get("院校名称")); major = name(row.get("专业名称"))
            if not school or not major:
                self.stats["empty_identity_rows"] += 1
                continue
            program_id = key(school, major)
            years = sorted({int(y) for h in row for y in re.findall(r"(20\d{2})年", h)})
            requirement = text(row.get("选考科目"))
            if is_plan:
                self.subjects[requirement] += 1
                self.institution(school, {"school_nature": text(row.get("办学性质"))})
            for year in years:
                props = {**source, "year": year, "province": "浙江", "dataset_id": DATASET_ID}
                if is_plan:
                    count = number(row.get(f"{year}年计划人数"), True)
                    if count is None: continue
                    props.update(plan_count=count, level=text(row.get("层次")), school_nature=text(row.get("办学性质")), subject_requirement_raw=requirement, subject_requirement_scope="原表行级要求，未按年区分", source_institution_code=text(row.get("院校代码")), source_major_code=text(row.get("专业代码")), tuition_raw=text(row.get("学费")), duration_raw=text(row.get("学制")), remark=text(row.get("备注")))
                    identity = key(program_id, year, props["source_institution_code"], props["source_major_code"], count, requirement, props["remark"], props["tuition_raw"], props["duration_raw"], props["level"], props["school_nature"])
                else:
                    score = number(row.get(f"{year}年最低分"))
                    rank = number(row.get(f"{year}年最低位次"), True, True)
                    if score is None and rank is None:
                        self.stats["empty_offer_years"] += 1
                        continue
                    props.update(min_score=score, min_rank=rank)
                    identity = key(program_id, year, score, rank)
                self.emit("plans" if is_plan else "offers", query, {"id": identity, "school": school, "major": major, "program_id": program_id, "props": props})
        self.flush()

    def link_and_validate(self):
        from app.reference_data import apply_location_supplements, apply_catalog_corrections
        apply_location_supplements(self.client)
        apply_catalog_corrections(self.client)
        self.client.run("""MATCH (p:AdmissionProgram) MATCH (m:MajorL3 {name:p.name})
          WITH p,collect(m) AS matches WHERE size(matches)=1
          FOREACH (m IN matches | MERGE (p)-[:MAPS_TO]->(m))""")
        self.client.run("""MATCH (i:Institution)-[:OFFERS_PROGRAM]->(:AdmissionProgram)-[:MAPS_TO]->(m:MajorL3)
          MERGE (i)-[:OFFERS_MAJOR]->(m)""")
        self.client.run("""MATCH (i:Institution)-[:HAS_MAJOR_SAT]->(f:MajorSatisfaction)
          MATCH (m:MajorL3 {name:f.major_name}) WHERE m.major_type=f.level
          MERGE (f)-[:FOR_MAJOR]->(m)""")
        # Equal program names are joined only within the same applicant province and year.
        self.client.run("""MATCH (p:PlanFact) WITH p.program_id AS program,p.year AS year,collect(p) AS plans
          WHERE size(plans)=1 MATCH (o:OfferFact {program_id:program,year:year})
          FOREACH (plan IN plans | MERGE (o)-[:HAS_PLAN]->(plan))""")
        self.client.run("""MATCH (o:OfferFact) WITH o.program_id AS program,o.year AS year,collect(o) AS facts
          WHERE size(facts)>1 FOREACH (f IN facts | SET f.conflicting=true)""")
        counts = self.run("MATCH (n) RETURN labels(n)[0] AS label,count(*) AS count ORDER BY label")
        audit = self.run("""MATCH (o:OfferFact) RETURN count(o) AS offers,
          count(o.min_rank) AS offers_with_rank,count(o.min_score) AS offers_with_score,
          min(o.year) AS first_year,max(o.year) AS last_year,
          count(CASE WHEN o.conflicting THEN 1 END) AS conflicting_offers""")[0]
        self.client.run("""MATCH (d:Dataset {dataset_id:$id}) SET d.import_status='ready',d.first_year=$first,
          d.last_year=$last,d.offer_count=$count""", {"id": DATASET_ID, "first": audit["first_year"], "last": audit["last_year"], "count": audit["offers"]})
        return {"nodes": counts, "audit": audit}

    def build(self, replace):
        started = time.time()
        self.prepare(replace)
        for title, action in [("专业目录", self.catalog), ("院校及排名", self.rankings), ("满意度与学科评估", self.satisfaction_and_evaluation), ("就业流向", self.employment), ("录取分数线", lambda: self.programs_and_facts("专业分数线.xlsx", False)), ("招生计划", lambda: self.programs_and_facts("招生计划.xlsx", True))]:
            print(f"导入：{title}", flush=True)
            action()
        print("建立关联并校验", flush=True)
        result = self.link_and_validate()
        report = {"dataset_id": DATASET_ID, "source_directory": "data", "source_files": self.file_ids,
                  "elapsed_seconds": round(time.time() - started, 1), "statistics": dict(self.stats),
                  "subject_requirements": dict(self.subjects), "issues_sample": self.issues, **result}
        output = ROOT / "docs" / "graph_build_report.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(output), **result}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Excel 数据目录，默认项目 data/")
    parser.add_argument("--validate", action="store_true", help="只校验文件与表头，不连接或修改数据库")
    args = parser.parse_args()
    if args.validate:
        files = GraphBuilder(None, args.data_dir).validate_sources()
        print(json.dumps({"valid":True,"files":len(files),"database_modified":False},ensure_ascii=False))
        return
    if args.sample:
        for path in sorted(args.data_dir.glob("*.xlsx")):
            rows = [{"sheet": sheet, "row": rownum, "values": values} for sheet, rownum, values in excel_records(path, args.sample)]
            print(json.dumps({"file": path.name, "samples": rows}, ensure_ascii=False, default=str))
        return
    client = Neo4jHttpClient(settings.neo4j_url, settings.neo4j_user, settings.neo4j_password, settings.neo4j_db)
    GraphBuilder(client, args.data_dir).build(args.replace)


if __name__ == "__main__":
    main()
