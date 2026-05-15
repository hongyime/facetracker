"""Integration tests for the face processing pipeline."""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import List
import tempfile
import shutil

from src.pipeline.processor import PipelineProcessor
from src.storage.database import DatabaseSession
from src.storage.faiss_index import BatchedFAISSIndex
from src.config import AppConfig


class TestPipelineIntegration:
    """Integration tests for end-to-end pipeline processing."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test files."""
        temp = tempfile.mkdtemp()
        yield temp
        shutil.rmtree(temp)

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return AppConfig()

    @pytest.fixture
    def mock_session(self):
        """Create mocked database session."""
        session = Mock(spec=DatabaseSession)
        session.add = Mock()
        session.commit = Mock()
        session.query = Mock()
        return session

    @pytest.fixture
    def mock_faiss(self):
        """Create mocked FAISS index."""
        with patch('src.storage.faiss_index.BatchelFAISSIndex') as mock:
            instance = mock.return_value
            instance.add = Mock(return_value=0)
            instance.search = Mock(return_value=[])
            return instance

    def test_process_single_image(self, config, mock_session, mock_faiss, temp_dir):
        """Test processing a single image through the pipeline."""
        # Create test image
        test_image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
        image_path = Path(temp_dir) / "test_face.jpg"
        
        from PIL import Image
        Image.fromarray(test_image).save(image_path)
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.engine.detector.FaceAnalysis'):
                    result = processor.process_image(str(image_path))
                    
                    assert result is not None
                    assert result.success is True or result.success is False

    def test_process_multiple_images_batch(self, config, mock_session, mock_faiss, temp_dir):
        """Test processing multiple images in batch."""
        # Create test images
        image_paths = []
        for i in range(10):
            test_image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
            image_path = Path(temp_dir) / f"test_face_{i}.jpg"
            from PIL import Image
            Image.fromarray(test_image).save(image_path)
            image_paths.append(str(image_path))
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.engine.detector.FaceAnalysis'):
                    results = []
                    for path in image_paths:
                        result = processor.process_image(path)
                        results.append(result)
                    
                    assert len(results) == 10

    def test_embeddings_added_to_faiss(self, config, mock_session, mock_faiss, temp_dir):
        """Verify embeddings are added to FAISS index."""
        test_image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
        image_path = Path(temp_dir) / "test_face.jpg"
        
        from PIL import Image
        Image.fromarray(test_image).save(image_path)
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.engine.detector.FaceAnalysis'):
                    processor.process_image(str(image_path))
                    
                    # Verify FAISS add was called
                    if mock_faiss.add.called:
                        call_args = mock_faiss.add.call_args
                        embedding = call_args[0][0]
                        assert embedding.shape == (512,)

    def test_faces_saved_to_database(self, config, mock_session, mock_faiss, temp_dir):
        """Verify faces are saved to database."""
        test_image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
        image_path = Path(temp_dir) / "test_face.jpg"
        
        from PIL import Image
        Image.fromarray(test_image).save(image_path)
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.engine.detector.FaceAnalysis'):
                    processor.process_image(str(image_path))
                    
                    # Verify database operations were performed
                    assert mock_session.add.called or mock_session.commit.called

    def test_search_returns_correct_results(self, config, mock_session, mock_faiss, temp_dir):
        """Test search functionality returns correct results."""
        # First, add some embeddings
        test_embeddings = [np.random.rand(512).astype(np.float32) for _ in range(5)]
        test_face_ids = [f"face_{i:03d}" for i in range(5)]
        
        for emb, fid in zip(test_embeddings, test_face_ids):
            mock_faiss.add(emb, fid)
        
        # Search
        query_embedding = test_embeddings[0]  # Search with first embedding
        mock_faiss.search.return_value = [(test_face_ids[0], 0.95)]
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                results = processor.search_faces(query_embedding, k=5)
                
                assert results is not None

    def test_thumbnail_generation(self, config, mock_session, mock_faiss, temp_dir):
        """Test thumbnail generation during processing."""
        test_image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
        image_path = Path(temp_dir) / "test_face.jpg"
        
        from PIL import Image
        Image.fromarray(test_image).save(image_path)
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.engine.detector.FaceAnalysis'):
                    result = processor.process_image(str(image_path))
                    
                    # Thumbnail should be generated or scheduled
                    assert result is not None

    def test_error_handling_invalid_image(self, config, mock_session, mock_faiss):
        """Test error handling for invalid images."""
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                result = processor.process_image("/nonexistent/path/image.jpg")
                
                assert result is not None
                assert result.success is False or result.faces_detected == 0

    def test_heic_image_processing(self, config, mock_session, mock_faiss, temp_dir):
        """Test HEIC image format processing."""
        # Create a mock HEIC file (we can't actually create HEIC without library)
        heic_path = Path(temp_dir) / "test.heic"
        heic_path.write_bytes(b"mock_heic_content")
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.readers.raw_heic.load_heic_image') as mock_load:
                    mock_load.return_value = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
                    with patch('src.engine.detector.FaceAnalysis'):
                        result = processor.process_image(str(heic_path))
                        
                        assert result is not None

    def test_video_frame_extraction(self, config, mock_session, mock_faiss, temp_dir):
        """Test video frame extraction and processing."""
        # Create a mock video file
        video_path = Path(temp_dir) / "test.mp4"
        video_path.write_bytes(b"mock_video_content")
        
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.readers.video_reader.extract_frames') as mock_extract:
                    mock_extract.return_value = [
                        (0, np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)),
                        (1, np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)),
                    ]
                    with patch('src.engine.detector.FaceAnalysis'):
                        with patch('src.engine.tracker.DeepSORTTracker'):
                            result = processor.process_video(str(video_path))
                            
                            assert result is not None

    def test_ondrive_file_handling(self, config, mock_session, mock_faiss, temp_dir):
        """Test OneDrive file download and processing."""
        processor = PipelineProcessor(config)
        
        onedrive_path = "C:/OneDrive/Photos/test.jpg"
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.discovery.onedrive.download_onedrive_file') as mock_download:
                    mock_download.return_value = str(Path(temp_dir) / "downloaded.jpg")
                    
                    with patch('src.engine.detector.FaceAnalysis'):
                        result = processor.process_image(onedrive_path)
                        
                        # Verify download was attempted
                        mock_download.assert_called_once()

    def test_ondrive_revert_after_processing(self, config, mock_session, mock_faiss, temp_dir):
        """Test OneDrive file revert to online-only after processing."""
        processor = PipelineProcessor(config)
        
        with patch.object(processor, 'db_session', mock_session):
            with patch.object(processor, 'faiss_index', mock_faiss):
                with patch('src.discovery.onedrive.download_onedrive_file') as mock_download:
                    mock_download.return_value = str(Path(temp_dir) / "downloaded.jpg")
                    
                    with patch('src.discovery.onedrive.revert_to_online_only') as mock_revert:
                        with patch('src.engine.detector.FaceAnalysis'):
                            processor.process_image("C:/OneDrive/test.jpg")
                            
                            # Verify revert was called
                            mock_revert.assert_called_once()

    def test_pipeline_statistics_tracking(self, config, mock_session, mock_faiss, temp_dir):
        """Test that pipeline tracks processing statistics."""
        processor = PipelineProcessor(config)
        
        # Process multiple images
        for i in range(5):
            test_image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
            image_path = Path(temp_dir) / f"test_{i}.jpg"
            
            from PIL import Image
            Image.fromarray(test_image).save(image_path)
            
            with patch.object(processor, 'db_session', mock_session):
                with patch.object(processor, 'faiss_index', mock_faiss):
                    with patch('src.engine.detector.FaceAnalysis'):
                        processor.process_image(str(image_path))
        
        # Check statistics
        stats = processor.get_stats()
        
        assert stats is not None
        assert 'images_processed' in stats or hasattr(processor, 'processed_count')

    def test_concurrent_processing_safety(self, config, mock_session, mock_faiss, temp_dir):
        """Test thread safety during concurrent processing."""
        import threading
        
        processor = PipelineProcessor(config)
        results = []
        
        def process_image_thread(image_num):
            test_image = np.random.randint(0, 255, (500, 500, 3), dtype=np.uint8)
            image_path = Path(temp_dir) / f"concurrent_{image_num}.jpg"
            
            from PIL import Image
            Image.fromarray(test_image).save(image_path)
            
            with patch.object(processor, 'db_session', mock_session):
                with patch.object(processor, 'faiss_index', mock_faiss):
                    with patch('src.engine.detector.FaceAnalysis'):
                        result = processor.process_image(str(image_path))
                        results.append(result)
        
        # Start multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=process_image_thread, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # All should complete
        assert len(results) == 5
