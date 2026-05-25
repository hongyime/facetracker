# Audit Log

Numbered findings from the deep audit, with status. See `AUDIT.md` for
the narrative summary.

| # | File | Category | Issue | Status |
|---|------|----------|-------|--------|
| 1 | src/config.py | RUNTIME-BLOCKER | `Settings` rejected `HOST_FACE_STORAGE` env var — app would not import | FIXED |
| 2 | src/main.py:69 | RELIABILITY | Shutdown referenced unset module global `indexing_manager` | FIXED |
| 3 | test_manager_locally.py | BUG | `import time` was below first usage | FIXED |
| 4 | src/storage/database.py | RESOURCE-LEAK | `get_database()` built a new engine + pool per call | FIXED (module-level cache) |
| 5 | src/api/routes/search.py | RESOURCE-LEAK / RACE | Shared `db.session` across requests | FIXED (request-scoped session) |
| 6 | src/api/routes/identity.py | RESOURCE-LEAK / RACE | Shared `db.session` | FIXED |
| 7 | src/api/routes/stats.py | RESOURCE-LEAK / RACE | Shared `db.session` | FIXED |
| 8 | src/api/routes/files.py | RESOURCE-LEAK / RACE | Shared `db.session` | FIXED |
| 9 | src/storage/faiss_index.py | CONCURRENCY | Check-and-trigger merge race in `add()` | FIXED (decision under lock) |
| 10 | src/storage/faiss_index.py | CONCURRENCY | `search()` could observe half-merged state | FIXED (search under lock) |
| 11 | src/discovery/onedrive.py | SECURITY | PowerShell injection in `_check_cloud_attribute` | FIXED ($args[0] + LiteralPath) |
| 12 | src/discovery/onedrive.py | SECURITY | PowerShell injection in `download_file` | FIXED |
| 13 | src/discovery/onedrive.py | SECURITY | PowerShell injection in `revert_to_online_only` fallback | FIXED |
| 14 | operations-dashboard/backend/main.py | SECURITY | CORS `allow_origins=["*"]` + credentials | FIXED (pinned allowlist) |
| 15 | operations-dashboard/backend/main.py | RELIABILITY | Global handler returned HTTP 200 on all errors | FIXED |
| 16 | operations-dashboard/backend/main.py | CONCURRENCY | Disconnect could remove twice | FIXED (guarded remove) |
| 17 | operations-dashboard/backend/main.py | CONCURRENCY | Broadcast iterated mutable list | FIXED (snapshot under lock) |
| 18 | operations-dashboard/backend/main.py | RESOURCE-LEAK | Dead WS connections never pruned | FIXED |
| 19 | src/storage/faiss_index.py | DATA-INTEGRITY | Merge published in-memory before disk write | FIXED |
| 20 | src/storage/faiss_index.py | DATA-INTEGRITY | Index saved before ids — crash = unrecoverable | FIXED (ids first, recovery on load) |
| 21 | src/discovery/onedrive.py | BUG | `_check_reparse_point` true for any reparse tag | FIXED (content match) |
| 22 | src/pipeline/processor.py | LOGIC-BUG | Best-frame quality hardcoded `0.8` | FIXED (real quality + IoU) |
| 23 | src/pipeline/processor.py | LOGIC-BUG | Re-detect used `detections[0]` blindly | FIXED (IoU match) |
| 24 | src/pipeline/processor.py | DATA-COMPLETENESS | `Image.width/height` never written | FIXED |
| 25 | src/storage/database.py | DATA-INTEGRITY | `Face.image_id` lacked index + cascade | FIXED |
| 26 | src/discovery/onedrive.py | LOGIC-BUG | `revert_to_online_only` returned True when both branches failed | FIXED |
| 27 | src/api/routes/search.py | API-CORRECTNESS | `search_within_identity` returned fake empty list | FIXED (HTTP 501) |
| 28 | src/utils/atomic.py | LOGIC-BUG | `atomic_operation` ignored its rollback callable | FIXED |
| 29 | src/discovery/onedrive.py | OBSERVABILITY | `print()` instead of logger | FIXED |
| 30 | src/storage/faiss_index.py | OBSERVABILITY | `print()` instead of logger | FIXED |
| 31 | src/api/routes/identity.py | API-CORRECTNESS | `avg_quality_score` hardcoded 0.8 | FIXED (AVG query) |
| 32 | src/api/routes/identity.py | API-CORRECTNESS | `get_identity` thumbnail always None | FIXED |
| 33 | src/api/routes/* | API-CORRECTNESS | Unimplemented endpoints returned fabricated success | FIXED (HTTP 501) |
