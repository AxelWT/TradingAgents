from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_whitelisted = Column(Boolean, default=False, nullable=False)

    analysis_tasks = relationship(
        "AnalysisTask", back_populates="user", order_by="AnalysisTask.created_at.desc()"
    )


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String, nullable=False)
    asset_type = Column(String, default="stock")
    trade_date = Column(String, nullable=False)
    status = Column(String, default="pending", index=True)
    config = Column(JSON, nullable=True)
    signal = Column(String, nullable=True)
    rating = Column(String, nullable=True)
    final_report = Column(Text, nullable=True)
    agent_reports = Column(JSON, nullable=True)
    token_usage = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    scheduled_job_id = Column(String, ForeignKey("scheduled_jobs.id"), nullable=True, index=True)

    user = relationship("User", back_populates="analysis_tasks")
    scheduled_job = relationship("ScheduledJob", back_populates="analysis_tasks")


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id = Column(String, primary_key=True)
    email = Column(String, index=True, nullable=False)
    code_hash = Column(String, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    ticker = Column(String, nullable=False)
    asset_type = Column(String, default="stock")
    analysts = Column(JSON, nullable=True)
    research_depth = Column(Integer, default=2)
    llm_provider = Column(String, default="openai")
    backend_url = Column(String, nullable=True)
    quick_think_llm = Column(String, nullable=True)
    deep_think_llm = Column(String, nullable=True)
    output_language = Column(String, default="English")
    google_thinking_level = Column(String, nullable=True)
    openai_reasoning_effort = Column(String, nullable=True)
    anthropic_effort = Column(String, nullable=True)

    cron_expr = Column(String, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False, index=True)

    created_by = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)

    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    last_task_id = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)

    analysis_tasks = relationship("AnalysisTask", back_populates="scheduled_job")
