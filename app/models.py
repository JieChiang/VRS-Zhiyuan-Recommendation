from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, FiniteFloat, StringConstraints, model_validator

AIName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class LayerRatioRequest(BaseModel):
    ratio_chong: int = Field(default=3, ge=0)
    ratio_wen: int = Field(default=4, ge=0)
    ratio_bao: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def validate_layer_ratio(self) -> "LayerRatioRequest":
        if self.ratio_chong + self.ratio_wen + self.ratio_bao == 0:
            raise ValueError("冲稳保比例不能同时为 0")
        return self


class RecommendationRequest(LayerRatioRequest):
    source_province: Literal["浙江"] = "浙江"
    score: Optional[int] = Field(default=None, ge=0)
    rank: int = Field(..., ge=1)
    subject_combo: Optional[str] = None
    majors: List[str] = Field(default_factory=list)
    provinces: List[str] = Field(default_factory=list)
    target_institutions: List[str] = Field(default_factory=list)
    target_count: int = Field(default=80, ge=10, le=300)
    ratio_chong: int = Field(default=3, ge=0)
    ratio_wen: int = Field(default=4, ge=0)
    ratio_bao: int = Field(default=3, ge=0)
    rank_window: int = Field(default=1000, ge=50, le=100000)
    candidate_scope: Literal["all", "window"] = "all"
    year: int = Field(default=2024, ge=2010, le=2100)


class AdjustRequest(LayerRatioRequest):
    rank: int = Field(..., ge=1)
    target_count: int = Field(default=80, ge=10, le=300)
    ratio_chong: int = Field(default=3, ge=0)
    ratio_wen: int = Field(default=4, ge=0)
    ratio_bao: int = Field(default=3, ge=0)
    base_candidates: List[Dict[str, Any]] = Field(default_factory=list)


class CompareItem(BaseModel):
    institution: str
    major: str
    year: Optional[int] = None


class CompareRequest(BaseModel):
    institutions: List[str] = Field(default_factory=list)
    compare_items: List[CompareItem] = Field(default_factory=list)
    major_keyword: str = ""
    year: int = 2024


class ChatRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    context: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def limit_context(self):
        if len(json.dumps(self.context, ensure_ascii=False)) > 60000:
            raise ValueError("上下文过长，请减少成绩记录后重试")
        return self


class SaveStrategyRequest(BaseModel):
    name: str
    payload: Dict[str, Any]


class RecycleRestoreRequest(BaseModel):
    bin_type: str
    item: Dict[str, Any]


class MajorIntroRequest(BaseModel):
    majors: List[AIName] = Field(min_length=1, max_length=10)


class MockExamRecord(BaseModel):
    id: str
    source: str = "text"
    raw_text: str = Field(default="", max_length=10000)
    ocr_text: str = Field(default="", max_length=10000)
    note: str = ""
    image_names: List[str] = Field(default_factory=list, max_length=20)


class MockExamFormatRequest(BaseModel):
    records: List[MockExamRecord] = Field(min_length=1, max_length=20)
    user_hint: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def require_text(self):
        if not any(r.raw_text.strip() or r.ocr_text.strip() for r in self.records):
            raise ValueError("请提供成绩文本或 OCR 识别内容")
        return self


class EnrichInstitutionsRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)


class MockExamAnalyzeRequest(BaseModel):
    formatted_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30000)]
    user_hint: str = Field(default="", max_length=2000)


class ProbabilityRequest(BaseModel):
    rank: int = Field(..., ge=1)
    institution: str
    major: str
    year: int = 2024


class BatchProbabilityRequest(BaseModel):
    rank: int = Field(..., ge=1)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    year: int = 2024


class OptimizeRequest(LayerRatioRequest):
    rank: int = Field(..., ge=1)
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    target_count: int = Field(default=80, ge=10, le=300)
    ratio_chong: int = Field(default=3, ge=0)
    ratio_wen: int = Field(default=4, ge=0)
    ratio_bao: int = Field(default=3, ge=0)
    user_preferences: Dict[str, FiniteFloat] = Field(default_factory=dict)


class CareerSimulateRequest(BaseModel):
    institution: AIName
    major: AIName
    num_years: int = Field(default=10, ge=3, le=30)
    year: int = Field(default=2024, ge=2019, le=2024)


class MarketAnalysisRequest(BaseModel):
    majors: List[AIName] = Field(min_length=1, max_length=6)


class PeerInsightsRequest(BaseModel):
    year: int = Field(default=2024, ge=2010, le=2100)
    rank: int = Field(..., ge=1)
    provinces: List[str] = Field(default_factory=list)
    majors: List[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=5, le=50)
    subject_combo: Optional[str] = None
    rank_window: int = Field(default=5000, ge=50, le=100000)
    candidate_scope: Literal["all", "window"] = "all"


class KgExplorerRequest(BaseModel):
    keyword: str = ""
    node_type: str = "all"
    limit: int = Field(default=50, ge=10, le=200)
