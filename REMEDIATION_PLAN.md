# Facetracker Remediation Plan

Status: DRAFT for review — no code changed yet.
Author: design review, 2026-05-30.
Basis: source + live DB inspection. Three first-pass design-review claims were
falsified during verification and are recorded in the Appendix so we don't
re-introduce them as "fixes".

Live baseline at time of writing:
- faces=17,619  identities=13,941  mapped_faces=17,003  outbox=17,619 (all committed)
- FAISS: IndexIVFFlat, live_count=17,619, live_ids=17,619 (zero drift right now)
- 4 containers healthy; index_workers=1 (env) ; FAISS_INDEX_TYPE=IVFFlat (env)

--------------------------------------------------------------------------------
## Guiding constraints (do not violate)

- Live system. Postgres + Redis stay up. api + dashboard are cycleable.
- Schema changes are additive via SQLAlchemy create_all (no Alembic today).
- Source is bind-mounted (C:/facetracker/src -> /app/src); code edits go live on
  container restart, no rebuild.
- `docker-compose up -d` reloads .env; `restart` does NOT.
- No destructive ops without explicit approval and a stated rollback.
- Backups exist under Y:\facetracker\backups\ ; weekly schtask keeps 4.

--------------------------------------------------------------------------------
## Phase 0 — Hygiene (zero behavioural risk, do first)

P0.1  Delete path-corruption junk dirs `./config;C` and `./src;C` (empty
      artifacts from a malformed command). Verify empty first, then remove.
      Rollback: none needed (empty dirs).

P0.2  Remove `.env.bak.20260527_115025` from repo root (stale, secret-bearing).
      Add `.env.bak.*` to .gitignore. Confirm it is not tracked in git history;
      if it is, that is a separate secret-rotation conversation — FLAG, do not
      silently ignore.

P0.3  Fix config/env default drift: `src/config.py` defaults
      `faiss_index_type="HNSW64"` but production runs IVFFlat via .env. Change
      the code default to "IVFFlat" so a fresh boot without .env does not build
      the wrong index family. Additive, no runtime change (env already wins).

P0.4  Resolve `index_workers` drift: config.py default=2, .env=1, and >1 was
      empirically slower on this CPU. Set config default=1 and add a one-line
      comment pointing at the ONNX intra-op saturation finding.

Acceptance: repo root clean; `python -c "from src.config import settings;
print(settings.faiss_index_type, settings.index_workers)"` prints `IVFFlat 1`.

--------------------------------------------------------------------------------
## Phase 1 — Silent-corruption guards (highest real risk)

CONTEXT: The merge path in faiss_index.py is crash-safe for the on-disk
ids/index files (ids-before-index ordering + trim-on-load). The UNGUARDED gap:
if the process dies AFTER `live_index.add()` but BEFORE `_save_ids_atomic`, the
in-memory vectors are lost, the outbox rows are already (or will be) marked
`committed`, and committed rows are never re-drained. Result: faces present in
`faces.embedding_vec` but absent from FAISS, permanently unsearchable, with no
detector. Current drift is zero, but nothing watches for it.

P1.1  Add a reconciler: compare COUNT(faces) (or count of faces with non-null
      embedding_vec) against faiss_index.live_count. Expose the delta in
      /health and the dashboard. Read-only; no mutation. This is the detector
      that is missing today.

P1.2  Add a rebuild-from-DB recovery script: `scripts/faiss_rebuild_from_db.py`
      that reads `faces.embedding_id + embedding_vec` and reconstructs the
      FAISS index file from scratch. This is the recovery action when P1.1
      reports drift, or when the index file is lost/corrupt. Today there is NO
      path to rebuild — only migrate/autotune scripts. Must write to a temp
      index and atomically swap, never mutate the live file in place.

P1.3  IVF untrained-merge trap guard: if the index is IVFFlat and untrained,
      `_ensure_ivf_trained` silently POSTPONES every merge until staging hits
      nlist*8 (4,096) vectors. With force_merge after small reaper batches the
      index can sit untrained indefinitely and faces silently never become
      searchable. Add: (a) a WARNING-level log already exists — promote a
      persistent "index untrained, N faces unsearchable" signal into /health so
      it cannot be missed; (b) document that a fresh IVF index must be
      bootstrapped via the migration script, not grown from empty.

Acceptance: /health returns faiss_live_count, db_face_count, drift, and
index_trained. Rebuild script dry-run prints the vector count it WOULD rebuild
without writing. Inject-drift smoke test (delete an ids entry, restart) is
caught by P1.1.

--------------------------------------------------------------------------------
## Phase 2 — Identity subsystem decision (architectural debt)

CONTEXT: src/identity/{clustering,metrics,verification}.py are imported by NO
runtime code — only scripts/cluster_faces.py. The API identity routes are
read-only (list/get). 13,941 identities for 17,619 faces (~1.26 faces/identity)
indicates near-singleton clusters: clustering is a stale, manually-triggered
batch artifact, not a live capability. The PRD presents identity management as
a feature; the runtime does not deliver it.

