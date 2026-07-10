import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session

from app.analysis.schemas import AnalysisCreateRequest, AnalysisTaskResponse, AnalysisListResponse
from app.analysis.runner import run_analysis_task, manager
from app.dependencies import get_current_user
from app.db.database import get_db
from app.db.models import AnalysisTask, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("", response_model=AnalysisTaskResponse, status_code=201)
async def create_analysis(
    req: AnalysisCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task_id = str(uuid.uuid4())
    task = AnalysisTask(
        id=task_id,
        user_id=current_user.id,
        ticker=req.ticker,
        asset_type=req.asset_type,
        trade_date=req.trade_date,
        status="pending",
        config=req.model_dump(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    loop = asyncio.get_running_loop()
    background_tasks.add_task(run_analysis_task, task_id, req.model_dump(), current_user.id, loop)

    return _task_to_response(task)


@router.get("", response_model=AnalysisListResponse)
def list_analysis(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AnalysisTask).filter(AnalysisTask.user_id == current_user.id)
    if status:
        query = query.filter(AnalysisTask.status == status)
    total = query.count()
    tasks = (
        query.order_by(AnalysisTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return AnalysisListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=total,
    )


@router.get("/{task_id}", response_model=AnalysisTaskResponse)
def get_analysis(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = (
        db.query(AnalysisTask)
        .filter(
            AnalysisTask.id == task_id,
            AnalysisTask.user_id == current_user.id,
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Analysis task not found")
    return _task_to_response(task)


@router.delete("/{task_id}", status_code=204)
def delete_analysis(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = (
        db.query(AnalysisTask)
        .filter(
            AnalysisTask.id == task_id,
            AnalysisTask.user_id == current_user.id,
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Analysis task not found")
    if task.status in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a running analysis",
        )
    db.delete(task)
    db.commit()
    manager.clear_buffer(task_id)


@router.websocket("/ws/{task_id}")
async def analysis_websocket(websocket: WebSocket, task_id: str):
    # Validate token BEFORE accepting the WebSocket handshake.
    # close() before accept() rejects the upgrade request entirely.
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    try:
        from app.dependencies import get_current_user as _get_user
        from fastapi.security import HTTPAuthorizationCredentials
        import app.db.database as _db_mod

        db = _db_mod.SessionLocal()
        try:
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            user = await _get_user(creds, db)
            task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
        finally:
            db.close()
    except Exception as e:
        logger.warning("WebSocket auth failed: %s", e)
        await websocket.close(code=4001)
        return

    if task is None or task.user_id != user.id:
        await websocket.close(code=4003)
        return

    await websocket.accept()
    logger.info("WebSocket connected for task %s", task_id)

    existing = manager.active.get(task_id)
    if existing is not None and existing is not websocket:
        try:
            await existing.close(code=4000)
        except Exception:
            pass

    # Snapshot buffered events and register the new WS in one synchronous
    # step (no await between them) so no event is lost or duplicated:
    # - Events before the snapshot → in the snapshot → replayed below.
    # - Events after registration → pushed directly to the WS, not buffered.
    snapshot = list(manager.get_buffered(task_id))
    manager.active[task_id] = websocket

    for msg in snapshot:
        try:
            await websocket.send_json(msg)
        except Exception:
            logger.warning("Failed to replay buffered event for task %s", task_id)
            break

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if manager.active.get(task_id) is websocket:
            manager.active.pop(task_id, None)
        logger.info("WebSocket disconnected for task %s", task_id)


def _task_to_response(task: AnalysisTask) -> AnalysisTaskResponse:
    return AnalysisTaskResponse(
        id=task.id,
        ticker=task.ticker,
        asset_type=task.asset_type,
        trade_date=task.trade_date,
        status=task.status,
        signal=task.signal,
        rating=task.rating,
        final_report=task.final_report,
        agent_reports=task.agent_reports,
        token_usage=task.token_usage,
        error_message=task.error_message,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )
