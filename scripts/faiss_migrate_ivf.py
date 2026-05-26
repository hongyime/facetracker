#!/usr/bin/env python3
"""Migrate the FAISS live index from HNSW to IVFFlat.

Bootstraps a trained IVFFlat index from the canonical source-of-truth — the
``faces.embedding_vec`` column in postgres. Writes the new index + ids file
to sibling paths (``.ivf.faiss`` / ``.ivf.ids.npy``) so the existing HNSW
files stay untouched as the rollback path.

Usage (run from repo root, with the api STOPPED to keep things simple):

    docker compose stop api
    docker run --rm --env-file .env --network facetracker-net \\
        -v "$(pwd)":/app -w /app facetracker-api \\
        python scripts/faiss_migrate_ivf.py

    # Inspect output. If happy, swap atomically:
    mv data/faiss/live.faiss            data/faiss/live.faiss.hnsw.bak
    mv data/faiss/live.ids.npy          data/faiss/live.ids.npy.hnsw.bak
    mv data/faiss/live.faiss.ivf        data/faiss/live.faiss
    mv data/faiss/live.ivf.ids.npy      data/faiss/live.ids.npy

    # Flip config
    echo "FAISS_INDEX_TYPE=IVFFlat" >> .env

    docker compose up -d api

Rollback if anything goes wrong:

    docker compose stop api
    mv data/faiss/live.faiss            data/faiss/live.faiss.ivf.failed
    mv data/faiss/live.ids.npy          data/faiss/live.ids.npy.ivf.failed
    mv data/faiss/live.faiss.hnsw.bak   data/faiss/live.faiss
    mv data/faiss/live.ids.npy.hnsw.bak data/faiss/live.ids.npy
    # remove FAISS_INDEX_TYPE=IVFFlat from .env
    docker compose up -d api

The script never deletes anything. Worst case, you have an extra .ivf.faiss
file you can rm later.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import faiss  # type: ignore
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Add repo root to path so we can import src.* when run from anywhere.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import settings  # noqa: E402
from src.storage.database import Face  # noqa: E402

DIM = 512


def main() -> int:
    nlist = settings.faiss_ivf_nlist
    nprobe = settings.faiss_ivf_nprobe
    live_path = Path(settings.faiss_live_path)
    out_index_path = live_path.with_suffix(".faiss.ivf")
    # We'll honour the "<base>.ids.npy" convention used by faiss_index.py,
    # but with a `.ivf` infix to keep the legacy file intact.
    out_ids_path = live_path.with_name(live_path.stem + ".ivf.ids.npy")

    print(f"Repo root         : {REPO_ROOT}")
    print(f"DB URL            : {settings.database_url[:60]}...")
    print(f"Live (HNSW) path  : {live_path}    exists={live_path.exists()}")
    print(f"Output index path : {out_index_path}")
    print(f"Output ids path   : {out_ids_path}")
    print(f"IVF nlist         : {nlist}")
    print(f"IVF nprobe        : {nprobe}")
    print()

    if out_index_path.exists() or out_ids_path.exists():
        print(
            "ERROR: output files already exist. Move or delete them and retry "
            "to avoid silently overwriting a previous migration:"
        )
        if out_index_path.exists():
            print(f"  rm {out_index_path}")
        if out_ids_path.exists():
            print(f"  rm {out_ids_path}")
        return 2

    # --- Pull all (embedding_id, embedding_vec) from postgres ----------------
    # Stream-friendly: yield_per keeps memory bounded even at millions of rows.
    print("Connecting to postgres...")
    engine = create_engine(settings.database_url)
    t0 = time.time()
    ids: list[str] = []
    vecs: list[np.ndarray] = []
    with Session(engine) as session:
        q = (
            session.query(Face.embedding_id, Face.embedding_vec)
            .filter(Face.embedding_vec.is_not(None))
            .yield_per(2048)
        )
        for fid, vec in q:
            if vec is None:
                continue
            arr = np.asarray(vec, dtype=np.float32)
            if arr.shape != (DIM,):
                # Defensive: skip rows whose vec column is the wrong shape.
                # Should never happen given the pgvector(512) constraint.
                print(f"  WARNING: skipping {fid!r} — bad shape {arr.shape}")
                continue
            ids.append(fid)
            vecs.append(arr)
    n = len(ids)
    pull_dt = time.time() - t0
    print(f"Pulled {n} vectors from DB in {pull_dt:.1f}s")
    print()

    if n == 0:
        print("ERROR: no vectors found in faces.embedding_vec. Aborting.")
        return 3

    # FAISS recommends >= nlist * ~30 training vectors for stable centroids,
    # and minimum nlist * 8. With 16k+ vectors and nlist=4096 we're fine.
    if n < nlist * 8:
        print(
            f"ERROR: only {n} vectors, but nlist={nlist} needs >= {nlist * 8} "
            f"for stable training. Either lower faiss_ivf_nlist (try "
            f"max(64, 4*sqrt(N)) = {max(64, int(4 * (n ** 0.5)))}) and rerun, "
            f"or postpone the migration until you have more vectors."
        )
        return 4

    # Stack and L2-normalize. The live API normalizes embeddings before adding,
    # so we MUST do the same here or query similarity scores will be wrong.
    train_array = np.vstack(vecs).astype(np.float32)
    print("L2-normalizing embeddings (matches runtime add() behavior)...")
    faiss.normalize_L2(train_array)

    # --- Build, train, populate, persist ------------------------------------
    print("Building untrained IVFFlat shell...")
    quantizer = faiss.IndexFlatIP(DIM)
    index = faiss.IndexIVFFlat(quantizer, DIM, nlist, faiss.METRIC_INNER_PRODUCT)
    index.nprobe = nprobe  # informational; nprobe is set per-boot from config

    print(f"Training IVF on all {n} vectors (k-means, this takes a minute)...")
    t0 = time.time()
    index.train(train_array)
    print(f"  trained in {time.time() - t0:.1f}s, is_trained={index.is_trained}")

    print(f"Adding {n} vectors to trained index...")
    t0 = time.time()
    index.add(train_array)
    print(f"  added in {time.time() - t0:.1f}s, ntotal={index.ntotal}")

    if index.ntotal != n:
        print(
            f"ERROR: index.ntotal={index.ntotal} but expected {n}. "
            f"Something went wrong — refusing to write output files."
        )
        return 5

    # --- Persist (atomic rename pattern, mirrors runtime _save_*_atomic) ----
    print(f"Writing index to {out_index_path}.tmp ...")
    tmp_index = out_index_path.with_suffix(".faiss.ivf.tmp")
    tmp_ids = out_ids_path.with_name(out_ids_path.name + ".tmp.npy")

    faiss.write_index(index, str(tmp_index))
    np.save(str(tmp_ids), np.array(ids, dtype=object), allow_pickle=True)

    # Atomic renames onto final paths
    tmp_index.replace(out_index_path)
    tmp_ids.replace(out_ids_path)

    # --- Sanity check the persisted files round-trip cleanly ----------------
    print()
    print("Sanity check: reading back persisted files...")
    rt_index = faiss.read_index(str(out_index_path))
    rt_ids = np.load(str(out_ids_path), allow_pickle=True).tolist()
    print(f"  read-back ntotal = {rt_index.ntotal}")
    print(f"  read-back ids    = {len(rt_ids)}")
    if rt_index.ntotal != n or len(rt_ids) != n:
        print("ERROR: persisted file round-trip mismatch. Investigate before swap.")
        return 6

    # Sanity-check search recall on a random sample. Each vector's nearest
    # neighbour should be itself with similarity ~1.0 (we added the same
    # vectors we trained on).
    print("Sanity check: nearest-neighbour recall on 64 random vectors...")
    rt_ivf = faiss.extract_index_ivf(rt_index)
    rt_ivf.nprobe = max(1, nprobe)
    sample_idx = np.random.default_rng(42).choice(n, size=min(64, n), replace=False)
    sample = train_array[sample_idx]
    D, I = rt_index.search(sample, k=1)
    self_hits = int((I.flatten() == sample_idx).sum())
    print(f"  self-hit rate at k=1 nprobe={nprobe}: {self_hits}/{len(sample_idx)}")
    if self_hits < int(0.9 * len(sample_idx)):
        print(
            "  WARNING: self-hit recall is below 90%. nprobe may be too low, "
            "or training was unstable. Consider rerunning with a higher nprobe."
        )

    print()
    print("Migration complete. Files written:")
    print(f"  {out_index_path}")
    print(f"  {out_ids_path}")
    print()
    print("Next steps (manual, intentionally — see header):")
    print("  1) docker compose stop api")
    print(f"  2) mv {live_path} {live_path}.hnsw.bak")
    print(f"  3) mv {live_path.with_name(live_path.stem + '.ids.npy')} "
          f"{live_path.with_name(live_path.stem + '.ids.npy.hnsw.bak')}")
    print(f"  4) mv {out_index_path} {live_path}")
    print(f"  5) mv {out_ids_path} {live_path.with_name(live_path.stem + '.ids.npy')}")
    print("  6) Set FAISS_INDEX_TYPE=IVFFlat in .env")
    print("  7) docker compose up -d api")
    return 0


if __name__ == "__main__":
    sys.exit(main())
