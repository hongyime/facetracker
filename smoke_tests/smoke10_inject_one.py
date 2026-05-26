"""Inject a single outbox row, wait for it to flip to 'committed' by the
running app's reaper. Used by smoke10_runner.sh."""
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import text

from src.config import settings
from src.storage.database import get_database
from src.storage.outbox import enqueue_face

from smoke_tests import (
    TEST_TAG, make_test_image, make_test_face, random_embedding,
    truncate_test_data,
)


def main() -> int:
    db = get_database(settings.database_url)
    truncate_test_data(db.engine)

    suffix = "s10_app"
    face_id = f"{TEST_TAG}{suffix}"

    session = db.SessionLocal()
    try:
        img = make_test_image(session, suffix=suffix)
        face = make_test_face(session, img, suffix=suffix)
        enqueue_face(session, face.embedding_id, random_embedding(seed=1010))
        session.commit()
    finally:
        session.close()

    # Wait up to 5s for the live reaper to drain
    deadline = time.time() + 5.0
    while time.time() < deadline:
        with db.engine.connect() as c:
            row = c.execute(text(
                "SELECT status, attempts FROM faiss_outbox WHERE face_id=:f"
            ), {"f": face_id}).first()
        if row and row.status == "committed":
            print(f"committed_in={5.0 - (deadline - time.time()):.2f}s attempts={row.attempts}")
            truncate_test_data(db.engine)
            print("PASS")
            return 0
        time.sleep(0.1)

    with db.engine.connect() as c:
        row = c.execute(text(
            "SELECT status, attempts, last_error FROM faiss_outbox WHERE face_id=:f"
        ), {"f": face_id}).first()
    print(f"FAIL: status={row.status if row else 'NO_ROW'}")
    return 10


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
