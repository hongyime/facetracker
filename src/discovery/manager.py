"""Indexing manager to coordinate scanning and processing."""

import threading
import queue
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from src.utils.logging import get_logger
from src.discovery.scanner import DriveScanner, FileRecord
from src.discovery.manifest import FileManifestManager
from src.discovery.watcher import FileWatcher
from src.pipeline.processor import PipelineProcessor
from src.storage.database import Database
from src.config import Settings

logger = get_logger(__name__)


class IndexingManager:
    """
    Coordinates the background indexing process.
    
    Responsibilities:
    - Scanning drives for new/changed files
    - Queuing files for processing
    - Managing processing threads
    - Real-time file watching
    - Progress tracking
    """
    
    def __init__(
        self,
        config: Settings,
        processor: PipelineProcessor,
        manifest: FileManifestManager,
        watcher: FileWatcher,
        db: Database,
    ):
        self.config = config
        self.processor = processor
        self.manifest = manifest
        self.watcher = watcher
        self.db = db
        self.scanner = DriveScanner(config)
        
        # Queues
        self.processing_queue = queue.Queue(maxsize=config.index_queue_size)
        
        # Threading
        self._scan_thread: Optional[threading.Thread] = None
        self._worker_threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
        
        # Progress Tracking
        self.is_scanning = False
        self.current_file: Optional[str] = None
        self.files_scanned = 0
        self.files_total = 0
        self.files_processed = 0
        self.files_failed = 0
        self.scan_start_time: Optional[datetime] = None
        
        # Stats
        self.last_scan_completed: Optional[datetime] = None
        
    def start(self) -> None:
        """Start the indexing process."""
        if self._scan_thread and self._scan_thread.is_alive():
            logger.warning("Indexing already in progress")
            return
            
        logger.info("Starting Indexing Manager")
        self._stop_event.clear()
        
        # Start worker threads
        num_workers = self.config.index_workers
        for i in range(num_workers):
            t = threading.Thread(target=self._worker_loop, name=f"IndexerWorker-{i}")
            t.daemon = True
            t.start()
            self._worker_threads.append(t)

        # Recovery: re-queue any orphaned pending rows from prior incomplete runs.
        # Runs in its own thread so app startup is not blocked by a long DB
        # query against millions of rows. Workers will start draining the queue
        # immediately as recovery enqueues find them.
        recovery_thread = threading.Thread(
            target=self._recover_pending_images,
            name="PendingRecoveryThread",
        )
        recovery_thread.daemon = True
        recovery_thread.start()

        # Start scan thread
        self._scan_thread = threading.Thread(target=self._scan_loop, name="ScannerThread")
        self._scan_thread.daemon = True
        self._scan_thread.start()
        
        # Start watcher if enabled
        if self.config.watch_mode:
            watcher_thread = threading.Thread(
                target=self.watcher.start, 
                kwargs={"callback": self._on_file_event},
                name="WatcherStartupThread"
            )
            watcher_thread.daemon = True
            watcher_thread.start()
            
        logger.info(f"Indexing Manager started with {num_workers} workers")
        
    def stop(self) -> None:
        """Stop the indexing process."""
        logger.info("Stopping Indexing Manager...")
        self._stop_event.set()
        
        if self.watcher.is_running():
            self.watcher.stop()
            
        # Wait for threads to finish
        if self._scan_thread:
            self._scan_thread.join(timeout=5)
            
        for t in self._worker_threads:
            t.join(timeout=5)
            
        self._worker_threads.clear()
        logger.info("Indexing Manager stopped")
        
    def get_progress(self) -> Dict[str, Any]:
        """Get current indexing progress."""
        progress = 0
        if self.files_total > 0:
            progress = (self.files_scanned / self.files_total) * 100
            
        eta = None
        if self.is_scanning and self.scan_start_time and self.files_scanned > 0:
            elapsed = (datetime.now() - self.scan_start_time).total_seconds()
            if elapsed > 0:
                files_per_sec = self.files_scanned / elapsed
                remaining_files = self.files_total - self.files_scanned
                if files_per_sec > 0:
                    eta = remaining_files / files_per_sec
                
        return {
            "is_scanning": self.is_scanning,
            "current_file": self.current_file,
            "files_scanned": self.files_scanned,
            "files_total": self.files_total,
            "files_processed": self.files_processed,
            "files_failed": self.files_failed,
            "progress_percent": round(progress, 2),
            "eta_seconds": round(eta, 2) if eta is not None else None,
            "last_scan_completed": self.last_scan_completed.isoformat() if self.last_scan_completed else None
        }
        
    def _scan_loop(self) -> None:
        """Main loop for periodic drive scanning."""
        while not self._stop_event.is_set():
            try:
                self.is_scanning = True
                self.scan_start_time = datetime.now()
                self.files_scanned = 0
                self.files_total = 0
                
                logger.info("Starting drive scan...")
                
                # First pass: Count files for progress (optional but helpful)
                # For now, we'll just increment as we go
                
                for batch in self.scanner.scan_drives():
                    if self._stop_event.is_set():
                        break
                        
                    for record in batch:
                        self.files_total += 1
                        
                        # Check if file needs processing
                        if self.manifest.needs_processing(record.path, record.mtime, record.size):
                            # Add to queue (blocks if full)
                            try:
                                self.processing_queue.put(record, timeout=1)
                            except queue.Full:
                                # This shouldn't happen much with blocks, but just in case
                                pass
                                
                        self.files_scanned += 1
                        
                logger.info(f"Drive scan completed. Found {self.files_total} files.")
                self.last_scan_completed = datetime.now()
                self.is_scanning = False
                
                # Wait for next scan
                wait_time = self.config.watch_poll_interval * 60  # convert to seconds
                for _ in range(int(wait_time)):
                    if self._stop_event.is_set():
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                self.is_scanning = False
                time.sleep(60)  # Wait before retry
                
    def _recover_pending_images(self) -> None:
        """One-shot recovery for orphaned `images.status='pending'` rows.

        Three phases, all driven off SQL — does NOT re-run the detection
        pipeline against files that already have face rows. That avoids
        unique-violations on file_path and double-detection of the same image.

        Phase A (flip-to-completed):
            Pending rows with face_count > 0 are partial commits from a
            pre-P1 (caller-owned-Session) era — detection ran, faces were
            written, but the Image.status flip never landed. They are
            already ~99% done. Flip them to 'completed' so they leave
            the pending bucket.

        Phase B (outbox backfill):
            For every face row whose embedding_id is not yet present in
            the FAISS live_ids set, enqueue an outbox row so the reaper
            adds it to the index. This covers both the rows we just
            flipped in Phase A AND any pre-existing 'completed' rows
            whose embeddings were never persisted to FAISS.

        Phase C (mark-failed for empty pending):
            Pending rows with face_count=0 had no faces detected (legit)
            OR died before detection (illegit). Either way, marking them
            'failed' clears the pending bucket; the scanner will re-pick
            up any file that's still on disk on the next walk.

        The recovery only runs once per process start and is idempotent
        across restarts: a row that was flipped to completed last time
        won't be touched again.
        """
        from sqlalchemy import text

        log_prefix = "[recovery]"
        try:
            session = self.db.SessionLocal()
        except Exception as e:
            logger.error(f"{log_prefix} cannot open recovery session: {e}")
            return

        try:
            # --- Phase A: flip partial-commit pending rows to completed.
            try:
                with self.db.engine.begin() as conn:
                    res = conn.execute(
                        text(
                            "UPDATE images SET status='completed' "
                            " WHERE status='pending' AND face_count > 0"
                        )
                    )
                    flipped = res.rowcount or 0
                logger.info(f"{log_prefix} phaseA: flipped {flipped} pending->completed (had faces)")
            except Exception as e:
                logger.error(f"{log_prefix} phaseA failed: {e}")
                flipped = 0

            # --- Phase B: backfill outbox for faces missing from FAISS.
            # Use ORM to leverage pgvector type adapter; raw SQL on
            # `embedding_vec` would return text needing manual parsing.
            try:
                import numpy as np

                from src.storage.database import Face
                from src.storage.outbox import serialize_embedding

                live = set()
                if (
                    self.processor is not None
                    and getattr(self.processor, "faiss_index", None) is not None
                    and hasattr(self.processor.faiss_index, "live_ids_set")
                ):
                    live = set(self.processor.faiss_index.live_ids_set)

                BATCH = 500
                last_id = 0
                enqueued = 0
                while not self._stop_event.is_set():
                    rows = (
                        session.query(Face.id, Face.embedding_id, Face.embedding_vec)
                        .filter(Face.id > last_id)
                        .filter(Face.embedding_id.isnot(None))
                        .filter(Face.embedding_vec.isnot(None))
                        .order_by(Face.id)
                        .limit(BATCH)
                        .all()
                    )
                    if not rows:
                        break
                    last_id = rows[-1].id

                    # Bulk-insert outbox rows; ON CONFLICT DO NOTHING covers
                    # the case where Phase B is re-run.
                    with self.db.engine.begin() as conn:
                        for r in rows:
                            if r.embedding_id in live:
                                continue
                            try:
                                vec = np.asarray(r.embedding_vec, dtype=np.float32)
                                if vec.shape != (512,):
                                    logger.warning(
                                        f"{log_prefix} phaseB skip face_id={r.embedding_id}: "
                                        f"unexpected shape {vec.shape}"
                                    )
                                    continue
                                emb_bytes = serialize_embedding(vec)
                                conn.execute(
                                    text(
                                        "INSERT INTO faiss_outbox "
                                        "  (face_id, embedding, status, attempts, created_at) "
                                        "VALUES (:fid, :emb, 'pending', 0, NOW()) "
                                        "ON CONFLICT (face_id) DO NOTHING"
                                    ),
                                    {"fid": r.embedding_id, "emb": emb_bytes},
                                )
                                enqueued += 1
                            except Exception as ie:
                                logger.warning(
                                    f"{log_prefix} phaseB skip face_id={r.embedding_id}: {ie}"
                                )

                    # Periodic progress for the long backfill.
                    if last_id % (BATCH * 10) < BATCH:
                        logger.info(f"{log_prefix} phaseB progress: enqueued={enqueued}")

                logger.info(f"{log_prefix} phaseB: enqueued {enqueued} outbox rows")
            except Exception as e:
                logger.error(f"{log_prefix} phaseB failed: {e}")

            # --- Phase C: mark empty pending rows failed so they leave the bucket.
            try:
                with self.db.engine.begin() as conn:
                    res = conn.execute(
                        text(
                            "UPDATE images "
                            "   SET status='failed', "
                            "       error_message='recovery: pending with no faces, never started' "
                            " WHERE status='pending' AND face_count = 0"
                        )
                    )
                    cleared = res.rowcount or 0
                logger.info(f"{log_prefix} phaseC: marked {cleared} empty pending rows failed")
            except Exception as e:
                logger.error(f"{log_prefix} phaseC failed: {e}")

            logger.info(f"{log_prefix} done")
        except Exception as e:
            logger.error(f"{log_prefix} aborted: {e}")
        finally:
            session.close()

    def _worker_loop(self) -> None:
        """Worker thread loop to process files from the queue.

        Each file gets a fresh DB Session opened from the engine pool and
        closed in finally. This is the per-file transaction boundary —
        commit/rollback decisions live inside `processor.process_file`.
        """
        while not self._stop_event.is_set():
            try:
                # Get file from queue
                try:
                    record = self.processing_queue.get(timeout=1)
                except queue.Empty:
                    continue

                self.current_file = record.path

                session = self.db.SessionLocal()
                try:
                    result = self.processor.process_file(Path(record.path), session=session)
                finally:
                    session.close()

                if result.status == "success":
                    self.files_processed += 1
                    # Update manifest
                    self.manifest.add_file(
                        record.path,
                        result.file_hash,
                        record.size,
                        record.mtime,
                        is_processed=True
                    )
                    self.manifest.save_manifest()
                else:
                    self.files_failed += 1
                    logger.warning(f"Failed to process {record.path}: {result.error_message}")

                self.processing_queue.task_done()
                self.current_file = None

            except Exception as e:
                logger.error(f"Error in worker thread: {e}")
                time.sleep(1)
                
    def _on_file_event(self, file_path: str, event_type: str) -> None:
        """Callback for file system events."""
        logger.info(f"File event: {event_type} - {file_path}")
        
        if event_type == "deleted":
            self.manifest.mark_deleted(file_path)
            self.manifest.save_manifest()
        else:
            # For created/modified, check if it needs processing
            try:
                p = Path(file_path)
                if not p.exists():
                    return
                    
                stat = p.stat()
                if self.manifest.needs_processing(file_path, stat.st_mtime, stat.st_size):
                    record = FileRecord(
                        path=file_path,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        extension=p.suffix.lower()
                    )
                    # Try to add to queue without blocking too long
                    try:
                        self.processing_queue.put(record, timeout=0.1)
                    except queue.Full:
                        logger.warning(f"Queue full, skipping real-time event for {file_path}")
            except Exception as e:
                logger.error(f"Error handling file event: {e}")
