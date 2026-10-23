from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.models import (
    AdjustRequest,
    BatchProbabilityRequest,
    CareerSimulateRequest,
    ChatRequest,
    CompareRequest,
    EnrichInstitutionsRequest,
    KgExplorerRequest,
    MajorIntroRequest,
    MarketAnalysisRequest,
    MockExamAnalyzeRequest,
    MockExamFormatRequest,
    OptimizeRequest,
    PeerInsightsRequest,
    ProbabilityRequest,
    RecommendationRequest,
    RecycleRestoreRequest,
    SaveStrategyRequest,
)
from app.neo4j_http import Neo4jHttpClient
from app.services.deepseek_cloud import DeepSeekCloudService, ModelServiceError
from app.services.deepseek_local import OllamaService
from app.services.configuration import ConfigurationChecks
from app.services.kg_service import KgService
from app.services.recommender import RecommenderService
from app.services.recommendation_export import RecommendationExportRequest, XLSX_TYPE, build_recommendation_workbook
from app.storage import LocalStorage


app = FastAPI(title="高考志愿推荐系统", version="1.0.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def static_url(path: str) -> str:
    modified = (Path(__file__).parent / "static" / path).stat().st_mtime_ns
    return f"/static/{path}?v={modified}"


templates.env.globals["static_url"] = static_url

neo4j_client = Neo4jHttpClient(
    base_url=settings.neo4j_url,
    username=settings.neo4j_user,
    password=settings.neo4j_password,
    database=settings.neo4j_db,
)
kg_service = KgService(neo4j_client)
recommender_service = RecommenderService(neo4j_client)
storage = LocalStorage(settings.storage_dir / "app.db")
deepseek_service = DeepSeekCloudService(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    model=settings.deepseek_model,
    timeout=settings.deepseek_timeout,
)
ollama_service = OllamaService(
    base_url=settings.ollama_base_url,
    model=settings.ollama_model,
    timeout=settings.ollama_timeout,
)
configuration_checks = ConfigurationChecks(settings)


@app.exception_handler(ModelServiceError)
async def model_error_handler(request: Request, exc: ModelServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc), "code": exc.code})


