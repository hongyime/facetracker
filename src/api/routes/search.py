"""Search API routes for face search operations."""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import List, Optional
import numpy as np
from PIL import Image
import io
import time
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.database import Database, get_database
from src.storage.faiss_index import BatchedFAISSIndex
from src.engine.embedder import FaceEmbedder
from src.engine.detector import FaceDetector
from src.search.engine import SearchEngine, SearchResult, SearchResponse
from src.search.ranking import RankingStrategy

router = APIRouter()

# Global instances for reuse
_detector = None
_embedder = None
_faiss_index = None
_search_engine = None


def get_db():
    """Dependency to get database session."""
    db = get_database(settings.database_url)
    try:
        yield db.session
    finally:
        pass  # Database class manages session lifetime


def get_search_service() -> SearchEngine:
    """Dependency to get search engine."""
    global _search_engine, _faiss_index
    if _faiss_index is None:
        _faiss_index = BatchedFAISSIndex(settings)
    if _search_engine is None:
        _search_engine = SearchEngine(_faiss_index, settings)
    return _search_engine


def get_detector_service() -> FaceDetector:
    """Dependency to get face detector."""
    global _detector
    if _detector is None:
        _detector = FaceDetector()
    return _detector


def get_embedder_service() -> FaceEmbedder:
    """Dependency to get face embedder."""
    global _embedder
    if _embedder is None:
        _embedder = FaceEmbedder()
    return _embedder


@router.post("/search", response_model=SearchResponse)
async def search_faces(
    image: UploadFile = File(...),
    top_k: int = 100,
    min_similarity: Optional[float] = None,
    db: Session = Depends(get_db),
    search_engine: SearchEngine = Depends(get_search_service),
    detector: FaceDetector = Depends(get_detector_service),
    embedder: FaceEmbedder = Depends(get_embedder_service),
):
    """
    Search for similar faces by uploading an image.
    """
    start_time = time.time()
    try:
        # Read and detect
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))
        img_array = np.array(img.convert("RGB"))
        
        faces = detector.detect(img_array)
        if not faces:
            return SearchResponse(
                results=[], 
                total_found=0, 
                query_embedding_dim=512, 
                search_time_ms=(time.time() - start_time) * 1000
            )
        
        # Best face (most prominent)
        best_face = max(faces, key=lambda f: f.quality_score)
        
        # Embed
        embedding = embedder.embed(img_array, best_face.bbox)
        if embedding is None:
            raise HTTPException(status_code=400, detail="Failed to extract embedding")
        
        # Search
        results = search_engine.search(
            embedding, 
            k=top_k, 
            threshold=min_similarity, 
            db_session=db
        )
        
        return SearchResponse(
            results=results,
            total_found=len(results),
            query_embedding_dim=512,
            search_time_ms=(time.time() - start_time) * 1000
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/multi", response_model=SearchResponse)
async def search_multi_face(
    image: UploadFile = File(...),
    mode: str = "any",
    top_k: int = 100,
    min_similarity: Optional[float] = None,
    db: Session = Depends(get_db),
    search_engine: SearchEngine = Depends(get_search_service),
    detector: FaceDetector = Depends(get_detector_service),
    embedder: FaceEmbedder = Depends(get_embedder_service),
):
    """
    Multi-face search - find images containing specific people.
    """
    start_time = time.time()
    try:
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))
        img_array = np.array(img.convert("RGB"))
        
        faces = detector.detect(img_array)
        if not faces:
            return SearchResponse(
                results=[], 
                total_found=0, 
                query_embedding_dim=512, 
                search_time_ms=(time.time() - start_time) * 1000
            )
        
        # Embed all detected faces
        embeddings = []
        for face in faces:
            emb = embedder.embed(img_array, face.bbox)
            if emb is not None:
                embeddings.append(emb)
        
        if not embeddings:
            raise HTTPException(status_code=400, detail="No usable faces detected")
        
        # Search multi
        results = search_engine.search_multi(
            embeddings,
            mode=mode,
            k=top_k,
            threshold=min_similarity,
            db_session=db
        )
        
        return SearchResponse(
            results=results,
            total_found=len(results),
            query_embedding_dim=512,
            search_time_ms=(time.time() - start_time) * 1000
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/identity/{identity_id}")
async def search_within_identity(
    identity_id: int,
    image: UploadFile = File(...),
    top_k: int = 50,
):
    """
    Search for faces within a specific identity cluster.
    
    Args:
        identity_id: Identity cluster ID
        image: Query image
        top_k: Number of results
        
    Returns:
        Matching faces from the specified identity
    """
    # This would require database filtering by identity
    # For now, return a placeholder response
    return {
        "identity_id": identity_id,
        "message": "Identity-restricted search - coming soon",
        "results": [],
    }
