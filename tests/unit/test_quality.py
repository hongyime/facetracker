"""Unit tests for quality scoring module."""

import pytest
import numpy as np
from src.engine.quality import QualityScorer, QualityMetrics
from src.config import EngineConfig


class TestQualityScorer:
    """Test cases for QualityScorer class."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return EngineConfig()

    @pytest.fixture
    def scorer(self, config):
        """Create quality scorer instance."""
        return QualityScorer(config)

    def test_scorer_initialization(self, scorer):
        """Test scorer initializes correctly."""
        assert scorer is not None
        assert scorer.laplacian_threshold == 100.0
        assert scorer.min_face_area_percent == 0.05

    def test_compute_laplacian_variance_sharp_image(self, scorer):
        """Test Laplacian variance on sharp image."""
        # Create a sharp image with high frequency content
        sharp_image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        variance = scorer.compute_laplacian_variance(sharp_image)
        
        assert variance >= 0
        assert isinstance(variance, float)

    def test_compute_laplacian_variance_blurry_image(self, scorer):
        """Test Laplacian variance on blurry image."""
        # Create a uniform (blurry) image
        blurry_image = np.ones((100, 100, 3), dtype=np.uint8) * 128
        variance = scorer.compute_laplacian_variance(blurry_image)
        
        # Uniform image should have very low variance
        assert variance < 10.0

    def test_compute_laplacian_variance_grayscale(self, scorer):
        """Test Laplacian variance on grayscale image."""
        grayscale_image = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        variance = scorer.compute_laplacian_variance(grayscale_image)
        
        assert variance >= 0

    def test_compute_normalized_area(self, scorer):
        """Test normalized area calculation."""
        image_size = (1000, 1000)  # 1,000,000 pixels
        
        # Face occupying 10% of image
        face_bbox = [200, 200, 500, 500]  # 300x300 = 90,000 pixels
        normalized = scorer.compute_normalized_area(face_bbox, image_size)
        
        assert 0.0 <= normalized <= 1.0
        assert abs(normalized - 0.09) < 0.001  # 9% of image

    def test_compute_normalized_area_small_face(self, scorer):
        """Test normalized area for small face."""
        image_size = (1000, 1000)
        
        # Small face (1% of image)
        face_bbox = [450, 450, 550, 550]  # 100x100 = 10,000 pixels
        normalized = scorer.compute_normalized_area(face_bbox, image_size)
        
        assert abs(normalized - 0.01) < 0.001

    def test_compute_normalized_area_large_face(self, scorer):
        """Test normalized area for large face."""
        image_size = (1000, 1000)
        
        # Large face (50% of image)
        face_bbox = [0, 0, 707, 707]  # ~500,000 pixels
        normalized = scorer.compute_normalized_area(face_bbox, image_size)
        
        assert 0.4 <= normalized <= 0.6

    def test_compute_quality_score_high_quality(self, scorer):
        """Test quality score for high-quality face."""
        laplacian_variance = 500.0  # High
        normalized_area = 0.15  # Good size
        
        score = scorer.compute_quality_score(laplacian_variance, normalized_area)
        
        assert 0.0 <= score <= 1.0
        assert score > 0.7  # Should be high quality

    def test_compute_quality_score_low_quality_blurry(self, scorer):
        """Test quality score for blurry face."""
        laplacian_variance = 50.0  # Low (blurry)
        normalized_area = 0.15  # Good size
        
        score = scorer.compute_quality_score(laplacian_variance, normalized_area)
        
        assert 0.0 <= score <= 1.0
        assert score < 0.5  # Should be lower quality due to blur

    def test_compute_quality_score_low_quality_small(self, scorer):
        """Test quality score for small face."""
        laplacian_variance = 500.0  # High
        normalized_area = 0.02  # Very small
        
        score = scorer.compute_quality_score(laplacian_variance, normalized_area)
        
        assert 0.0 <= score <= 1.0
        assert score < 0.5  # Should be lower quality due to size

    def test_compute_quality_score_both_poor(self, scorer):
        """Test quality score for poor quality in both aspects."""
        laplacian_variance = 50.0  # Low
        normalized_area = 0.02  # Small
        
        score = scorer.compute_quality_score(laplacian_variance, normalized_area)
        
        assert 0.0 <= score <= 1.0
        assert score < 0.3  # Should be very low quality

    def test_evaluate_face_complete(self, scorer):
        """Test complete face evaluation."""
        image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
        bbox = [100, 100, 300, 300]  # 200x200 face
        
        metrics = scorer.evaluate_face(image, bbox)
        
        assert isinstance(metrics, QualityMetrics)
        assert metrics.laplacian_variance >= 0
        assert 0.0 <= metrics.normalized_area <= 1.0
        assert 0.0 <= metrics.quality_score <= 1.0

    def test_evaluate_face_with_crop_margin(self, scorer):
        """Test face evaluation with crop margin."""
        image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
        bbox = [200, 200, 300, 300]  # 100x100 face
        
        # With 15% margin
        metrics = scorer.evaluate_face(image, bbox, margin=0.15)
        
        assert isinstance(metrics, QualityMetrics)

    def test_quality_metrics_dataclass(self):
        """Test QualityMetrics dataclass."""
        metrics = QualityMetrics(
            laplacian_variance=250.0,
            normalized_area=0.1,
            quality_score=0.75,
        )
        
        assert metrics.laplacian_variance == 250.0
        assert metrics.normalized_area == 0.1
        assert metrics.quality_score == 0.75

    def test_is_acceptable_quality_high_threshold(self, scorer):
        """Test quality acceptance with high threshold."""
        metrics = QualityMetrics(
            laplacian_variance=300.0,
            normalized_area=0.12,
            quality_score=0.8,
        )
        
        assert scorer.is_acceptable_quality(metrics, threshold=0.7) is True
        assert scorer.is_acceptable_quality(metrics, threshold=0.9) is False

    def test_is_acceptable_quality_medium_threshold(self, scorer):
        """Test quality acceptance with medium threshold."""
        metrics_good = QualityMetrics(
            laplacian_variance=300.0,
            normalized_area=0.12,
            quality_score=0.6,
        )
        
        metrics_bad = QualityMetrics(
            laplacian_variance=50.0,
            normalized_area=0.03,
            quality_score=0.3,
        )
        
        assert scorer.is_acceptable_quality(metrics_good, threshold=0.5) is True
        assert scorer.is_acceptable_quality(metrics_bad, threshold=0.5) is False

    def test_laplacian_variance_edge_cases(self, scorer):
        """Test Laplacian variance edge cases."""
        # All zeros
        zero_image = np.zeros((50, 50, 3), dtype=np.uint8)
        variance_zero = scorer.compute_laplacian_variance(zero_image)
        assert variance_zero >= 0
        
        # All max value
        max_image = np.ones((50, 50, 3), dtype=np.uint8) * 255
        variance_max = scorer.compute_laplacian_variance(max_image)
        assert variance_max >= 0

    def test_normalized_area_edge_cases(self, scorer):
        """Test normalized area edge cases."""
        image_size = (100, 100)
        
        # Zero area
        bbox_zero = [50, 50, 50, 50]
        normalized_zero = scorer.compute_normalized_area(bbox_zero, image_size)
        assert normalized_zero == 0.0
        
        # Full image area
        bbox_full = [0, 0, 100, 100]
        normalized_full = scorer.compute_normalized_area(bbox_full, image_size)
        assert normalized_full == 1.0

    def test_compute_quality_score_weights(self, scorer):
        """Test that quality score properly weights both factors."""
        # Same laplacian, different areas
        score_large = scorer.compute_quality_score(300.0, 0.2)
        score_small = scorer.compute_quality_score(300.0, 0.05)
        
        # Larger face should generally score higher (all else equal)
        assert score_large >= score_small
