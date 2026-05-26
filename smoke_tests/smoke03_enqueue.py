"""Smoke 3: enqueue_face writes a row with the right shape.

- Seed Image + Face.
- Call enqueue_face with a 512-d embedding.
- Verify outbox row: face_id matches, embedding bytes deserialize to same vector,
  status='pending', attempts=0.
"""
from __future__ import annotations

import sys

import numpy as np
from sqlalchemy import select

from src.config import settings
from src.storage.database import get_database
from src.storage.outbox import FaissOutbox, enqueue_face, deserialize_embedding

from smoke_tests import (
    TEST_TAG, make_test_image, make_test_face, random_embedding,
    truncate_test_data,
)


def main() -> int:
    db = get_database(settings.database_url)
    db.create_tables()

    # Clean slate (test rows only)
    truncate_test_data(db.engine)

    suffix = "s3a"
    emb = random_embedding(seed=42)

    # Phase 1: write Image+Face+outbox in one transaction
    session = db.SessionLocal()
    try:
        img = make_test_image(session, suffix=suffix)
        face = make_test_face(session, img, suffix=suffix)
        enqueue_face(session, face.embedding_id, emb)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # Phase 2: read back
    session = db.SessionLocal()
    try:
        face_id = f"{TEST_TAG}{suffix}"
        row = session.execute(
            select(FaissOutbox).where(FaissOutbox.face_id == face_id)
        ).scalar_one()

        print(f"id={row.id}")
        print(f"face_id={row.face_id}")
        print(f"status={row.status}")
        print(f"attempts={row.attempts}")
        print(f"embedding_len_bytes={len(row.embedding)}")
        print(f"created_at_set={row.created_at is not None}")
        print(f"claimed_at={row.claimed_at}")
        print(f"committed_at={row.committed_at}")

        assert row.face_id == face_id, f"face_id mismatch: {row.face_id} != {face_id}"
        assert row.status == "pending", f"status={row.status}"
        assert row.attempts == 0, f"attempts={row.attempts}"
        assert len(row.embedding) == 512 * 4, f"embedding bytes {len(row.embedding)}"

        recovered = deserialize_embedding(bytes(row.embedding))
        diff = float(np.abs(recovered - emb).max())
        print(f"max_abs_diff={diff:.6e}")
        assert diff < 1e-6, "deserialize mismatch"

        # Idempotency check: re-enqueue same face_id MUST raise IntegrityError
        # because face_id is UNIQUE in the outbox table.
        session2 = db.SessionLocal()
        try:
            enqueue_face(session2, face_id, emb)
            try:
                session2.commit()
                print("FAIL: duplicate enqueue did not raise")
                return 3
            except Exception as e:
                print(f"dup_enqueue_raised={type(e).__name__}")
                session2.rollback()
        finally:
            session2.close()

    finally:
        session.close()

    # Cleanup
    truncate_test_data(db.engine)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
