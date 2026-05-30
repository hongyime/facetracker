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
        # Legacy aliases (kept for dashboard JS).
        "files_scanned": 0,
        "files_total": 0,
        # Three-counter view (3A).
        "files_discovered": 0,
        "files_queued": 0,
        "files_skipped": 0,
        "files_processed": 0,
        "files_failed": 0,
        "progress_percent": 0,
        "eta_seconds": None,
        "per_drive": {},
        "queue_depth": 0,
        "queue_high_water_mark": 0,
        "processing_rate_per_sec": None,
        "processing_eta_seconds": None,
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
    - audit_log_age_seconds: how long ago the auditor last ran (verifies
                             eviction actually completed; runs every 6h).
    - evict_healthy: True if (pending<=threshold) AND (daemon ran in last 6h)
                     AND (auditor ran in last 30h). False if any signal is
                     stale or pending grew past the threshold (indicates
                     daemon is firing but OneDrive is rejecting evictions).

    Dashboard surfaces unhealthy state as a banner so we don't silently
    accumulate C: drive bloat or let the auditor go dormant.
    """
    from sqlalchemy import or_
    import os as _os
    import time as _time

    # Tunable: number of pending rows beyond which the eviction daemon is
    # presumed unable to keep up. At 17k faces / 14k identities the steady
    # state is ~0; a single ingest wave bumps this temporarily. 100 is a
    # large enough headroom that one batch ingest won't trip the alarm,
    # and small enough that a real failure mode (signals fired but
    # OneDrive rejecting them) shows within ~2 hourly runs.
    PENDING_CEILING = 100
    EVICT_STALE_SECONDS = 21600  # 6h (daemon runs hourly; allow several misses)
    AUDIT_STALE_SECONDS = 108000  # 30h (auditor runs 6-hourly; allow >1 miss)

    ingested = db.query(func.count(Image.id)).filter(
        or_(
            Image.file_path.like("%/OneDrive/%"),
            Image.file_path.like("%/OneDrive - %"),
        )
    ).scalar() or 0

    pending = db.query(func.count(Image.id)).filter(
        Image.onedrive_revert_pending == True  # noqa: E712
    ).scalar() or 0

    def _log_age(path: str):
        if not _os.path.exists(path):
            return None
        try:
            return int(_time.time() - _os.path.getmtime(path))
        except OSError:
            return None

    evict_age = _log_age("/mnt/c/facetracker/logs/onedrive_evict.log")
    audit_age = _log_age("/mnt/c/facetracker/logs/onedrive_audit.log")

    # Compose health signal. Order matters for the message: most actionable
    # failure first.
    reasons = []
    if pending > PENDING_CEILING:
        reasons.append(
            f"pending={pending} exceeds ceiling={PENDING_CEILING} "
            f"(daemon firing but evictions not landing; check OneDrive sync state)"
        )
    if evict_age is None or evict_age > EVICT_STALE_SECONDS:
        reasons.append(
            f"eviction daemon stale (last_run={evict_age}s ago, threshold={EVICT_STALE_SECONDS}s); "
            f"check FacetrackerOneDriveEvict scheduled task"
        )
    if audit_age is None or audit_age > AUDIT_STALE_SECONDS:
        reasons.append(
            f"audit daemon stale (last_run={audit_age}s ago, threshold={AUDIT_STALE_SECONDS}s); "
            f"check FacetrackerOneDriveAudit scheduled task"
        )

    healthy = len(reasons) == 0

    if healthy:
        message = (
            f"OneDrive eviction daemon healthy. {pending} pending, "
            f"evict last_run={evict_age}s ago, audit last_run={audit_age}s ago."
        )
    else:
        message = "WARNING: " + "; ".join(reasons)

    return {
        "ingested_count": int(ingested),
        "revert_pending": int(pending),
        "evict_log_age_seconds": evict_age,
        "audit_log_age_seconds": audit_age,
        "evict_healthy": bool(healthy),
        "pending_ceiling": PENDING_CEILING,
        "message": message,
    }

@router.get("/recent-activity")
async def get_recent_activity(limit: int = 50) -> Dict[str, Any]:
    """Get recent indexing activity.

    NOT IMPLEMENTED — returns HTTP 501 rather than a fabricated empty list.
    """
    raise HTTPException(status_code=501, detail="stats.recent-activity is not implemented yet")
