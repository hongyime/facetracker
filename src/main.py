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

    # 0. OneDrive eviction-daemon health check.
    #
    # OneDrive Files-On-Demand: when the container reads a cloud-only file,
    # the bytes get hydrated to local C: cache. Without an eviction daemon
    # those bytes stay forever and C: bloats unbounded. The Windows-host
    # daemon (scripts/onedrive_evict.ps1) polls images.onedrive_revert_pending
    # and runs `attrib +U -P` to flag files for re-eviction.
    #
    # Boot-time check: if there are >0 pending rows AND the eviction log shows
    # no run in the last 6h, log a warning. We don't refuse to boot — the
    # daemon may legitimately be late (host rebooted, schtasks missed a run)
    # and we don't want a transient daemon failure to take down the API.
    #
    # Set FACETRACKER_DISABLE_ONEDRIVE_HEALTHCHECK=1 to suppress this entirely.
    import os as _os
    if _os.environ.get("FACETRACKER_DISABLE_ONEDRIVE_HEALTHCHECK", "").strip() != "1":
        try:
            _evict_log = "/mnt/c/facetracker/logs/onedrive_evict.log"
            _stale = True
            if _os.path.exists(_evict_log):
                import time as _time
                _age = _time.time() - _os.path.getmtime(_evict_log)
                _stale = _age > 21600  # 6 hours
            if _stale:
                logger.warning(
                    "OneDrive eviction daemon log is stale or missing "
                    f"(path={_evict_log}). If you're scanning OneDrive, "
                    "schedule scripts/onedrive_evict.ps1 hourly via Task Scheduler "
                    "or C: bloat will accumulate. See docs/onedrive-sidecar-plan.md."
                )
        except Exception as _e:
            logger.debug(f"OneDrive health check skipped: {_e}")

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
    allow_origins=["http://localhost:5454", "http://localhost:3000", "http://localhost:8700", "http://localhost:8701", "http://127.0.0.1:5454", "http://127.0.0.1:8700", "http://127.0.0.1:8701"],
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
