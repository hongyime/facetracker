"""Database module with SQLAlchemy models for Face Tracker."""

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    ForeignKey, Boolean, Index, Text, event, text
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from pgvector.sqlalchemy import Vector
from datetime import datetime
from typing import Optional, List
import numpy as np

Base = declarative_base()


class Image(Base):
    """Image table storing metadata about processed images."""
    
    __tablename__ = "images"
    
    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(Text, nullable=False, unique=True, index=True)
    file_hash = Column(String(64), nullable=False, index=True)
    file_size = Column(Integer, nullable=False)
    file_mtime = Column(Float, nullable=False)
    width = Column(Integer)
    height = Column(Integer)
    status = Column(String(50), default="pending", index=True)  # pending, processing, completed, failed
    error_message = Column(Text)
    is_video = Column(Boolean, default=False)
    video_frames = Column(Integer, default=0)
    face_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    faces = relationship("Face", back_populates="image", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_images_file_hash", "file_hash"),
        Index("idx_images_status", "status"),
    )


class Face(Base):
    """Face table storing detected faces and their embeddings."""
    
    __tablename__ = "faces"
    
    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True)
    embedding_id = Column(String(64), unique=True, nullable=False, index=True)
    
    # Normalized bounding box (0-1)
    bbox_x1 = Column(Float, nullable=False)
    bbox_y1 = Column(Float, nullable=False)
    bbox_x2 = Column(Float, nullable=False)
    bbox_y2 = Column(Float, nullable=False)
    
    # Pixel coordinates
    bbox_px_x1 = Column(Integer, nullable=False)
    bbox_px_y1 = Column(Integer, nullable=False)
    bbox_px_x2 = Column(Integer, nullable=False)
    bbox_px_y2 = Column(Integer, nullable=False)
    
    # Quality metrics
    quality_score = Column(Float, nullable=False, index=True)
    laplacian_variance = Column(Float)
    face_area_percent = Column(Float)
    detection_confidence = Column(Float)
    
    # Embedding stored as halfvec (16-bit float)
    embedding_vec = Column(Vector(512))
    
    thumbnail_path = Column(Text)
    
    # Tracking info (for video frames)
    track_id = Column(Integer)
    frame_number = Column(Integer)
    video_path = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    image = relationship("Image", back_populates="faces")
    identity_mappings = relationship("FaceIdentityMap", back_populates="face", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_faces_embedding_id", "embedding_id"),
        Index("idx_faces_quality_score", "quality_score"),
    )


class Identity(Base):
    """Identity table representing a unique person."""
    
    __tablename__ = "identities"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    label = Column(String(255))  # User-assigned label
    is_verified = Column(Boolean, default=False)
    cluster_id = Column(Integer)  # Original clustering assignment
    
    # Cluster centroid embedding
    centroid_embedding = Column(Vector(512))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    face_mappings = relationship("FaceIdentityMap", back_populates="identity", cascade="all, delete-orphan")
    audit_logs = relationship("VerificationAudit", back_populates="identity", cascade="all, delete-orphan")


class FaceIdentityMap(Base):
    """Mapping table between faces and identities."""
    
    __tablename__ = "face_identity_map"
    
    id = Column(Integer, primary_key=True, index=True)
    face_id = Column(Integer, ForeignKey("faces.id"), nullable=False, unique=True)
    identity_id = Column(Integer, ForeignKey("identities.id"), nullable=False)
    similarity_to_centroid = Column(Float)
    is_primary = Column(Boolean, default=False)  # Primary representative face
    assigned_by = Column(String(50))  # auto, user, merge
    confidence = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    face = relationship("Face", back_populates="identity_mappings")
    identity = relationship("Identity", back_populates="face_mappings")


class VerificationAudit(Base):
    """Audit log for identity verification actions."""
    
    __tablename__ = "verification_audit"
    
    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("identities.id"), nullable=False)
    action = Column(String(50), nullable=False)  # verify, merge, split, rename
    previous_value = Column(Text)
    new_value = Column(Text)
    user_id = Column(String(100))
    reason = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    identity = relationship("Identity", back_populates="audit_logs")


