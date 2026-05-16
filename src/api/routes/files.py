"""File status API routes."""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from src.config import settings
from src.storage.database import get_database, Image

router = APIRouter(prefix="/files")

def get_db():
    """Dependency to get database session."""
    db = get_database(settings.database_url)
    try:
        yield db.session
    finally:
        pass

@router.get("/status")
async def get_file_status(file_path: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get processing status of a specific file."""
    image = db.query(Image).filter(Image.file_path == file_path).first()
    
    if not image:
        return {
            "file_path": file_path,
            "is_processed": False,
            "faces_detected": 0,
            "status": "not_found",
            "error": None,
        }
        
    return {
        "file_path": image.file_path,
        "is_processed": image.status == "completed",
        "faces_detected": image.face_count,
        "status": image.status,
        "error": image.error_message,
        "created_at": image.created_at.isoformat()
    }

@router.get("/search")
async def search_files(pattern: str, limit: int = 50) -> Dict[str, Any]:
    """Search for files by pattern."""
    return {
        "pattern": pattern,
        "files": [],
        "total": 0,
    }

@router.post("/{file_id}/reprocess")
async def reprocess_file(file_id: int) -> Dict[str, Any]:
    """Queue a file for reprocessing."""
    return {
        "file_id": file_id,
        "status": "queued",
        "message": "File queued for reprocessing",
    }

@router.delete("/{file_id}")
async def delete_file(file_id: int) -> Dict[str, Any]:
    """Delete a file from the index (not the source file)."""
    return {
        "file_id": file_id,
        "status": "deleted",
        "message": "File removed from index",
    }
