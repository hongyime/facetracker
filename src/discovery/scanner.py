"""Efficient parallel file scanner with generator-based yields."""

import os
from pathlib import Path
from typing import Generator, List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json

from src.config import Settings


@dataclass
class FileRecord:
    """Record of a discovered file."""
    path: str
    size: int
    mtime: float
    extension: str
    drive_type: str = "local"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "extension": self.extension,
            "drive_type": self.drive_type,
        }


class DriveScanner:
    """
    Efficient parallel file scanner.
    
    Uses os.scandir() for fast directory traversal and ThreadPoolExecutor
    for parallel scanning of multiple drives.
    """
    
    def __init__(self, config: Settings):
        """
        Initialize the drive scanner.
        
        Args:
            config: Application settings
        """
        self.config = config
        self.exclude_paths = set(config.exclude_paths)
        self.supported_extensions = set(config.all_supported_extensions)
        
        # Parse drive sources
        self.drive_sources = []
        if config.drive_sources:
            for source in config.drive_sources:
                if not source.exclude:
                    self.drive_sources.append(source)
    
    def scan_drives(self, batch_size: int = 1000) -> Generator[List[FileRecord], None, None]:
        """
        Scan all configured drives in parallel.
        
        Args:
            batch_size: Number of files to yield per batch
            
        Yields:
            Batches of FileRecord objects
        """
        if not self.drive_sources:
            # Scan default drives
            self.drive_sources = [
                {"path": "C:/", "type": "local"},
                {"path": "D:/", "type": "local"},
            ]
        
        buffer: List[FileRecord] = []
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            
            for source in self.drive_sources:
                path = source.get("path") if isinstance(source, dict) else source.path
                future = executor.submit(self._scan_single_drive, path)
                futures[future] = path
            
            for future in as_completed(futures):
                drive_path = futures[future]
                try:
                    for record in future.result():
                        buffer.append(record)
                        
                        if len(buffer) >= batch_size:
                            yield buffer
                            buffer = []
                            
                except Exception as e:
                    print(f"Error scanning {drive_path}: {e}")
        
        # Yield remaining files
        if buffer:
            yield buffer
    
    def _scan_single_drive(self, drive_path: str) -> Generator[FileRecord, None, None]:
        """
        Scan a single drive recursively.
        
        Args:
            drive_path: Root path to scan
            
        Yields:
            FileRecord objects for matching files
        """
        drive_path = Path(drive_path)
        
        if not drive_path.exists():
            return
        
        # Check if drive is in exclude paths
        if str(drive_path) in self.exclude_paths:
            return
        
        try:
            for root, dirs, files in self._scandir_recursive(str(drive_path)):
                for filename in files:
                    file_path = Path(root) / filename
                    
                    # Check extension
                    ext = file_path.suffix.lower()
                    if ext not in self.supported_extensions:
                        continue
                    
                    # Check exclusion paths
                    if self._is_excluded(file_path):
                        continue
                    
                    try:
                        stat = file_path.stat()
                        yield FileRecord(
                            path=str(file_path),
                            size=stat.st_size,
                            mtime=stat.st_mtime,
                            extension=ext,
                            drive_type="local",
                        )
                    except (OSError, IOError):
                        # Skip inaccessible files
                        continue
                        
        except PermissionError:
            print(f"Permission denied: {drive_path}")
        except Exception as e:
            print(f"Error scanning {drive_path}: {e}")
    
    def _scandir_recursive(self, path: str) -> Generator[tuple, None, None]:
        """
        Recursively scan directories using os.scandir().
        
        Args:
            path: Directory path to scan
            
        Yields:
            Tuples of (root, dirs, files) like os.walk()
        """
        try:
            entries = list(os.scandir(path))
        except (PermissionError, OSError):
            return
        
        dirs = []
        files = []
        
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    # Skip excluded directories
                    if str(entry.path) not in self.exclude_paths:
                        dirs.append(entry.name)
                elif entry.is_file(follow_symlinks=False):
                    files.append(entry.name)
            except (PermissionError, OSError):
                continue
        
        if files:
            yield (path, dirs, files)
        
        # Recurse into subdirectories
        for dir_name in dirs:
            subdir = os.path.join(path, dir_name)
            yield from self._scandir_recursive(subdir)
    
    def _is_excluded(self, file_path: Path) -> bool:
        """
        Check if a file path should be excluded.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if excluded
        """
        path_str = str(file_path)
        
        for exclude_path in self.exclude_paths:
            if path_str.startswith(exclude_path):
                return True
        
        return False
    
    def scan_directory(self, directory: str, batch_size: int = 1000) -> Generator[List[FileRecord], None, None]:
        """
        Scan a single directory.
        
        Args:
            directory: Directory path to scan
            batch_size: Number of files per batch
            
        Yields:
            Batches of FileRecord objects
        """
        buffer: List[FileRecord] = []
        
        for record in self._scan_single_drive(directory):
            buffer.append(record)
            
            if len(buffer) >= batch_size:
                yield buffer
                buffer = []
        
        if buffer:
            yield buffer
