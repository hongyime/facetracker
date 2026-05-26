"""Smoke 7: After max_attempts FAISS write failures, row parks as 'failed'.

Inject a faulty FAISS index whose `add()` always raises, then drive the
reaper through max_attempts retries. Row should:
  - have attempts incremented each cycle
  - flip back to 'pending' after each failed merge while attempts < max_attempts
  - flip to 'failed' (terminal) once attempts >= max_attempts
  - NOT be re-claimed afterwards
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

os.environ["FACE_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="smoke7_faiss_")
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


class FaultyFaiss(BatchedFAISSIndex):
    """FAISS index whose add() always blows up."""

    def add(self, embedding, face_id):  # type: ignore[override]
        raise RuntimeError("simulated FAISS write failure")

    # force_merge gets called too — make it explode as well to be sure.
    def force_merge(self):  # type: ignore[override]
        raise RuntimeError("simulated merge failure")


MAX_ATTEMPTS = 3  # smaller for test


def main() -> int:
    os.makedirs(os.path.dirname(settings.faiss_live_path), exist_ok=True)
    os.makedirs(settings.faiss_staging_dir, exist_ok=True)

    db = get_database(settings.database_url)
    db.create_tables()
    truncate_test_data(db.engine)

    faiss_index = FaultyFaiss(settings)

    # Seed one outbox row.
    session = db.SessionLocal()
    try:
        img = make_test_image(session, suffix="s7")
        face = make_test_face(session, img, suffix="s7")
        enqueue_face(session, face.embedding_id, random_embedding(seed=7))
        session.commit()
    finally:
        session.close()

    face_id = f"{TEST_TAG}s7"

    reaper = FaissReaper(
        database=db,
        faiss_index=faiss_index,
        poll_interval_ms=100,
        batch_size=64,
        stuck_timeout_s=120,
        max_attempts=MAX_ATTEMPTS,
    )

    # Drive drain manually MAX_ATTEMPTS times. Each call:
    #   - claims the row (status=merging, attempts++)
    #   - faulty FAISS raises
    #   - except handler flips to 'pending' (or 'failed' on final attempt)
    statuses = []
    for i in range(MAX_ATTEMPTS + 2):  # extra runs to confirm no re-claim
        n = reaper._drain_once()
        with db.engine.connect() as c:
            row = c.execute(text(
                "SELECT status, attempts, last_error FROM faiss_outbox WHERE face_id=:f"
            ), {"f": face_id}).first()
        statuses.append((i, n, row.status, row.attempts, (row.last_error or "")[:60]))
        print(f"iter={i} drained={n} status={row.status} attempts={row.attempts} err={(row.last_error or '')[:60]}")

    # Expectations:
    #   iter 0: drained=0 (claim succeeds) but FAISS fails -> pending, attempts=1
    #   iter 1: drained=0, pending, attempts=2
    #   iter 2: drained=0, FAILED, attempts=3
    #   iter 3+: drained=0 (no longer pending, claim sees nothing), status stays FAILED
    final = statuses[-1]
    assert final[2] == "failed", f"expected final status=failed, got {final}"
    assert final[3] == MAX_ATTEMPTS, f"expected attempts={MAX_ATTEMPTS}, got {final[3]}"

    # Confirm last_error captured something
    with db.engine.connect() as c:
        last_err = c.execute(text(
            "SELECT last_error FROM faiss_outbox WHERE face_id=:f"
        ), {"f": face_id}).scalar()
    print(f"last_error_present={bool(last_err)} sample={last_err[:80] if last_err else None}")
    assert last_err and "simulated" in last_err

    # count_by_status sanity
    counts = reaper.count_by_status()
    print(f"counts={counts}")
    assert counts.get("failed", 0) == 1

    truncate_test_data(db.engine)
    shutil.rmtree(TMP_FAISS, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
