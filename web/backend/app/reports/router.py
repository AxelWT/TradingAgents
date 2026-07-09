from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.dependencies import get_current_user
from app.db.database import get_db
from app.db.models import AnalysisTask, User
from app.analysis.schemas import AnalysisTaskResponse, AnalysisListResponse
from app.analysis.router import _task_to_response

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=AnalysisListResponse)
def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ticker: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AnalysisTask).filter(
        AnalysisTask.user_id == current_user.id,
        AnalysisTask.status == "completed",
    )
    if ticker:
        query = query.filter(AnalysisTask.ticker.ilike(f"%{ticker}%"))
    total = query.count()
    tasks = (
        query.order_by(AnalysisTask.completed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return AnalysisListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=total,
    )


@router.get("/{task_id}", response_model=AnalysisTaskResponse)
def get_report(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = (
        db.query(AnalysisTask)
        .filter(
            AnalysisTask.id == task_id,
            AnalysisTask.user_id == current_user.id,
            AnalysisTask.status == "completed",
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _task_to_response(task)


@router.get("/{task_id}/download")
def download_report(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = (
        db.query(AnalysisTask)
        .filter(
            AnalysisTask.id == task_id,
            AnalysisTask.user_id == current_user.id,
            AnalysisTask.status == "completed",
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Report not found")

    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        content=task.final_report or "",
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename=report_{task.ticker}_{task.trade_date}.md"
        },
    )
