"""Smoke 8: _save_image_record commits Image + Face + outbox atomically.

Bypass face detection (insightface) — directly construct a ProcessingResult
with synthetic faces and call _save_image_record, then verify all three
records exist after commit AND that a forced rollback leaves nothing behind.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["FACE_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="smoke8_faiss_")
os.environ["HOST_FACE_STORAGE"] = os.environ["FACE_STORAGE_ROOT"]
TMP_FAISS = os.environ["FACE_STORAGE_ROOT"]

import numpy as np
from sqlalchemy import text

from src.config import settings
from src.storage.database import get_database, Image, Face
from src.pipeline.processor import PipelineProcessor, ProcessingResult
from src.storage.outbox import enqueue_face

from smoke_tests import (
    TEST_TAG, TEST_PATH_PREFIX, random_embedding, truncate_test_data,
)


def make_synthetic_result(file_path: Path, n_faces: int = 2) -> ProcessingResult:
    """Build a ProcessingResult that looks like the pipeline produced it,
    without actually running detection."""
    result = ProcessingResult()
    result.file_path = file_path
    result.file_hash = f"{TEST_TAG}s8-hash-{n_faces}"
    result.status = "success"
    result.is_video = False
    result.video_frames_processed = 0
    result.faces_processed = n_faces
    result.width = 640
    result.height = 480
    result.face_objects = []
    for i in range(n_faces):
        f = Face(
            embedding_id=f"{TEST_TAG}s8_f{i}",
            bbox_x1=0.1 * (i + 1), bbox_y1=0.1, bbox_x2=0.5, bbox_y2=0.5,
            bbox_px_x1=64, bbox_px_y1=48, bbox_px_x2=320, bbox_px_y2=240,
            quality_score=0.85,
            laplacian_variance=120.0,
            face_area_percent=0.16,
            detection_confidence=0.99,
            embedding_vec=None,
        )
        emb = random_embedding(seed=8000 + i)
        result.face_objects.append((f, emb))
    return result


def main() -> int:
    db = get_database(settings.database_url)
    db.create_tables()
    truncate_test_data(db.engine)

    # Make a real on-disk file so result.file_path.stat() works
    img_dir = Path(tempfile.mkdtemp(prefix="smoke8_img_"))
    img_path = img_dir / f"{TEST_TAG.replace(':','_')}s8.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xd9" * 16)  # tiny valid-ish JPEG
    print(f"img_path={img_path} size={img_path.stat().st_size}")

    # Spin up a partial PipelineProcessor — only need _save_image_record.
    # Avoid full __init__ (loads insightface). Instead bind method manually:
    proc = PipelineProcessor.__new__(PipelineProcessor)
    proc.db = db  # bare minimum

    N = 2
    result = make_synthetic_result(img_path, n_faces=N)

    # ---- Happy path ----
    session = db.SessionLocal()
    try:
        proc._save_image_record(session, result)
    finally:
        session.close()

    with db.engine.connect() as c:
        n_img = c.execute(text(
            "SELECT COUNT(*) FROM images WHERE file_hash=:h"
        ), {"h": result.file_hash}).scalar()
        n_face = c.execute(text(
            "SELECT COUNT(*) FROM faces WHERE embedding_id LIKE :t"
        ), {"t": f"{TEST_TAG}s8_f%"}).scalar()
        n_out = c.execute(text(
            "SELECT COUNT(*) FROM faiss_outbox WHERE face_id LIKE :t"
        ), {"t": f"{TEST_TAG}s8_f%"}).scalar()
        # FK image_id should be set for faces
        face_image_ids = [r.image_id for r in c.execute(text(
            "SELECT image_id FROM faces WHERE embedding_id LIKE :t"
        ), {"t": f"{TEST_TAG}s8_f%"}).fetchall()]
    print(f"happy: images={n_img} faces={n_face} outbox={n_out} face_image_ids={face_image_ids}")
    assert n_img == 1
    assert n_face == N
    assert n_out == N
    assert len(set(face_image_ids)) == 1, "faces should share one image_id"

    # ---- Rollback path: simulate a crash mid-record by raising AFTER faces but BEFORE commit ----
    truncate_test_data(db.engine)
    # Use a DIFFERENT file path so the unique constraint on images.file_path
    # doesn't fire before our injected RuntimeError can.
    rollback_path = img_dir / f"{TEST_TAG.replace(':','_')}s8_rb.jpg"
    rollback_path.write_bytes(b"\xff\xd8\xff\xd9" * 16)
    rollback_result = make_synthetic_result(rollback_path, n_faces=N)
    rollback_result.file_hash = f"{TEST_TAG}s8-hash-rollback"
    for i, (f, _) in enumerate(rollback_result.face_objects):
        f.embedding_id = f"{TEST_TAG}s8_rb_{i}"

    # Monkeypatch enqueue_face to fail on the second face — must trigger rollback
    import src.pipeline.processor as proc_mod
    original_enqueue = proc_mod.enqueue_face
    counter = {"n": 0}

    def faulty_enqueue(session, face_id, embedding):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("simulated mid-write crash")
        return original_enqueue(session, face_id, embedding)

    proc_mod.enqueue_face = faulty_enqueue
    try:
        session = db.SessionLocal()
        try:
            proc._save_image_record(session, rollback_result)
            print("FAIL: _save_image_record did not raise")
            return 8
        except RuntimeError as e:
            print(f"caught_expected_exception={e}")
        finally:
            session.close()
    finally:
        proc_mod.enqueue_face = original_enqueue

    # After rollback, NOTHING should be persisted.
    with db.engine.connect() as c:
        n_img = c.execute(text(
            "SELECT COUNT(*) FROM images WHERE file_hash=:h"
        ), {"h": rollback_result.file_hash}).scalar()
        n_face = c.execute(text(
            "SELECT COUNT(*) FROM faces WHERE embedding_id LIKE :t"
        ), {"t": f"{TEST_TAG}s8_rb_%"}).scalar()
        n_out = c.execute(text(
            "SELECT COUNT(*) FROM faiss_outbox WHERE face_id LIKE :t"
        ), {"t": f"{TEST_TAG}s8_rb_%"}).scalar()
    print(f"after_rollback: images={n_img} faces={n_face} outbox={n_out}")
    assert n_img == 0, f"image leaked through rollback: {n_img}"
    assert n_face == 0, f"face leaked through rollback: {n_face}"
    assert n_out == 0, f"outbox leaked through rollback: {n_out}"

    # Cleanup
    truncate_test_data(db.engine)
    shutil.rmtree(img_dir, ignore_errors=True)
    shutil.rmtree(TMP_FAISS, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
