#!/usr/bin/env python3
"""
scripts/faiss_rebuild_from_db.py
=================================
Rebuild the FAISS live index from scratch using face embeddings stored in
Postgres. Run this whenever the on-disk index is corrupt, missing, or out of
sync with the database.

IMPORTANT — IVF BOOTSTRAP:
  A fresh IVFFlat index CANNOT be grown from empty. FAISS requires
  nlist * 8 training points before the first add(). If you delete the
  live index file and restart the API, the reaper will accumulate faces
  in the outbox but they will never become searchable until this script
  (or faiss_migrate_ivf.py) trains and writes a populated index.

  TL;DR: after any index loss, run this script before restarting the API.

USAGE (inside the api container):
    docker exec -it facetracker-api python /app/scripts/faiss_rebuild_from_db.py

USAGE (dry-run, no write):
    docker exec -it facetracker-api python /app/scripts/faiss_rebuild_from_db.py --dry-run

USAGE (reload API after rebuild without restart):
    docker exec -it facetracker-api python /app/scripts/faiss_rebuild_from_db.py --reload

SAFETY:
  - Writes atomically: new index lands in a .tmp file, then renamed in one
    operation. The live index is never partially overwritten.
  - If interrupted mid-build the .tmp file is left behind and can be deleted
    safely. The existing live index is untouched until the rename succeeds.
  - Does NOT restart or modify the running API process. After the script
    finishes, the API will pick up the new index on next startup, or
    immediately if --reload is used.
"""

import sys
import os
import argparse
import time
import logging
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger("faiss_rebuild")

# ---------------------------------------------------------------------------
# Inline the config we need so the script can run without importing the whole
# FastAPI app. Override via env vars if your .env differs.
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:facetracker123@postgres:5432/facetracker",
)
FACE_STORAGE_ROOT = os.environ.get("FACE_STORAGE_ROOT", "/app/storage")
FAISS_INDEX_TYPE  = os.environ.get("FAISS_INDEX_TYPE", "IVFFlat")
FAISS_NLIST       = int(os.environ.get("FAISS_NLIST", "512"))
FAISS_NPROBE      = int(os.environ.get("FAISS_NPROBE", "32"))
DIMENSION         = 512   # buffalo_l w600k_r50 embedding dimension

LIVE_PATH  = Path(FACE_STORAGE_ROOT) / "embeddings" / "live" / "face_index.faiss"
IDS_PATH   = LIVE_PATH.with_suffix(".ids.npy")


def fetch_embeddings(engine):
    """Fetch all (embedding_id, embedding_vec) rows from faces table.

    Returns:
        list of (str embedding_id, np.ndarray shape=(512,)) tuples
    """
    import numpy as np
    from sqlalchemy import text

    logger.info("Fetching embeddings from Postgres...")
    t0 = time.time()

    rows = []
    with engine.connect() as conn:
        # Stream in batches to avoid loading 17k x 512 floats into one
        # Python list at once — each row is ~2KB so 17k = ~34MB, fine,
        # but we batch anyway for progress reporting.
        BATCH = 2000
        offset = 0
        while True:
            result = conn.execute(
                text(
                    "SELECT embedding_id, embedding_vec "
                    "FROM faces "
                    "WHERE embedding_vec IS NOT NULL "
                    "ORDER BY id "
                    "LIMIT :lim OFFSET :off"
                ),
                {"lim": BATCH, "off": offset},
            ).fetchall()
            if not result:
                break
            for eid, evec in result:
                if evec is not None:
                    if isinstance(evec, str):
                        import json
                        evec = json.loads(evec)
                    arr = np.array(evec, dtype=np.float32)
                    if arr.shape == (DIMENSION,):
                        rows.append((eid, arr))
                    else:
                        logger.warning(f"Skipping {eid}: unexpected shape {arr.shape}")
            offset += BATCH
            logger.info(f"  fetched {len(rows)} embeddings so far...")

    elapsed = time.time() - t0
    logger.info(f"Fetched {len(rows)} embeddings in {elapsed:.1f}s")
    return rows


