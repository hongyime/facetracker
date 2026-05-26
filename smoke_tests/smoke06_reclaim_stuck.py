"""Smoke 6: FaissReaper._reclaim_stuck() flips orphaned 'merging' rows back to 'pending'.

Simulates a reaper crash mid-merge: row left in `merging` with old `claimed_at`.
Subsequent reaper instance must reclaim within stuck_timeout_s.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

os.environ["FACE_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="smoke6_faiss_")
os.environ["HOST_FACE_STORAGE"] = os.environ["FACE_STORAGE_ROOT"]
TMP_FAISS = os.environ["FACE_STORAGE_ROOT"]

from sqlalchemy import text

from src.config import settings
from src.storage.database import get_database
from src.storage.faiss_index import BatchedFAISSIndex
from src.storage.outbox import FaissReaper, enqueue_face

from smoke_tests import (
    TEST_TAG, make_test_image, make_test_face, random_embedding,
    truncate_test_data,
)


def main() -> int:
    os.makedirs(os.path.dirname(settings.faiss_live_path), exist_ok=True)
    os.makedirs(settings.faiss_staging_dir, exist_ok=True)

    db = get_database(settings.database_url)
    db.create_tables()
    truncate_test_data(db.engine)

    faiss_index = BatchedFAISSIndex(settings)

    # Seed one face + outbox row, then manually flip it to 'merging' with
    # claimed_at well past the stuck_timeout.
    session = db.SessionLocal()
    try:
        img = make_test_image(session, suffix="s6")
        face = make_test_face(session, img, suffix="s6")
        enqueue_face(session, face.embedding_id, random_embedding(seed=99))
        session.commit()
    finally:
        session.close()

    face_id = f"{TEST_TAG}s6"

    # Force the row into the orphaned-merging state.
    with db.engine.begin() as c:
        c.execute(text(
            "UPDATE faiss_outbox "
            "   SET status='merging', "
            "       claimed_at=NOW() - INTERVAL '200 seconds', "
            "       attempts=1 "
            " WHERE face_id=:f"
        ), {"f": face_id})

    # Sanity: status is merging, claimed_at is old
    with db.engine.connect() as c:
        row = c.execute(text(
            "SELECT status, attempts, "
            "       EXTRACT(EPOCH FROM (NOW() - claimed_at))::int AS age_s "
            "  FROM faiss_outbox WHERE face_id=:f"
        ), {"f": face_id}).first()
        print(f"pre_status={row.status} pre_attempts={row.attempts} age_s={row.age_s}")
        assert row.status == "merging"
        assert row.age_s >= 120

    # Build a reaper but don't start the loop; call _reclaim_stuck directly.
    reaper = FaissReaper(
        database=db,
        faiss_index=faiss_index,
        poll_interval_ms=100,
        batch_size=64,
        stuck_timeout_s=120,
        max_attempts=5,
    )
    n = reaper._reclaim_stuck()
    print(f"reclaimed={n}")
    assert n == 1, f"expected 1 reclaimed, got {n}"

    with db.engine.connect() as c:
        row = c.execute(text(
            "SELECT status, attempts FROM faiss_outbox WHERE face_id=:f"
        ), {"f": face_id}).first()
        print(f"post_status={row.status} post_attempts={row.attempts}")
        assert row.status == "pending"
        # attempts NOT decremented — preserved so max_attempts still applies
        assert row.attempts == 1

    # Edge case: a NON-stuck merging row (claimed_at recent) MUST NOT be reclaimed.
    with db.engine.begin() as c:
        c.execute(text(
            "UPDATE faiss_outbox "
            "   SET status='merging', claimed_at=NOW(), attempts=1 "
            " WHERE face_id=:f"
        ), {"f": face_id})
    n2 = reaper._reclaim_stuck()
    print(f"reclaimed_recent={n2}")
    assert n2 == 0, f"recent merging must not be reclaimed, got {n2}"

    truncate_test_data(db.engine)
    shutil.rmtree(TMP_FAISS, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
