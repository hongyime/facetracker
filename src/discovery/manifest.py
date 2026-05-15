"""File manifest manager for incremental updates."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from src.config import Settings
from src.utils.atomic import atomic_write_json


class FileManifestManager:
    """
    Manages file manifest for tracking processed files.
    
    The manifest enables incremental updates by tracking:
    - File paths and hashes
    - Modification times and sizes
    - Processing status
    - Deleted files
    """
    
    def __init__(self, config: Settings):
        """
        Initialize the manifest manager.
        
        Args:
            config: Application settings
        """
        self.config = config
        self.manifest_path = Path(config.face_storage_root) / "state" / "file_manifest.json"
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # In-memory manifest cache
        self._manifest: Optional[Dict[str, Any]] = None
    
    @property
    def manifest(self) -> Dict[str, Any]:
        """Load manifest from disk if not cached."""
        if self._manifest is None:
            self._manifest = self._load_manifest()
        return self._manifest
    
    def _load_manifest(self) -> Dict[str, Any]:
        """
        Load manifest from disk.
        
        Returns:
            Manifest dictionary
        """
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading manifest: {e}")
        
        return {
            "files": {},
            "deleted": [],
            "last_updated": datetime.utcnow().isoformat(),
        }
    
    def save_manifest(self) -> None:
        """Save manifest to disk atomically."""
        self.manifest["last_updated"] = datetime.utcnow().isoformat()
        atomic_write_json(self.manifest_path, self.manifest)
        self._manifest = None  # Invalidate cache
    
    def add_file(
        self,
        file_path: str,
        file_hash: str,
        file_size: int,
        file_mtime: float,
        is_processed: bool = False,
    ) -> None:
        """
        Add or update a file in the manifest.
        
        Args:
            file_path: Full file path
            file_hash: SHA256 hash of file
            file_size: File size in bytes
            file_mtime: File modification time
            is_processed: Whether file has been processed
        """
        self.manifest["files"][file_path] = {
            "path": file_path,
            "hash": file_hash,
            "size": file_size,
            "mtime": file_mtime,
            "is_processed": is_processed,
            "added_at": datetime.utcnow().isoformat(),
        }
    
    def get_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get file record from manifest.
        
        Args:
            file_path: File path to look up
            
        Returns:
            File record or None if not found
        """
        return self.manifest["files"].get(file_path)
    
    def needs_processing(self, file_path: str, current_mtime: float, current_size: int) -> bool:
        """
        Check if a file needs processing.
        
        A file needs processing if:
        - It's not in the manifest
        - It has been modified (mtime changed)
        - It has a different size
        
        Args:
            file_path: File path to check
            current_mtime: Current modification time
            current_size: Current file size
            
        Returns:
            True if file needs processing
        """
        record = self.get_file(file_path)
        
        if record is None:
            return True
        
        if record.get("is_processed", False):
            # Check if file has changed
            if abs(record.get("mtime", 0) - current_mtime) > 1:
                return True
            if record.get("size", 0) != current_size:
                return True
        
        return False
    
    def mark_processed(self, file_path: str) -> None:
        """
        Mark a file as processed.
        
        Args:
            file_path: File path to mark
        """
        if file_path in self.manifest["files"]:
            self.manifest["files"][file_path]["is_processed"] = True
            self.manifest["files"][file_path]["processed_at"] = datetime.utcnow().isoformat()
    
    def mark_deleted(self, file_path: str) -> None:
        """
        Mark a file as deleted.
        
        Args:
            file_path: File path to mark as deleted
        """
        if file_path in self.manifest["files"]:
            # Move to deleted list
            record = self.manifest["files"].pop(file_path)
            record["deleted_at"] = datetime.utcnow().isoformat()
            self.manifest["deleted"].append(record)
    
    def get_unprocessed_files(self) -> List[Dict[str, Any]]:
        """
        Get all unprocessed files.
        
        Returns:
            List of unprocessed file records
        """
        return [
            record for record in self.manifest["files"].values()
            if not record.get("is_processed", False)
        ]
    
    def get_processed_count(self) -> int:
        """
        Get count of processed files.
        
        Returns:
            Number of processed files
        """
        return sum(
            1 for record in self.manifest["files"].values()
            if record.get("is_processed", False)
        )
    
    def get_total_count(self) -> int:
        """
        Get total count of files in manifest.
        
        Returns:
            Total number of files
        """
        return len(self.manifest["files"])
    
    def get_deleted_count(self) -> int:
        """
        Get count of deleted files.
        
        Returns:
            Number of deleted files
        """
        return len(self.manifest["deleted"])
    
    def cleanup_deleted(self, max_age_days: int = 30) -> None:
        """
        Clean up old deleted file records.
        
        Args:
            max_age_days: Maximum age of deleted records to keep
        """
        cutoff = datetime.utcnow().timestamp() - (max_age_days * 24 * 60 * 60)
        
        self.manifest["deleted"] = [
            record for record in self.manifest["deleted"]
            if datetime.fromisoformat(record.get("deleted_at", "1970-01-01")).timestamp() > cutoff
        ]
    
    def export_summary(self) -> Dict[str, Any]:
        """
        Export manifest summary statistics.
        
        Returns:
            Summary dictionary
        """
        return {
            "total_files": self.get_total_count(),
            "processed_files": self.get_processed_count(),
            "unprocessed_files": self.get_total_count() - self.get_processed_count(),
            "deleted_files": self.get_deleted_count(),
            "last_updated": self.manifest.get("last_updated"),
        }
