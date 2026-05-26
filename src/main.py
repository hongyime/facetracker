"""Main FastAPI application for Face Tracker."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import redis

from src.config import settings, get_settings
from src.utils.logging import setup_logging, get_logger
from src.storage.database import get_database, Base
from src.storage.faiss_index import BatchedFAISSIndex
from src.storage.outbox import FaissReaper, FaissOutbox  # noqa: F401  (FaissOutbox import ensures table is registered with Base)
from src.pipeline.processor import PipelineProcessor
from src.discovery.manifest import FileManifestManager
from src.discovery.watcher import FileWatcher
from src.discovery.manager import IndexingManager
from src.api.routes import search, identity, stats, files
from pathlib import Path

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown.

    Lifecycle order matters:

      startup:  db -> faiss -> reaper -> processor -> indexing manager
      shutdown: indexing manager -> reaper -> db

    The reaper is started BEFORE the indexing manager so any face the
    pipeline writes is drained immediately. It is stopped AFTER the
    indexing manager so the last few outbox rows the pipeline emitted
    are flushed before we exit.
    """
    # Startup
    logger.info("Starting Face Tracker API...")

    setup_logging(settings.log_level)

    # 1. Database (engine + SessionLocal)
    db = get_database(settings.database_url)
    db.create_tables()  # creates faiss_outbox via the FaissOutbox import above
    logger.info("Database connected")

    # 2. FAISS index (in-memory + on-disk)
    faiss_index = BatchedFAISSIndex(settings)

    # 3. Outbox reaper — runs whenever the API is up, regardless of whether
    #    the indexing manager is actively scanning. Keeps recently-ingested
    #    faces searchable within `faiss_reaper_poll_ms` of their DB commit.
    reaper = FaissReaper(
        database=db,
        faiss_index=faiss_index,
        poll_interval_ms=settings.faiss_reaper_poll_ms,
        batch_size=settings.faiss_reaper_batch_size,
        stuck_timeout_s=settings.faiss_reaper_stuck_timeout_s,
        max_attempts=settings.faiss_reaper_max_attempts,
    )
    reaper.start()
    app.state.faiss_reaper = reaper

    # 4. Pipeline processor — does NOT touch FAISS directly anymore;
    #    writes go through the outbox.
    processor = PipelineProcessor(
        db=db,
        faiss_index=faiss_index,
        thumbnail_cache_path=Path(settings.thumbnail_cache_path)
    )

    # 5. Discovery + indexing manager (workers open per-file Sessions)
    manifest = FileManifestManager(settings)
    watcher = FileWatcher(settings)
    app.state.indexing_manager = IndexingManager(
        config=settings,
        processor=processor,
        manifest=manifest,
        watcher=watcher,
        db=db,
    )
    app.state.indexing_manager.start()

    logger.info("Face Tracker API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Face Tracker API...")

    mgr = getattr(app.state, "indexing_manager", None)
    if mgr is not None:
        try:
            mgr.stop()
        except Exception as e:
            logger.error(f"Error stopping indexing manager: {e}")

    rpr = getattr(app.state, "faiss_reaper", None)
    if rpr is not None:
        try:
            rpr.stop()
        except Exception as e:
            logger.error(f"Error stopping FAISS reaper: {e}")

    db.close()
    logger.info("Database connection closed")


# Create FastAPI application
app = FastAPI(
    title="Face Tracker API",
    description="Private face search engine API",
    version="4.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5151", "http://localhost:3000", "http://localhost:8700", "http://127.0.0.1:5151", "http://127.0.0.1:8700"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(search.router, prefix="/api/v1", tags=["search"])
app.include_router(identity.router, prefix="/api/v1", tags=["identity"])
app.include_router(stats.router, prefix="/api/v1", tags=["stats"])
app.include_router(files.router, prefix="/api/v1", tags=["files"])


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Face Tracker API",
        "version": "4.0.0",
        "description": "Private face search engine",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.dashboard_port,
        reload=False,
    )