class FileManifest(Base):
    """File manifest for tracking processed files."""
    
    __tablename__ = "file_manifest"
    
    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(Text, nullable=False, unique=True, index=True)
    file_hash = Column(String(64), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_mtime = Column(Float, nullable=False)
    
    # Processing status
    is_processed = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    last_checked = Column(DateTime, default=datetime.utcnow)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_file_manifest_path", "file_path"),
        Index("idx_file_manifest_processed", "is_processed"),
    )


class OneDriveFile(Base):
    """OneDrive file tracking table."""
    
    __tablename__ = "onedrive_files"
    
    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(Text, nullable=False, unique=True, index=True)
    
    # OneDrive status indicators
    is_placeholder = Column(Boolean, default=False)
    is_online_only = Column(Boolean, default=False)
    is_local = Column(Boolean, default=False)
    
    # Detection method results
    has_reparse_point = Column(Boolean, default=False)
    has_cloud_attribute = Column(Boolean, default=False)
    size_mismatch = Column(Boolean, default=False)
    
    # Processing status
    download_status = Column(String(50))  # pending, downloading, completed, failed
    revert_status = Column(String(50))  # pending, reverting, completed, failed
    
    local_path = Column(Text)  # Temp path when downloaded
    original_size = Column(Integer)
    downloaded_size = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Database connection management
class Database:
    """Database connection and session manager.

    NOTE: This class still exists for the indexing pipeline and the FastAPI
    lifespan, which use the long-lived `session` property. For request-scoped
    work in HTTP routes, prefer `get_db_session()` below — it yields a fresh
    Session per request and closes it in finally.
    """
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self.SessionLocal = None
        self._session = None
    
    def connect(self) -> None:
        """Create database engine and session factory."""
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )
    
    def create_tables(self) -> None:
        """Create all tables in the database."""
        if self.engine:
            with self.engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            Base.metadata.create_all(bind=self.engine)
    
    def get_session(self):
        """Get a database session."""
        if not self.SessionLocal:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self.SessionLocal()
    
    def close(self) -> None:
        """Close database connection."""
        if self.engine:
            self.engine.dispose()

    @property
    def session(self):
        """Internal session for direct calls."""
        if self._session is None:
            self._session = self.get_session()
        return self._session

    def get_image_by_hash(self, file_hash: str) -> Optional[Image]:
        """Get image by file hash."""
        return self.session.query(Image).filter(Image.file_hash == file_hash).first()

    def add_image(self, image: Image) -> None:
        """Add image to session."""
        self.session.add(image)

    def add_face(self, face: Face) -> None:
        """Add face to session."""
        self.session.add(face)

    def commit(self) -> None:
        """Commit current transaction."""
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def rollback(self) -> None:
        """Rollback current transaction."""
        self.session.rollback()


# --- Module-level engine cache ------------------------------------------------
# `get_database(url)` used to construct a NEW Database (and therefore a new
# SQLAlchemy engine + connection pool) on EVERY call, including every HTTP
# request. Routes invoking it per-request leaked connection pools indefinitely.
# We now cache one Database (one engine) per database_url.
import threading as _threading
_DB_CACHE: dict = {}
_DB_CACHE_LOCK = _threading.Lock()


def get_database(database_url: str) -> Database:
    """Return a connected Database for the given URL, cached per process.

    Safe to call from multiple threads / requests; only one engine is created
    per unique URL.
    """
    db = _DB_CACHE.get(database_url)
    if db is not None:
        return db
    with _DB_CACHE_LOCK:
        db = _DB_CACHE.get(database_url)
        if db is None:
            db = Database(database_url)
            db.connect()
            _DB_CACHE[database_url] = db
        return db


def get_db_session(database_url: str):
    """FastAPI-style request-scoped Session generator.

    Usage in a route module:
        from src.config import settings
        from src.storage.database import get_db_session
        def get_db():
            yield from get_db_session(settings.database_url)
        @router.get(...)
        def handler(db: Session = Depends(get_db)): ...

    Each request gets its own Session bound to the cached engine; the Session
    is closed in finally so connections return to the pool deterministically.
    """
    db = get_database(database_url)
    session = db.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def reset_database_cache() -> None:
    """Dispose all cached engines. Intended for tests / shutdown."""
    with _DB_CACHE_LOCK:
        for db in _DB_CACHE.values():
            try:
                db.close()
            except Exception:
                pass
        _DB_CACHE.clear()