def is_login(request: Request) -> bool:
    return request.cookies.get("vrs_auth") == "1"


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    if not is_login(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("main_page.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Any:
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
) -> Any:
    if not username.strip() or not password.strip():
        return templates.TemplateResponse("login.html", {"request": request, "error": "用户名和密码不能为空"})
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie("vrs_auth", "1", httponly=True, max_age=3600 * 24 * 7)
    return resp


@app.post("/logout")
def logout() -> Any:
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("vrs_auth")
    return resp


@app.get("/recommend", response_class=HTMLResponse)
def recommend_page(request: Request) -> Any:
    if not is_login(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("recommend_page.html", {"request": request})


@app.get("/majors", response_class=HTMLResponse)
def majors_page(request: Request) -> Any:
    if not is_login(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("majors_page.html", {"request": request})


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request) -> Any:
    if not is_login(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("compare_page.html", {"request": request})


@app.get("/trajectory", response_class=HTMLResponse)
def trajectory_page(request: Request) -> Any:
    if not is_login(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("trajectory_page.html", {"request": request})


@app.get("/simulate", response_class=HTMLResponse)
def simulate_page(request: Request) -> Any:
    if not is_login(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("simulate_page.html", {"request": request})


@app.get("/kg-explorer", response_class=HTMLResponse)
def kg_explorer_page(request: Request) -> Any:
    if not is_login(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("kg_explorer.html", {"request": request})


@app.get("/api/v1/health")
def health() -> Dict[str, Any]:
    try:
        neo4j_status = kg_service.health()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Neo4j连接失败: {exc}") from exc
    return {
        "status": "ok",
        "neo4j": neo4j_status,
        "deepseek_cloud": {
            "configured": deepseek_service.configured(),
            "base_url": settings.deepseek_base_url,
            "model": settings.deepseek_model,
            "display_name": "DeepSeek V4.1 Flash" if settings.deepseek_model == "deepseek-flash" else settings.deepseek_model,
        },
        "ollama": {
            "configured": ollama_service.configured(),
            "base_url": settings.ollama_base_url,
            "model": settings.ollama_model,
        },
        "ocr": {"tesseract_cmd": settings.tesseract_cmd},
    }


@app.get("/api/v1/setup/status")
def setup_status(request: Request) -> Dict[str, Any]:
    if not is_login(request):
        raise HTTPException(status_code=401, detail="请先登录")
    return configuration_checks.status()


@app.post("/api/v1/setup/verify-model")
def setup_verify_model(request: Request) -> Dict[str, Any]:
    if not is_login(request):
        raise HTTPException(status_code=401, detail="请先登录")
    return configuration_checks.verify_model()


@app.get("/api/v1/data/scope")
def data_scope() -> Dict[str, Any]:
    try:
        return kg_service.data_scope()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"数据范围暂不可用: {exc}") from exc


@app.post("/api/v1/recommend/run")
def recommend_run(payload: RecommendationRequest) -> Dict[str, Any]:
    try:
        return recommender_service.recommend(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"推荐计算失败: {exc}") from exc


@app.post("/api/v1/recommend/adjust")
def recommend_adjust(payload: AdjustRequest) -> Dict[str, Any]:
    try:
        return recommender_service.adjust(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重算失败: {exc}") from exc


@app.post("/api/v1/recommend/export")
def recommend_export(payload: RecommendationExportRequest, request: Request) -> Response:
    if not is_login(request):
        raise HTTPException(status_code=401, detail="请先登录后导出")
    return Response(
        content=build_recommendation_workbook(payload),
        media_type=XLSX_TYPE,
        headers={"Content-Disposition": 'attachment; filename="VRS-recommendations.xlsx"',
                 "Cache-Control": "no-store"},
    )


@app.post("/api/v1/recommend/enrich")
def recommend_enrich(payload: EnrichInstitutionsRequest) -> Dict[str, Any]:
    if not payload.items:
        return {"data": {}}
    rows = neo4j_client.run_rows("""MATCH (i:Institution) WHERE i.name IN $names
      RETURN i.name AS name,i.level AS level,i.school_nature AS nature""",
      {"names": [str(item.get("name", "")) for item in payload.items]})
    return {"data": {row["name"]: {"level": row.get("level") or "", "nature": row.get("nature") or ""}
                     for row in rows}, "source": "neo4j"}


@app.post("/api/v1/compare/data")
def compare_data(payload: CompareRequest) -> Dict[str, Any]:
    try:
        return kg_service.compare_data(
            payload.institutions,
            payload.major_keyword,
            payload.year,
            [x.model_dump() for x in payload.compare_items],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"对比数据查询失败: {exc}") from exc


@app.get("/api/v1/kg/search")
def kg_search(keyword: str = Query(..., min_length=1), limit: int = 20) -> Dict[str, Any]:
    try:
        return kg_service.search(keyword, limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"图谱搜索失败: {exc}") from exc


@app.get("/api/v1/kg/detail/institution")
def kg_detail_institution(name: str, year: int = 2024) -> Dict[str, Any]:
    try:
        return kg_service.institution_detail(name, year)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"院校详情查询失败: {exc}") from exc


@app.get("/api/v1/recommend/detail")
def recommend_detail(institution: str, major: str, year: int = 2024, fact_id: str = "") -> Dict[str, Any]:
    try:
        return kg_service.recommend_item_detail(institution, major, year, fact_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"推荐详情查询失败: {exc}") from exc


@app.get("/api/v1/kg/detail/major")
def kg_detail_major(name: str) -> Dict[str, Any]:
    try:
        return kg_service.major_detail(name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"专业详情查询失败: {exc}") from exc


@app.get("/api/v1/majors/l1")
def majors_l1() -> Dict[str, Any]:
    try:
        return {"items": kg_service.major_l1_list()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询一级专业失败: {exc}") from exc


@app.get("/api/v1/majors/l2")
def majors_l2(l1_norm_name: str) -> Dict[str, Any]:
    try:
        return {"items": kg_service.major_l2_list(l1_norm_name)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询二级专业失败: {exc}") from exc


@app.get("/api/v1/majors/l3")
def majors_l3(l2_norm_name: str) -> Dict[str, Any]:
    try:
        return {"items": kg_service.major_l3_list(l2_norm_name)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询三级专业失败: {exc}") from exc


@app.post("/api/v1/majors/intro")
def majors_intro(payload: MajorIntroRequest) -> Dict[str, Any]:
    try:
        details = kg_service.major_details_batch(payload.majors)
        prompt = (
            "请基于以下专业数据，按“专业名称、培养方向、就业与报考建议”结构输出中文介绍，避免编造，简洁清晰：\n"
            + json.dumps(details, ensure_ascii=False)
        )
        answer = deepseek_service.chat(prompt, {"graph_context": {"catalog_majors": details}})
        return {"details": details, "llm": answer}
    except ModelServiceError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"专业介绍生成失败: {exc}") from exc


@app.post("/api/v1/mock-exams/ocr")
async def mock_exam_ocr(file: UploadFile = File(...)) -> Dict[str, Any]:
    try:
        from io import BytesIO
        from pathlib import Path as _Path

        from PIL import Image
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        if not _Path(settings.tesseract_cmd).exists():
            raise RuntimeError(f"Tesseract不存在: {settings.tesseract_cmd}")
        content = await file.read()
        image = Image.open(BytesIO(content))
        text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        return {"filename": file.filename, "ocr_text": text.strip()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OCR识别失败: {exc}") from exc


@app.post("/api/v1/mock-exams/format")
def mock_exam_format(payload: MockExamFormatRequest) -> Dict[str, Any]:
    try:
        records = [r.model_dump() for r in payload.records]
        result = deepseek_service.format_mock_exam_records(records, payload.user_hint)
        return {"formatted": result}
    except ModelServiceError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"成绩格式化失败: {exc}") from exc


@app.post("/api/v1/mock-exams/analyze")
def mock_exam_analyze(payload: MockExamAnalyzeRequest) -> Dict[str, Any]:
    try:
        result = deepseek_service.analyze_advantage_fields(payload.formatted_text, payload.user_hint)
        return {"analysis": result}
    except ModelServiceError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"优势分析失败: {exc}") from exc


@app.post("/api/v1/chat/local")
def chat_local(payload: ChatRequest) -> Dict[str, Any]:
    # Compatibility alias: the existing UI has already consolidated cloud AI.
    return chat_cloud(payload)


@app.post("/api/v1/chat/cloud")
def chat_cloud(payload: ChatRequest) -> Dict[str, Any]:
    preferences = {key: payload.context[key] for key in (
        "score", "rank", "year", "subject_combo", "majors", "provinces", "target_institutions",
        "extra_note", "mock_exams", "rank_window", "candidate_scope") if key in payload.context}
    try:
        graph_context = kg_service.ai_context(payload.question, preferences)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=503, detail="图谱资料暂时不可用，请稍后重试。") from None
    result = deepseek_service.chat(payload.question, {"user_preferences": preferences, "graph_context": graph_context})
    result["sources"] = graph_context["historical_offers"]
    return result


@app.post("/api/v1/session/save-strategy")
def save_strategy(payload: SaveStrategyRequest) -> Dict[str, Any]:
    storage.save_strategy(payload.name, payload.payload)
    return {"ok": True}


@app.get("/api/v1/session/list-strategy")
def list_strategy() -> Dict[str, Any]:
    return {"items": storage.list_strategy()}


# ── Admission Probability ──
@app.post("/api/v1/recommend/probability")
def recommend_probability(payload: BatchProbabilityRequest) -> Dict[str, Any]:
    try:
        results = {}
        for item in payload.items:
            inst = item.get("institution", "")
            maj = item.get("major", "")
            if not inst or not maj:
                continue
            history = kg_service.admission_history(inst, maj, payload.year)
            prob = recommender_service.calculate_probability(payload.rank, history)
            results[f"{inst}|{maj}"] = prob
        return {"probabilities": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"概率计算失败: {exc}") from exc


# ── Strategy Optimizer ──
@app.post("/api/v1/recommend/optimize")
def recommend_optimize(payload: OptimizeRequest) -> Dict[str, Any]:
    try:
        return recommender_service.optimize(
            payload.rank,
            payload.candidates,
            payload.target_count,
            payload.ratio_chong,
            payload.ratio_wen,
            payload.ratio_bao,
            payload.user_preferences,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"策略优化失败: {exc}") from exc


# ── Career Pathway Simulator ──
@app.post("/api/v1/career/simulate")
def career_simulate(payload: CareerSimulateRequest) -> Dict[str, Any]:
    try:
        kg_context = kg_service.recommend_item_detail(
            payload.institution, payload.major, payload.year
        )
        return deepseek_service.simulate_career_pathway(
            payload.institution, payload.major, kg_context, payload.num_years
        )
    except ModelServiceError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"职业模拟失败: {exc}") from exc


# ── Market Analysis ──
@app.post("/api/v1/majors/market-analysis")
def majors_market_analysis(payload: MarketAnalysisRequest) -> Dict[str, Any]:
    try:
        details = kg_service.major_details_batch(payload.majors)
        return deepseek_service.analyze_market_alignment(payload.majors, {"catalog_majors": details})
    except ModelServiceError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"市场分析失败: {exc}") from exc


# ── Peer Insights ──
@app.post("/api/v1/kg/peer-insights")
def kg_peer_insights(payload: PeerInsightsRequest) -> Dict[str, Any]:
    try:
        return kg_service.peer_insights(
            payload.rank, payload.provinces, payload.majors, payload.limit, payload.year,
            payload.subject_combo or "", payload.rank_window, payload.candidate_scope
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同伴分析失败: {exc}") from exc


# ── KG Explorer ──
@app.post("/api/v1/kg/explorer-data")
def kg_explorer_data(payload: KgExplorerRequest) -> Dict[str, Any]:
    try:
        return kg_service.graph_explorer_data(
            payload.keyword, payload.node_type, payload.limit
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"图谱数据获取失败: {exc}") from exc


@app.post("/api/v1/recycle/add")
def recycle_add(payload: RecycleRestoreRequest) -> Dict[str, Any]:
    storage.add_recycle(payload.bin_type, payload.item)
    return {"ok": True}


@app.get("/api/v1/recycle/list")
def recycle_list(bin_type: Optional[str] = None) -> Dict[str, Any]:
    return {"items": storage.list_recycle(bin_type)}


@app.post("/api/v1/recycle/restore")
def recycle_restore(payload: RecycleRestoreRequest) -> Dict[str, Any]:
    if not storage.restore_recycle(payload.bin_type, payload.item):
        raise HTTPException(status_code=404, detail="回收站中没有此条目，可能已恢复。")
    # Return the item for the caller to replay into its local recommendation list.
    return {"ok": True, "restored": payload.item, "bin_type": payload.bin_type}
