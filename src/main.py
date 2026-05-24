"""Main FastAPI application for Face Tracker."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import redis

from src.config import settings, get_settings
from src.utils.logging import setup_logging, get_logger
from src.storage.database import get_database, Base
from src.storage.faiss_index import BatchedFAISSIndex
from src.pipeline.processor import PipelineProcessor
from src.discovery.manifest import FileManifestManager
from src.discovery.watcher import FileWatcher
from src.discovery.manager import IndexingManager
from src.api.routes import search, identity, stats, files
from pathlib import Path

logger = get_logger(__name__)

# Global instances
indexing_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    global indexing_manager
    
    # Startup
    logger.info("Starting Face Tracker API...")
    
    # Setup logging
    setup_logging(settings.log_level)
    
    # Initialize database connection
    db = get_database(settings.database_url)
    db.create_tables()
    logger.info("Database connected")
    
    # Initialize FAISS index
    faiss_index = BatchedFAISSIndex(settings)
    
    # Initialize processor
    processor = PipelineProcessor(
        db=db,
        faiss_index=faiss_index,
        thumbnail_cache_path=Path(settings.thumbnail_cache_path)
    )
    
    # Initialize discovery components
    manifest = FileManifestManager(settings)
    watcher = FileWatcher(settings)
    
    # Initialize and start indexing manager
    app.state.indexing_manager = IndexingManager(
        config=settings,
        processor=processor,
        manifest=manifest,
        watcher=watcher
    )
    app.state.indexing_manager.start()
    
    logger.info("Face Tracker API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Face Tracker API...")
    if indexing_manager:
        indexing_manager.stop()
        
    db.close()
    logger.info("Database connection closed")


# Create FastAPI application
app = FastAPI(
    title="Face Tracker API",
    description="Private face search engine API",
    version="4.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5151", "http://localhost:3000", "http://localhost:8700", "http://127.0.0.1:5151", "http://127.0.0.1:8700"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(search.router, prefix="/api/v1", tags=["search"])
app.include_router(identity.router, prefix="/api/v1", tags=["identity"])
app.include_router(stats.router, prefix="/api/v1", tags=["stats"])
app.include_router(files.router, prefix="/api/v1", tags=["files"])


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Face Tracker API",
        "version": "4.0.0",
        "description": "Private face search engine",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=settings.dashboard_port,
        reload=False,
    )