def build_index(rows, index_type: str):
    """Build a FAISS index from (embedding_id, vec) rows.

    Returns:
        (faiss_index, id_list)
    """
    import numpy as np
    import faiss

    if not rows:
        raise ValueError("No embeddings fetched — aborting rebuild")

    n = len(rows)
    ids   = [r[0] for r in rows]
    vecs  = np.stack([r[1] for r in rows], axis=0).astype(np.float32)

    logger.info(f"Normalising {n} vectors (L2)...")
    faiss.normalize_L2(vecs)

    logger.info(f"Building {index_type} index (dim={DIMENSION}, nlist={FAISS_NLIST})...")
    t0 = time.time()

    if index_type == "IVFFlat":
        quantizer = faiss.IndexFlatIP(DIMENSION)
        index = faiss.IndexIVFFlat(quantizer, DIMENSION, FAISS_NLIST, faiss.METRIC_INNER_PRODUCT)
        # Need to train before adding — IVFFlat learns cluster centroids.
        # Use the full dataset; for large indexes a random 10% sample suffices.
        train_data = vecs if n <= 50_000 else vecs[::max(1, n // 50_000)]
        logger.info(f"  Training on {len(train_data)} vectors...")
        index.train(train_data)
        index.nprobe = FAISS_NPROBE
    elif index_type == "Flat":
        index = faiss.IndexFlatIP(DIMENSION)
    elif index_type.startswith("HNSW"):
        m = int(index_type[4:]) if len(index_type) > 4 else 64
        index = faiss.IndexHNSWFlat(DIMENSION, m, faiss.METRIC_INNER_PRODUCT)
    else:
        raise ValueError(f"Unknown FAISS_INDEX_TYPE: {index_type!r}")

    logger.info(f"  Adding {n} vectors...")
    index.add(vecs)

    elapsed = time.time() - t0
    logger.info(f"Index built in {elapsed:.1f}s — {index.ntotal} vectors indexed")
    return index, ids


def save_atomically(index, ids, dry_run: bool):
    """Write index + ids files atomically via temp-then-rename."""
    import numpy as np
    import faiss

    LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)

    tmp_index = LIVE_PATH.with_suffix(".faiss.tmp")
    tmp_ids   = IDS_PATH.with_name(IDS_PATH.name + ".tmp.npy")

    if dry_run:
        logger.info("[DRY-RUN] Would write:")
        logger.info(f"  {LIVE_PATH}  ({index.ntotal} vectors)")
        logger.info(f"  {IDS_PATH}  ({len(ids)} ids)")
        return

    logger.info("Writing index to temp files...")
    faiss.write_index(index, str(tmp_index))
    np.save(str(tmp_ids), np.array(ids))

    logger.info("Renaming temp files to live paths (atomic)...")
    tmp_index.replace(LIVE_PATH)
    tmp_ids.replace(IDS_PATH)

    logger.info(f"Done. Live index: {LIVE_PATH}")
    logger.info(f"      Live ids:   {IDS_PATH}")


def reload_api():
    """POST to the API's /admin/faiss/reload endpoint to hot-reload without restart."""
    import urllib.request, json as _json

    url = "http://localhost:5454/api/v1/admin/faiss/reload"
    logger.info(f"Requesting live reload via {url}...")
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = _json.loads(resp.read())
            logger.info(f"Reload response: {body}")
    except Exception as e:
        logger.warning(
            f"API reload request failed: {e}\n"
            "The new index will be picked up on next API restart."
        )


def main():
    parser = argparse.ArgumentParser(description="Rebuild FAISS index from Postgres embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Build index but do not write to disk")
    parser.add_argument("--reload",  action="store_true", help="POST to API reload endpoint after writing")
    parser.add_argument("--index-type", default=FAISS_INDEX_TYPE, help=f"Index type (default: {FAISS_INDEX_TYPE})")
    args = parser.parse_args()

    try:
        from sqlalchemy import create_engine
    except ImportError:
        logger.error("sqlalchemy not installed — run inside the api container")
        sys.exit(1)

    try:
        import faiss  # noqa
    except ImportError:
        logger.error("faiss-cpu not installed — run inside the api container")
        sys.exit(1)

    logger.info(f"Connecting to {DATABASE_URL}...")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    rows = fetch_embeddings(engine)
    if not rows:
        logger.error("No embeddings found in DB — nothing to rebuild")
        sys.exit(1)

    index, ids = build_index(rows, args.index_type)
    save_atomically(index, ids, dry_run=args.dry_run)

    if args.reload and not args.dry_run:
        reload_api()

    logger.info("Rebuild complete.")


if __name__ == "__main__":
    main()
