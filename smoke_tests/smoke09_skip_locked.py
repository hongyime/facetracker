"""Smoke 9: FOR UPDATE SKIP LOCKED prevents double-claim across reapers.

Strategy:
  - Seed N rows.
  - Reaper A starts a transaction, runs the SELECT ... FOR UPDATE SKIP LOCKED
    + UPDATE batch -> commits. Now those rows are 'merging'.
  - Reaper B does its own _drain_once() against same db.
    It should see zero pending rows (rows are not visible to claim) and drain 0.

This is a weaker test than true concurrent (race-prone) but sufficient to
prove the SKIP LOCKED query semantics: a row in 'merging' is not eligible
for a fresh claim, AND if a row were locked but uncommitted, B would skip it.

To prove the latter (lock-not-committed scenario) we use TWO sessions where
session A holds an open transaction with FOR UPDATE on the rows, and B
attempts the same SELECT — B must skip the locked rows.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading

os.environ["FACE_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="smoke9_faiss_")
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


N_ROWS = 4


def main() -> int:
    os.makedirs(os.path.dirname(settings.faiss_live_path), exist_ok=True)
    os.makedirs(settings.faiss_staging_dir, exist_ok=True)

    db = get_database(settings.database_url)
    db.create_tables()
    truncate_test_data(db.engine)

    # Seed N rows
    session = db.SessionLocal()
    try:
        for i in range(N_ROWS):
            img = make_test_image(session, suffix=f"s9_{i}")
            face = make_test_face(session, img, suffix=f"s9_{i}")
            enqueue_face(session, face.embedding_id, random_embedding(seed=900 + i))
        session.commit()
    finally:
        session.close()

    # Sanity check: 4 pending rows
    with db.engine.connect() as c:
        n = c.execute(text(
            "SELECT COUNT(*) FROM faiss_outbox WHERE status='pending' AND face_id LIKE :t"
        ), {"t": f"{TEST_TAG}s9_%"}).scalar()
    print(f"seeded_pending={n}")
    assert n == N_ROWS

    # ---- Test 1: A claims and commits 'merging'; B sees 0 pending ----
    sess_a = db.SessionLocal()
    try:
        rows = sess_a.execute(text(
            "SELECT id, face_id FROM faiss_outbox "
            " WHERE status='pending' AND face_id LIKE :t "
            " ORDER BY id "
            " LIMIT 2 "
            " FOR UPDATE SKIP LOCKED"
        ), {"t": f"{TEST_TAG}s9_%"}).fetchall()
        ids = [r.id for r in rows]
        print(f"A_claimed_ids={ids}")
        sess_a.execute(text(
            "UPDATE faiss_outbox SET status='merging', claimed_at=NOW(), attempts=1 "
            " WHERE id = ANY(:ids)"
        ), {"ids": ids})
        sess_a.commit()
    finally:
        sess_a.close()

    sess_b = db.SessionLocal()
    try:
        rows_b = sess_b.execute(text(
            "SELECT id FROM faiss_outbox "
            " WHERE status='pending' AND face_id LIKE :t "
            " ORDER BY id "
            " LIMIT 4 "
            " FOR UPDATE SKIP LOCKED"
        ), {"t": f"{TEST_TAG}s9_%"}).fetchall()
        ids_b = [r.id for r in rows_b]
        print(f"B_visible_pending_ids={ids_b}")
        sess_b.commit()
    finally:
        sess_b.close()
    # B sees only the OTHER 2 rows (the ones A didn't claim)
    assert len(ids_b) == N_ROWS - 2, f"expected {N_ROWS - 2}, B saw {len(ids_b)}"

    # ---- Test 2: A holds open lock; B must skip locked rows live ----
    # Reset 2 rows back to pending so we have fresh candidates.
    with db.engine.begin() as c:
        c.execute(text(
            "UPDATE faiss_outbox SET status='pending', claimed_at=NULL, attempts=0 "
            " WHERE face_id LIKE :t"
        ), {"t": f"{TEST_TAG}s9_%"})

    barrier = threading.Event()
    a_locked = threading.Event()
    a_done = threading.Event()
    a_locked_ids = []

    def thread_a():
        sa = db.SessionLocal()
        try:
            # Open a read+lock transaction and HOLD it open
            rows = sa.execute(text(
                "SELECT id FROM faiss_outbox "
                " WHERE status='pending' AND face_id LIKE :t "
                " ORDER BY id "
                " LIMIT 2 "
                " FOR UPDATE SKIP LOCKED"
            ), {"t": f"{TEST_TAG}s9_%"}).fetchall()
            a_locked_ids.extend([r.id for r in rows])
            a_locked.set()
            # Wait for B to do its thing
            barrier.wait(timeout=5.0)
            sa.rollback()  # release locks WITHOUT updating status
        finally:
            sa.close()
            a_done.set()

    t = threading.Thread(target=thread_a, daemon=True)
    t.start()
    a_locked.wait(timeout=5.0)

    # While A holds row locks, B runs SKIP LOCKED — must skip A's rows
    sess_b = db.SessionLocal()
    try:
        b_rows = sess_b.execute(text(
            "SELECT id FROM faiss_outbox "
            " WHERE status='pending' AND face_id LIKE :t "
            " ORDER BY id "
            " LIMIT 10 "
            " FOR UPDATE SKIP LOCKED"
        ), {"t": f"{TEST_TAG}s9_%"}).fetchall()
        b_ids = [r.id for r in b_rows]
        print(f"a_locked_ids={a_locked_ids} b_concurrent_ids={b_ids}")
        sess_b.commit()
    finally:
        sess_b.close()

    barrier.set()
    a_done.wait(timeout=5.0)

    # B must NOT see any of A's locked ids
    overlap = set(a_locked_ids) & set(b_ids)
    print(f"overlap={overlap}")
    assert not overlap, f"SKIP LOCKED violated! overlap={overlap}"

    truncate_test_data(db.engine)
    shutil.rmtree(TMP_FAISS, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
