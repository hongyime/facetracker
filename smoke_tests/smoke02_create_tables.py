"""Smoke 2: create_tables() creates faiss_outbox with all expected columns + indexes.

Run inside api container with mount of src + config + .env, postgres reachable as 'postgres'.
"""
import sys
from sqlalchemy import inspect, text

from src.config import settings
from src.storage.database import get_database
from src.storage.outbox import FaissOutbox  # noqa: F401 — register on Base


def main() -> int:
    db = get_database(settings.database_url)
    db.create_tables()

    insp = inspect(db.engine)
    tables = set(insp.get_table_names())
    print(f"tables_count={len(tables)}")
    print(f"has_faiss_outbox={'faiss_outbox' in tables}")
    if "faiss_outbox" not in tables:
        print("FAIL: faiss_outbox not created")
        return 1

    cols = {c["name"]: c for c in insp.get_columns("faiss_outbox")}
    expected = {
        "id", "face_id", "embedding", "status", "attempts",
        "last_error", "created_at", "claimed_at", "committed_at",
    }
    missing = expected - cols.keys()
    extra = cols.keys() - expected
    print(f"missing_cols={sorted(missing)}")
    print(f"extra_cols={sorted(extra)}")
    if missing:
        print("FAIL: missing columns")
        return 2

    indexes = insp.get_indexes("faiss_outbox")
    idx_cols = sorted(tuple(i["column_names"]) for i in indexes)
    print(f"indexes={idx_cols}")

    # Check FK from faiss_outbox.face_id -> faces.embedding_id
    fks = insp.get_foreign_keys("faiss_outbox")
    print(f"foreign_keys={[(fk['constrained_columns'], fk['referred_table'], fk['referred_columns']) for fk in fks]}")

    # Check unique on face_id
    uniques = insp.get_unique_constraints("faiss_outbox")
    print(f"unique_constraints={[(u.get('name'), u['column_names']) for u in uniques]}")

    # Confirm row count starts at 0
    with db.engine.begin() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM faiss_outbox")).scalar()
    print(f"faiss_outbox_rows={n}")

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
