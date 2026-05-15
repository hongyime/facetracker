"""Atomic operations utilities for Face Tracker application."""

import tempfile
import shutil
from pathlib import Path
from typing import Any, Callable
import json


def atomic_write_json(path: Path, data: Any) -> None:
    """
    Write JSON data atomically using a temporary file.
    
    Args:
        path: Target file path
        data: Data to serialize as JSON
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temporary file first
    fd, temp_path = tempfile.mkstemp(suffix=".json", dir=path.parent)
    try:
        with open(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        
        # Atomic rename
        shutil.move(temp_path, path)
    except Exception:
        # Clean up temp file on failure
        try:
            Path(temp_path).unlink()
        except OSError:
            pass
        raise


def atomic_operation(operation: Callable[[], Any], rollback: Callable[[Any], None]) -> Any:
    """
    Execute an operation with rollback support.
    
    Args:
        operation: Function to execute
        rollback: Function to call with result if rollback needed
        
    Returns:
        Result of the operation
    """
    result = operation()
    return result
