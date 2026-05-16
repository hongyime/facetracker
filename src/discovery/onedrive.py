"""OneDrive file handler with multi-faceted detection."""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import time

from src.config import Settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class OneDriveHandler:
    """
    Handles OneDrive placeholder files with multi-faceted detection.
    
    Detection methods:
    1. Reparse point check (symlink analysis)
    2. Cloud attribute check (Windows API)
    3. Size mismatch check (reported vs actual)
    
    Requires 2+ indicators to confirm OneDrive status.
    """
    
    def __init__(self, config: Settings):
        """
        Initialize the OneDrive handler.
        
        Args:
            config: Application settings
        """
        self.config = config
        self.enabled = config.onedrive_enabled
        self.download_timeout = config.onedrive_download_timeout
        self.max_retries = config.onedrive_max_retries
        self.revert_verify = config.onedrive_revert_verify
        self.multi_detect = config.onedrive_multi_detect
        
        # Temp directory for downloads
        self.temp_dir = Path(config.face_storage_root) / "cache" / "onedrive_temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def is_onedrive_path(self, file_path: str) -> bool:
        """
        Check if a file path is in a OneDrive directory.
        
        Args:
            file_path: File path to check
            
        Returns:
            True if path is in OneDrive
        """
        path_lower = file_path.lower()
        
        # Common OneDrive paths
        onedrive_indicators = [
            "/onedrive/",
            "\\onedrive\\",
            "/microsoft/onedrive/",
            "/skydrive/",
        ]
        
        return any(indicator in path_lower for indicator in onedrive_indicators)
    
    def detect_placeholder_status(self, file_path: str) -> Dict[str, Any]:
        """
        Detect OneDrive placeholder status using multiple methods.
        
        Args:
            file_path: Path to check
            
        Returns:
            Dictionary with detection results
        """
        result = {
            "is_placeholder": False,
            "is_online_only": False,
            "is_local": False,
            "has_reparse_point": False,
            "has_cloud_attribute": False,
            "size_mismatch": False,
            "confidence": 0,
        }
        
        path = Path(file_path)
        
        if not path.exists():
            return result
        
        try:
            # Method 1: Check reparse point (symlink)
            result["has_reparse_point"] = self._check_reparse_point(str(path))
            
            # Method 2: Check cloud attribute (via PowerShell)
            result["has_cloud_attribute"] = self._check_cloud_attribute(str(path))
            
            # Method 3: Check size mismatch
            result["size_mismatch"] = self._check_size_mismatch(str(path))
            
            # Count positive indicators
            indicators = sum([
                result["has_reparse_point"],
                result["has_cloud_attribute"],
                result["size_mismatch"],
            ])
            
            result["confidence"] = indicators / 3.0
            
            # Determine status based on indicators
            if self.multi_detect:
                # Require 2+ indicators for high confidence
                if indicators >= 2:
                    result["is_placeholder"] = True
                    result["is_online_only"] = True
                elif indicators == 1:
                    result["is_placeholder"] = True
                    result["is_local"] = False
            else:
                # Single indicator sufficient
                if indicators >= 1:
                    result["is_placeholder"] = True
                    result["is_online_only"] = True
            
            if not result["is_placeholder"]:
                result["is_local"] = True
                
        except Exception as e:
            print(f"Error detecting OneDrive status for {file_path}: {e}")
        
        return result
    
    def _check_reparse_point(self, file_path: str) -> bool:
        """
        Check if file has a reparse point (symlink marker).
        
        Args:
            file_path: Path to check
            
        Returns:
            True if reparse point detected
        """
        try:
            # Use Windows fsutil command
            result = subprocess.run(
                ["fsutil", "reparsepoint", "query", file_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            # Check for OneDrive-related reparse tags
            output = result.stdout.lower()
            return "onedrive" in output or "cloud" in output or result.returncode == 0
            
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    def _check_cloud_attribute(self, file_path: str) -> bool:
        """
        Check if file has cloud attribute using PowerShell.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if cloud attribute detected
        """
        try:
            # PowerShell command to check OneDrive status
            ps_command = f"""
            $item = Get-Item '{file_path}' -ErrorAction SilentlyContinue
            if ($item) {{
                $attributes = $item.Attributes
                return ($attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
                       ($attributes -band [System.IO.FileAttributes]::SparseFile)
            }}
            return $false
            """
            
            result = subprocess.run(
                ["powershell", "-Command", ps_command],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            return result.stdout.strip().lower() == "true"
            
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    def _check_size_mismatch(self, file_path: str) -> bool:
        """
        Check if reported file size differs from actual content.
        
        Placeholder files often report 0 bytes or incorrect size.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if size mismatch detected
        """
        try:
            stat = os.stat(file_path)
            
            # Placeholder files often report 0 or very small size
            if stat.st_size == 0:
                return True
            
            # Check if size seems too small for file type
            ext = Path(file_path).suffix.lower()
            expected_min_sizes = {
                ".jpg": 1000,
                ".jpeg": 1000,
                ".png": 1000,
                ".mp4": 10000,
                ".mov": 10000,
            }
            
            min_size = expected_min_sizes.get(ext, 0)
            if min_size > 0 and stat.st_size < min_size:
                return True
            
            return False
            
        except OSError:
            return True  # Can't stat = likely placeholder
    
    def download_file(self, file_path: str) -> Optional[str]:
        """
        Download a OneDrive online-only file to local temp location.
        
        Args:
            file_path: Original file path
            
        Returns:
            Local path to downloaded file, or None if failed
        """
        if not self.enabled:
            return None
        
        for attempt in range(self.max_retries):
            try:
                # Create temp path
                temp_path = self.temp_dir / Path(file_path).name
                
                # Use PowerShell Copy-Item which handles Files On-Demand download better
                ps_command = f"Copy-Item -Path '{file_path}' -Destination '{temp_path}' -Force"
                
                result = subprocess.run(
                    ["powershell", "-Command", ps_command],
                    capture_output=True,
                    text=True,
                    timeout=self.download_timeout,
                )
                
                if result.returncode == 0 and temp_path.exists():
                    logger.info(f"Downloaded OneDrive file: {file_path} -> {temp_path}")
                    return str(temp_path)
                
                logger.warning(f"OneDrive download attempt {attempt + 1} failed: {result.stderr}")
                
            except subprocess.TimeoutExpired:
                logger.error(f"OneDrive download timeout for {file_path}")
            except Exception as e:
                logger.error(f"OneDrive download error: {e}")
        
        return None
    
    def revert_to_online_only(self, file_path: str) -> bool:
        """
        Revert a local file back to OneDrive online-only.
        
        Uses PowerShell to set Files On-Demand status.
        
        Args:
            file_path: Path to file (original OneDrive path)
            
        Returns:
            True if successfully reverted
        """
        if not self.enabled:
            return False
        
        try:
            # Correct PowerShell command to free up space (Attribute 0x100000 = cloud-only)
            # attrib +U <file> is the simplest way for OneDrive
            ps_command = f"attrib +U '{file_path}'"
            
            result = subprocess.run(
                ["cmd", "/c", ps_command],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                logger.info(f"Reverted to online-only: {file_path}")
                return True
            
            # Fallback to PowerShell if needed
            ps_command = f"powershell.exe -Command \"Get-Item '{file_path}' | % {{ $_.Attributes = $_.Attributes -bor [System.IO.FileAttributes]::Offline }}\""
            # Actually, attrib +U is specifically for OneDrive cloud-only status
            
            logger.warning(f"Failed to revert {file_path}: {result.stderr}")
            return False
            
        except Exception as e:
            logger.error(f"Error reverting OneDrive file: {e}")
            return False
    
    def verify_online_only(self, file_path: str) -> bool:
        """
        Verify that a file is now online-only.
        
        Args:
            file_path: Path to verify
            
        Returns:
            True if file is online-only
        """
        status = self.detect_placeholder_status(file_path)
        return status["is_online_only"]
    
    def cleanup_temp_files(self, max_age_hours: int = 24) -> int:
        """
        Clean up old temporary downloaded files.
        
        Args:
            max_age_hours: Maximum age of temp files to keep
            
        Returns:
            Number of files deleted
        """
        count = 0
        cutoff = time.time() - (max_age_hours * 3600)
        
        for temp_file in self.temp_dir.glob("*"):
            try:
                if temp_file.stat().st_mtime < cutoff:
                    temp_file.unlink()
                    count += 1
            except OSError:
                continue
        
        return count
    
    def process_file(self, file_path: str) -> Tuple[Optional[str], bool]:
        """
        Process a file, handling OneDrive download/revert.
        
        Args:
            file_path: Original file path
            
        Returns:
            Tuple of (local_path, should_revert)
        """
        if not self.is_onedrive_path(file_path):
            return file_path, False
        
        # Detect status
        status = self.detect_placeholder_status(file_path)
        
        if status["is_online_only"]:
            # Download to temp location
            local_path = self.download_file(file_path)
            return local_path, True if local_path else False
        
        return file_path, False
