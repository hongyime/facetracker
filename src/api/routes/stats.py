"""Stats API routes for dashboard and monitoring."""

from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.config import settings
from src.storage.database import get_database, get_db_session, Image, Face, Identity

router = APIRouter(prefix="/stats")

def get_db():
    """Dependency to get database session — request-scoped, pool-safe."""
    yield from get_db_session(settings.database_url)

@router.get("")
async def get_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get overall system statistics."""
    total_faces = db.query(func.count(Face.id)).scalar()
    total_images = db.query(func.count(Image.id)).scalar()
    total_identities = db.query(func.count(Identity.id)).scalar()
    total_videos = db.query(func.count(Image.id)).filter(Image.is_video == True).scalar()
    
    files_processed = db.query(func.count(Image.id)).filter(Image.status == "completed").scalar()
    files_failed = db.query(func.count(Image.id)).filter(Image.status == "failed").scalar()
    
    return {
        "total_faces": total_faces or 0,
        "total_images": total_images or 0,
        "total_identities": total_identities or 0,
        "total_videos": total_videos or 0,
        "indexing": {
            "files_processed": files_processed or 0,
            "files_failed": files_failed or 0,
            "faces_per_image_avg": round(total_faces / total_images, 2) if total_images and total_faces else 0,
        }
    }

@router.get("/scan-progress")
async def get_scan_progress(request: Request) -> Dict[str, Any]:
    """Get current scan progress."""
    indexing_manager = getattr(request.app.state, "indexing_manager", None)
    
    if indexing_manager:
        return indexing_manager.get_progress()
        
    return {
        "is_scanning": False,
        "current_file": None,
        "files_scanned": 0,
        "files_total": 0,
        "progress_percent": 0,
        "eta_seconds": None,
    }

@router.get("/onedrive")
async def get_onedrive_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """OneDrive ingestion + eviction status.

    Reports:
    - ingested_count: OneDrive files in DB
    - revert_pending: files awaiting host-side `attrib +U -P` (the
                      onedrive_evict.ps1 daemon should drain these hourly)
    - evict_log_age_seconds: how long ago the daemon last ran. None if
                             the log file doesn't exist.
    - evict_healthy: True if pending=0 OR daemon ran in last 6h.

    Dashboard surfaces unhealthy state as a banner so we don't silently
    accumulate C: drive bloat.
    """
    from sqlalchemy import or_
    import os as _os
    import time as _time

    ingested = db.query(func.count(Image.id)).filter(
        or_(
            Image.file_path.like("%/OneDrive/%"),
            Image.file_path.like("%/OneDrive - %"),
        )
    ).scalar() or 0

    pending = db.query(func.count(Image.id)).filter(
        Image.onedrive_revert_pending == True  # noqa: E712
    ).scalar() or 0

    evict_log = "/mnt/c/facetracker/logs/onedrive_evict.log"
    evict_age = None
    if _os.path.exists(evict_log):
        try:
            evict_age = int(_time.time() - _os.path.getmtime(evict_log))
        except OSError:
            evict_age = None

    # Healthy if either: no work pending, OR daemon ran recently.
    healthy = (pending == 0) or (evict_age is not None and evict_age < 21600)

    return {
        "ingested_count": int(ingested),
        "revert_pending": int(pending),
        "evict_log_age_seconds": evict_age,
        "evict_healthy": bool(healthy),
        "message": (
            f"OneDrive eviction daemon healthy. {pending} pending, "
            f"last run {evict_age}s ago."
            if healthy else
            f"WARNING: {pending} OneDrive files awaiting eviction. "
            f"Daemon last ran {evict_age}s ago "
            "(threshold 6h). Schedule scripts/onedrive_evict.ps1 in "
            "Task Scheduler or run manually to prevent C: bloat."
        ),
    }

@router.get("/recent-activity")
async def get_recent_activity(limit: int = 50) -> Dict[str, Any]:
    """Get recent indexing activity.

    NOT IMPLEMENTED — returns HTTP 501 rather than a fabricated empty list.
    """
    raise HTTPException(status_code=501, detail="stats.recent-activity is not implemented yet")
