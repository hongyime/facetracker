"""Search API routes for face search operations."""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import List, Optional
import numpy as np
from PIL import Image
import io
import time
from sqlalchemy.orm import Session

from src.config import settings
from src.storage.database import Database, get_database, get_db_session
from src.storage.faiss_index import BatchedFAISSIndex
from src.engine.detector import FaceDetector
from src.search.engine import SearchEngine, SearchResult, SearchResponse
from src.search.ranking import RankingStrategy

router = APIRouter()

# Global instances for reuse
_detector = None
_faiss_index = None
_search_engine = None


def get_db():
    """Dependency to get database session — request-scoped, pool-safe."""
    yield from get_db_session(settings.database_url)


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


@router.post("/search", response_model=SearchResponse)
async def search_faces(
    image: UploadFile = File(...),
    top_k: int = 100,
    min_similarity: Optional[float] = None,
    db: Session = Depends(get_db),
    search_engine: SearchEngine = Depends(get_search_service),
    detector: FaceDetector = Depends(get_detector_service),
):
    """
    Search for similar faces by uploading an image.
    """
    start_time = time.time()
    try:
        # Read and detect (extract_embeddings=True pulls embedding from buffalo_l recognition module)
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))
        img_array = np.array(img.convert("RGB"))
        
        faces = detector.detect(img_array, extract_embeddings=True)
        if not faces:
            return SearchResponse(
                results=[], 
                total_found=0, 
                query_embedding_dim=512, 
                search_time_ms=(time.time() - start_time) * 1000
            )
        
        # Best face (most prominent)
        best_face = max(faces, key=lambda f: f.quality_score)
        
        # Pull embedding from detector result — same vector space as indexed faces
        embedding = best_face.embedding
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
):
    """
    Multi-face search - find images containing specific people.
    """
    start_time = time.time()
    try:
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))
        img_array = np.array(img.convert("RGB"))
        
        faces = detector.detect(img_array, extract_embeddings=True)
        if not faces:
            return SearchResponse(
                results=[], 
                total_found=0, 
                query_embedding_dim=512, 
                search_time_ms=(time.time() - start_time) * 1000
            )
        
        # Pull embeddings from detector results — same vector space as indexed faces
        embeddings = [f.embedding for f in faces if f.embedding is not None]
        
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

    NOT IMPLEMENTED. The previous version returned a hardcoded empty list,
    which silently misled callers. Returns HTTP 501 instead so clients
    correctly surface the gap.
    """
    raise HTTPException(
        status_code=501,
        detail="search_within_identity is not implemented yet",
    )
