"""Explicit, billable smoke test: python scripts/verify_llm.py --live."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description="验证真实 DeepSeek 与图谱接口（会消耗少量 API 额度）")
    parser.add_argument("--live", action="store_true", help="明确执行真实模型调用")
    args = parser.parse_args()
    if not args.live:
        parser.error("需使用 --live 才会调用付费 API")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings

    client = TestClient(app)
    cases = [
        ("grounded_chat", "/chat/cloud", {"question": "我关注浙江大学。请引用一条2024年历史录取数据并注明来源，说明是否代表今年录取要求，100字内。", "context": {"year": 2024, "target_institutions": ["浙江大学"]}}, None),
        ("major_intro", "/majors/intro", {"majors": ["计算机科学与技术"]}, "llm"),
        ("major_intro_missing_catalog", "/majors/intro", {"majors": ["人工智能"]}, "llm"),
        ("exam_format", "/mock-exams/format", {"records": [{"id": "synthetic-1", "raw_text": "第1次模拟考试：总分650，校排名100。未提供省位次。", "ocr_text": "总分660"}]}, "formatted"),
        ("advantage_analysis", "/mock-exams/analyze", {"formatted_text": "模拟考试总分650；选考物理、化学、生物；没有单科分数和省位次。", "user_hint": "不推断单科优势，150字内"}, "analysis"),
        ("career_json", "/career/simulate", {"institution": "浙江大学", "major": "工科试验班(信息)", "num_years": 10}, None),
        ("market_json", "/majors/market-analysis", {"majors": ["计算机科学与技术", "哲学"]}, None),
    ]
    report = {"at": datetime.now(timezone.utc).isoformat(), "model": settings.deepseek_model,
              "base_url": settings.deepseek_base_url, "synthetic_exam_data": True, "checks": []}
    for name, path, payload, wrapper in cases:
        start = time.monotonic()
        response = client.post("/api/v1" + path, json=payload)
        data = response.json()
        result = data.get(wrapper, {}) if wrapper else data
        ok = response.status_code == 200 and result.get("model") == "deepseek-flash"
        if name == "career_json":
            ok = ok and bool(result.get("data", {}).get("stages"))
        elif name == "market_json":
            ok = ok and set(result.get("data", {})) == set(payload["majors"])
        else:
            ok = ok and bool(result.get("answer"))
        if name == "grounded_chat":
            ok = ok and bool(result.get("sources"))
        check = {"name": name, "ok": bool(ok), "status": response.status_code,
                 "seconds": round(time.monotonic() - start, 2), "result": data}
        report["checks"].append(check)
        print(json.dumps({k: v for k, v in check.items() if k != "result"}, ensure_ascii=False), flush=True)
    report["passed"] = all(x["ok"] for x in report["checks"])
    output = Path(__file__).resolve().parents[1] / "docs" / "llm_verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