This phase is a DECISION, not yet an implementation. Two mutually exclusive
directions — pick one before any code:

  Option A (wire it up):
    - Run clustering as a scheduled job (cron/schtask) with incremental
      assignment of new faces to existing centroids.
    - Add merge/split/verify/rename endpoints (tables + VerificationAudit +
      max_undo_stack already exist for this).
    - Re-cluster the existing 17.6k faces so identities become meaningful.
    Cost: substantial. This is the "finish the product" path.

  Option B (cut it):
    - Remove src/identity/* from runtime expectations, mark PRD identity
      sections as ASPIRATIONAL/NOT SHIPPED, optionally keep the script as an
      offline tool. Leave tables in place (additive, harmless) or document them
      as script-owned.
    Cost: low. This is the "stop the codebase from lying" path.

RECOMMENDATION: Option B now, Option A as a future project. A half-built
identity feature is worse than none because it invites building on data that
isn't real. Decide explicitly; do not leave it ambiguous.

Acceptance: a written decision recorded in SPEC.md or PRD.md. If B: PRD updated,
no orphaned imports remain misleadingly "available". If A: a tracked plan with
its own phases.

--------------------------------------------------------------------------------
## Phase 3 — Security baseline (single-user, Tailscale-exposed)

CONTEXT: Zero auth on any route. api:5454 and dashboard:8701 are host ports;
on a Tailscale tailnet every tailnet peer can hit them unauthenticated.

P3.1  Add a static bearer-token guard (env-configured) as a FastAPI dependency
      on all /api/v1 routes. Localhost health check exempt. Token in .env, never
      committed. Minimal, sufficient for a single-user system.

P3.2  Harden the `file_path` query-param surface in files.py: it is currently
      safe (equality DB lookup only, no filesystem open), but add a
      normalization/whitelist guard now so a future endpoint that does open()
      cannot introduce traversal. Defensive, low cost.

P3.3  Review CORS: allow_credentials=True + allow_methods=["*"] is fine while
      origins are localhost-only. Add a comment pinning the invariant so origins
      are never widened without revisiting.

Acceptance: unauthenticated request to /api/v1/stats returns 401; authenticated
returns 200; /health still open.

--------------------------------------------------------------------------------
## Phase 4 — Reliability / observability

P4.1  /health upgrade (folds in P1.1/P1.3): check DB connectivity, outbox
      backlog by status, failed-row count, faiss drift, index_trained. Return
      degraded (not just healthy) when any threshold is breached.

P4.2  Alert on outbox `failed` rows: surface count in /health and dashboard.
      After max_attempts a row parks as failed silently today.

P4.3  Outbox retention: prune `committed` rows older than N days. Each carries a
      redundant 2KB embedding blob already stored in faces.embedding_vec
      (~35MB redundant at current scale, grows linearly). Read-committed-only
      delete; never touch pending/merging/failed.

P4.4  Redis decision: it is imported (main.py:6) but never instantiated or used.
      search_cache_enabled=True config does nothing. Either implement the search
      cache or drop the container + dependency + config. Recommend DROP unless
      search latency becomes a problem.

Acceptance: /health reflects real subsystem state; a forced failed row shows up;
retention dry-run reports rows it would prune.

--------------------------------------------------------------------------------
## Phase 5 — Engineering hygiene (lower urgency)

P5.1  Minimal CI (GitHub Action): run the existing smoke + unit tests on push.
      They are good (idempotency, reclaim-stuck, skip-locked) but rot unrun.
P5.2  datetime.utcnow() is deprecated (3.12) and mixes naive timestamps with
      Postgres NOW() (tz-aware) in reaper stuck-reclaim math. Works now; migrate
      to timezone-aware datetimes to remove the latent tz-config landmine.
P5.3  Doc consolidation: AUDIT.md, AUDIT_LOG.md, security_audit.md, SPEC.md,
      PRD.md (115KB), Testing_Prompt_*.md, onedrive-sidecar-plan.md. Mark
      shipped vs aspirational. The PRD currently overstates capabilities.
P5.4  Remove dead config: DriveSource nested BaseSettings + drive_sources list
      is never populated meaningfully.

--------------------------------------------------------------------------------
## Sequencing & rationale

1. Phase 0 first — pure hygiene, zero risk, clears noise.
2. Phase 1 next — the only UNGUARDED silent-corruption path in the system.
   Detector (P1.1) + recovery (P1.2) before anything that could trigger drift.
3. Phase 2 decision before Phase 3/4 build-out, so we don't secure/observe a
   subsystem we're about to cut.
4. Phase 3 security — quick, meaningful given Tailscale exposure.
5. Phase 4 reliability — folds into the /health work started in Phase 1.
6. Phase 5 — hygiene, do as capacity allows.

## Explicitly OUT of scope / deferred
- DB orphan deletion (144 orphans in Instagram Scrape Bot\.portal\nyjc) —
  destructive, deferred, separate approval.
- Increasing index_workers — DISPROVEN on this hardware (ONNX intra-op pool
  saturates; >1 worker measured slower). Do not revisit without new hardware.
- GPU acceleration — no discrete GPU; integrated UHD 620 unreachable from the
  Linux container. Not viable.

--------------------------------------------------------------------------------
## Appendix — design-review claims FALSIFIED during verification

These were asserted in the verbal design review and then DISPROVEN by reading
the code/live state. Recorded so they are not re-introduced as "fixes":

F1. "Use-after-close session bug in outbox._drain_once." FALSE. The claim-phase
    exception handler closes + re-raises (exits the method); all later blocks
    run on a session that is committed-but-open, which is valid in SQLAlchemy.
    No bug. No fix needed.

F2. "Flip to IVFFlat before the scaling cliff / force_merge rewrites whole HNSW
    index every batch." FALSE/MOOT. Live index is ALREADY IndexIVFFlat
    (.env FAISS_INDEX_TYPE=IVFFlat; confirmed in live logs). IVF add is O(1),
    not an O(N) whole-graph rewrite. The migration was already run. The residual
    real issue is the untrained-IVF trap (P1.3) and the config default drift
    (P0.3), not a pending migration.

F3. "13,941 identities is live clustering output." MISLEADING. It is a stale,
    script-only batch artifact; clustering is not in the runtime (Phase 2).
