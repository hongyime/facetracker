"""Smoke 5: BatchedFAISSIndex.add()/add_batch() are idempotent on face_id.

The reaper's correctness invariant (no duplicate FAISS vectors on retry)
depends on `live_ids_set` membership and `add()` returning -1 on dup.

Test:
- Single add: first add returns 0, second returns -1, total unchanged after merge.
- Batch add: re-submitting the same ids returns 0 new adds.
- Mixed batch: half new, half dup -> only new are added.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

os.environ["FACE_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="smoke5_faiss_")
os.environ["HOST_FACE_STORAGE"] = os.environ["FACE_STORAGE_ROOT"]
TMP_FAISS = os.environ["FACE_STORAGE_ROOT"]

import numpy as np

from src.config import settings
from src.storage.faiss_index import BatchedFAISSIndex


def main() -> int:
    assert TMP_FAISS in settings.faiss_live_path

    os.makedirs(os.path.dirname(settings.faiss_live_path), exist_ok=True)
    os.makedirs(settings.faiss_staging_dir, exist_ok=True)

    idx = BatchedFAISSIndex(settings)

    rng = np.random.default_rng(7)
    embs = rng.standard_normal((4, 512)).astype(np.float32)
    embs /= (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-12)

    fids = [f"smoke-test:s5_{i}" for i in range(4)]

    # 1) First adds succeed
    r0 = idx.add(embs[0], fids[0])
    r1 = idx.add(embs[1], fids[1])
    print(f"first_add r0={r0} r1={r1}")
    assert r0 != -1 and r1 != -1, "fresh adds should not be -1"

    # 2) Re-add same face_id -> dedup (-1)
    r0_dup = idx.add(embs[0], fids[0])
    print(f"redundant_add r0_dup={r0_dup}")
    assert r0_dup == -1, f"dup should return -1, got {r0_dup}"

    # 3) Force merge so live_ids_set is populated
    idx.force_merge()
    print(f"after_merge total={idx.total_count} live_ids_set_size={len(idx.live_ids_set)}")
    assert idx.total_count == 2, f"expected 2 after merge, got {idx.total_count}"
    assert idx.contains(fids[0])
    assert idx.contains(fids[1])

    # 4) Re-add post-merge -> still dedup against live_ids_set
    r0_post = idx.add(embs[0], fids[0])
    print(f"post_merge_dup r0_post={r0_post}")
    assert r0_post == -1, f"post-merge dup should return -1, got {r0_post}"

    # 5) Mixed batch: 2 new + 2 already-live  -> 2 added
    n_added = idx.add_batch(embs, fids)  # all 4: 0,1 are dups; 2,3 are new
    print(f"batch_mixed n_added={n_added}")
    assert n_added == 2, f"expected 2 new from mixed batch, got {n_added}"

    idx.force_merge()
    print(f"final total={idx.total_count} live_ids_set_size={len(idx.live_ids_set)}")
    assert idx.total_count == 4, f"expected 4 final, got {idx.total_count}"
    for f in fids:
        assert idx.contains(f), f"missing {f}"

    # 6) Re-running batch returns 0
    n_added2 = idx.add_batch(embs, fids)
    print(f"batch_redundant n_added2={n_added2}")
    assert n_added2 == 0, f"redundant batch should add 0, got {n_added2}"
    assert idx.total_count == 4

    shutil.rmtree(TMP_FAISS, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
