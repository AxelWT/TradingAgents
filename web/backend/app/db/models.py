from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, JSON, ForeignKey, Integer
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

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

    user = relationship("User", back_populates="analysis_tasks")
