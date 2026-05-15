"""Search API routes for face search operations."""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import List, Optional
import numpy as np
from PIL import Image
import io

from src.config import settings
from src.storage.faiss_index import BatchedFAISSIndex
from src.storage.thumbnail_cache import ThumbnailCache
from src.engine.embedder import FaceEmbedder
from src.engine.detector import FaceDetector
from src.search.engine import SearchEngine
from src.search.ranking import RankingStrategy
from src.search.multi_face import MultiFaceSearcher, MultiFaceQuery

router = APIRouter()

# Initialize components (lazy loading)
_embedder: Optional[FaceEmbedder] = None
_detector: Optional[FaceDetector] = None
_faiss_index: Optional[BatchedFAISSIndex] = None
_thumbnail_cache: Optional[ThumbnailCache] = None
_search_engine: Optional[SearchEngine] = None
_ranking_strategy: Optional[RankingStrategy] = None


def get_embedder() -> FaceEmbedder:
    """Get or create face embedder instance."""
    global _embedder
    if _embedder is None:
        _embedder = FaceEmbedder(settings)
    return _embedder


def get_detector() -> FaceDetector:
    """Get or create face detector instance."""
    global _detector
    if _detector is None:
        _detector = FaceDetector(settings)
    return _detector


def get_faiss_index() -> BatchedFAISSIndex:
    """Get or create FAISS index instance."""
    global _faiss_index
    if _faiss_index is None:
        _faiss_index = BatchedFAISSIndex(settings)
    return _faiss_index


def get_thumbnail_cache() -> ThumbnailCache:
    """Get or create thumbnail cache instance."""
    global _thumbnail_cache
    if _thumbnail_cache is None:
        _thumbnail_cache = ThumbnailCache(settings)
    return _thumbnail_cache


def get_search_engine() -> SearchEngine:
    """Get or create search engine instance."""
    global _search_engine
    if _search_engine is None:
        _search_engine = SearchEngine(get_faiss_index(), settings)
    return _search_engine


def get_ranking_strategy() -> RankingStrategy:
    """Get or create ranking strategy instance."""
    global _ranking_strategy
    if _ranking_strategy is None:
        _ranking_strategy = RankingStrategy()
    return _ranking_strategy


