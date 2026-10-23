from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.models import AdjustRequest, RecommendationRequest
from app.graph_data import DATASET_ID, eligibility, selected_subjects, subject_requirement_info
from app.services.preference_filters import RECOMMENDATION_VERSION, location_aliases, major_matches, resolve_major_terms
from app.neo4j_http import Neo4jHttpClient


class RecommenderService:
    def __init__(self, client: Neo4jHttpClient) -> None:
        self.client = client

    @staticmethod
    def _layer_targets(target_count: int, chong: int, wen: int, bao: int) -> tuple[int, int, int]:
        weights = (chong, wen, bao)
        total = sum(weights)
        if min(weights) < 0 or total <= 0:
            raise ValueError("冲稳保比例必须非负且不能同时为 0")
        counts = [target_count * weight // total for weight in weights]
        # 最大余数法：分配取整后的剩余名额，目标总数保持不变。
        order = sorted(range(3), key=lambda i: (target_count * weights[i] % total), reverse=True)
        for i in order[: target_count - sum(counts)]:
            counts[i] += 1
        return counts[0], counts[1], counts[2]

    def _fetch_candidates(self, req: RecommendationRequest, diagnostics=None) -> list[dict[str, Any]]:
        if req.source_province != "浙江":
            raise ValueError("当前数据仅支持浙江生源")
        subjects = selected_subjects(req.subject_combo or "")
        resolutions = []
        terms = resolve_major_terms(self.client, req.majors, resolutions)
        cypher = """
        MATCH (o:OfferFact)
        WHERE o.dataset_id=$dataset AND o.province=$source_province AND o.year=$year
          AND o.min_rank >= $lower AND o.min_rank <= $upper
          AND coalesce(o.conflicting,false)=false
        MATCH (i:Institution)-[:HAS_OFFER]->(o)-[:FOR_PROGRAM]->(p:AdmissionProgram)
        WHERE (size($major_terms)=0 OR any(x IN $major_terms WHERE p.name CONTAINS x))
          AND (size($provinces)=0 OR i.province IN $provinces OR i.province IN $locations OR i.city IN $locations)
        OPTIONAL MATCH (o)-[:HAS_PLAN]->(plan:PlanFact)
        RETURN i.name AS institution,p.name AS major,o.year AS year,
          p.program_id AS program_id,o.fact_id AS fact_id,
          coalesce(plan.level,i.level) AS level,coalesce(plan.school_nature,i.school_nature) AS school_nature,
          i.website AS website,i.province AS destination_province,i.city AS destination_city,
          o.min_score AS min_score,o.min_rank AS min_rank,plan.plan_count AS plan_count,
          plan.subject_requirement_raw AS subject_requirement,plan.subject_requirement_scope AS subject_requirement_scope,
          plan IS NOT NULL AS plan_matched,plan.fact_id AS plan_fact_id,
          plan.source_file AS plan_source,plan.source_row AS plan_source_row,
          o.source_file AS source_file,o.source_sheet AS source_sheet,o.source_row AS source_row,
          o.province AS source_province,o.dataset_id AS dataset_id,
          abs(o.min_rank-$rank) AS rank_gap
        ORDER BY rank_gap,min_rank,institution,major
        LIMIT 30000
        """
        rows = self.client.run_rows(cypher, {
            "dataset": DATASET_ID, "source_province": req.source_province,
            "year": req.year, "rank": req.rank, "lower": max(1,req.rank-req.rank_window) if req.candidate_scope == "window" else 1,
            "upper": req.rank+req.rank_window if req.candidate_scope == "window" else 2147483647,
            "majors": req.majors, "provinces": req.provinces,
            "major_terms": [t.removeprefix("=") for t in terms], "locations": location_aliases(req.provinces),
        })
        result = []
        stats = {"retrieved": len(rows), "unrelated_direction_excluded": 0, "subject_excluded": 0,
                 "subject_pending": 0, "subject_unrestricted": 0,
                 "expanded_major_terms": terms, "major_resolutions":resolutions,
                 "search_limit_reached": len(rows) >= 30000}
        for row in rows:
            if not major_matches(row.get("major", ""), terms):
                stats["unrelated_direction_excluded"] += 1
                continue
            info = subject_requirement_info(row.get("subject_requirement"), plan_matched=row.get("plan_matched") is True)
            state = eligibility(info["effective"], subjects, complete=len(subjects) == 3)
            row["subject_eligibility"] = state
            row["subject_requirement_kind"] = info["kind"]
            row["subject_requirement_display"] = info["display"]
            options = info["options"]
            row["subject_missing"] = min((sorted(set(group) - subjects) for group in options), key=len) if options else []
            if state != "ineligible":
                result.append(row)
                stats["subject_pending"] += state == "unknown"
                stats["subject_unrestricted"] += info["kind"] == "unrestricted"
            else:
                stats["subject_excluded"] += 1
        stats["available_candidates"] = len(result)
        if diagnostics is not None:
            diagnostics.update(stats)
        return result

    def _split_layers(
        self,
        candidates: list[dict[str, Any]],
        rank: int,
        target_count: int,
        ratio_chong: int,
        ratio_wen: int,
        ratio_bao: int,
    ) -> dict[str, Any]:
        chong_n, wen_n, bao_n = self._layer_targets(target_count, ratio_chong, ratio_wen, ratio_bao)
        chong_pool: list[dict[str, Any]] = []
        wen_pool: list[dict[str, Any]] = []
        bao_pool: list[dict[str, Any]] = []
        allowed = {layer for layer, weight in zip(["冲","稳","保"], [ratio_chong,ratio_wen,ratio_bao]) if weight>0}
        unique = {}
        for original in candidates:
            identity = (original.get("institution"), original.get("major"), original.get("year"))
            unique.setdefault(identity, original)
        permitted = []
        for original in unique.values():
            item = dict(original)
            item["layer"] = self._classify_layer(int(item["min_rank"]), rank)
            if item["layer"] not in allowed:
                continue
            permitted.append(item)
            if item["layer"] == "冲":
                chong_pool.append(item)
            elif item["layer"] == "稳":
                wen_pool.append(item)
            else:
                bao_pool.append(item)

        def take(pool: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
            return pool[:n]

        chong = take(chong_pool, chong_n)
        wen = take(wen_pool, wen_n)
        bao = take(bao_pool, bao_n)

        merged = chong + wen + bao
        if len(merged) < target_count:
            used = {(x["institution"], x["major"], x["year"]) for x in merged}
            for item in permitted:
                key = (item["institution"], item["major"], item["year"])
                if key in used:
                    continue
                merged.append(item)
                used.add(key)
                if len(merged) >= target_count:
                    break

        # 补足候选后重新生成分层，保证列表和统计使用同一批结果。
        merged = merged[:target_count]
        chong = [x for x in merged if x["layer"] == "冲"]
        wen = [x for x in merged if x["layer"] == "稳"]
        bao = [x for x in merged if x["layer"] == "保"]

        return {
            "chong": chong,
            "wen": wen,
            "bao": bao,
            "all": chong + wen + bao,
            "meta": {
                "target_count": target_count,
                "layer_target": {"冲": chong_n, "稳": wen_n, "保": bao_n},
                "layer_actual": {"冲": len(chong), "稳": len(wen), "保": len(bao)},
                "disabled_layers": [x for x in ["冲","稳","保"] if x not in allowed],
                "layer_eligible_count": len(permitted),
            },
        }

    @staticmethod
    def _classify_layer(min_rank: int, rank: int) -> str:
        if min_rank < rank - 300:
            return "冲"
        if min_rank <= rank + 300:
            return "稳"
        return "保"

    def recommend(self, req: RecommendationRequest) -> dict[str, Any]:
        diagnostics = {}
        fetched = self._fetch_candidates(req, diagnostics)
        subjects = selected_subjects(req.subject_combo or "")
        pending = [x for x in fetched if x["subject_eligibility"] == "unknown"]
        candidates = [x for x in fetched if x["subject_eligibility"] == "eligible"] if len(subjects) == 3 else fetched
        diagnostics["primary_candidates"] = len(candidates)
        target_hits = []
        if req.target_institutions:
            target_set = set(req.target_institutions)
            for item in candidates:
                if item["institution"] in target_set:
                    tagged = dict(item)
                    tagged["tag"] = "*目标院校"
                    target_hits.append(tagged)

        layers = self._split_layers(
            candidates,
            req.rank,
            req.target_count,
            req.ratio_chong,
            req.ratio_wen,
            req.ratio_bao,
        )
        warnings = []
        if len(subjects) < 3:
            warnings.append(f"仅填写{len(subjects)}门选考科目，信息未完整；不限选科或已满足明确要求的专业正常保留，其余条目仅作探索候选，请补全后核验。")
        if len(candidates) < req.target_count:
            scope_note = "可切换全部候选或调整窗口" if req.candidate_scope == "window" else "已检索全部历史位次，可调整城市或专业偏好"
            warnings.append(f"当前条件下共有{len(candidates)}条候选；{scope_note}。")
        if diagnostics.get("search_limit_reached"):
            warnings.append("检索结果达到系统上限，请缩小位次窗口或增加偏好条件。")
        if layers["meta"]["disabled_layers"]:
            warnings.append("比例为0的分层已禁用：" + "、".join(layers["meta"]["disabled_layers"]) + "；不会用这些分层补足数量。")
        if len(layers["all"]) < min(len(candidates), req.target_count):
            warnings.append(f"按当前分层比例只有{layers['meta']['layer_eligible_count']}条可选记录，已保留实际数量；可调整冲稳保比例。")
        if len(subjects) == 3 and pending:
            warnings.append(f"另有{len(pending)}条历史记录缺少可核验的选科资料，单独列为待核实，不计入已核验推荐。")
        layers["meta"].update(dataset_id=DATASET_ID,source_province="浙江",reference_year=req.year,
                              recommendation_version=RECOMMENDATION_VERSION, rank_window=req.rank_window,
                              candidate_scope=req.candidate_scope,
                              rank_range=[max(1, req.rank-req.rank_window), req.rank+req.rank_window] if req.candidate_scope == "window" else None,
                              scope_note="全部符合地域、领域和选科条件的历史候选，按位次分层排序" if req.candidate_scope == "all" else "仅检索指定历史位次窗口",
                              requested_locations=req.provinces, subject_selection_complete=len(subjects) == 3,
                              filter_diagnostics=diagnostics, warnings=warnings,
                              selected_subjects=sorted(selected_subjects(req.subject_combo or "")),
                              qualification_note="原表明确不限或匹配计划中的空白要求表示不限选科；没有匹配计划不等于不限。其他要求按完整选科核验，资料不足的候选待核实。批次和科类原表未注明。")
        layers["target_hits"] = target_hits[: req.target_count]
        layers["meta"]["input_snapshot"] = req.model_dump()
        layers["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        layers["candidates"] = candidates[:max(200, req.target_count)]
        layers["pending_candidates"] = pending if len(subjects) == 3 else []
        return layers

    def adjust(self, req: AdjustRequest) -> dict[str, Any]:
        return self._split_layers(
            req.base_candidates,
            req.rank,
            req.target_count,
            req.ratio_chong,
            req.ratio_wen,
            req.ratio_bao,
        )

    # ── Admission Probability ──
    def calculate_probability(
        self, rank: int, history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not history or len(history) < 2:
            return {
                "probability": None,
                "confidence": "low",
                "message": "历史数据不足(需至少2年数据)，无法计算概率",
                "history": history,
            }

        ranks = []
        def history_year(row: dict[str, Any]) -> int:
            try:
                return int(row.get("year", 0) or 0)
            except (ValueError, TypeError):
                return 0

        for row in sorted(history, key=history_year):
            try:
                r = int(row["min_rank"])
                if r > 0:
                    ranks.append(r)
            except (KeyError, ValueError, TypeError, OverflowError):
                continue

        if len(ranks) < 2:
            return {
                "probability": None,
                "confidence": "low",
                "message": "有效历史位次数据不足",
                "history": history,
            }

        n = len(ranks)
        mean_rank = sum(ranks) / n
        variance = sum((r - mean_rank) ** 2 for r in ranks) / n
        std_dev = math.sqrt(variance) if variance > 0 else 1.0

        # Use a sigmoid-based probability model
        # Higher probability when user's rank is better (smaller) than historical mean
        z_score = (rank - mean_rank) / std_dev

        # Sigmoid: probability decreases as z_score increases
        # When z=0 (exactly at mean), probability ≈ 50%
        # When z=-1 (one std better), probability ≈ 73%
        # When z=+1 (one std worse), probability ≈ 27%
        # Use k=-1.2 for steeper/shallower curve
        k = 1.2
        # 避免历史方差很小时 exp 正指数溢出。
        exponent = k * z_score
        if exponent >= 0:
            exp_neg = math.exp(-exponent)
            probability = exp_neg / (1.0 + exp_neg)
        else:
            probability = 1.0 / (1.0 + math.exp(exponent))
        prob_pct = round(probability * 100, 1)

        # Determine confidence level
        if n >= 4:
            confidence = "high"
            conf_msg = f"基于{n}年数据，置信度较高"
        elif n >= 3:
            confidence = "medium"
            conf_msg = f"基于{n}年数据，置信度中等"
        else:
            confidence = "low"
            conf_msg = f"仅{n}年数据，仅供参考"

        # Risk level
        if prob_pct >= 65:
            risk = "低风险(保)"
        elif prob_pct >= 35:
            risk = "中等风险(稳)"
        else:
            risk = "高风险(冲)"

        return {
            "probability": prob_pct,
            "confidence": confidence,
            "risk_level": risk,
            "message": f"录取概率约{prob_pct}%，{conf_msg}，{risk}",
            "stats": {
                "years_of_data": n,
                "mean_rank": round(mean_rank, 1),
                "std_dev": round(std_dev, 1),
                "recent_rank": ranks[-1],
                "trend": "上升" if len(ranks) >= 2 and ranks[-1] < ranks[0] else "下降" if len(ranks) >= 2 and ranks[-1] > ranks[0] else "稳定",
                "z_score": round(z_score, 2),
            },
            "history": history,
        }

    # ── Strategy Optimizer ──
    def optimize(
        self,
        rank: int,
        candidates: list[dict[str, Any]],
        target_count: int,
        ratio_chong: int,
        ratio_wen: int,
        ratio_bao: int,
        user_preferences: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        if not candidates:
            return {"optimized": [], "score": 0, "message": "无候选数据"}

        prefs = user_preferences or {}
        chong_n, wen_n, bao_n = self._layer_targets(target_count, ratio_chong, ratio_wen, ratio_bao)

        def item_score(item: dict[str, Any]) -> float:
            score = 0.0
            try:
                mr = int(item.get("min_rank", 999999))
                # Proximity bonus: closer to user's rank = better match
                gap = abs(mr - rank)
                proximity = max(0, 1.0 - gap / 10000.0) * 40
                score += proximity

                # Institution preference bonus
                inst = str(item.get("institution", ""))
                for kw, weight in prefs.items():
                    if kw in inst:
                        score += weight * 15

                # Major preference bonus
                major = str(item.get("major", ""))
                for kw, weight in prefs.items():
                    if kw in major:
                        score += weight * 15

                # Quality bonus from level
                level = str(item.get("level", ""))
                if "本科" in level:
                    score += 10
                if "公办" in str(item.get("school_nature", "")):
                    score += 10

                # Plan count bonus (more slots = higher chance)
                pc = int(item.get("plan_count", 0) or 0)
                if pc > 0:
                    score += min(10, math.log2(pc + 1) * 3)
            except (ValueError, TypeError):
                pass
            return score

        scored = []
        for original in candidates:
            item = dict(original)
            item["_score"] = round(item_score(item), 2)
            scored.append(item)
        scored.sort(key=lambda item: (-item["_score"], str(item.get("institution", "")), str(item.get("major", ""))))
        unique = {}
        for item in scored:
            identity = (str(item.get("institution", "")), str(item.get("major", "")), item.get("year"))
            unique.setdefault(identity, item)
        layers = self._split_layers(list(unique.values()),rank,target_count,ratio_chong,ratio_wen,ratio_bao)
        chosen = layers["all"]
        return {"optimized": chosen, "score": round(sum(item["_score"] for item in chosen), 2),
                "meta": {**layers["meta"], "algorithm": "偏好加权与冲稳保配额排序", "dataset_id": DATASET_ID}}
