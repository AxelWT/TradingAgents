from pydantic import BaseModel
from typing import Optional


class AnalysisCreateRequest(BaseModel):
    ticker: str
    trade_date: str
    asset_type: str = "stock"
    analysts: list[str] = ["market", "social", "news", "fundamentals"]
    research_depth: int = 2
    llm_provider: str = "openai"
    backend_url: Optional[str] = None
    quick_think_llm: Optional[str] = None
    deep_think_llm: Optional[str] = None
    output_language: str = "English"
    google_thinking_level: Optional[str] = None
    openai_reasoning_effort: Optional[str] = None
    anthropic_effort: Optional[str] = None


class AnalysisTaskResponse(BaseModel):
    id: str
    ticker: str
    asset_type: str
    trade_date: str
    status: str
    signal: Optional[str] = None
    rating: Optional[str] = None
    final_report: Optional[str] = None
    agent_reports: Optional[dict] = None
    token_usage: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    class Config:
        from_attributes = True


class AnalysisListResponse(BaseModel):
    tasks: list[AnalysisTaskResponse]
    total: int
