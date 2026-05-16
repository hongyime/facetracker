"""Identity management API routes."""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.config import settings
from src.storage.database import get_database, Identity, Face, FaceIdentityMap

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/identities", tags=["identities"])


class IdentityResponse(BaseModel):
    """Response model for identity information."""
    identity_id: str
    name: Optional[str]
    face_count: int
    created_at: str
    updated_at: str
    avg_quality_score: float
    thumbnail_url: Optional[str]


class IdentityListResponse(BaseModel):
    """Response model for listing identities."""
    identities: List[IdentityResponse]
    total: int
    page: int
    page_size: int


class MergeRequest(BaseModel):
    """Request to merge identities."""
    source_ids: List[str]
    target_id: str


class SplitRequest(BaseModel):
    """Request to split faces from an identity."""
    identity_id: str
    face_ids: List[str]
    new_identity_name: Optional[str] = None


class VerifyRequest(BaseModel):
    """Request to verify a face belongs to an identity."""
    face_id: str
    confirm: bool


def get_db():
    """Dependency to get database session."""
    db = get_database(settings.database_url)
    try:
        yield db.session
    finally:
        pass


@router.get("", response_model=IdentityListResponse)
async def list_identities(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    min_faces: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List all identities with pagination."""
    query = db.query(Identity)
    
    if min_faces:
        query = query.join(FaceIdentityMap).group_by(Identity.id).having(func.count(FaceIdentityMap.id) >= min_faces)
    
    total = query.count()
    offset = (page - 1) * page_size
    identities = query.offset(offset).limit(page_size).all()
    
    results = []
    for identity in identities:
        face_count = db.query(func.count(FaceIdentityMap.id)).filter(FaceIdentityMap.identity_id == identity.id).scalar()
        
        primary_face = db.query(Face).join(FaceIdentityMap).filter(
            FaceIdentityMap.identity_id == identity.id,
            FaceIdentityMap.is_primary == True
        ).first()
        
        if not primary_face:
            primary_face = db.query(Face).join(FaceIdentityMap).filter(
                FaceIdentityMap.identity_id == identity.id
            ).first()

        results.append(IdentityResponse(
            identity_id=str(identity.id),
            name=identity.name,
            face_count=face_count or 0,
            created_at=identity.created_at.isoformat(),
            updated_at=identity.updated_at.isoformat(),
            avg_quality_score=0.8,
            thumbnail_url=primary_face.thumbnail_path if primary_face else None
        ))
        
    return IdentityListResponse(
        identities=results,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{identity_id}", response_model=IdentityResponse)
async def get_identity(identity_id: str, db: Session = Depends(get_db)):
    """Get details of a specific identity."""
    try:
        identity_int_id = int(identity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid identity ID")

    identity = db.query(Identity).filter(Identity.id == identity_int_id).first()
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
        
    face_count = db.query(func.count(FaceIdentityMap.id)).filter(FaceIdentityMap.identity_id == identity.id).scalar()
    
    return IdentityResponse(
        identity_id=str(identity.id),
        name=identity.name,
        face_count=face_count or 0,
        created_at=identity.created_at.isoformat(),
        updated_at=identity.updated_at.isoformat(),
        avg_quality_score=0.8,
        thumbnail_url=None
    )
