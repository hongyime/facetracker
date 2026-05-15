"""Ranking strategies for search results."""

from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime
import numpy as np

from .engine import SearchResult


@dataclass
class RankedResult(SearchResult):
    """Search result with ranking score."""
    ranking_score: float = 0.0
    recency_factor: float = 1.0
    quality_factor: float = 1.0


class RankingStrategy:
    """
    Ranking strategy combining multiple factors.
    
    Factors:
    - Similarity score from FAISS
    - Quality score of the face detection
    - Recency of the image
    """
    
    def __init__(
        self,
        similarity_weight: float = 0.5,
        quality_weight: float = 0.3,
        recency_weight: float = 0.2,
        recency_decay_days: float = 365.0
    ):
        """
        Initialize ranking strategy.
        
        Args:
            similarity_weight: Weight for similarity score (0-1)
            quality_weight: Weight for quality score (0-1)
            recency_weight: Weight for recency factor (0-1)
            recency_decay_days: Days for recency to decay to 0.5
        """
        self.similarity_weight = similarity_weight
        self.quality_weight = quality_weight
        self.recency_weight = recency_weight
        self.recency_decay_days = recency_decay_days
        
        # Normalize weights
        total = similarity_weight + quality_weight + recency_weight
        if total > 0:
            self.similarity_weight /= total
            self.quality_weight /= total
            self.recency_weight /= total
    
    def rank(
        self,
        results: List[SearchResult],
        reference_date: Optional[datetime] = None
    ) -> List[RankedResult]:
        """
        Rank search results using combined scoring.
        
        Args:
            results: List of SearchResult objects
            reference_date: Reference date for recency calculation
            
        Returns:
            List of RankedResult objects sorted by ranking score
        """
        if reference_date is None:
            reference_date = datetime.utcnow()
        
        ranked_results = []
        
        for result in results:
            # Compute recency factor (requires image timestamp)
            recency_factor = self._compute_recency_factor(
                result.image_id, reference_date
            )
            
            # Normalize quality score (assume 0-1 range)
            quality_factor = min(1.0, max(0.0, result.quality_score))
            
            # Combined ranking score
            ranking_score = (
                self.similarity_weight * result.similarity +
                self.quality_weight * quality_factor +
                self.recency_weight * recency_factor
            )
            
            ranked_results.append(RankedResult(
                face_id=result.face_id,
                image_id=result.image_id,
                file_path=result.file_path,
                similarity=result.similarity,
                quality_score=result.quality_score,
                thumbnail_path=result.thumbnail_path,
                bbox_x=result.bbox_x,
                bbox_y=result.bbox_y,
                bbox_w=result.bbox_w,
                bbox_h=result.bbox_h,
                ranking_score=ranking_score,
                recency_factor=recency_factor,
                quality_factor=quality_factor
            ))
        
        # Sort by ranking score (descending)
        ranked_results.sort(key=lambda r: r.ranking_score, reverse=True)
        
        return ranked_results
    
    def _compute_recency_factor(
        self,
        image_id: str,
        reference_date: datetime
    ) -> float:
        """
        Compute recency factor based on image ID timestamp.
        
        Image IDs contain timestamps. We extract and compute decay.
        
        Args:
            image_id: Image identifier (contains timestamp)
            reference_date: Reference date
            
        Returns:
            Recency factor (0-1), where 1 is most recent
        """
        # Try to extract timestamp from image_id
        # Format: img_YYYYMMDD_HHMMSS_xxx
        try:
            parts = image_id.split('_')
            if len(parts) >= 3:
                date_str = parts[1]
                time_str = parts[2]
                
                # Parse date
                year = int(date_str[:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
                
                hour = int(time_str[:2]) if len(time_str) >= 2 else 0
                minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                second = int(time_str[4:6]) if len(time_str) >= 6 else 0
                
                image_date = datetime(year, month, day, hour, minute, second)
                
                # Compute days difference
                days_diff = (reference_date - image_date).days
                
                if days_diff < 0:
                    return 1.0  # Future date, treat as most recent
                
                # Exponential decay: factor = 0.5^(days / half_life)
                half_life = self.recency_decay_days
                recency_factor = 0.5 ** (days_diff / half_life)
                
                return recency_factor
                
        except (ValueError, IndexError):
            pass
        
        # Default: neutral recency
        return 0.5
    
    def rank_by_similarity_only(
        self,
        results: List[SearchResult]
    ) -> List[RankedResult]:
        """
        Rank results by similarity score only.
        
        Args:
            results: List of SearchResult objects
            
        Returns:
            List of RankedResult objects sorted by similarity
        """
        ranked_results = []
        
        for result in results:
            ranked_results.append(RankedResult(
                face_id=result.face_id,
                image_id=result.image_id,
                file_path=result.file_path,
                similarity=result.similarity,
                quality_score=result.quality_score,
                thumbnail_path=result.thumbnail_path,
                bbox_x=result.bbox_x,
                bbox_y=result.bbox_y,
                bbox_w=result.bbox_w,
                bbox_h=result.bbox_h,
                ranking_score=result.similarity,
                recency_factor=1.0,
                quality_factor=min(1.0, max(0.0, result.quality_score))
            ))
        
        ranked_results.sort(key=lambda r: r.similarity, reverse=True)
        
        return ranked_results