@router.post("/search")
async def search_faces(
    image: UploadFile = File(...),
    top_k: int = 100,
    min_similarity: float = 0.6,
    use_ranking: bool = True,
):
    """
    Search for similar faces by uploading an image.
    
    Args:
        image: Uploaded image file
        top_k: Number of results to return
        min_similarity: Minimum similarity threshold
        use_ranking: Whether to apply ranking strategy
        
    Returns:
        List of matching faces with similarity scores and thumbnails
    """
    try:
        # Read uploaded image
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))
        img_array = np.array(img)
        
        # Detect faces
        detector = get_detector()
        faces = detector.detect(img_array)
        
        if not faces:
            return {"results": [], "message": "No faces detected in query image"}
        
        # Use the largest/most prominent face for search
        best_face = max(faces, key=lambda f: f.get("quality_score", 0))
        
        # Extract embedding
        embedder = get_embedder()
        embedding = embedder.embed(img_array, best_face["bbox"])
        
        if embedding is None:
            raise HTTPException(status_code=400, detail="Failed to extract face embedding")
        
        # Search using search engine
        search_engine = get_search_engine()
        
        # Note: For full functionality, we need a database session
        # This is a simplified version without DB
        faiss_index = get_faiss_index()
        raw_results = faiss_index.search(embedding, k=top_k)
        
        # Filter by similarity threshold
        filtered_results = [
            {"face_id": face_id, "similarity": round(score, 4)}
            for face_id, score in raw_results
            if score >= min_similarity
        ]
        
        # Apply ranking if requested
        if use_ranking and filtered_results:
            ranking_strategy = get_ranking_strategy()
            # Create SearchResult objects for ranking
            from src.search.engine import SearchResult
            search_results = [
                SearchResult(
                    face_id=r["face_id"],
                    image_id="",  # Would come from DB
                    file_path="",
                    similarity=r["similarity"],
                    quality_score=0.5  # Would come from DB
                )
                for r in filtered_results
            ]
            
            ranked = ranking_strategy.rank_by_similarity_only(search_results)
            filtered_results = [
                {
                    "face_id": r.face_id,
                    "similarity": r.similarity,
                    "ranking_score": r.ranking_score,
                }
                for r in ranked
            ]
        
        # Get thumbnails for results
        thumbnail_cache = get_thumbnail_cache()
        for result in filtered_results:
            thumb_path = thumbnail_cache.get_thumbnail_path(result["face_id"])
            result["thumbnail_path"] = str(thumb_path) if thumb_path and thumb_path.exists() else None
        
        return {
            "query_face": {
                "bbox": best_face["bbox"],
                "quality_score": round(best_face.get("quality_score", 0), 4),
            },
            "results": filtered_results,
            "total_found": len(filtered_results),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/multi")
async def search_multi_face(
    image: UploadFile = File(...),
    mode: str = "any",  # "any" or "all"
    top_k: int = 100,
    min_similarity: float = 0.6,
):
    """
    Multi-face search - find images containing specific people.
    
    Args:
        image: Uploaded image with multiple faces
        mode: "any" (find any matching face) or "all" (find all faces together)
        top_k: Number of results per face
        min_similarity: Minimum similarity threshold
        
    Returns:
        Search results based on mode with ranked results
    """
    try:
        # Read uploaded image
        contents = await image.read()
        img = Image.open(io.BytesIO(contents))
        img_array = np.array(img)
        
        # Detect all faces
        detector = get_detector()
        faces = detector.detect(img_array)
        
        if not faces:
            return {"results": [], "message": "No faces detected in query image"}
        
        # Extract embeddings for all faces
        embedder = get_embedder()
        face_embeddings = []
        face_bboxes = []
        face_quality_scores = []
        
        for face in faces:
            embedding = embedder.embed(img_array, face["bbox"])
            if embedding is not None:
                face_embeddings.append(embedding)
                face_bboxes.append(face["bbox"])
                face_quality_scores.append(face.get("quality_score", 0))
        
        if not face_embeddings:
            raise HTTPException(status_code=400, detail="Failed to extract any face embeddings")
        
        # Use MultiFaceSearcher
        search_engine = get_search_engine()
        multi_searcher = MultiFaceSearcher(search_engine)
        
        # Create query
        query = multi_searcher.create_query_from_detections(
            embeddings=face_embeddings,
            bboxes=face_bboxes,
            quality_scores=face_quality_scores,
            mode=mode
        )
        
        # Perform search (simplified without DB session)
        faiss_index = get_faiss_index()
        all_results = {}
        
        for i, embedding in enumerate(face_embeddings):
            raw_results = faiss_index.search(embedding, k=top_k)
            
            filtered = [
                {"face_id": face_id, "similarity": round(score, 4)}
                for face_id, score in raw_results
                if score >= min_similarity
            ]
            
            all_results[f"face_{i}"] = {
                "bbox": face_bboxes[i],
                "quality_score": round(face_quality_scores[i], 4),
                "matches": filtered,
            }
        
        if mode == "all":
            # Find images that contain matches for ALL faces
            face_sets = [
                set(m["face_id"] for m in data["matches"])
                for data in all_results.values()
            ]
            
            if face_sets and all(face_sets):
                common_faces = set.intersection(*face_sets)
                combined_results = [
                    {"face_id": face_id, "similarity": 1.0}
                    for face_id in common_faces
                ]
            else:
                combined_results = []
            
            return {
                "mode": "all",
                "faces_detected": len(face_embeddings),
                "results": combined_results,
                "per_face_results": all_results,
            }
        else:
            # mode == "any": Union of all results
            # Aggregate by face_id, keeping best score
            aggregated = {}
            for face_data in all_results.values():
                for match in face_data["matches"]:
                    face_id = match["face_id"]
                    if face_id not in aggregated or match["similarity"] > aggregated[face_id]["similarity"]:
                        aggregated[face_id] = match
            
            # Sort by similarity
            union_results = sorted(
                aggregated.values(),
                key=lambda x: x["similarity"],
                reverse=True
            )[:top_k]
            
            return {
                "mode": "any",
                "faces_detected": len(face_embeddings),
                "results": union_results,
                "per_face_results": all_results,
            }
        
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
