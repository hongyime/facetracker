
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.append(str(Path.cwd()))

from src.config import settings
from src.storage.database import get_database
from src.storage.faiss_index import BatchedFAISSIndex
from src.pipeline.processor import PipelineProcessor
from src.discovery.manifest import FileManifestManager
from src.discovery.watcher import FileWatcher
from src.discovery.manager import IndexingManager

def test_manager():
    print("Testing Indexing Manager initialization...")
    
    # Use a temporary database for testing
    test_db_url = "postgresql://postgres:changeme@localhost:5433/facetracker"
    db = get_database(test_db_url)
    db.create_tables()
    
    faiss_index = BatchedFAISSIndex(settings)
    
    processor = PipelineProcessor(
        db=db,
        faiss_index=faiss_index,
        thumbnail_cache_path=Path(settings.thumbnail_cache_path)
    )
    
    manifest = FileManifestManager(settings)
    watcher = FileWatcher(settings)
    
    manager = IndexingManager(
        config=settings,
        processor=processor,
        manifest=manifest,
        watcher=watcher
    )
    
    print("Manager initialized. Starting...")
    manager.start()
    
    # Wait a bit to see progress
    for _ in range(10):
        progress = manager.get_progress()
        print(f"Progress: {progress['files_scanned']} / {progress['files_total']} (scanning: {progress['is_scanning']})")
        if progress['current_file']:
            print(f"Current file: {progress['current_file']}")
        time.sleep(2)
        
    print("Stopping manager...")
    manager.stop()
    print("Test complete.")

if __name__ == "__main__":
    try:
        test_manager()
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
