"""Smoke 4: FaissReaper drains pending → committed end-to-end.

- Override FACE_STORAGE_ROOT to /tmp/smoke4_faiss so we don't touch Y:/faces.
- Seed N faces + outbox rows.
- Start reaper, wait until count_by_status shows them all committed.
- Verify FAISS index reports them via search.
- Cleanup: outbox rows AND tmp faiss files (NOT live data).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

# Override BEFORE importing src.config
os.environ["FACE_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="smoke4_faiss_")
# AliasChoices picks the FIRST matching env var; .env sets HOST_FACE_STORAGE
# which would shadow our override. Override both to be explicit.
os.environ["HOST_FACE_STORAGE"] = os.environ["FACE_STORAGE_ROOT"]
TMP_FAISS = os.environ["FACE_STORAGE_ROOT"]
print(f"[ENV] FACE_STORAGE_ROOT={os.environ.get('FACE_STORAGE_ROOT')}")
print(f"[ENV] HOST_FACE_STORAGE={os.environ.get('HOST_FACE_STORAGE')}")
print(f"tmp_faiss_root={TMP_FAISS}")

import numpy as np
from sqlalchemy import text

from src.config import settings  # picks up override
print(f"[POST-IMPORT] settings.face_storage_root={settings.face_storage_root}")
print(f"[POST-IMPORT] settings.faiss_live_path={settings.faiss_live_path}")
from src.storage.database import get_database
from src.storage.faiss_index import BatchedFAISSIndex
from src.storage.outbox import FaissReaper, FaissOutbox, enqueue_face

from smoke_tests import (
    TEST_TAG, make_test_image, make_test_face, random_embedding,
    truncate_test_data,
)


N_FACES = 5


def main() -> int:
    # Sanity: FAISS path must point inside the tmp dir, not Y:/faces
    assert TMP_FAISS in settings.faiss_live_path, \
        f"override leaked! faiss_live_path={settings.faiss_live_path}"
    print(f"faiss_live_path={settings.faiss_live_path}")

    # Make sure the embeddings/live and embeddings/staging dirs exist
    os.makedirs(os.path.dirname(settings.faiss_live_path), exist_ok=True)
    os.makedirs(settings.faiss_staging_dir, exist_ok=True)

    db = get_database(settings.database_url)
    db.create_tables()
    truncate_test_data(db.engine)

    # Build FAISS index in tmp
    faiss_index = BatchedFAISSIndex(settings)
    print(f"faiss_initial_total={faiss_index.total_count}")

    # Seed N faces with outbox rows
    face_ids = []
    embeddings = []
    session = db.SessionLocal()
    try:
        for i in range(N_FACES):
            img = make_test_image(session, suffix=f"s4_{i}")
            face = make_test_face(session, img, suffix=f"s4_{i}")
            emb = random_embedding(seed=1000 + i)
            enqueue_face(session, face.embedding_id, emb)
            face_ids.append(face.embedding_id)
            embeddings.append(emb)
        session.commit()
    finally:
        session.close()

    # Verify outbox state pre-drain
    with db.engine.connect() as c:
        n_pending = c.execute(text(
            "SELECT COUNT(*) FROM faiss_outbox WHERE status='pending' AND face_id LIKE :t"
        ), {"t": f"{TEST_TAG}s4_%"}).scalar()
    print(f"pending_pre_drain={n_pending}")
    assert n_pending == N_FACES

    # Start reaper with very fast poll for the test
    reaper = FaissReaper(
        database=db,
        faiss_index=faiss_index,
        poll_interval_ms=100,
        batch_size=64,
        stuck_timeout_s=120,
        max_attempts=5,
    )
    reaper.start()

    # Wait up to 10s for drain
    t0 = time.time()
    deadline = t0 + 10.0
    committed = 0
    while time.time() < deadline:
        with db.engine.connect() as c:
            committed = c.execute(text(
                "SELECT COUNT(*) FROM faiss_outbox WHERE status='committed' AND face_id LIKE :t"
            ), {"t": f"{TEST_TAG}s4_%"}).scalar()
        if committed >= N_FACES:
            break
        time.sleep(0.05)
    drain_ms = (time.time() - t0) * 1000.0
    print(f"committed={committed}/{N_FACES} drain_ms={drain_ms:.1f}")

    reaper.stop(timeout=3.0)

    if committed < N_FACES:
        # Surface why
        with db.engine.connect() as c:
            rows = c.execute(text(
                "SELECT id, status, attempts, last_error FROM faiss_outbox "
                "WHERE face_id LIKE :t ORDER BY id"
            ), {"t": f"{TEST_TAG}s4_%"}).fetchall()
            for r in rows:
                print(f"  outbox: id={r.id} status={r.status} attempts={r.attempts} err={r.last_error}")
        return 4

    # FAISS contains assertion
    print(f"faiss_total_after={faiss_index.total_count}")
    print(f"faiss_live_ids_set_size={len(faiss_index.live_ids_set)}")
    for fid in face_ids:
        assert faiss_index.contains(fid), f"FAISS missing {fid}"

    # Search for one of the embeddings — top-1 should be itself
    target = face_ids[0]
    hits = faiss_index.search(embeddings[0], k=3)
    print(f"search_top3={hits}")
    assert hits and hits[0][0] == target, f"top-1 != {target}, got {hits}"

    # Cleanup
    truncate_test_data(db.engine)
    shutil.rmtree(TMP_FAISS, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
