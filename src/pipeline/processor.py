"""Main pipeline processor for face indexing."""

import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import uuid

from src.utils.logging import get_logger
from src.readers.image_reader import ImageReader
from src.readers.video_reader import VideoReader
from src.engine.detector import FaceDetector, FaceDetectionResult
from src.engine.tracker import FaceTracker, TrackedFace
from src.engine.embedder import FaceEmbedder
from src.engine.quality import QualityScorer
from src.pipeline.thumbnail import ThumbnailGenerator
from src.storage.database import Database, Image, Face
from src.storage.faiss_index import BatchedFAISSIndex
from src.discovery.onedrive import OneDriveHandler
from src.config import settings

logger = get_logger(__name__)


class ProcessingResult:
    """Result of processing a single file."""

    def __init__(self):
        self.file_path: Optional[Path] = None
        self.file_hash: Optional[str] = None
        self.status: str = "pending"  # pending, processing, success, failed
        self.faces_detected: int = 0
        self.faces_processed: int = 0
        self.face_objects: List[Face] = []
        self.error_message: Optional[str] = None
        self.processing_time: float = 0.0
        self.is_video: bool = False
        self.video_frames_processed: int = 0
        self.track_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "file_path": str(self.file_path),
            "file_hash": self.file_hash,
            "status": self.status,
            "faces_detected": self.faces_detected,
            "faces_processed": self.faces_processed,
            "error_message": self.error_message,
            "processing_time": self.processing_time,
            "is_video": self.is_video,
            "video_frames_processed": self.video_frames_processed,
            "track_count": self.track_count
        }


