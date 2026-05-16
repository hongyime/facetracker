"""Stats API routes for dashboard and monitoring."""

from fastapi import APIRouter, Depends
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.config import settings
from src.storage.database import get_database, Image, Face, Identity

router = APIRouter(prefix="/stats")

def get_db():
    """Dependency to get database session."""
    db = get_database(settings.database_url)
    try:
        yield db.session
    finally:
        pass

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
async def get_scan_progress() -> Dict[str, Any]:
    """Get current scan progress."""
    return {
        "is_scanning": False,
        "current_file": None,
        "files_scanned": 0,
        "files_total": 0,
        "progress_percent": 0,
        "eta_seconds": None,
    }

@router.get("/onedrive")
async def get_onedrive_stats() -> Dict[str, Any]:
    """Get OneDrive-specific statistics."""
    return {
        "files_processed": 0,
        "files_online_only": 0,
        "space_saved_mb": 0,
        "download_failures": 0,
        "revert_failures": 0,
    }

@router.get("/recent-activity")
async def get_recent_activity(limit: int = 50) -> Dict[str, Any]:
    """Get recent indexing activity."""
    return {
        "activities": [],
        "total": 0,
    }
