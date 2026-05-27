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

    # 0. OneDrive safety check — refuse to boot if a scan root contains a
    #    OneDrive cache without that path being EXCLUDED. Reads through the
    #    Docker NTFS pass-through don't currently trigger Files-On-Demand
    #    dehydration (verified empirically), but we don't trust that to hold
    #    forever. Without this guard, a future scan could quietly hydrate the
    #    entire OneDrive library onto C:, blowing out local disk. The proper
    #    long-term fix is the host-side sidecar — see docs/onedrive-sidecar-plan.md.
    #
    #    Disable with FACETRACKER_ALLOW_ONEDRIVE_SCAN=1 only if you've read
    #    that doc and know what you're signing up for.
    import os as _os
    _allow_onedrive = _os.environ.get("FACETRACKER_ALLOW_ONEDRIVE_SCAN", "").strip() == "1"
    _onedrive_markers = ("OneDrive", "onedrive")
    _scan_roots = [getattr(d, "path", "") for d in (settings.drive_sources or [])]
    _excludes = list(settings.exclude_paths or [])
    _unsafe = []
    for root in _scan_roots:
        # walk root one level deep looking for OneDrive subdirs
        try:
            if not _os.path.isdir(root):
                continue
            for entry in _os.listdir(root):
                full = _os.path.join(root, entry)
                if not _os.path.isdir(full):
                    # also recurse one more level for /mnt/c/Users/<user>/OneDrive
                    continue
                if any(m in entry for m in _onedrive_markers):
                    if not any(full.startswith(ex) or ex.startswith(full) for ex in _excludes):
                        _unsafe.append(full)
                # check Users subdirs explicitly
                if entry == "Users":
                    try:
                        for user in _os.listdir(full):
                            udir = _os.path.join(full, user)
                            if not _os.path.isdir(udir):
                                continue
                            for child in _os.listdir(udir):
                                cfull = _os.path.join(udir, child)
                                if _os.path.isdir(cfull) and any(m in child for m in _onedrive_markers):
                                    if not any(cfull.startswith(ex) or ex.startswith(cfull) for ex in _excludes):
                                        _unsafe.append(cfull)
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            continue
    if _unsafe and not _allow_onedrive:
        msg = (
            "REFUSING TO START: scan roots contain OneDrive directories that are not in EXCLUDE_PATHS:\n  - "
            + "\n  - ".join(sorted(set(_unsafe)))
            + "\nA full scan could trigger Files-On-Demand dehydration and bloat C:.\n"
            + "Fix one of:\n"
            + "  (a) Add the path(s) above to EXCLUDE_PATHS in .env and restart, OR\n"
            + "  (b) Set FACETRACKER_ALLOW_ONEDRIVE_SCAN=1 if you've read docs/onedrive-sidecar-plan.md\n"
            + "      and accept the risk (NOT recommended without the sidecar)."
        )
        logger.error(msg)
        raise RuntimeError("OneDrive scan-safety check failed; see log above.")
    if _unsafe and _allow_onedrive:
        logger.warning(
            f"OneDrive paths under scan roots NOT excluded: {sorted(set(_unsafe))}. "
            "Override active via FACETRACKER_ALLOW_ONEDRIVE_SCAN=1. "
            "If you see C: drive bloat, abort scan and read docs/onedrive-sidecar-plan.md."
        )

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
