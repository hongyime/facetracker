"""Batched FAISS index for high-throughput ingestion."""

import faiss
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
import threading
import time
from datetime import datetime

from src.config import Settings


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
        
        # Initialize empty index if no existing index
        self._initialize_index()
    
    def _initialize_index(self) -> None:
        """Initialize or load the FAISS index."""
        if self.live_path.exists():
            try:
                self.live_index = faiss.read_index(str(self.live_path))
                self.live_count = self.live_index.ntotal
                print(f"Loaded existing FAISS index with {self.live_count} vectors")
            except Exception as e:
                print(f"Failed to load existing index: {e}. Creating new index.")
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
        faiss.normalize_L2(embedding)
        
        self.staging_vectors.append(embedding)
        self.staging_ids.append(face_id)
        
        # Check if merge needed
        if len(self.staging_vectors) >= self.staging_size:
            self._merge_staging_to_live()
        
        return len(self.staging_vectors) - 1
    
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
        
        for i, emb in enumerate(embeddings):
            self.staging_vectors.append(emb)
            self.staging_ids.append(face_ids[i])
        
        # Check if merge needed
        if len(self.staging_vectors) >= self.staging_size:
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
        
        # Search live index only
        D, I = self.live_index.search(embedding, k)
        
        # Convert to list of (face_id, score) tuples
        results = []
        for i, (dist, idx) in enumerate(zip(D[0], I[0])):
            if idx < len(self.live_ids):
                results.append((self.live_ids[idx], float(dist)))
        
        return results
    
    def _merge_staging_to_live(self) -> None:
        """
        Merge staging buffer into live index atomically.
        
        This method is thread-safe and blocks searches during merge.
        """
        with self.merge_lock:
            if len(self.staging_vectors) == 0:
                return
            
            print(f"Merging {len(self.staging_vectors)} vectors from staging to live index...")
            
            # Create combined index
            staging_array = np.array(self.staging_vectors, dtype=np.float32)
            
            # Add staging vectors to live index
            self.live_index.add(staging_array)
            self.live_ids.extend(self.staging_ids)
            self.live_count = self.live_index.ntotal
            
            # Save index to disk
            self._save_index()
            
            # Clear staging buffer
            self.staging_vectors.clear()
            self.staging_ids.clear()
            self.last_merge_time = datetime.utcnow()
            
            print(f"Merge complete. Live index now has {self.live_count} vectors.")
    
    def _save_index(self) -> None:
        """Save the live index to disk."""
        temp_path = self.live_path.with_suffix(".faiss.tmp")
        
        try:
            faiss.write_index(self.live_index, str(temp_path))
            # Atomic rename
            temp_path.replace(self.live_path)
        except Exception as e:
            print(f"Error saving FAISS index: {e}")
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
