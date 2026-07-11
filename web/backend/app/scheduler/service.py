import asyncio
import contextlib
import logging
import threading
import uuid
from datetime import datetime, timezone

from croniter import croniter
from sqlalchemy.orm import Session

from app.db import database as _db_mod
from app.db.models import AnalysisTask, ScheduledJob

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None

TICK_INTERVAL_SECONDS = 60


def compute_next_run(cron_expr: str, base: datetime | None = None) -> datetime:
    """Return the next firing time (UTC) for ``cron_expr`` after ``base``.

    croniter works with naive datetimes by default; we feed it UTC and attach
    tzinfo on the way out so the stored value is timezone-aware.
    """
    base = base or datetime.now(timezone.utc)
    naive_utc = base.astimezone(timezone.utc).replace(tzinfo=None)
    cron = croniter(cron_expr, naive_utc)
    next_naive = cron.get_next(datetime)
    return next_naive.replace(tzinfo=timezone.utc)


def validate_cron(cron_expr: str) -> bool:
    try:
        croniter(cron_expr, datetime.now(timezone.utc))
        return True
    except Exception:
        return False


def _build_task_config(job: ScheduledJob) -> dict:
    return {
        "ticker": job.ticker,
        "asset_type": job.asset_type or "stock",
        "analysts": job.analysts or ["market", "social", "news", "fundamentals"],
        "research_depth": job.research_depth or 2,
        "llm_provider": job.llm_provider or "openai",
        "backend_url": job.backend_url,
        "quick_think_llm": job.quick_think_llm,
        "deep_think_llm": job.deep_think_llm,
        "output_language": job.output_language or "English",
        "google_thinking_level": job.google_thinking_level,
        "openai_reasoning_effort": job.openai_reasoning_effort,
        "anthropic_effort": job.anthropic_effort,
        # trade_date is filled in per-run below.
    }


def trigger_job_run(job_id: str) -> str:
    """Create and run an AnalysisTask for a scheduled job immediately.

    Runs the (blocking) analysis in a background daemon thread so the caller
    (scheduler tick or manual ``POST /run``) is not blocked. Returns the
    created AnalysisTask id.
    """
    db: Session = _db_mod.SessionLocal()
    try:
        job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
        if job is None:
            raise ValueError(f"ScheduledJob {job_id} not found")

        trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        config = _build_task_config(job)
        config["trade_date"] = trade_date

        task_id = str(uuid.uuid4())
        task = AnalysisTask(
            id=task_id,
            user_id=job.created_by,
            ticker=job.ticker,
            asset_type=job.asset_type or "stock",
            trade_date=trade_date,
            status="pending",
            config=config,
            scheduled_job_id=job.id,
        )
        db.add(task)
        db.commit()

        thread = threading.Thread(
            target=_run_headless,
            args=(task_id, config, job.created_by),
            daemon=True,
            name=f"scheduled-job-{job_id}",
        )
        thread.start()
        logger.info("Scheduled job %s triggered, analysis task %s", job_id, task_id)
        return task_id
    finally:
        db.close()


def _run_headless(task_id: str, config: dict, user_id: str):
    from app.analysis.runner import run_analysis_task

    run_analysis_task(task_id, config, user_id, loop=None, headless=True)


async def _tick():
    """Scan for due jobs and fire them."""
    db: Session = _db_mod.SessionLocal()
    fired: list[tuple[str, str]] = []
    try:
        now = datetime.now(timezone.utc)
        due_jobs = (
            db.query(ScheduledJob)
            .filter(ScheduledJob.enabled == True)  # noqa: E712
            .filter(ScheduledJob.next_run_at.isnot(None))
            .filter(ScheduledJob.next_run_at <= now)
            .all()
        )
        for job in due_jobs:
            try:
                task_id = trigger_job_run(job.id)
                job.last_run_at = now
                job.last_task_id = task_id
                job.last_error = None
                job.next_run_at = compute_next_run(job.cron_expr, now)
                fired.append((job.id, task_id))
            except Exception as exc:
                logger.exception("Failed to fire scheduled job %s", job.id)
                job.last_error = str(exc)
                job.next_run_at = compute_next_run(job.cron_expr, now)
        if fired:
            db.commit()
    finally:
        db.close()

    if fired:
        logger.info("Scheduler tick fired %d job(s): %s", len(fired), fired)


async def _scheduler_loop():
    assert _stop_event is not None
    logger.info("Scheduler loop started (tick=%ss)", TICK_INTERVAL_SECONDS)
    while not _stop_event.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("Scheduler tick error")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_stop_event.wait(), timeout=TICK_INTERVAL_SECONDS)
    logger.info("Scheduler loop stopped")


def start_scheduler():
    global _scheduler_task, _stop_event
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _stop_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_scheduler_loop())


async def stop_scheduler():
    global _scheduler_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _scheduler_task is not None:
        try:
            await asyncio.wait_for(_scheduler_task, timeout=10)
        except asyncio.TimeoutError:
            _scheduler_task.cancel()
        _scheduler_task = None
    _stop_event = None
