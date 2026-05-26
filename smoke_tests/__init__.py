"""Shared smoke fixtures.

IMPORTANT: This module avoids importing from src.* at top level so that
test scripts can override env vars (FACE_STORAGE_ROOT etc.) BEFORE
src.config.Settings is instantiated. All src imports are deferred into
the helper bodies.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Optional

import numpy as np

# Tag prefix so we can clean only smoke-test rows
TEST_TAG = "smoke-test:"
TEST_PATH_PREFIX = f"/tmp/{TEST_TAG}"


def random_embedding(seed: Optional[int] = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


def make_test_image(session, suffix: str = ""):
    from src.storage.database import Image  # deferred
    s = suffix or uuid.uuid4().hex[:8]
    img = Image(
        file_path=f"{TEST_PATH_PREFIX}{s}.jpg",
        file_hash=f"{TEST_TAG}{s}-hash",
        file_size=1024,
        file_mtime=float(time.time()),
        width=640,
        height=480,
        status="completed",
        is_video=False,
        video_frames=0,
        face_count=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(img)
    session.flush()
    return img


def make_test_face(session, image, suffix: str = ""):
    from src.storage.database import Face  # deferred
    s = suffix or uuid.uuid4().hex[:8]
    face = Face(
        image_id=image.id,
        embedding_id=f"{TEST_TAG}{s}",
        bbox_x1=0.1, bbox_y1=0.1, bbox_x2=0.5, bbox_y2=0.5,
        bbox_px_x1=64, bbox_px_y1=48, bbox_px_x2=320, bbox_px_y2=240,
        quality_score=0.85,
        laplacian_variance=120.0,
        face_area_percent=0.16,
        detection_confidence=0.99,
        embedding_vec=None,
        created_at=datetime.utcnow(),
    )
    session.add(face)
    session.flush()
    return face


def truncate_test_data(engine) -> None:
    """Remove ONLY rows tagged with TEST_TAG. Safe against live data."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM faiss_outbox WHERE face_id LIKE :t"
        ), {"t": f"{TEST_TAG}%"})
        conn.execute(text(
            "DELETE FROM face_identity_map WHERE face_id IN ("
            "  SELECT id FROM faces WHERE embedding_id LIKE :t"
            ")"
        ), {"t": f"{TEST_TAG}%"})
        conn.execute(text(
            "DELETE FROM faces WHERE embedding_id LIKE :t"
        ), {"t": f"{TEST_TAG}%"})
        conn.execute(text(
            "DELETE FROM images WHERE file_path LIKE :t OR file_hash LIKE :t2"
        ), {"t": f"{TEST_PATH_PREFIX}%", "t2": f"{TEST_TAG}%"})