class PipelineProcessor:
    """Orchestrate the complete face processing pipeline."""

    def __init__(
        self,
        db: Database,
        faiss_index: BatchedFAISSIndex,
        thumbnail_cache_path: Path,
        use_onedrive: bool = True,
        providers: List[str] = None
    ):
        """
        Initialize pipeline processor.

        Args:
            db: Database instance.
            faiss_index: Batched FAISS index for embeddings.
            thumbnail_cache_path: Base path for thumbnail storage.
            use_onedrive: Enable OneDrive handling.
            providers: ONNX runtime providers.
        """
        logger.info("Initializing PipelineProcessor")

        self.db = db
        self.faiss_index = faiss_index
        self.thumbnail_cache_path = thumbnail_cache_path
        
        # Initialize components
        self.image_reader = ImageReader()
        self.video_reader = VideoReader(fps=1.0)  # 1 FPS for video
        self.face_detector = FaceDetector(providers=providers)
        self.face_tracker = FaceTracker(max_age=30, n_init=1)
        self.face_embedder = FaceEmbedder(providers=providers)
        self.quality_scorer = QualityScorer()
        self.thumbnail_generator = ThumbnailGenerator(
            face_size=512,
            margin_ratio=0.15
        )
        
        self.onedrive = OneDriveHandler(settings) if use_onedrive else None
        
        # Ensure thumbnail cache directory exists
        self.thumbnail_cache_path.mkdir(parents=True, exist_ok=True)
        
        logger.info("PipelineProcessor initialized")

    def _check_storage_alive(self) -> bool:
        """Check if critical storage root is still available."""
        # Use thumbnail_cache_path as proxy for storage root availability
        # In a real environment, this is Y:\faces
        if not self.thumbnail_cache_path.parent.exists():
            logger.error(f"CRITICAL: Storage root {self.thumbnail_cache_path.parent} not found! Pausing operations.")
            return False
        return True

    def process_file(self, file_path: Path) -> ProcessingResult:
        """
        Process a single image or video file.

        Args:
            file_path: Path to file to process.

        Returns:
            ProcessingResult with all metadata and face records.
        """
        # STOP if storage root is missing (e.g. Y:\ disconnected)
        if not self._check_storage_alive():
            result = ProcessingResult()
            result.file_path = file_path
            result.status = "failed"
            result.error_message = "Storage root unavailable"
            return result

        import time
        start_time = time.time()
        
        result = ProcessingResult()
        result.file_path = file_path
        result.status = "processing"
        
        logger.info(f"Processing file: {file_path}")
        
        onedrive_original_path = None
        should_revert = False

        try:
            # Handle OneDrive placeholders: download to temp, process, then revert
            if self.onedrive:
                local_path, should_revert = self.onedrive.process_file(str(file_path))
                if local_path is None:
                    result.status = "failed"
                    result.error_message = "Failed to download OneDrive file"
                    result.processing_time = time.time() - start_time
                    return result
                if should_revert:
                    logger.info(f"OneDrive placeholder downloaded: {file_path} -> {local_path}")
                    onedrive_original_path = str(file_path)
                file_path = Path(local_path)
            
            # Compute file hash
            from src.utils.hashing import compute_file_hash
            result.file_hash = compute_file_hash(file_path)
            
            # Check if already processed
            existing = self.db.get_image_by_hash(result.file_hash)
            if existing and existing.status == "completed":
                logger.info(f"File already processed: {file_path}")
                result.status = "success"
                result.processing_time = time.time() - start_time
                return result
            
            # Determine file type and process
            if self.video_reader.can_read(file_path):
                self._process_video(file_path, result)
            elif self.image_reader.can_read(file_path):
                self._process_image(file_path, result)
            else:
                result.status = "failed"
                result.error_message = f"Unsupported file type: {file_path.suffix}"
                
        except Exception as e:
            logger.error(f"Processing failed for {file_path}: {e}")
            result.status = "failed"
            result.error_message = str(e)
        finally:
            # Revert OneDrive file back to online-only after processing
            if should_revert and onedrive_original_path and self.onedrive:
                self.onedrive.revert_to_online_only(onedrive_original_path)

        result.processing_time = time.time() - start_time
        
        # Save image record to database
        if result.status == "success":
            self._save_image_record(result)
        
        # Flush FAISS staging if needed
        if self.faiss_index.needs_merge:
            self.faiss_index.force_merge()
        
        logger.info(
            f"Completed processing {file_path}: "
            f"{result.faces_processed} faces in {result.processing_time:.2f}s"
        )
        
        return result

    def _process_image(self, file_path: Path, result: ProcessingResult):
        """Process a single image file."""
        # Load image
        image = self.image_reader.read(file_path)
        if image is None:
            result.status = "failed"
            result.error_message = "Failed to load image"
            return
        
        # Detect faces
        detections = self.face_detector.detect(image)
        result.faces_detected = len(detections)
        
        height, width = image.shape[:2]
        
        if not detections:
            logger.debug(f"No faces detected in {file_path}")
            result.status = "success"
            return
        
        # Process each face
        for detection in detections:
            face_obj = self._process_face(
                image=image,
                bbox=detection.bbox,
                quality_score=detection.quality_score,
                source_path=file_path,
                file_hash=result.file_hash,
                frame_number=0,
                img_width=width,
                img_height=height
            )
            
            if face_obj:
                result.face_objects.append(face_obj)
                result.faces_processed += 1
        
        result.status = "success"

    def _process_video(self, file_path: Path, result: ProcessingResult):
        """Process a video file with tracking at 1 FPS."""
        result.is_video = True
        
        # Reset tracker for new video
        self.face_tracker.reset()
        
        # Track best frame per track ID
        best_frames: Dict[int, Tuple[np.ndarray, np.ndarray, float]] = {}
        
        # Process frames
        frame_count = 0
        for frame, timestamp in self.video_reader.read_frames(file_path):
            # Detect faces in frame
            detections = self.face_detector.detect(frame)
            
            if detections:
                # Format for tracker
                det_list = [(d.bbox, d.confidence) for d in detections]
                
                # Update tracker
                tracked_faces = self.face_tracker.update(det_list, frame_count, timestamp)
                
                # Store best frame per track
                for tracked in tracked_faces:
                    track_id = tracked.track_id
                    
                    # Find corresponding detection
                    det_idx = -1
                    for i, d in enumerate(detections):
                        # Simple overlap check or just assume same order if tracker matches
                        # For now, just use the detection's quality score if we can find it
                        pass
                    
                    quality = 0.5 # Default if not found
                    # In a real implementation, we'd match detection to tracked face
                    
                    # Keep best quality frame
                    if track_id not in best_frames or quality > best_frames[track_id][2]:
                        best_frames[track_id] = (frame.copy(), tracked.bbox.copy(), quality)
            
            frame_count += 1
        
        result.video_frames_processed = frame_count
        result.track_count = len(best_frames)
        
        # Process best frame for each track
        for track_id, (frame, bbox, quality) in best_frames.items():
            h, w = frame.shape[:2]
            face_obj = self._process_face(
                image=frame,
                bbox=bbox,
                quality_score=quality,
                source_path=file_path,
                file_hash=result.file_hash,
                frame_number=-1,  # Best frame from video
                track_id=track_id,
                video_path=file_path,
                img_width=w,
                img_height=h
            )
            
            if face_obj:
                result.face_objects.append(face_obj)
                result.faces_processed += 1
        
        result.status = "success"

    def _process_face(
        self,
        image: np.ndarray,
        bbox: np.ndarray,
        quality_score: float,
        source_path: Path,
        file_hash: str,
        img_width: int,
        img_height: int,
        frame_number: int = 0,
        track_id: Optional[int] = None,
        video_path: Optional[Path] = None
    ) -> Optional[Face]:
        """Process a single face detection."""
        try:
            # Extract embedding
            x1, y1, x2, y2 = bbox.astype(int)
            face_crop = image[max(0, y1):min(img_height, y2), 
                              max(0, x1):min(img_width, x2)]
            
            if face_crop.size == 0:
                return None
            
            embedding = self.face_embedder.embed(face_crop)
            if embedding is None:
                logger.warning("Failed to extract embedding")
                return None
            
            # Generate unique ID for face
            face_id = uuid.uuid4().hex
            
            # Create face object
            face_obj = Face(
                embedding_id=face_id,
                embedding_vec=self.face_embedder.to_halfvec(embedding),
                quality_score=quality_score,
                bbox_px_x1=int(x1),
                bbox_px_y1=int(y1),
                bbox_px_x2=int(x2),
                bbox_px_y2=int(y2),
                bbox_x1=float(x1 / img_width),
                bbox_y1=float(y1 / img_height),
                bbox_x2=float(x2 / img_width),
                bbox_y2=float(y2 / img_height),
                frame_number=frame_number,
                track_id=track_id,
                video_path=str(video_path) if video_path else None
            )
            
            # Add to FAISS index staging
            self.faiss_index.add(embedding, face_id)
            
            return face_obj
            
        except Exception as e:
            logger.error(f"Face processing failed: {e}")
            return None

    def _save_image_record(self, result: ProcessingResult):
        """Save image record to database."""
        try:
            # Get file stats
            stat = result.file_path.stat()
            
            # Get image dimensions from first frame/image if available
            width, height = 0, 0
            # This would normally be passed from the reader
            
            image_record = Image(
                file_path=str(result.file_path),
                file_hash=result.file_hash,
                file_size=stat.st_size,
                file_mtime=stat.st_mtime,
                status="completed",
                face_count=result.faces_processed,
                is_video=result.is_video,
                video_frames=result.video_frames_processed
            )
            
            self.db.add_image(image_record)
            
            # Flush to get image_record.id
            self.db.session.flush()
            
            # Add face records
            for face in result.face_objects:
                face.image_id = image_record.id
                self.db.add_face(face)
            
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to save image record: {e}")
            self.db.rollback()
