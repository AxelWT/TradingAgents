import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ScheduledJob, User
from app.dependencies import get_current_admin
from app.scheduler.schemas import (
    ScheduledJobCreateRequest,
    ScheduledJobListResponse,
    ScheduledJobResponse,
    ScheduledJobRunResponse,
    ScheduledJobUpdateRequest,
)
from app.scheduler.service import compute_next_run, trigger_job_run, validate_cron

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scheduled-jobs", tags=["admin"])


def _job_to_response(job: ScheduledJob) -> ScheduledJobResponse:
    return ScheduledJobResponse(
        id=job.id,
        name=job.name,
        ticker=job.ticker,
        asset_type=job.asset_type or "stock",
        analysts=job.analysts,
        research_depth=job.research_depth or 2,
        llm_provider=job.llm_provider or "openai",
        backend_url=job.backend_url,
        quick_think_llm=job.quick_think_llm,
        deep_think_llm=job.deep_think_llm,
        output_language=job.output_language or "English",
        google_thinking_level=job.google_thinking_level,
        openai_reasoning_effort=job.openai_reasoning_effort,
        anthropic_effort=job.anthropic_effort,
        cron_expr=job.cron_expr,
        enabled=job.enabled,
        created_by=job.created_by,
        created_at=job.created_at,
        next_run_at=job.next_run_at,
        last_run_at=job.last_run_at,
        last_task_id=job.last_task_id,
        last_error=job.last_error,
    )


@router.post("", response_model=ScheduledJobResponse, status_code=201)
def create_job(
    req: ScheduledJobCreateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not validate_cron(req.cron_expr):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cron expression: {req.cron_expr}",
        )
    if not req.analysts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one analyst must be selected",
        )

    job = ScheduledJob(
        id=str(uuid.uuid4()),
        name=req.name,
        ticker=req.ticker,
        asset_type=req.asset_type,
        analysts=req.analysts,
        research_depth=req.research_depth,
        llm_provider=req.llm_provider,
        backend_url=req.backend_url,
        quick_think_llm=req.quick_think_llm,
        deep_think_llm=req.deep_think_llm,
        output_language=req.output_language,
        google_thinking_level=req.google_thinking_level,
        openai_reasoning_effort=req.openai_reasoning_effort,
        anthropic_effort=req.anthropic_effort,
        cron_expr=req.cron_expr,
        enabled=req.enabled,
        created_by=admin.id,
        next_run_at=compute_next_run(req.cron_expr) if req.enabled else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info("admin %s created scheduled job %s (%s)", admin.email, job.id, job.name)
    return _job_to_response(job)


@router.get("", response_model=ScheduledJobListResponse)
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(ScheduledJob)
    total = query.count()
    jobs = (
        query.order_by(ScheduledJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ScheduledJobListResponse(jobs=[_job_to_response(j) for j in jobs], total=total)


@router.get("/{job_id}", response_model=ScheduledJobResponse)
def get_job(
    job_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    return _job_to_response(job)


@router.patch("/{job_id}", response_model=ScheduledJobResponse)
def update_job(
    job_id: str,
    req: ScheduledJobUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    updates = req.model_dump(exclude_unset=True)

    if "analysts" in updates and not updates["analysts"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one analyst must be selected",
        )

    cron_changed = "cron_expr" in updates
    if cron_changed and not validate_cron(updates["cron_expr"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cron expression: {updates['cron_expr']}",
        )

    for key, value in updates.items():
        setattr(job, key, value)

    # Recompute next_run_at when cron or enabled changes.
    if cron_changed or "enabled" in updates:
        if job.enabled:
            job.next_run_at = compute_next_run(job.cron_expr)
        else:
            job.next_run_at = None

    db.commit()
    db.refresh(job)
    logger.info("admin %s updated scheduled job %s", admin.email, job.id)
    return _job_to_response(job)


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    db.delete(job)
    db.commit()
    logger.info("admin %s deleted scheduled job %s", admin.email, job.id)


@router.post("/{job_id}/run", response_model=ScheduledJobRunResponse)
def run_job_now(
    job_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    task_id = trigger_job_run(job.id)
    logger.info(
        "admin %s manually triggered scheduled job %s -> task %s", admin.email, job.id, task_id
    )
    return ScheduledJobRunResponse(
        task_id=task_id,
        message="Analysis started. The report will appear in Reports once complete.",
    )
