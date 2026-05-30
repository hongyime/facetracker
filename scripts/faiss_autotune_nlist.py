#!/usr/bin/env python3
"""Re-train FAISS IVFFlat with a better nlist when the corpus has grown.

The IVF rule of thumb is K = 4*sqrt(N) clusters, with a hard floor of
nlist*8 training points for FAISS k-means to converge. Today (~17k faces)
nlist=512 is correct. Once the corpus crosses ~250k faces nlist should
move to ~2048-4096 to keep search latency flat.

This script is operator-friendly: run it any time, it computes the right
nlist, compares to the live one, and either tells you "no change needed"
or runs the migration. It is non-destructive — the existing index is
preserved as a `.predeploy` backup before the swap, so rollback is one mv.

Decision logic:
  - Read live face count from postgres.
  - target_nlist = next power of 2 >= 4*sqrt(N), clamped to [256, 16384]
  - If abs(target / current) within [0.5, 2.0]: no change. We don't
    rebuild for marginal gains; rebuild has cost.
  - If outside that band AND we have >= target_nlist*8 training points:
    rebuild.
  - Otherwise: report what would change but don't do it.

This script:
  1. Computes target_nlist
  2. Pulls embeddings from postgres
  3. Trains a new IVFFlat with target_nlist
  4. Adds embeddings, normalizes, writes to *.candidate
  5. Sanity-check recall on a 64-vector self-query
  6. Atomic-swap: live -> .predeploy_<stamp>, candidate -> live
  7. Bumps FAISS_IVF_NLIST in .env via sed-equivalent (writes new, renames)

Run with --dry-run to see decision without touching anything.
Run with --confirm to actually rebuild + swap.

Designed to be safe to run while the api is up; we ONLY swap files when
--confirm-and-swap is used AND the api was stopped beforehand. The script
will refuse to swap if it sees the api container running.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import faiss  # type: ignore
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import settings  # noqa: E402

DIM = 512
NLIST_FLOOR = 256
NLIST_CEIL = 16384
TRAINING_POINTS_PER_CLUSTER = 8  # FAISS hard floor


def _next_power_of_two(n: int) -> int:
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def _compute_target_nlist(face_count: int) -> int:
    if face_count <= 0:
        return NLIST_FLOOR
    raw = 4 * math.sqrt(face_count)
    p2 = _next_power_of_two(int(round(raw)))
    return max(NLIST_FLOOR, min(NLIST_CEIL, p2))


def _within_no_op_band(current: int, target: int) -> bool:
    if current == target:
        return True
    ratio = target / max(current, 1)
    return 0.5 <= ratio <= 2.0


def _api_container_running() -> bool:
    """Best-effort docker check. If we can't tell, assume YES (refuse to swap)."""
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "name=facetracker-api", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "facetracker-api" in out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True


def _live_index_paths() -> tuple[Path, Path]:
    # Same logic as backup_snapshot.py
    if Path("/.dockerenv").exists():
        cand = Path("/app/storage/embeddings/live")
        if cand.exists():
            base = cand
        else:
            base = Path("/mnt/y/facetracker/faces/embeddings/live")
    else:
        base = Path("Y:/facetracker/faces/embeddings/live")
    return base / "face_index.faiss", base / "face_index.ids.npy"


def _load_face_embeddings():
    from sqlalchemy import create_engine, text  # type: ignore

    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM faces WHERE embedding_vec IS NOT NULL")).scalar()
        print(f"  postgres reports {n} faces with embeddings")
        rows = conn.execute(
            text(
                "SELECT embedding_id, embedding_vec FROM faces "
                "WHERE embedding_vec IS NOT NULL ORDER BY id"
            )
        ).fetchall()
    eids = []
    vecs = []
    for r in rows:
        arr = np.asarray(r.embedding_vec, dtype=np.float32)
        if arr.shape != (DIM,):
            continue
        eids.append(r.embedding_id)
        vecs.append(arr)
    if not vecs:
        return [], np.zeros((0, DIM), dtype=np.float32)
    arr = np.ascontiguousarray(np.vstack(vecs).astype(np.float32))
    faiss.normalize_L2(arr)
    return eids, arr


def _build_and_train(embeddings: np.ndarray, nlist: int) -> faiss.IndexIVFFlat:
    quantizer = faiss.IndexFlatIP(DIM)
    index = faiss.IndexIVFFlat(quantizer, DIM, nlist, faiss.METRIC_INNER_PRODUCT)
    print(f"  training IVF nlist={nlist} on {embeddings.shape[0]} vectors ...", flush=True)
    t0 = time.time()
    index.train(embeddings)
    print(f"    trained in {time.time() - t0:.1f}s", flush=True)
    index.add(embeddings)
    index.nprobe = settings.faiss_ivf_nprobe
    return index


