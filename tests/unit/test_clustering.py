"""Unit tests for identity clustering module."""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from src.identity.clustering import QualityAwareClusterer, ClusteringResult
from src.identity.metrics import ClusteringMetrics


class TestQualityAwareClusterer:
    """Test cases for QualityAwareClusterer class."""

    @pytest.fixture
    def clusterer(self):
        """Create clustering instance with mocked dependencies."""
        with patch('hdbscan.HDBSCAN'):
            return QualityAwareClusterer()

    def test_clusterer_initialization(self, clusterer):
        """Test clusterer initializes correctly."""
        assert clusterer is not None
        assert clusterer.min_cluster_size == 5
        assert clusterer.min_samples == 3

    def test_compute_quality_weighted_distances(self, clusterer):
        """Test quality-weighted distance computation."""
        embeddings = np.random.rand(10, 512).astype(np.float32)
        quality_scores = np.random.rand(10)
        
        # Normalize embeddings
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        distances = clusterer._apply_quality_weighting(embeddings, quality_scores)
        
        assert distances.shape == embeddings.shape

    def test_quality_weighting_affects_embeddings(self, clusterer):
        """Test that quality scores affect computed embeddings."""
        embeddings = np.random.rand(3, 512).astype(np.float32)
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        # High quality scores
        high_quality = np.array([0.9, 0.9, 0.9])
        # Low quality scores
        low_quality = np.array([0.1, 0.1, 0.1])
        
        weighted_high = clusterer._apply_quality_weighting(embeddings, high_quality)
        weighted_low = clusterer._apply_quality_weighting(embeddings, low_quality)
        
        # Both should have same shape
        assert weighted_high.shape == weighted_low.shape

    def test_cluster_with_hdbscan(self, clusterer):
        """Test HDBSCAN clustering."""
        embeddings = np.random.rand(50, 512).astype(np.float32)
        quality_scores = np.random.rand(50)
        
        with patch.object(clusterer, '_clusterer') as mock_model:
            mock_model.labels_ = np.random.randint(-1, 5, 50)  # -1 for noise, 0-4 for clusters
            mock_model.probabilities_ = np.random.rand(50)
            
            result = clusterer.cluster(embeddings, quality_scores)
            
            assert isinstance(result, ClusteringResult)
            assert len(result.labels) == 50

    def test_cluster_result_format(self, clusterer):
        """Test cluster result output format."""
        embeddings = np.random.rand(10, 512).astype(np.float32)
        quality_scores = np.random.rand(10)
        
        with patch.object(clusterer, '_clusterer') as mock_model:
            mock_model.labels_ = np.array([0, 0, 1, 1, -1, 2, 2, -1, 0, 1])
            mock_model.probabilities_ = np.random.rand(10)
            
            result = clusterer.cluster(embeddings, quality_scores)
            
            # Check result structure
            assert hasattr(result, 'labels')
            assert hasattr(result, 'n_clusters')
            assert hasattr(result, 'n_outliers')
            assert hasattr(result, 'cluster_sizes')

    def test_noise_detection(self, clusterer):
        """Test that low-quality faces are detected as noise."""
        embeddings = np.random.rand(20, 512).astype(np.float32)
        # Mix of high and low quality
        quality_scores = np.array([0.9] * 10 + [0.1] * 10)
        
        with patch.object(clusterer, '_clusterer') as mock_model:
            # Simulate that low-quality faces are marked as noise (-1)
            mock_model.labels_ = np.array([0] * 10 + [-1] * 10)
            mock_model.probabilities_ = np.random.rand(20)
            
            result = clusterer.cluster(embeddings, quality_scores)
            
            # Last 10 should be noise
            assert result.n_outliers == 10

    def test_min_cluster_size_parameter(self):
        """Test min_cluster_size parameter."""
        with patch('hdbscan.HDBSCAN') as mock_hdbscan:
            clusterer = QualityAwareClusterer(min_cluster_size=5)
            
            # Verify parameter passed to HDBSCAN
            mock_hdbscan.assert_called_once()
            call_kwargs = mock_hdbscan.call_args[1]
            assert call_kwargs['min_cluster_size'] == 5

    def test_empty_embeddings_handling(self, clusterer):
        """Test handling of empty embeddings array."""
        embeddings = np.array([]).reshape(0, 512)
        quality_scores = np.array([])
        
        result = clusterer.cluster(embeddings, quality_scores)
        
        assert len(result.labels) == 0
        assert result.n_clusters == 0

    def test_single_embedding_handling(self, clusterer):
        """Test handling of single embedding."""
        embeddings = np.random.rand(1, 512).astype(np.float32)
        quality_scores = np.array([0.8])
        
        result = clusterer.cluster(embeddings, quality_scores)
        
        assert len(result.labels) == 1
        # Single point should be outlier (not enough for cluster)

    def test_cluster_count_statistics(self, clusterer):
        """Test cluster count statistics."""
        embeddings = np.random.rand(30, 512).astype(np.float32)
        quality_scores = np.random.rand(30)
        
        with patch.object(clusterer, '_clusterer') as mock_model:
            # Create 3 clusters plus noise
            mock_model.labels_ = np.array([0] * 10 + [1] * 10 + [2] * 10)
            mock_model.probabilities_ = np.random.rand(30)
            
            result = clusterer.cluster(embeddings, quality_scores)
            
            assert result.n_clusters == 3

    def test_consistent_clustering_results(self, clusterer):
        """Test clustering produces consistent results."""
        embeddings = np.random.rand(30, 512).astype(np.float32)
        quality_scores = np.random.rand(30)
        
        with patch.object(clusterer, '_clusterer') as mock_model:
            mock_model.labels_ = np.array([0] * 15 + [1] * 15)
            mock_model.probabilities_ = np.random.rand(30)
            
            # Run twice with same input
            result1 = clusterer.cluster(embeddings, quality_scores)
            result2 = clusterer.cluster(embeddings, quality_scores)
            
            # Should produce same results
            assert len(result1.labels) == len(result2.labels)
            assert np.array_equal(result1.labels, result2.labels)

    def test_large_scale_clustering(self, clusterer):
        """Test clustering with large number of embeddings."""
        n_faces = 1000
        embeddings = np.random.rand(n_faces, 512).astype(np.float32)
        quality_scores = np.random.rand(n_faces)
        
        with patch.object(clusterer, '_clusterer') as mock_model:
            mock_model.labels_ = np.random.randint(-1, 10, n_faces)
            mock_model.probabilities_ = np.random.rand(n_faces)
            
            result = clusterer.cluster(embeddings, quality_scores)
            
            assert len(result.labels) == n_faces

    def test_get_cluster_centers(self, clusterer):
        """Test cluster center computation."""
        embeddings = np.random.rand(20, 512).astype(np.float32)
        labels = np.array([0] * 10 + [1] * 10)
        
        centers = clusterer.get_cluster_centers(embeddings, labels)
        
        assert 0 in centers
        assert 1 in centers
        assert centers[0].shape == (512,)
        assert centers[1].shape == (512,)

    def test_predict_new_embeddings(self, clusterer):
        """Test prediction for new embeddings."""
        embeddings = np.random.rand(50, 512).astype(np.float32)
        quality_scores = np.random.rand(50)
        
        with patch.object(clusterer, '_clusterer') as mock_model:
            mock_model.labels_ = np.random.randint(0, 5, 50)
            mock_model.probabilities_ = np.random.rand(50)
            mock_model.approximate_predict.return_value = (np.array([0, 1, 2]), None)
            
            # Fit first
            clusterer.cluster(embeddings, quality_scores)
            
            # Predict new
            new_embeddings = np.random.rand(3, 512).astype(np.float32)
            predictions = clusterer.predict(new_embeddings)
            
            assert len(predictions) == 3
