"""Pipeline module for face processing."""

from src.pipeline.processor import PipelineProcessor, ProcessingResult
from src.pipeline.thumbnail import ThumbnailGenerator

__all__ = [
    "PipelineProcessor",
    "ProcessingResult",
    "ThumbnailGenerator",
]