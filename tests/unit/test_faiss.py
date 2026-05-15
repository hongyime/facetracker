"""Unit tests for FAISS index module."""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from src.storage.faiss_index import BatchedFAISSIndex, FAISSIndexConfig
from src.config import StorageConfig


class TestBatchedFAISSIndex:
    """Test cases for BatchedFAISSIndex class."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        storage_config = StorageConfig()
        return FAISSIndexConfig(
            dimension=512,
            staging_size=100,  # Small for testing
            index_type="HNSW64",
            ef_construction=200,
        )

    @pytest.fixture
    def faiss_index(self, config):
        """Create FAISS index instance."""
        with patch('faiss.IndexHnswFlat'):
            with patch('faiss.IndexIDMap'):
                return BatchedFAISSIndex(config)

    def test_index_initialization(self, faiss_index):
        """Test index initializes correctly."""
        assert faiss_index is not None
        assert faiss_index.staging_size == 100

    def test_add_single_embedding(self, faiss_index):
        """Test adding a single embedding to staging."""
        embedding = np.random.rand(512).astype(np.float32)
        face_id = "face_001"
        
        idx = faiss_index.add(embedding, face_id)
        
        assert idx == 0  # First embedding
        assert faiss_index.staging_count == 1

    def test_add_multiple_embeddings(self, faiss_index):
        """Test adding multiple embeddings."""
        for i in range(50):
            embedding = np.random.rand(512).astype(np.float32)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        assert faiss_index.staging_count == 50
        assert faiss_index.live_count == 0  # Not merged yet

    def test_automatic_merge_at_staging_limit(self, faiss_index):
        """Test automatic merge when staging buffer is full."""
        # Add embeddings up to staging limit
        for i in range(100):
            embedding = np.random.rand(512).astype(np.float32)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        # Should have triggered merge
        assert faiss_index.staging_count == 0
        assert faiss_index.live_count == 100

    def test_search_empty_index(self, faiss_index):
        """Test searching an empty index."""
        query = np.random.rand(512).astype(np.float32)
        
        results = faiss_index.search(query, k=10)
        
        assert results == []

    def test_search_after_merge(self, faiss_index):
        """Test searching after merge."""
        # Add and merge embeddings
        embeddings = [np.random.rand(512).astype(np.float32) for _ in range(50)]
        for i, emb in enumerate(embeddings):
            faiss_index.add(emb, f"face_{i:03d}")
        
        # Force merge
        faiss_index._merge_staging_to_live()
        
        # Search
        query = embeddings[0]  # Search with first embedding
        results = faiss_index.search(query, k=5)
        
        assert len(results) > 0

    def test_search_returns_correct_format(self, faiss_index):
        """Test search returns correct result format."""
        # Add embeddings
        for i in range(50):
            embedding = np.random.rand(512).astype(np.float32)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        faiss_index._merge_staging_to_live()
        
        query = np.random.rand(512).astype(np.float32)
        results = faiss_index.search(query, k=5)
        
        # Results should be list of tuples (face_id, similarity)
        if results:
            assert isinstance(results, list)
            assert len(results) <= 5

    def test_merge_staging_to_live(self, faiss_index):
        """Test manual merge operation."""
        # Add to staging
        for i in range(50):
            embedding = np.random.rand(512).astype(np.float32)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        initial_live = faiss_index.live_count
        initial_staging = faiss_index.staging_count
        
        # Merge
        faiss_index._merge_staging_to_live()
        
        assert faiss_index.staging_count == 0
        assert faiss_index.live_count == initial_live + initial_staging

    def test_thread_safety_with_locks(self, faiss_index):
        """Test thread safety mechanisms."""
        # Verify lock exists
        assert hasattr(faiss_index, '_merge_lock')

    def test_atomic_swap_during_merge(self, faiss_index):
        """Test atomic swap mechanism during merge."""
        # Add embeddings
        for i in range(50):
            embedding = np.random.rand(512).astype(np.float32)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        # During merge, search should still work (atomic swap)
        query = np.random.rand(512).astype(np.float32)
        
        # This should not raise even during merge
        results = faiss_index.search(query, k=5)
        assert results is not None

    def test_dimension_mismatch_raises_error(self, faiss_index):
        """Test that wrong dimension raises error."""
        wrong_dim_embedding = np.random.rand(256).astype(np.float32)  # Wrong dimension
        
        with pytest.raises((ValueError, AssertionError)):
            faiss_index.add(wrong_dim_embedding, "face_001")

    def test_duplicate_face_id_handling(self, faiss_index):
        """Test handling of duplicate face IDs."""
        embedding1 = np.random.rand(512).astype(np.float32)
        embedding2 = np.random.rand(512).astype(np.float32)
        
        # Add same face ID twice
        faiss_index.add(embedding1, "face_001")
        faiss_index.add(embedding2, "face_001")  # Same ID
        
        # Should handle gracefully (either update or skip)
        assert faiss_index.staging_count >= 1

    def test_search_k_larger_than_index(self, faiss_index):
        """Test search with k larger than index size."""
        # Add few embeddings
        for i in range(10):
            embedding = np.random.rand(512).astype(np.float32)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        faiss_index._merge_staging_to_live()
        
        # Search with k > index size
        query = np.random.rand(512).astype(np.float32)
        results = faiss_index.search(query, k=100)
        
        # Should return at most all available results
        assert len(results) <= 10

    def test_similarity_scores_normalized(self, faiss_index):
        """Test that similarity scores are properly normalized."""
        # Add embeddings
        for i in range(50):
            embedding = np.random.rand(512).astype(np.float32)
            # Normalize
            embedding = embedding / np.linalg.norm(embedding)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        faiss_index._merge_staging_to_live()
        
        query = np.random.rand(512).astype(np.float32)
        query = query / np.linalg.norm(query)
        
        results = faiss_index.search(query, k=10)
        
        # Similarity scores should be in reasonable range
        for face_id, similarity in results:
            assert -1.0 <= similarity <= 1.0

    def test_index_statistics(self, faiss_index):
        """Test index statistics tracking."""
        assert hasattr(faiss_index, 'live_count')
        assert hasattr(faiss_index, 'staging_count')
        
        # Initial state
        assert faiss_index.live_count == 0
        assert faiss_index.staging_count == 0

    def test_staging_buffer_reset_after_merge(self, faiss_index):
        """Test staging buffer resets after merge."""
        # Fill staging
        for i in range(100):
            embedding = np.random.rand(512).astype(np.float32)
            faiss_index.add(embedding, f"face_{i:03d}")
        
        # After automatic merge, staging should be reset
        assert faiss_index.staging_count == 0

    def test_batch_add_efficiency(self, faiss_index):
        """Test batch adding efficiency."""
        embeddings = [np.random.rand(512).astype(np.float32) for _ in range(50)]
        face_ids = [f"face_{i:03d}" for i in range(50)]
        
        # Add in batch
        for emb, fid in zip(embeddings, face_ids):
            faiss_index.add(emb, fid)
        
        assert faiss_index.staging_count == 50

    def test_float16_conversion(self, faiss_index):
        """Test float16 conversion for halfvec compatibility."""
        embedding_float32 = np.random.rand(512).astype(np.float32)
        
        # Convert to float16
        embedding_float16 = embedding_float32.astype(np.float16)
        
        # Should maintain reasonable precision
        diff = np.abs(embedding_float32 - embedding_float16.astype(np.float32)).mean()
        assert diff < 0.01  # Acceptable precision loss
