"""Small, source-linked metadata corrections; raw admission facts stay intact."""

LOCATION_SUPPLEMENTS = [{
    "name": "四川国际标榜职业学院",
    "city": "成都市",
    "source_url": "https://www.polus.edu.cn/wp-content/uploads/2024/03/20140321.pdf",
    "verification_url": "https://www.polus.edu.cn/polus-at-a-glance/contact",
    "note": "学校官网存档资料及联系页面均注明成都市龙泉驿区；只补充缺失城市，不推断录取校区。",
}]

# Only source-code/name inconsistencies verified against public catalog tables.
CATALOG_CORRECTIONS = [
    {"kind":"本科","code":"0702","name":"物理学类",
     "source_url":"https://www.sdzk.cn/Floadup/file/20250317/6387782010007663213616549.pdf"},
    {"kind":"本科","code":"1004","name":"公共卫生与预防医学类",
     "source_url":"https://www.cq.gov.cn/ywdt/jrcq/202603/P020260301265942063941.pdf"},
    {"kind":"本科","code":"1007","name":"药学类",
     "source_url":"https://www.cq.gov.cn/ywdt/jrcq/202603/P020260301265942063941.pdf"},
]


def apply_catalog_corrections(client):
    from app.graph_data import key
    rows = [{**r,"key":key(r["kind"],r["code"],r["name"])} for r in CATALOG_CORRECTIONS]
    corrected = client.run_rows("""UNWIND $rows AS row
      MATCH (m:MajorL3)-[rel:BELONGS_TO]->(old:MajorL2)-[:BELONGS_TO]->(field:MajorL1)
      WHERE m.major_type=row.kind AND old.major_type=row.kind AND old.code=row.code AND old.name<>row.name
      MERGE (canonical:MajorL2 {norm_name:row.key})
      SET canonical.name=row.name,canonical.code=row.code,canonical.major_type=row.kind
      MERGE (canonical)-[:BELONGS_TO]->(field)
      SET m.category_name_raw=coalesce(m.category_name_raw,old.name),
          m.category_correction_source=row.source_url,m.category_correction_note='依据专业类代码核验修正原表分类名，原始名称已保留'
      DELETE rel
      MERGE (m)-[:BELONGS_TO]->(canonical)
      RETURN m.name AS major,m.code AS code,m.source_row AS source_row,
        m.category_name_raw AS original_category,canonical.name AS category,row.source_url AS evidence_url""", {"rows":rows})
    client.run_rows("""UNWIND $rows AS row MATCH (old:MajorL2)
      WHERE old.major_type=row.kind AND old.code=row.code AND old.name<>row.name
        AND NOT EXISTS { MATCH ()-[:BELONGS_TO]->(old) }
      DETACH DELETE old""", {"rows":rows})
    return corrected


def apply_location_supplements(client):
    return client.run_rows("""UNWIND $rows AS row
      MATCH (i:Institution {name:row.name})
      WHERE i.city IS NULL OR trim(i.city)='' OR (i.city_supplemented=true AND i.city=row.city)
      SET i.city=row.city,i.city_supplemented=true,i.city_evidence_url=row.source_url,
          i.city_verification_url=row.verification_url,i.city_evidence_note=row.note
      RETURN i.name AS institution,i.city AS city,i.city_evidence_url AS source_url""", {"rows":LOCATION_SUPPLEMENTS})
