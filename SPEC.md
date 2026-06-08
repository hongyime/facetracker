§G
impl unified face search ops dashboard

§C
- React + Vite + TS frontend
- FastAPI backend
- Dark enterprise UI (#0a0a0a)
- Dense bento layout
- Real-time WS health broadast
- Production Docker (multi-stage)
- Service-agnostic abstractions
- Storage root at Y:/faces
- Postgres data at Y:/faces/postgres_data

§I
- API: /api/{service}/{resource}
- WS: /ws/health
- Web: http://localhost:8700

§V
1. All responses match {data, error, meta} contract.
2. WS broadcasts every 5s.
3. Sidebar links valid React Router paths.
4. pl-64 gap between sidebar and content.
5. No ZeroDivisionError in stats logic.
6. Thread-safe file manifest (RLock).
7. NumPy types converted to primitives for SQL.
8. State (Postgres, FAISS, Cache) MUST live in Y:/faces.

§T
id|status|task|cites
T1|x|scaffold vite frontend|V3
T2|x|impl generic components (MetricCard, DataTable)|
T3|x|impl FastAPI backend shell|V1
T4|x|impl WS health broadcast|V2
T5|x|map frontend to real FaceTracker API|V1,I.api
T6|x|fix sidebar spacing and pl-64|V4
T7|x|fix ZeroDivision and NumPy SQL errors|V5,V7
T8|x|fix thread-safety in manifest|V6
T9|.|resume processing with migration to Y:/faces|V8
T10|.|verify identity clustering run|
T11|.|fix duplicate insert: upsert images on file_path|V9
T12|.|exclude Plex/transcoder/cache dirs from scan|V10
T13|.|multi-stage Dockerfile: 2.95GB->~800MB|
T14|.|migrate postgres_data C:->Y:/faces (SPEC drift)|V8

§V
9. Image inserts MUST be idempotent on file_path (ON CONFLICT DO UPDATE).
10. EXCLUDE_PATHS MUST cover Plex transcoder + thumbnail caches.

§B
id|date|cause|fix
B1|2026-05-18|ZeroDivision in elapsed calculation|add elapsed > 0 check
B2|2026-05-18|Blocking recursive watch on startup|offload watcher to thread
B3|2026-05-19|NumPy float64 SQL serialization error|cast to float() in pipeline
B4|2026-05-19|Double .ids extension in FAISS save|correct path.with_suffix use
B5|2026-05-19|Local disk exhaustion from Postgres|migrate POSTGRES_DATA_PATH to Y:/faces
B6|2026-05-20|UniqueViolation ix_images_file_path: re-insert on rescan|upsert on file_path; add V9
B7|2026-05-20|Plex PhotoTranscoder cache being indexed (ephemeral)|exclude /mnt/c/musicstream/plex; add V10
B8|2026-05-20|.env POSTGRES_DATA_PATH=C:/facetracker/postgres_data violates V8|move to Y:/faces/postgres_data
B9|2026-05-20|Docker WSL VHDX bloated 321GB (slack)|wsl shutdown + Optimize-VHD; add periodic compact

§D — Architectural Decisions
id|date|decision|rationale
D1|2026-06-07|Identity subsystem: Option A (wire it up)|Incremental clustering already runs post-scan. API endpoints for merge/split/rename/list-faces now implemented. Re-cluster with lower threshold to collapse singletons is a separate operational step (scripts/cluster_faces.py --mode=full --threshold=0.5 --confirm). Identity is a core product feature, not aspirational.
