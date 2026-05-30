#!/usr/bin/env python3
"""Cluster face embeddings into identities.

Two modes:

  --mode=full
      Wipe every existing FaceIdentityMap + Identity row and recompute from
      scratch using Chinese Whispers label propagation on a FAISS-built kNN
      graph. Use this on first run, after a threshold change, or when you
      know past clustering was wrong and you want a clean slate.

  --mode=incremental
      Assign only faces NOT yet in face_identity_map. Each new face goes
      to the nearest existing identity by centroid cosine similarity if
      similarity >= threshold, otherwise becomes the seed of a new
      identity. Existing assignments are NEVER changed. Use this on cron.

Algorithm: Chinese Whispers
  1) For each face, FAISS-search its top K nearest neighbours.
  2) Build an undirected graph where edge (a,b) exists iff cos(a,b) >= threshold.
  3) Iterate label propagation: each node adopts the most common label
     among its weighted neighbours (weights = similarity). Converges in
     5-15 iterations for typical face data.
  4) Each connected component label = one identity. Compute per-cluster
     centroid as the mean of L2-normalized member embeddings.

Decisions encoded:
  - Threshold default 0.6 (strict; minimises false merges across people).
    Tune via --threshold or settings.identity_cluster_threshold.
  - K=20 nearest neighbours considered per face. Higher K = denser graph =
    more merges. 20 is a sane default for face embeddings; raise if
    clusters look too fragmented.
  - Per-face uniqueness in face_identity_map enforced by DB constraint —
    if you re-run --mode=full, we DELETE all existing rows in one TX
    before re-inserting. The DELETE is the only destructive op; protected
    behind --confirm.

Usage (always run inside docker so it sees postgres + the FAISS index):

  # Dry run — prints cluster size distribution, writes nothing:
  docker run --rm --env-file .env --network facetracker-net \\
      -v "$(pwd):/app" -w /app -e FACE_STORAGE_ROOT=/mnt/y/facetracker/faces \\
      -v "Y:/facetracker/faces:/mnt/y/facetracker/faces" facetracker-api \\
      python scripts/cluster_faces.py --mode=full --threshold=0.6 --dry-run

  # Real run with --confirm — deletes existing identities + repopulates:
  docker run ... python scripts/cluster_faces.py --mode=full --threshold=0.6 --confirm

  # Incremental (default; no --confirm needed because non-destructive):
  docker run ... python scripts/cluster_faces.py --mode=incremental
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import faiss  # type: ignore
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import settings  # noqa: E402
from src.storage.database import (  # noqa: E402
    Face,
    FaceIdentityMap,
    Identity,
)

DIM = 512


# --- Helpers -----------------------------------------------------------------


def _load_all_faces(session: Session) -> Tuple[List[int], List[str], np.ndarray]:
    """Load every face's (db_id, embedding_id, embedding_vec).

    Returns (db_ids, embedding_ids, embeddings_array).
    embeddings_array is L2-normalized so that inner product = cosine sim.
    """
    print("Loading all faces from postgres...", flush=True)
    t0 = time.time()
    db_ids: List[int] = []
    eids: List[str] = []
    vecs: List[np.ndarray] = []
    q = (
        session.query(Face.id, Face.embedding_id, Face.embedding_vec)
        .filter(Face.embedding_vec.is_not(None))
        .yield_per(2048)
    )
    for fid, eid, vec in q:
        if vec is None:
            continue
        arr = np.asarray(vec, dtype=np.float32)
        if arr.shape != (DIM,):
            print(f"  WARNING: skipping face_id={fid} bad shape {arr.shape}")
            continue
        db_ids.append(fid)
        eids.append(eid)
        vecs.append(arr)
    n = len(db_ids)
    print(f"  loaded {n} faces in {time.time() - t0:.1f}s", flush=True)
    if n == 0:
        return [], [], np.zeros((0, DIM), dtype=np.float32)
    arr = np.vstack(vecs).astype(np.float32)
    faiss.normalize_L2(arr)
    return db_ids, eids, arr


def _build_knn_graph(
    embeddings: np.ndarray, k: int, threshold: float
) -> Dict[int, List[Tuple[int, float]]]:
    """Build a kNN graph using FAISS, retain only edges with sim >= threshold.

    Returns adjacency dict: {node_idx -> [(neighbour_idx, similarity), ...]}.
    Self-edges are excluded. The graph is symmetrised — even if A is in B's
    top-K but B is not in A's top-K, we still add the edge in both directions
    if the similarity passes the threshold (FAISS gives us an asymmetric
    kNN graph; CW prefers symmetric input).
    """
    n = embeddings.shape[0]
    print(
        f"Building kNN graph (k={k}, threshold={threshold}) "
        f"with FAISS flat IP index for max recall...",
        flush=True,
    )
    t0 = time.time()
    # Use a fresh flat IP index for accuracy here — we aren't running queries
    # at scale, just one-shot, so flat exact search is the safe choice.
    # If we used the live IVFFlat index we'd inherit nprobe=32 recall (~98%)
    # and miss some edges; flat IP is exact.
    index = faiss.IndexFlatIP(DIM)
    index.add(embeddings)
    # k+1 because the closest neighbour is always the point itself.
    D, I = index.search(embeddings, k + 1)
    print(f"  FAISS kNN done in {time.time() - t0:.1f}s", flush=True)

    adj: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    edge_count = 0
    for i in range(n):
        for j_idx, sim in zip(I[i], D[i]):
            if j_idx == i or j_idx < 0:
                continue
            if sim < threshold:
                continue
            j = int(j_idx)
            sim_f = float(sim)
            adj[i].append((j, sim_f))
            adj[j].append((i, sim_f))  # symmetrise
            edge_count += 1

    # Dedupe — symmetrisation may have inserted both (i,j) and (j,i) when
    # both directions were present in the FAISS results.
    deduped: Dict[int, List[Tuple[int, float]]] = {}
    for i, neighbours in adj.items():
        seen: Dict[int, float] = {}
        for j, s in neighbours:
            if j not in seen or seen[j] < s:
                seen[j] = s
        deduped[i] = [(j, s) for j, s in seen.items()]

    print(
        f"  graph: {n} nodes, ~{edge_count} edges (pre-dedup), "
        f"avg degree {edge_count * 2 / max(n, 1):.1f}",
        flush=True,
    )
    return deduped


def _chinese_whispers(
    adj: Dict[int, List[Tuple[int, float]]],
    n_nodes: int,
    max_iter: int = 30,
    seed: int = 0,
) -> np.ndarray:
    """Iterative label propagation. Returns array of cluster labels per node.

    Each node starts with a unique label. Per iteration, each node (visited
    in random order) adopts the most-weighted label among its neighbours.
    Stops when no node changed labels in a full sweep, or after max_iter.
    """
    print(f"Running Chinese Whispers (max_iter={max_iter})...", flush=True)
    t0 = time.time()
    rng = np.random.default_rng(seed)
    labels = np.arange(n_nodes, dtype=np.int64)
    order = np.arange(n_nodes)

    for it in range(max_iter):
        rng.shuffle(order)
        changed = 0
        for i in order:
            neighbours = adj.get(int(i), [])
            if not neighbours:
                continue
            scores: Dict[int, float] = defaultdict(float)
            for j, sim in neighbours:
                scores[int(labels[j])] += sim
            # Pick label with max weighted vote; break ties by smaller label.
            best_label = min(
                (lbl for lbl, sc in scores.items() if sc == max(scores.values())),
                default=int(labels[i]),
            )
            if best_label != labels[i]:
                labels[i] = best_label
                changed += 1
        print(f"  iter {it + 1}: {changed} label changes", flush=True)
        if changed == 0:
            break

    print(f"  CW done in {time.time() - t0:.1f}s", flush=True)
    return labels


def _compact_labels(labels: np.ndarray) -> Tuple[np.ndarray, int]:
    """Remap arbitrary CW label values to dense 0..K-1. Returns (compact, K)."""
    unique = np.unique(labels)
    remap = {old: new for new, old in enumerate(unique.tolist())}
    compact = np.array([remap[int(x)] for x in labels], dtype=np.int64)
    return compact, len(unique)


def _compute_centroids(
    embeddings: np.ndarray, labels: np.ndarray, n_clusters: int
) -> np.ndarray:
    """Per-cluster centroid = L2-normalized mean of member embeddings.

    Embeddings are already normalized; their mean is not unit-length, so
    we re-normalize. This makes centroid·embedding == cosine similarity.
    """
    centroids = np.zeros((n_clusters, DIM), dtype=np.float32)
    counts = np.zeros(n_clusters, dtype=np.int64)
    for i, lbl in enumerate(labels):
        centroids[lbl] += embeddings[i]
        counts[lbl] += 1
    # Avoid div-by-zero (shouldn't happen after compact_labels but defensive)
    counts = np.maximum(counts, 1)
    centroids = (centroids / counts[:, None]).astype(np.float32)
    # faiss.normalize_L2 requires a C-contiguous float32 ndarray; the division
    # above can produce a non-contiguous view depending on numpy version.
    centroids = np.ascontiguousarray(centroids)
    faiss.normalize_L2(centroids)
    return centroids


# --- Modes -------------------------------------------------------------------


def _mode_full(
    session: Session,
    threshold: float,
    k_neighbours: int,
    dry_run: bool,
    confirm: bool,
) -> int:
    db_ids, eids, embeddings = _load_all_faces(session)
    n = len(db_ids)
    if n == 0:
        print("ERROR: no faces with embeddings found.")
        return 2

    adj = _build_knn_graph(embeddings, k=k_neighbours, threshold=threshold)
    labels = _chinese_whispers(adj, n_nodes=n)
    labels, n_clusters = _compact_labels(labels)
    centroids = _compute_centroids(embeddings, labels, n_clusters)

    sizes = Counter(int(x) for x in labels)
    size_dist = Counter(sizes.values())
    print()
    print(f"Clustering result: {n} faces -> {n_clusters} clusters")
    print(f"Cluster size distribution (size -> count):")
    for size in sorted(size_dist.keys()):
        marker = "(noise)" if size == 1 else ""
        print(f"  size={size:>6}  clusters={size_dist[size]:>6}  {marker}")
    top = sizes.most_common(10)
    print(f"Largest 10 clusters: {[s for _, s in top]}")
    print(f"Singletons (size=1): {size_dist.get(1, 0)}")
    print()

    if dry_run:
        print("DRY RUN — no changes written. Re-run with --confirm to apply.")
        return 0

    if not confirm:
        print(
            "REFUSING to proceed without --confirm. --mode=full DELETES every "
            "existing identity + face_identity_map row before re-inserting. "
            "If that is what you want, re-run with --confirm. If it isn't, "
            "use --mode=incremental."
        )
        return 3

    # --- Destructive write phase. One TX. ---
    print("Wiping existing identities + face_identity_map ...", flush=True)
    t0 = time.time()
    session.execute(text("DELETE FROM face_identity_map"))
    session.execute(text("DELETE FROM verification_audit"))  # FK to identities
    session.execute(text("DELETE FROM identities"))
    print(f"  deleted in {time.time() - t0:.1f}s", flush=True)

    print(f"Inserting {n_clusters} identities ...", flush=True)
    t0 = time.time()
    # Insert identities and capture their generated IDs by index (cluster_id).
    cluster_to_db_id: Dict[int, int] = {}
    for cluster_idx in range(n_clusters):
        ident = Identity(
            cluster_id=cluster_idx,
            centroid_embedding=centroids[cluster_idx].tolist(),
            is_verified=False,
        )
        session.add(ident)
    session.flush()  # gets autogenerated identity.id values back
    # Reread to map cluster_idx -> identity.id
    rows = session.execute(
        text("SELECT id, cluster_id FROM identities")
    ).fetchall()
    cluster_to_db_id = {int(r.cluster_id): int(r.id) for r in rows}
    print(f"  identities inserted in {time.time() - t0:.1f}s", flush=True)

    print(f"Inserting {n} face_identity_map rows ...", flush=True)
    t0 = time.time()
    # Bulk insert via raw SQL for speed at scale.
    rows_to_insert = []
    for i in range(n):
        cluster_idx = int(labels[i])
        identity_db_id = cluster_to_db_id[cluster_idx]
        sim = float(np.dot(embeddings[i], centroids[cluster_idx]))
        rows_to_insert.append(
            {
                "face_id": db_ids[i],
                "identity_id": identity_db_id,
                "similarity_to_centroid": sim,
                "is_primary": False,
                "assigned_by": "auto",
                "confidence": sim,
            }
        )
    # Insert in batches of 1000 to keep the SQL string size bounded.
    batch = 1000
    for start in range(0, len(rows_to_insert), batch):
        chunk = rows_to_insert[start : start + batch]
        session.execute(
            text(
                "INSERT INTO face_identity_map "
                "(face_id, identity_id, similarity_to_centroid, is_primary, assigned_by, confidence, created_at) "
                "VALUES (:face_id, :identity_id, :similarity_to_centroid, :is_primary, :assigned_by, :confidence, NOW())"
            ),
            chunk,
        )
    print(f"  face_identity_map inserted in {time.time() - t0:.1f}s", flush=True)

    # Mark per-cluster primary face = the one closest to centroid.
    print("Marking per-cluster primary faces ...", flush=True)
    session.execute(
        text(
            """
            UPDATE face_identity_map
               SET is_primary = TRUE
             WHERE id IN (
                 SELECT DISTINCT ON (identity_id) id
                   FROM face_identity_map
                  ORDER BY identity_id, similarity_to_centroid DESC NULLS LAST
             )
            """
        )
    )

    session.commit()
    print(f"COMMIT — {n_clusters} identities, {n} face mappings.")
    return 0


def _mode_incremental(
    session: Session,
    threshold: float,
) -> int:
    print("Incremental mode: assigning new faces to existing or new identities.")

    # 1) Find all faces NOT yet mapped.
    print("Finding unmapped faces ...", flush=True)
    rows = session.execute(
        text(
            """
            SELECT f.id, f.embedding_id, f.embedding_vec
              FROM faces f
              LEFT JOIN face_identity_map m ON m.face_id = f.id
             WHERE m.id IS NULL
               AND f.embedding_vec IS NOT NULL
            """
        )
    ).fetchall()
    if not rows:
        print("  no unmapped faces — nothing to do.")
        return 0

    new_db_ids: List[int] = []
    new_vecs: List[np.ndarray] = []
    for r in rows:
        arr = np.asarray(r.embedding_vec, dtype=np.float32)
        if arr.shape != (DIM,):
            continue
        new_db_ids.append(int(r.id))
        new_vecs.append(arr)
    n_new = len(new_db_ids)
    if n_new == 0:
        print("  no usable unmapped faces.")
        return 0
    new_arr = np.ascontiguousarray(np.vstack(new_vecs).astype(np.float32))
    faiss.normalize_L2(new_arr)
    print(f"  {n_new} unmapped faces to assign", flush=True)

    # 2) Load existing centroids.
    rows = session.execute(
        text("SELECT id, centroid_embedding FROM identities WHERE centroid_embedding IS NOT NULL")
    ).fetchall()
    if rows:
        existing_ids = [int(r.id) for r in rows]
        existing_centroids = np.ascontiguousarray(
            np.vstack(
                [np.asarray(r.centroid_embedding, dtype=np.float32) for r in rows]
            ).astype(np.float32)
        )
        faiss.normalize_L2(existing_centroids)
        print(f"  {len(existing_ids)} existing identities loaded", flush=True)
        idx = faiss.IndexFlatIP(DIM)
        idx.add(existing_centroids)
        D, I = idx.search(new_arr, 1)
        nearest_sim = D[:, 0]
        nearest_idx = I[:, 0]
    else:
        existing_ids = []
        existing_centroids = np.zeros((0, DIM), dtype=np.float32)
        nearest_sim = np.full(n_new, -2.0, dtype=np.float32)  # force "no match"
        nearest_idx = np.full(n_new, -1, dtype=np.int64)

    # 3) For each new face: assign to nearest if sim>=threshold, else seed
    #    a brand-new identity. Insert in one TX.
    assigned_existing = 0
    new_seeds = 0
    insertions: List[Dict] = []
    new_identity_inserts: List[Tuple[int, np.ndarray]] = []  # (placeholder cluster_id, embedding)

    for i in range(n_new):
        if nearest_sim[i] >= threshold and nearest_idx[i] >= 0:
            target_identity_id = existing_ids[int(nearest_idx[i])]
            insertions.append(
                {
                    "face_id": new_db_ids[i],
                    "identity_id": target_identity_id,
                    "similarity_to_centroid": float(nearest_sim[i]),
                    "is_primary": False,
                    "assigned_by": "auto",
                    "confidence": float(nearest_sim[i]),
                }
            )
            assigned_existing += 1
        else:
            # New identity needed; we'll INSERT identity row first, then map.
            new_seeds += 1
            new_identity_inserts.append((i, new_arr[i]))

    print(
        f"  match-to-existing: {assigned_existing}, new-identity-seeds: {new_seeds}",
        flush=True,
    )

    # Insert new identities, capture IDs.
    seed_face_to_identity_id: Dict[int, int] = {}
    if new_identity_inserts:
        # Find a starting cluster_id beyond the existing max.
        max_cluster_id = (
            session.execute(text("SELECT COALESCE(MAX(cluster_id), -1) FROM identities")).scalar()
            or -1
        )
        next_cluster_id = max_cluster_id + 1
        for i, emb in new_identity_inserts:
            ident = Identity(
                cluster_id=next_cluster_id,
                centroid_embedding=emb.tolist(),
                is_verified=False,
            )
            session.add(ident)
            session.flush()  # get ident.id
            seed_face_to_identity_id[i] = ident.id
            insertions.append(
                {
                    "face_id": new_db_ids[i],
                    "identity_id": ident.id,
                    "similarity_to_centroid": 1.0,  # seed face IS the centroid
                    "is_primary": True,
                    "assigned_by": "auto",
                    "confidence": 1.0,
                }
            )
            next_cluster_id += 1

    # Bulk insert face_identity_map rows.
    if insertions:
        batch = 1000
        for start in range(0, len(insertions), batch):
            chunk = insertions[start : start + batch]
            session.execute(
                text(
                    "INSERT INTO face_identity_map "
                    "(face_id, identity_id, similarity_to_centroid, is_primary, assigned_by, confidence, created_at) "
                    "VALUES (:face_id, :identity_id, :similarity_to_centroid, :is_primary, :assigned_by, :confidence, NOW()) "
                    # face_id has UNIQUE constraint — concurrent re-runs would
                    # otherwise blow up. ON CONFLICT skip is the right choice
                    # because if a face IS mapped, we should not overwrite it.
                    "ON CONFLICT (face_id) DO NOTHING"
                ),
                chunk,
            )

    session.commit()
    print(
        f"COMMIT — {assigned_existing} faces matched existing, "
        f"{new_seeds} new identities seeded.",
        flush=True,
    )
    return 0


# --- CLI ---------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("full", "incremental"),
        default="incremental",
        help="full = re-cluster everything (destructive). incremental = assign new faces only.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Cosine similarity threshold for same-person edges (default 0.6).",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=20,
        help="kNN neighbours per face when building graph (full mode only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute clusters and print stats but write nothing.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required for --mode=full to actually wipe + re-cluster.",
    )
    args = parser.parse_args()

    print(f"=== cluster_faces.py mode={args.mode} threshold={args.threshold} ===")
    print(f"DB URL: {settings.database_url[:60]}...")
    print()

    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        if args.mode == "full":
            return _mode_full(
                session,
                threshold=args.threshold,
                k_neighbours=args.k,
                dry_run=args.dry_run,
                confirm=args.confirm,
            )
        else:
            return _mode_incremental(session, threshold=args.threshold)


if __name__ == "__main__":
    sys.exit(main())
