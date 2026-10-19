"""Shared, deterministic preference matching using source catalog names."""
from __future__ import annotations

import re

from app.graph_data import name

RECOMMENDATION_VERSION = "preferences-v6"

# Supplement only domain matching; do not invent catalog codes or admission facts.
# Education Ministry computing-category lists: see docs/位次120000检索核对.md.
COMPUTING_SUPPLEMENT = {"大数据技术", "大数据工程技术", "云计算技术应用", "数据科学与大数据技术"}
TEACHER_ATTRIBUTES = {"师范", "师范类", "含师范", "职教师范", "含职教师范", "非公费师范"}
ACCOUNTING_TERMS = {"会计", "会计学", "财务管理", "审计", "审计学", "财务会计类",
                    "大数据与会计", "大数据与财务管理", "大数据与审计"}


def location_aliases(values):
    aliases = set()
    for value in values:
        value = name(value)
        if not value:
            continue
        base = re.sub(r"(?:壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区|省|市)$", "", value)
        aliases.update([value, base, base + "市", base + "省", base + "自治区", base + "特别行政区"])
        full_names = {"广西":"广西壮族自治区", "宁夏":"宁夏回族自治区", "新疆":"新疆维吾尔自治区"}
        if base in full_names:
            aliases.add(full_names[base])
    return sorted(aliases)


def resolve_major_terms(client, keywords, explanations=None):
    requested = list(dict.fromkeys(name(x) for x in keywords if name(x)))
    if not requested:
        return []
    aliases = {"AI":"人工智能", "ai":"人工智能", "师范教育":"师范", "师范类":"师范"}
    parsed = []
    for original in requested:
        value = aliases.get(original, original)
        mode = "field" if value.endswith("门类") else "major" if value.endswith("专业") else "auto"
        key = value.removesuffix("门类") if mode == "field" else value.removesuffix("专业") if mode == "major" else value
        parsed.append((original, key, mode))
    keys = sorted({key for _,key,_ in parsed})
    rows = client.run_rows("""MATCH (m:MajorL3)-[:BELONGS_TO]->(c:MajorL2)-[:BELONGS_TO]->(f:MajorL1)
      WHERE any(k IN $keywords WHERE m.name CONTAINS k OR c.name CONTAINS k OR f.name CONTAINS k)
      RETURN DISTINCT m.name AS major,c.name AS category,f.name AS field""", {"keywords":keys})
    terms = set()
    for original, key, mode in parsed:
        if key == "财会":
            terms.update(ACCOUNTING_TERMS)
            if explanations is not None:
                explanations.append({"input":original,"level":"领域别名","scope":["会计","财务管理","审计"],"catalog_matches":0})
            continue
        if key == "师范":
            terms.update(TEACHER_ATTRIBUTES)
            if explanations is not None:
                explanations.append({"input":original,"level":"招生属性","scope":["原表明确标注师范或含师范"],"catalog_matches":0})
            continue
        categories = {r.get("category") for r in rows if key in {
            r.get("category"), (r.get("category") or "").removesuffix("类"),
            (r.get("category") or "").removesuffix("学类")}}
        exact = [r for r in rows if r.get("major") == key]
        fields = {r.get("field") for r in rows if key in {r.get("field"), (r.get("field") or "").removesuffix("学")}}
        if mode == "field":
            selected = [r for r in rows if r.get("field") in fields]
            level = "门类"
        elif mode == "major":
            # Internal exact token also survives the broad Cypher prefilter.
            terms.add("=" + key)
            if explanations is not None:
                explanations.append({"input":original,"level":"指定专业","scope":[key],"catalog_matches":len(exact)})
            continue
        elif categories:
            selected = [r for r in rows if r.get("category") in categories]
            level = "专业类"
        elif exact:
            selected, level = exact, "指定专业"
        elif fields:
            selected = [r for r in rows if r.get("field") in fields]
            level = "门类"
        else:
            selected = [r for r in rows if (r.get("major") or "").startswith(key)]
            level = "招生名称"
        # Keep a literal prefix for raw admissions not covered by the old catalog.
        terms.add(key)
        terms.update(r["major"] for r in selected if r.get("major"))
        if level == "专业类":
            terms.update(categories)
        if key in {"计算机", "计算机类"}:
            terms.update(COMPUTING_SUPPLEMENT)
        if explanations is not None:
            labels = sorted(categories) if level == "专业类" else sorted(fields) if level == "门类" else [key]
            explanations.append({"input":original, "level":level, "scope":labels,
                                 "catalog_matches":len(selected)})
    return sorted(terms)


def major_matches(program, terms):
    if not terms:
        return True
    program = name(program)
    base = program.split("(", 1)[0]
    exact = {term[1:] for term in terms if term.startswith("=")}
    prefixes = {term for term in terms if not term.startswith("=")}
    if base in exact or any(base.startswith(term) or term == program for term in prefixes):
        return True
    terms = prefixes | exact
    # Grouped admissions may explicitly list catalog majors in parentheses.
    # A direction such as 人工智能法学方向 is not the catalog major 人工智能.
    components = re.split(r"[()、,;/]", program)
    if any(part in terms for part in components[1:] if part):
        return True
    if base.endswith("类") or "试验班" in base or "实验班" in base:
        for part in components[1:]:
            part = re.sub(r"^(?:包含|包括|含)(?:专业)?[:：]?", "", part)
            part = re.sub(r"(?:等)?专业$", "", part)
            if part in terms:
                return True
    return False
