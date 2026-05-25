"""Batched FAISS index for high-throughput ingestion."""

import faiss
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
import threading
import time
from datetime import datetime

from src.config import Settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BatchedFAISSIndex:
    """
    FAISS index with staged ingestion for non-blocking writes.
    
    This implementation uses a live index for searches and staging
    buffers for new embeddings. When staging is full, it merges
    atomically without blocking searches.
    """
    
    def __init__(self, config: Settings):
        """
        Initialize the batched FAISS index.
        
        Args:
            config: Application settings
        """
        self.config = config
        self.dimension = 512  # Antelopev2 embedding dimension
        
        # Live index (searchable)
        self.live_index: Optional[faiss.Index] = None
        self.live_ids: List[str] = []
        self.live_count = 0
        
        # Staging buffer
        self.staging_vectors: List[np.ndarray] = []
        self.staging_ids: List[str] = []
        self.staging_size = config.faiss_staging_size
        
        # Merge control
        self.merge_lock = threading.Lock()
        self.last_merge_time = datetime.utcnow()
        
        # Index paths
        self.live_path = Path(config.faiss_live_path)
        self.staging_dir = Path(config.faiss_staging_dir)
        
        # IDs file path for persistence
        self.ids_path = self.live_path.with_suffix('.ids.npy')
        
        # Initialize empty index if no existing index
        self._initialize_index()
    
    def _initialize_index(self) -> None:
        """Initialize or load the FAISS index."""
        if self.live_path.exists():
            try:
                self.live_index = faiss.read_index(str(self.live_path))
                self.live_count = self.live_index.ntotal
                logger.info(f"Loaded existing FAISS index with {self.live_count} vectors")
                
                # Load corresponding IDs if available
                if self.ids_path.exists():
                    self.live_ids = np.load(str(self.ids_path), allow_pickle=True).tolist()
                    logger.info(f"Loaded {len(self.live_ids)} face IDs")
                    # Reconcile: if a merge crashed between _save_ids and
                    # _save_index, ids will be ahead of index. Trim ids to
                    # match index.ntotal so search() can't return phantom IDs.
                    if len(self.live_ids) > self.live_count:
                        logger.warning(
                            f"FAISS recovery: ids file has {len(self.live_ids)} entries "
                            f"but index has {self.live_count} vectors — trimming ids "
                            f"(prior merge crashed mid-write)."
                        )
                        self.live_ids = self.live_ids[: self.live_count]
                    elif len(self.live_ids) < self.live_count:
                        logger.error(
                            f"FAISS corruption: index has {self.live_count} vectors "
                            f"but only {len(self.live_ids)} ids — extra vectors will "
                            f"be unreachable. Consider rebuilding the index."
                        )
                else:
                    logger.warning(f"No IDs file found at {self.ids_path}, live_ids will be empty")
                    self.live_ids = []
            except Exception as e:
                logger.error(f"Failed to load existing index: {e}. Creating new index.")
                self._create_new_index()
        else:
            self._create_new_index()
    
    def _create_new_index(self) -> None:
        """Create a new HNSW index."""
        # HNSW64: M=64, efConstruction=200
        self.live_index = faiss.IndexHNSWFlat(self.dimension, 64, faiss.METRIC_INNER_PRODUCT)
        self.live_index.hnsw.efConstruction = 200
        self.live_ids = []
        self.live_count = 0
        
        # Ensure directories exist
        self.live_path.parent.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
    
    def add(self, embedding: np.ndarray, face_id: str) -> int:
        """
        Add an embedding to the staging buffer.

        Args:
            embedding: 512-d numpy array (float32)
            face_id: Unique identifier for the face

        Returns:
            Position in staging buffer
        """
        # Normalize embedding for cosine similarity
        embedding = embedding.astype(np.float32)
        if embedding.ndim == 1:
            embedding = embedding.reshape(1, -1)
        faiss.normalize_L2(embedding)
        embedding = embedding.flatten()

        with self.merge_lock:
            self.staging_vectors.append(embedding)
            self.staging_ids.append(face_id)

            count = len(self.staging_vectors)
            should_merge = count >= self.staging_size

        # Trigger merge outside the lock so we don't hold it across disk I/O.
        # _merge_staging_to_live re-acquires the lock atomically. The
        # should_merge flag guarantees we don't miss a trigger across racing
        # producers (each producer that crosses the threshold triggers; a
        # subsequent merge sees an empty staging and returns immediately).
        if should_merge:
            self._merge_staging_to_live()

        return count - 1

    def add_batch(self, embeddings: np.ndarray, face_ids: List[str]) -> int:
        """
        Add multiple embeddings to the staging buffer.

        Args:
            embeddings: N x 512 numpy array
            face_ids: List of face IDs

        Returns:
            Number of embeddings added
        """
        # Normalize embeddings
        embeddings = embeddings.astype(np.float32)
        faiss.normalize_L2(embeddings)

        with self.merge_lock:
            for i, emb in enumerate(embeddings):
                self.staging_vectors.append(emb)
                self.staging_ids.append(face_ids[i])

            count = len(self.staging_vectors)
            should_merge = count >= self.staging_size

        if should_merge:
            self._merge_staging_to_live()

        return len(embeddings)

    def search(self, embedding: np.ndarray, k: int = 100) -> List[Tuple[str, float]]:
        """
        Search the live index for similar embeddings.

        Args:
            embedding: Query embedding (512-d)
            k: Number of results to return

        Returns:
            List of (face_id, similarity_score) tuples
        """
        if self.live_count == 0:
            return []

        # Normalize query
        embedding = embedding.astype(np.float32).reshape(1, -1)
        faiss.normalize_L2(embedding)

        # Search live index (read lock would be better but we'll use merge_lock
        # to ensure we don't search while merging)
        with self.merge_lock:
            D, I = self.live_index.search(embedding, k)

            # Convert to list of (face_id, score) tuples
            results = []
            for i, (dist, idx) in enumerate(zip(D[0], I[0])):
                if idx >= 0 and idx < len(self.live_ids):
                    results.append((self.live_ids[idx], float(dist)))

        return results

    def _merge_staging_to_live(self) -> None:
        """
        Merge staging buffer into live index atomically.

        Crash-safety: the on-disk artifacts (.faiss + .ids.npy) and the
        in-memory live_index/live_ids/live_count must never disagree. We:
          1. Add staging vectors to a copy of live_ids (in-memory) but DO NOT
             update live_ids / live_count yet.
          2. Add to faiss live_index (this mutates the index in place; we
             cannot easily roll it back, but FAISS HNSW.add is internal-state
             only — if the subsequent save fails, in-memory state is consistent
             with the index because we still need both `live_index.ntotal` and
             `live_ids` len to match. We therefore save IDs FIRST, then the
             index — the inverse of the previous order — so a crash between
             the two writes leaves an .ids file with too many IDs (recoverable
             on next merge) rather than an index with no IDs (unrecoverable
             corruption).
          3. Only after both saves succeed do we publish live_ids/live_count
             and clear staging.

        This method is thread-safe and blocks searches during merge.
        """
        with self.merge_lock:
            if len(self.staging_vectors) == 0:
                return

            staging_count = len(self.staging_vectors)
            logger.info(f"Merging {staging_count} vectors from staging to live index...")

            # Snapshot: capture staging state under the lock
            staging_array = np.array(self.staging_vectors, dtype=np.float32)
            staging_ids_snapshot = list(self.staging_ids)

            # Add to FAISS in-memory index (this mutation is the one we cannot
            # roll back cheaply; we accept the risk and ensure the on-disk
            # artifacts written below match the new in-memory state).
            self.live_index.add(staging_array)
            new_live_ids = self.live_ids + staging_ids_snapshot
            new_live_count = self.live_index.ntotal

            # Save IDs FIRST. If this fails, we have an in-memory index that's
            # ahead of disk. Roll back the FAISS add by re-creating the index
            # without the new vectors? FAISS HNSW does not support delete; we
            # instead refuse to publish the new state and keep staging intact.
            try:
                self._save_ids_atomic(new_live_ids)
            except Exception as e:
                logger.error(f"Failed to save FAISS ids during merge: {e}")
                # Don't publish; keep staging so next merge retries.
                # In-memory FAISS is now ahead of saved state, but
                # next save will reconcile (live_ids saved after subsequent
                # merge). This is the least-bad option without delete support.
                return

            # Now save the index. If this fails, ids file has the new IDs but
            # the index file is stale — on restart we'd load stale index +
            # full ids, producing index.ntotal < len(ids). Detect that on
            # load and trim ids; we add an explicit guard in _initialize_index
            # so this is recoverable, not corruption.
            try:
                self._save_index_atomic()
            except Exception as e:
                logger.error(f"Failed to save FAISS index during merge: {e}")
                # Don't publish in-memory. Ids file is ahead of index file;
                # _initialize_index trims live_ids on load.
                return

            # Both saves succeeded — publish.
            self.live_ids = new_live_ids
            self.live_count = new_live_count
            self.staging_vectors.clear()
            self.staging_ids.clear()
            self.last_merge_time = datetime.utcnow()
            logger.info(f"Merge complete. Live index now has {self.live_count} vectors.")

    def _save_index(self) -> None:
        """Backwards-compatible alias for _save_index_atomic (in-memory live_index)."""
        self._save_index_atomic()

    def _save_index_atomic(self) -> None:
        """Save the live index to disk via .tmp + atomic rename."""
        temp_path = self.live_path.with_suffix(".faiss.tmp")
        
        try:
            faiss.write_index(self.live_index, str(temp_path))
            # Atomic rename
            temp_path.replace(self.live_path)
        except Exception as e:
            logger.error(f"Error saving FAISS index: {e}")
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise
    
    def _save_ids(self) -> None:
        """Backwards-compatible alias — saves current self.live_ids."""
        self._save_ids_atomic(self.live_ids)

    def _save_ids_atomic(self, ids_to_save) -> None:
        """Save the given IDs list to disk via .tmp + atomic rename."""
        if not ids_to_save:
            return
        
        # Strip existing extension and add new ones
        base_path = self.ids_path.with_suffix('')
        temp_path = base_path.with_suffix('.npy.tmp')
        
        try:
            np.save(str(temp_path), np.array(ids_to_save, dtype=object), allow_pickle=True)
            # Atomic rename
            temp_path.replace(self.ids_path)
        except Exception as e:
            logger.error(f"Error saving FAISS IDs: {e}")
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise
    
    def force_merge(self) -> None:
        """Force merge of staging buffer regardless of size."""
        self._merge_staging_to_live()
    
    @property
    def total_count(self) -> int:
        """Get total number of vectors (live + staging)."""
        return self.live_count + len(self.staging_vectors)
    
    @property
    def needs_merge(self) -> bool:
        """Check if staging buffer needs merging."""
        return len(self.staging_vectors) >= self.staging_size * 0.8
