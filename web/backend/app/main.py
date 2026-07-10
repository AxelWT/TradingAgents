import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

from app.config import get_settings
from app.db.database import init_db, create_tables
from app.auth.router import router as auth_router
from app.analysis.router import router as analysis_router
from app.reports.router import router as reports_router
from app.ticker.router import router as ticker_router
from app.admin.router import router as admin_router
from app.auth.security import hash_password
from app.db.models import User


def bootstrap_admin():
    """If ADMIN_EMAIL + ADMIN_PASSWORD are configured, ensure the admin account exists."""
    settings = get_settings()
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return

    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if existing is None:
            admin = User(
                id=str(uuid.uuid4()),
                email=settings.ADMIN_EMAIL,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                is_admin=True,
                is_active=True,
                is_whitelisted=True,
            )
            db.add(admin)
            db.commit()
            logging.getLogger(__name__).info(
                "bootstrap: created admin account %s", settings.ADMIN_EMAIL
            )
        elif not existing.is_admin:
            existing.is_admin = True
            existing.is_active = True
            db.commit()
            logging.getLogger(__name__).info(
                "bootstrap: promoted %s to admin", settings.ADMIN_EMAIL
            )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    create_tables()
    bootstrap_admin()
    yield


app = FastAPI(
    title="TradingAgents API",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix=settings.API_PREFIX)
app.include_router(analysis_router, prefix=settings.API_PREFIX)
app.include_router(reports_router, prefix=settings.API_PREFIX)
app.include_router(ticker_router, prefix=settings.API_PREFIX)
app.include_router(admin_router, prefix=settings.API_PREFIX)


@app.get("/health")
def health_check():
    return {"status": "ok"}


frontend_dist = Path(os.getenv("FRONTEND_DIST", "/app/web/frontend/dist"))

if frontend_dist.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=frontend_dist / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        candidate = frontend_dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        index = frontend_dist / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404)
        return FileResponse(index)
