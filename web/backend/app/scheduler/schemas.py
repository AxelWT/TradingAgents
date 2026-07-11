from datetime import datetime

from pydantic import BaseModel


class ScheduledJobCreateRequest(BaseModel):
    name: str
    ticker: str
    asset_type: str = "stock"
    analysts: list[str] = ["market", "social", "news", "fundamentals"]
    research_depth: int = 2
    llm_provider: str = "openai"
    backend_url: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    output_language: str = "English"
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    cron_expr: str
    enabled: bool = True


class ScheduledJobUpdateRequest(BaseModel):
    name: str | None = None
    ticker: str | None = None
    asset_type: str | None = None
    analysts: list[str] | None = None
    research_depth: int | None = None
    llm_provider: str | None = None
    backend_url: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    output_language: str | None = None
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None


class ScheduledJobResponse(BaseModel):
    id: str
    name: str
    ticker: str
    asset_type: str
    analysts: list[str] | None = None
    research_depth: int
    llm_provider: str
    backend_url: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    output_language: str
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    cron_expr: str
    enabled: bool
    created_by: str
    created_at: datetime | None = None
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_task_id: str | None = None
    last_error: str | None = None

    class Config:
        from_attributes = True


class ScheduledJobListResponse(BaseModel):
    jobs: list[ScheduledJobResponse]
    total: int


class ScheduledJobRunResponse(BaseModel):
    task_id: str
    message: str
