import logging
import os
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    create_tables()
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
