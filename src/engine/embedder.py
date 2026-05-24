"""Face embedding extraction module using InsightFace."""

import numpy as np
from typing import List, Optional, Dict
import insightface
from insightface.app import FaceAnalysis

from src.utils.logging import get_logger

logger = get_logger(__name__)


class FaceEmbedder:
    """Extract 512-d face embeddings using InsightFace antelopev2 model."""

    def __init__(self, model_name: str = "antelopev2", providers: List[str] = None):
        """
        Initialize face embedder.

        Args:
            model_name: InsightFace model name (antelopev2 recommended).
            providers: ONNX runtime providers.
        """
        if providers is None:
            providers = ['CPUExecutionProvider']

        logger.info(f"Initializing FaceEmbedder with model: {model_name}")

        self.app = FaceAnalysis(
            name=model_name,
            providers=providers,
            allowed_modules=['recognition']
        )
        self.app.prepare(ctx_id=0, det_size=(640, 640))

        self.embedding_dim = 512
        logger.info(f"FaceEmbedder initialized, embedding dim: {self.embedding_dim}")

    def embed(self, image: np.ndarray, bbox: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """
        Extract embedding from a face image.

        Args:
            image: RGB image containing face (H, W, 3).
            bbox: Optional bounding box [x1, y1, x2, y2] to focus on.

        Returns:
            Normalized 512-d embedding as float32 array, or None on error.
        """
        try:
            # If bbox provided, crop to face
            if bbox is not None:
                x1, y1, x2, y2 = bbox.astype(int)
                image = image[y1:y2, x1:x2]
                
                if image.size == 0:
                    logger.warning("Empty face crop")
                    return None

            # Get face with embedding
            faces = self.app.get(image)

            if not faces:
                logger.warning("No face detected for embedding")
                return None

            # Use first detected face
            face = faces[0]
            
            if not hasattr(face, 'embedding') or face.embedding is None:
                logger.warning("No embedding available")
                return None

            # Get embedding and normalize
            embedding = face.embedding.astype(np.float32)
            
            # L2 normalize for cosine similarity
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding

        except Exception as e:
            logger.error(f"Embedding extraction failed: {e}")
            return None

    def embed_batch(
        self, 
        images: List[np.ndarray], 
        bboxes: Optional[List[np.ndarray]] = None
    ) -> List[Optional[np.ndarray]]:
        """
        Extract embeddings from multiple images.

        Args:
            images: List of RGB images.
            bboxes: Optional list of bounding boxes.

        Returns:
            List of embeddings (None for failed extractions).
        """
        embeddings = []
        for i, image in enumerate(images):
            bbox = bboxes[i] if bboxes else None
            emb = self.embed(image, bbox)
            embeddings.append(emb)
        
        return embeddings

    def to_halfvec(self, embedding: np.ndarray) -> np.ndarray:
        """
        Convert float32 embedding to float16 for PostgreSQL halfvec.

        Args:
            embedding: Float32 normalized embedding.

        Returns:
            Float16 embedding ready for halfvec storage.
        """
        return embedding.astype(np.float16)

    def from_halfvec(self, halfvec: np.ndarray) -> np.ndarray:
        """
        Convert float16 embedding back to float32.

        Args:
            halfvec: Float16 embedding from database.

        Returns:
            Float32 embedding for computation.
        """
        return halfvec.astype(np.float32)

    def cosine_similarity(
        self, 
        emb1: np.ndarray, 
        emb2: np.ndarray
    ) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            emb1: First normalized embedding.
            emb2: Second normalized embedding.

        Returns:
            Cosine similarity score (-1 to 1, higher = more similar).
        """
        try:
            # Ensure float32
            emb1 = self.from_halfvec(emb1) if emb1.dtype == np.float16 else emb1
            emb2 = self.from_halfvec(emb2) if emb2.dtype == np.float16 else emb2

            # Dot product of normalized vectors = cosine similarity
            similarity = np.dot(emb1, emb2)
            
            # Clamp to valid range
            return float(np.clip(similarity, -1.0, 1.0))

        except Exception as e:
            logger.error(f"Cosine similarity computation failed: {e}")
            return 0.0

    def distance(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Compute cosine distance between embeddings.

        Args:
            emb1: First embedding.
            emb2: Second embedding.

        Returns:
            Cosine distance (0 to 2, lower = more similar).
        """
        similarity = self.cosine_similarity(emb1, emb2)
        return 1.0 - similarity

    def verify(
        self, 
        emb1: np.ndarray, 
        emb2: np.ndarray, 
        threshold: float = 0.6
    ) -> bool:
        """
        Verify if two embeddings belong to the same person.

        Args:
            emb1: First embedding.
            emb2: Second embedding.
            threshold: Similarity threshold for match.

        Returns:
            True if embeddings match (same person).
        """
        similarity = self.cosine_similarity(emb1, emb2)
        return similarity >= threshold

    def get_embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self.embedding_dim
