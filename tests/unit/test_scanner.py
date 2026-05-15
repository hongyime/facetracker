"""Unit tests for file scanner module."""

import pytest
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import List, Generator
from src.discovery.scanner import DriveScanner, FileRecord
from src.config import DiscoveryConfig


class TestDriveScanner:
    """Test cases for DriveScanner class."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return DiscoveryConfig()

    @pytest.fixture
    def scanner(self, config):
        """Create scanner instance."""
        return DriveScanner(config)

    def test_scanner_initialization(self, scanner):
        """Test scanner initializes correctly."""
        assert scanner is not None
        assert scanner.excluded_paths is not None

    def test_is_excluded_path(self, scanner):
        """Test path exclusion logic."""
        # Add a test exclusion
        scanner.excluded_paths = ['/test/exclude', '/another/exclude']
        
        # Should be excluded
        assert scanner._is_excluded('/test/exclude/file.jpg') is True
        assert scanner._is_excluded('/another/exclude/subdir/file.png') is True
        
        # Should not be excluded
        assert scanner._is_excluded('/test/include/file.jpg') is False

    def test_is_valid_extension(self, scanner):
        """Test extension filtering."""
        # Valid extensions
        assert scanner._is_valid_extension('image.jpg') is True
        assert scanner._is_valid_extension('image.JPEG') is True
        assert scanner._is_valid_extension('photo.png') is True
        assert scanner._is_valid_extension('video.mp4') is True
        assert scanner._is_valid_extension('movie.MOV') is True
        
        # Invalid extensions
        assert scanner._is_valid_extension('document.pdf') is False
        assert scanner._is_valid_extension('archive.zip') is False
        assert scanner._is_valid_extension('file.txt') is False

    def test_scan_single_drive_basic(self, scanner):
        """Test basic single drive scanning."""
        mock_dir_entries = [
            Mock(name='image1.jpg', is_file=Mock(return_value=True), path='/test/image1.jpg'),
            Mock(name='image2.png', is_file=Mock(return_value=True), path='/test/image2.png'),
            Mock(name='subdir', is_file=Mock(return_value=False), path='/test/subdir'),
        ]
        
        with patch('os.scandir', return_value=mock_dir_entries):
            with patch('os.path.getsize', return_value=1024):
                with patch('os.path.getmtime', return_value=1234567890.0):
                    results = list(scanner.scan_single_drive('/test'))
                    
                    assert len(results) == 2
                    assert all(isinstance(r, FileRecord) for r in results)

    def test_scan_single_drive_excludes_directories(self, scanner):
        """Test that directories are excluded from results."""
        mock_dir_entries = [
            Mock(name='file.jpg', is_file=Mock(return_value=True), path='/test/file.jpg'),
            Mock(name='directory', is_file=Mock(return_value=False), path='/test/directory'),
        ]
        
        with patch('os.scandir', return_value=mock_dir_entries):
            with patch('os.path.getsize', return_value=1024):
                with patch('os.path.getmtime', return_value=1234567890.0):
                    results = list(scanner.scan_single_drive('/test'))
                    
                    assert len(results) == 1
                    assert results[0].path == '/test/file.jpg'

    def test_scan_single_drive_filters_extensions(self, scanner):
        """Test that invalid extensions are filtered."""
        mock_dir_entries = [
            Mock(name='valid.jpg', is_file=Mock(return_value=True), path='/test/valid.jpg'),
            Mock(name='invalid.pdf', is_file=Mock(return_value=True), path='/test/invalid.pdf'),
            Mock(name='valid.png', is_file=Mock(return_value=True), path='/test/valid.png'),
        ]
        
        with patch('os.scandir', return_value=mock_dir_entries):
            with patch('os.path.getsize', return_value=1024):
                with patch('os.path.getmtime', return_value=1234567890.0):
                    results = list(scanner.scan_single_drive('/test'))
                    
                    assert len(results) == 2
                    assert all(r.path.endswith(('.jpg', '.png')) for r in results)

    def test_scan_single_drive_excludes_configured_paths(self, scanner):
        """Test that configured paths are excluded."""
        scanner.excluded_paths = ['/test/excluded']
        
        mock_dir_entries = [
            Mock(name='included.jpg', is_file=Mock(return_value=True), path='/test/included.jpg'),
            Mock(name='excluded.jpg', is_file=Mock(return_value=True), path='/test/excluded/file.jpg'),
        ]
        
        with patch('os.scandir', return_value=mock_dir_entries):
            with patch('os.path.getsize', return_value=1024):
                with patch('os.path.getmtime', return_value=1234567890.0):
                    results = list(scanner.scan_single_drive('/test'))
                    
                    assert len(results) == 1
                    assert results[0].path == '/test/included.jpg'

    def test_file_record_creation(self, scanner):
        """Test FileRecord creation with correct attributes."""
        mock_entry = Mock(name='test.jpg', is_file=Mock(return_value=True), path='/test/test.jpg')
        
        with patch('os.path.getsize', return_value=2048):
            with patch('os.path.getmtime', return_value=1234567890.0):
                record = scanner._create_file_record(mock_entry)
                
                assert record.path == '/test/test.jpg'
                assert record.name == 'test.jpg'
                assert record.size == 2048
                assert record.mtime == 1234567890.0

    def test_scan_drives_parallel(self, scanner):
        """Test parallel scanning of multiple drives."""
        drive_sources = ['C:/test', 'D:/test']
        
        mock_entry = Mock(name='file.jpg', is_file=Mock(return_value=True), path='/test/file.jpg')
        
        with patch.object(scanner, 'scan_single_drive', return_value=iter([Mock()])):
            results = list(scanner.scan_drives(drive_sources))
            
            # Should scan both drives
            assert scanner.scan_single_drive.call_count == 2

    def test_generator_based_scanning(self, scanner):
        """Test that scanning uses generator pattern."""
        mock_dir_entries = [
            Mock(name='file1.jpg', is_file=Mock(return_value=True), path='/test/file1.jpg'),
            Mock(name='file2.jpg', is_file=Mock(return_value=True), path='/test/file2.jpg'),
        ]
        
        with patch('os.scandir', return_value=mock_dir_entries):
            with patch('os.path.getsize', return_value=1024):
                with patch('os.path.getmtime', return_value=1234567890.0):
                    result = scanner.scan_single_drive('/test')
                    
                    # Should be a generator
                    assert hasattr(result, '__iter__')
                    assert hasattr(result, '__next__')

    def test_scanner_handles_permission_errors(self, scanner):
        """Test scanner handles permission errors gracefully."""
        with patch('os.scandir', side_effect=PermissionError("Access denied")):
            results = list(scanner.scan_single_drive('/protected'))
            
            # Should return empty generator, not raise
            assert results == []

    def test_scanner_handles_file_not_found(self, scanner):
        """Test scanner handles missing directories."""
        with patch('os.scandir', side_effect=FileNotFoundError("Path not found")):
            results = list(scanner.scan_single_drive('/nonexistent'))
            
            # Should return empty generator, not raise
            assert results == []

    def test_scanner_uses_os_scandir_not_walk(self, scanner):
        """Verify scanner uses os.scandir (not os.walk)."""
        # This is more of a code review test, but we can verify behavior
        mock_dir_entries = [
            Mock(name='file.jpg', is_file=Mock(return_value=True), path='/test/file.jpg'),
        ]
        
        with patch('os.scandir', return_value=mock_dir_entries) as mock_scandir:
            with patch('os.path.getsize', return_value=1024):
                with patch('os.path.getmtime', return_value=1234567890.0):
                    list(scanner.scan_single_drive('/test'))
                    
                    # Verify scandir was called, not walk
                    mock_scandir.assert_called_once()

    def test_batch_size_configuration(self, config):
        """Test batch size configuration."""
        config.batch_size = 500
        scanner = DriveScanner(config)
        
        # Batch size should be configurable
        assert scanner.config.batch_size == 500
