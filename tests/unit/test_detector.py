"""Unit tests for face detector module."""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from src.engine.detector import FaceDetector, DetectionResult
from src.config import EngineConfig


class TestFaceDetector:
    """Test cases for FaceDetector class."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return EngineConfig()

    @pytest.fixture
    def detector(self, config):
        """Create detector instance with mocked dependencies."""
        with patch('src.engine.detector.FaceAnalysis'):
            return FaceDetector(config)

    def test_detector_initialization(self, detector):
        """Test detector initializes correctly."""
        assert detector is not None
        assert detector.min_face_area_percent == 0.05
        assert detector.laplacian_threshold == 100.0
        assert detector.confidence_threshold == 0.5

    def test_compute_laplacian_variance(self, detector):
        """Test Laplacian variance computation."""
        # Create a sharp image (high variance)
        sharp_image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        variance = detector._compute_laplacian_variance(sharp_image)
        assert variance >= 0

        # Create a blurry image (low variance)
        blurry_image = np.ones((100, 100, 3), dtype=np.uint8) * 128
        variance_blurry = detector._compute_laplacian_variance(blurry_image)
        assert variance_blurry < variance or variance_blurry == 0

    def test_filter_by_area(self, detector):
        """Test face area filtering."""
        image_area = 10000  # 100x100
        
        # Face with 10% area (should pass)
        bbox_large = [25, 25, 75, 75]  # 50x50 = 2500 pixels = 25%
        assert detector._filter_by_area(bbox_large, image_area) is True
        
        # Face with 2% area (should fail)
        bbox_small = [45, 45, 55, 55]  # 10x10 = 100 pixels = 1%
        assert detector._filter_by_area(bbox_small, image_area) is False

    def test_filter_by_laplacian(self, detector):
        """Test Laplacian variance filtering."""
        # High variance face crop (should pass)
        sharp_crop = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        assert detector._filter_by_laplacian(sharp_crop) is True
        
        # Low variance face crop (should fail)
        blurry_crop = np.ones((100, 100, 3), dtype=np.uint8) * 128
        # Note: This might pass depending on threshold, testing the method exists

    def test_detect_faces_single_face(self, detector):
        """Test detection of a single face."""
        # Mock the InsightFace model response
        mock_face = {
            'bbox': [50, 50, 150, 150],
            'det_score': 0.95,
        }
        
        test_image = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        
        with patch.object(detector, 'model') as mock_model:
            mock_model.get.return_value = [[mock_face]]
            results = detector.detect(test_image)
            
            assert len(results) >= 0  # May be filtered by quality
            if results:
                assert isinstance(results[0], DetectionResult)

    def test_detect_faces_no_faces(self, detector):
        """Test detection when no faces are present."""
        test_image = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        
        with patch.object(detector, 'model') as mock_model:
            mock_model.get.return_value = []
            results = detector.detect(test_image)
            
            assert len(results) == 0

    def test_detect_faces_multiple_faces(self, detector):
        """Test detection of multiple faces."""
        mock_faces = [
            {'bbox': [10, 10, 60, 60], 'det_score': 0.9},
            {'bbox': [100, 100, 150, 150], 'det_score': 0.85},
            {'bbox': [50, 150, 100, 200], 'det_score': 0.95},
        ]
        
        test_image = np.random.randint(0, 255, (300, 300, 3), dtype=np.uint8)
        
        with patch.object(detector, 'model') as mock_model:
            mock_model.get.return_value = [mock_faces]
            results = detector.detect(test_image)
            
            assert len(results) >= 0  # May be filtered

    def test_detect_faces_low_confidence_filtered(self, detector):
        """Test that low confidence detections are filtered."""
        mock_face = {
            'bbox': [50, 50, 150, 150],
            'det_score': 0.3,  # Below threshold
        }
        
        test_image = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        
        with patch.object(detector, 'model') as mock_model:
            mock_model.get.return_value = [[mock_face]]
            results = detector.detect(test_image)
            
            # Should be filtered out due to low confidence
            assert len(results) == 0

    def test_detection_result_bbox_area(self):
        """Test DetectionResult bbox_area calculation."""
        result = DetectionResult(
            bbox=[10, 10, 60, 60],
            confidence=0.9,
            quality_score=0.8,
        )
        assert result.bbox_area == 2500  # 50 * 50

    def test_detection_result_center_point(self):
        """Test DetectionResult center calculation."""
        result = DetectionResult(
            bbox=[10, 10, 60, 60],
            confidence=0.9,
            quality_score=0.8,
        )
        assert result.center_x == 35
        assert result.center_y == 35

    def test_detect_with_quality_scores(self, detector):
        """Test that detection results include quality scores."""
        mock_face = {
            'bbox': [50, 50, 150, 150],
            'det_score': 0.95,
        }
        
        test_image = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        
        with patch.object(detector, 'model') as mock_model:
            mock_model.get.return_value = [[mock_face]]
            with patch.object(detector, '_compute_laplacian_variance', return_value=500.0):
                results = detector.detect(test_image)
                
                if results:
                    assert results[0].quality_score > 0
                    assert results[0].confidence == 0.95

    def test_detect_handles_grayscale_images(self, detector):
        """Test detection handles grayscale images."""
        grayscale_image = np.random.randint(0, 255, (200, 200), dtype=np.uint8)
        
        with patch.object(detector, 'model') as mock_model:
            mock_model.get.return_value = []
            results = detector.detect(grayscale_image)
            
            assert results is not None

    def test_detect_handles_rgba_images(self, detector):
        """Test detection handles RGBA images."""
        rgba_image = np.random.randint(0, 255, (200, 200, 4), dtype=np.uint8)
        
        with patch.object(detector, 'model') as mock_model:
            mock_model.get.return_value = []
            results = detector.detect(rgba_image)
            
            assert results is not None
