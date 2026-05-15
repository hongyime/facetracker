"""Stats API routes for dashboard and monitoring."""

from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter()


@router.get("/stats")
async def get_stats() -> Dict[str, Any]:
    """
    Get overall system statistics.
    
    Returns:
        Dashboard statistics
    """
    # Placeholder - would query database and FAISS index
    return {
        "total_faces": 0,
        "total_images": 0,
        "total_identities": 0,
        "total_videos": 0,
        "storage": {
            "faiss_index_size_mb": 0,
            "thumbnail_cache_mb": 0,
            "database_size_mb": 0,
        },
        "indexing": {
            "files_processed": 0,
            "files_pending": 0,
            "faces_per_image_avg": 0,
        },
    }


@router.get("/stats/scan-progress")
async def get_scan_progress() -> Dict[str, Any]:
    """
    Get current scan progress.
    
    Returns:
        Scan status and progress
    """
    return {
        "is_scanning": False,
        "current_file": None,
        "files_scanned": 0,
        "files_total": 0,
        "progress_percent": 0,
        "eta_seconds": None,
    }


@router.get("/stats/onedrive")
async def get_onedrive_stats() -> Dict[str, Any]:
    """
    Get OneDrive-specific statistics.
    
    Returns:
        OneDrive savings and status
    """
    return {
        "files_processed": 0,
        "files_online_only": 0,
        "space_saved_mb": 0,
        "download_failures": 0,
        "revert_failures": 0,
    }


@router.get("/stats/recent-activity")
async def get_recent_activity(limit: int = 50) -> Dict[str, Any]:
    """
    Get recent indexing activity.
    
    Args:
        limit: Number of events to return
        
    Returns:
        Recent activity log
    """
    return {
        "activities": [],
        "total": 0,
    }


@router.get("/stats/clustering")
async def get_clustering_stats() -> Dict[str, Any]:
    """
    Get clustering quality metrics.
    
    Returns:
        Clustering validation metrics
    """
    return {
        "total_clusters": 0,
        "verified_clusters": 0,
        "pending_verification": 0,
        "metrics": {
            "silhouette_score": None,
            "calinski_harabasz_index": None,
            "davies_bouldin_index": None,
        },
    }