def _sanity_check_recall(index, embeddings: np.ndarray, sample: int = 64) -> float:
    n = embeddings.shape[0]
    k = min(sample, n)
    rng = np.random.default_rng(0)
    idx = rng.choice(n, size=k, replace=False)
    queries = np.ascontiguousarray(embeddings[idx])
    _, I = index.search(queries, 1)
    hits = sum(1 for i, hit in zip(idx, I[:, 0]) if hit == i)
    return hits / k


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Compute decision and stop.")
    parser.add_argument("--confirm-and-swap", action="store_true",
                        help="Actually rebuild AND atomically swap files. Requires api stopped.")
    parser.add_argument("--target-nlist", type=int,
                        help="Override automatic nlist computation (advanced).")
    args = parser.parse_args()

    print("=== faiss_autotune_nlist.py ===")
    current_nlist = settings.faiss_ivf_nlist
    print(f"  current nlist (from settings): {current_nlist}")

    print("Loading embeddings ...", flush=True)
    eids, embeddings = _load_face_embeddings()
    n = embeddings.shape[0]
    if n == 0:
        print("ERROR: no embeddings found in postgres.")
        return 2
    print(f"  loaded {n} embeddings")

    target = args.target_nlist or _compute_target_nlist(n)
    print(f"  computed target nlist: {target}  (rule: 4*sqrt({n}) -> next power of 2)")

    if _within_no_op_band(current_nlist, target):
        print(f"NO-OP: target {target} is within band of current {current_nlist}. Nothing to do.")
        return 0

    required = target * TRAINING_POINTS_PER_CLUSTER
    if n < required:
        print(
            f"REFUSING: would need >= {required} training points for nlist={target}, "
            f"only have {n}. Wait until the corpus grows."
        )
        return 3

    if args.dry_run:
        print(f"DRY RUN: would rebuild IVF with nlist={target}. No changes.")
        return 0

    if not args.confirm_and_swap:
        print("Pass --confirm-and-swap to actually rebuild + swap. (api must be stopped.)")
        return 0

    if _api_container_running():
        print("REFUSING to swap: facetracker-api is running. Stop it first:")
        print("    docker compose stop api")
        return 4

    # Build the new index in-memory.
    new_index = _build_and_train(embeddings, target)
    recall = _sanity_check_recall(new_index, embeddings)
    print(f"  self-hit recall (k=1, 64 samples): {recall:.3f}")
    if recall < 0.95:
        print(f"REFUSING: recall {recall:.3f} below 0.95 floor. Aborting swap.")
        return 5

    # Write candidate files first.
    live_index_path, live_ids_path = _live_index_paths()
    candidate_index = live_index_path.with_suffix(".faiss.candidate")
    candidate_ids = live_ids_path.with_suffix(".npy.candidate")
    print(f"  writing candidate files ...")
    faiss.write_index(new_index, str(candidate_index))
    ids_array = np.array(eids, dtype=object)
    np.save(str(candidate_ids), ids_array, allow_pickle=True)

    # Atomic-ish swap. Use timestamped predeploy backup so multiple runs are safe.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pre_index = live_index_path.with_suffix(f".faiss.predeploy_{stamp}")
    pre_ids = live_ids_path.with_suffix(f".npy.predeploy_{stamp}")
    print(f"  swap: live -> {pre_index.name}; candidate -> live")
    if live_index_path.exists():
        shutil.move(str(live_index_path), str(pre_index))
    if live_ids_path.exists():
        shutil.move(str(live_ids_path), str(pre_ids))
    shutil.move(str(candidate_index), str(live_index_path))
    shutil.move(str(candidate_ids), str(live_ids_path))

    # Update .env in place — careful: do NOT use patch/write_file (leaks
    # adjacent secrets). Use a sed-equivalent that rewrites only the matched
    # KEY=line. This preserves all surrounding lines including secrets exactly.
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        try:
            lines = env_path.read_text().splitlines(keepends=True)
            new_lines = []
            replaced = False
            for line in lines:
                if line.lstrip().startswith("FAISS_IVF_NLIST="):
                    new_lines.append(f"FAISS_IVF_NLIST={target}\n")
                    replaced = True
                else:
                    new_lines.append(line)
            if not replaced:
                new_lines.append(f"FAISS_IVF_NLIST={target}\n")
            tmp = env_path.with_suffix(".env.new")
            tmp.write_text("".join(new_lines))
            tmp.replace(env_path)
            print(f"  .env: FAISS_IVF_NLIST -> {target}")
        except OSError as e:
            print(f"  WARNING: could not update .env ({e}). Set FAISS_IVF_NLIST={target} manually.")

    print()
    print(f"DONE. Restart api with: docker compose up -d api")
    print(f"Rollback if needed: rename {pre_index.name} back to {live_index_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
