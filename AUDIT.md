# Audit Status — Face Tracker

Authoritative status of audit work. Earlier versions of this file (and
`security_audit.md`, `AUDIT_LOG.md`) claimed "no issues found" / "SAFE";
that was wrong and has been replaced.

The fixes recorded below were applied during a deep audit of the codebase
and runtime behaviour. See `AUDIT_LOG.md` for the full numbered list.

## Fixes applied

Configuration / startup
- `src/config.py` — `Settings` now accepts the `HOST_FACE_STORAGE` env var
  via `AliasChoices` and tolerates unknown keys with `extra="ignore"`. The
  app would not start prior; `pydantic_core.ValidationError` on import.
- `src/main.py` — shutdown reads `app.state.indexing_manager` instead of an
  unset module-level global, so background threads stop on FastAPI exit.
- `test_manager_locally.py` — `import time` moved to module scope.

Database / connections
- `src/storage/database.py` — `get_database()` caches one connected
  `Database` (one engine, one pool) per URL behind a lock instead of
  building a new engine + pool on every request. New `get_db_session()`
  yields a request-scoped `Session` for FastAPI `Depends(...)`.
- All API routes (`search.py`, `identity.py`, `stats.py`, `files.py`)
  migrated to `Depends(get_db)` backed by `get_db_session`. No more
  shared mutable `Database.session` per route.
- `Face.image_id` has `index=True` and `ON DELETE CASCADE` to support the
  cascade defined on the `Image.faces` relationship.

FAISS index
- `src/storage/faiss_index.py` —
  * `add()` and `add_batch()` decide whether to merge under the lock; the
    actual disk-touching merge runs outside the lock to avoid blocking
    producers.
  * `search()` runs under the merge lock so it cannot observe a half-built
    index during a swap.
  * Merge writes `.ids.npy` BEFORE the `.faiss` index, and only updates
    `live_ids` / `live_count` after both succeed. `_initialize_index`
    detects a crash between the two writes (ids ahead of index) and trims
    `live_ids`, so a power loss mid-merge is recoverable rather than
    corrupting search results.
  * Both writes go through `.tmp` + atomic rename.

OneDrive handler
- `src/discovery/onedrive.py` —
  * `_check_reparse_point` requires the `fsutil` output to mention
    "onedrive" or "cloud"; previously any reparse point (random symlink,
    junction) returned True and triggered a download.
  * `_check_cloud_attribute`, `download_file`, `revert_to_online_only`
    (PowerShell fallback): file paths are passed via `$args[0]` and
    `Get-Item -LiteralPath`, never interpolated into the script body.
    Filenames containing single quotes can no longer execute arbitrary
    PowerShell.
  * `revert_to_online_only` no longer returns success when both `attrib`
    and the PowerShell fallback fail.

Pipeline
- `src/pipeline/processor.py` —
  * Per-track best frame in `_process_video` now uses the detector's
    real `quality_score`, matched to the tracker bbox by IoU. The previous
    code used a hardcoded `0.8` so every track tied at "best".
  * On finalisation the embedding comes from the detection whose bbox
    overlaps the track, not `detections[0]`. Frames with multiple faces
    no longer cross-contaminate identities.
  * `width` / `height` are populated from the source media on both image
    and video paths and persisted on the `Image` record.

Operations dashboard (`operations-dashboard/backend/main.py`)
- CORS pinned to an explicit allowlist (env var `DASHBOARD_CORS_ORIGINS`).
  `allow_credentials=True` with `allow_origins=["*"]` is rejected by
  browsers anyway and was both broken and insecure.
- Global exception handler returns proper HTTP status codes (404, 500,
  ...) and a generic public message; full traceback is logged
  server-side. Previously every error returned HTTP 200 with a JSON
  envelope, hiding failures from monitoring and load balancers.
- `ConnectionManager` now snapshots `active_connections` under an
  `asyncio.Lock` before broadcasting, prunes dead sockets after the
  send loop, and guards `disconnect()` so double-removal is a no-op.

API stubs
- `search_within_identity`, `files.search`, `files.reprocess`,
  `files.delete`, `stats.onedrive`, `stats.recent_activity` return
  HTTP 501 instead of fabricated empty results.

Identity API
- `list_identities` and `get_identity` compute `avg_quality_score` from
  `AVG(Face.quality_score)` over the identity's faces and look up the
  primary (or first) face's `thumbnail_path` instead of returning `0.8`
  / `None`.

Logging
- `print()` calls in `onedrive.py` and `faiss_index.py` replaced with the
  module logger.

Atomic helpers
- `src/utils/atomic.py::atomic_operation` now actually invokes the
  rollback callback on exception and re-raises the original error;
  rollback failures are logged but do not mask the primary exception.

## Known limitations

- `_save_image_record` flush + face attach + commit is still a single
  Database session; if the process is killed between the flush and the
  commit the partial image row + faces are rolled back, but the
  embeddings already added to FAISS staging via `_process_face` are not
  rolled back. This is documented but not fixed — it requires a
  two-phase write or a pending-faces table.
- `Database` still exposes a long-lived `session` property used by
  `PipelineProcessor`; the audit moved HTTP routes off it but the
  indexing pipeline still relies on the singleton session.

## Auth and tenancy

This service runs locally (Y:/faces, Postgres on localhost). There is no
auth layer in front of the API and no tenant isolation; do not expose
the FastAPI port off-host without a reverse proxy that adds
authentication.
