# Face Tracker - Private Face Search Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)

A **production-ready, private face search engine** that indexes millions of faces from your local drives and OneDrive, providing PimEyes-style reverse image search capabilities—100% locally with no cloud dependencies.

## 🎯 Features

### Core Capabilities
- **Reverse Image Search**: Upload a photo → find all matching faces across your entire collection
- **Multi-Face Search**: Find group photos containing specific people
- **Real-Time Indexing**: New files are automatically discovered and indexed as they appear
- **OneDrive Integration**: Seamlessly process cloud-synced folders with intelligent placeholder handling
- **Video Processing**: Extract and index faces from videos using DeepSORT tracking at 3 FPS
- **Identity Management**: Automatic clustering, manual verification, and audit logging

### Technical Highlights
- **Scale**: Designed for 10M+ faces with optimized storage (~100GB vs ~1TB naive approach)
- **Performance**: <500ms search latency, 10K+ embeddings/second via batched FAISS ingestion
- **Storage Efficiency**: 
  - 16-bit halfvec embeddings (50% reduction)
  - Batched FAISS indexing (52% reduction)
  - On-demand thumbnail generation (eliminates 960GB of face crops)
- **Privacy First**: All data stays local, no external API calls, no subscriptions
- **Quality-Aware**: Multi-stage filtering (detection confidence, Laplacian variance, embedding quality)

### Supported Formats
- **Images**: JPEG, PNG, WebP, GIF, BMP, HEIC, HEIF, TIFF
- **RAW**: CR2, CR3, NEF, ARW, ORF, RW2, DNG, RAF
- **Videos**: MP4, MOV, M4V, AVI, MKV, WMV, WebM, FLV, 3GP

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Face Tracker v4.0                         │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   FastAPI    │────▶│   Search     │────▶│   Identity   │
│   Routes     │     │   Engine     │     │   Clustering │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                      │
       ▼                    ▼                      ▼
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ PostgreSQL  │  │   FAISS     │  │    Redis    │         │
│  │  + halfvec  │  │  Batched    │  │    Cache    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  File Discovery & Pipeline                   │
│  Watchdog Scanner → Face Detection → Embedding → Indexing   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Source Drives                             │
│  Local (C:/, Y:/) │ USB │ OneDrive Sync Folders             │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **API** | FastAPI | Async REST API with OpenAPI docs |
| **Database** | PostgreSQL + pgvector + halfvec | Metadata + 16-bit vector storage |
| **Vector Index** | FAISS (HNSW/IVF) | High-similarity search at scale |
| **Cache** | Redis | Search results, rate limiting, sessions |
| **Face Detection** | RetinaFace (InsightFace) | Accurate multi-face detection |
| **Embeddings** | InsightFace (ArcFace) | 512-d facial feature vectors |
| **Video Tracking** | DeepSORT | Temporal face tracking in videos |
| **Clustering** | HDBSCAN + UMAP | Quality-aware identity grouping |
| **File Monitoring** | Watchdog | Real-time file system events |
| **Containerization** | Docker + WSL2 | Cross-platform deployment |

---

## 🚀 Quick Start

### Prerequisites

- **Docker Desktop** (with WSL2 backend on Windows)
- **8GB+ RAM** recommended (16GB for large collections)
- **External storage** for face data (recommended: separate HDD/SSD)
- **Python 3.11+** (for local development only)

### 1. Clone the Repository

```bash
git clone https://github.com/theprawnorganisation/facetracker.git
cd facetracker
```

### 2. Configure Environment

Copy the example environment file and customize:

```bash
cp .env.example .env
```

Edit `.env` with your paths and preferences:

```ini
# Storage Paths
FACE_STORAGE_ROOT=Y:/faces           # External drive for embeddings/index
POSTGRES_DATA_PATH=./postgres_data   # Database persistence
APP_ROOT=C:/facetracker              # Application code location

# Drive Sources (JSON array)
DRIVE_SOURCES=[{"path": "C:/", "type": "local", "priority": 1},{"path": "Y:/Photos", "type": "local", "priority": 0}]

# Exclude sensitive/system paths
EXCLUDE_PATHS=["C:/Windows","C:/Program Files","Y:/faces"]

# Database Credentials
POSTGRES_PASSWORD=your_secure_password_here

# Search Settings
SEARCH_MIN_SIMILARITY=0.6            # Minimum match threshold (0-1)
SEARCH_TOP_K=100                     # Max results per query
```

### 3. Create Storage Directories

```bash
# Create the face storage root (on external drive or desired location)
mkdir -p Y:/faces/embeddings/live
mkdir -p Y:/faces/embeddings/staging
mkdir -p Y:/faces/media/thumbnails
mkdir -p Y:/faces/cache
mkdir -p Y:/faces/state
mkdir -p Y:/faces/logs
```

### 4. Start development containers

Use the [isolated cross-platform development setup](#isolated-container-development-on-windows-wsl-and-linux)
below. Production images are published by GitHub Actions; development uses a
separate explicit Compose file and locally built dev images.

This launches:
- **PostgreSQL** (pgvector-enabled) on port 5432
- **Redis** on port 6379
- **Face Tracker API** on port 5151 (configurable via `DASHBOARD_PORT`)

### 5. Verify Installation

Check service health:

```bash
curl http://localhost:5151/health
# Expected: {"status": "healthy"}
```

Access the interactive API documentation:

```
http://localhost:5151/docs
```

---

## 📖 Usage Guide

### API Endpoints

#### Search Operations

**Single-Face Search**
```bash
curl -X POST "http://localhost:5151/api/v1/search" \
  -F "file=@/path/to/query_image.jpg" \
  -F "threshold=0.6" \
  -F "top_k=50"
```

**Multi-Face Search**
```bash
curl -X POST "http://localhost:5151/api/v1/search/multi" \
  -F "file=@group_photo.jpg" \
  -F "face_indices=[0,2]" \
  -F "match_mode=all"
```

#### Identity Management

**List Identities**
```bash
curl "http://localhost:5151/api/v1/identity/"
```

**Assign Label to Cluster**
```bash
curl -X PUT "http://localhost:5151/api/v1/identity/cluster/{cluster_id}/label" \
  -H "Content-Type: application/json" \
  -d '{"label": "John Doe"}'
```

**Merge Two Clusters**
```bash
curl -X POST "http://localhost:5151/api/v1/identity/merge" \
  -H "Content-Type: application/json" \
  -d '{"source_cluster_id": "abc123", "target_cluster_id": "def456"}'
```

#### File Operations

**Get File Status**
```bash
curl "http://localhost:5151/api/v1/files/status?path=C:/Photos/vacation.jpg"
```

**Reprocess Failed Files**
```bash
curl -X POST "http://localhost:5151/api/v1/files/reprocess" \
  -H "Content-Type: application/json" \
  -d '{"paths": ["C:/Photos/failed1.jpg", "C:/Photos/failed2.jpg"]}'
```

#### System Statistics

**Get Dashboard Stats**
```bash
curl "http://localhost:5151/api/v1/stats/"
# Returns: total_images, total_faces, total_identities, index_status, etc.
```

### Indexing Workflow

The system automatically indexes files through this pipeline:

1. **Discovery**: Watchdog monitors configured drives for new/modified files
2. **Validation**: Checks format, size, exclusion rules
3. **Face Detection**: RetinaFace detects all faces with confidence scoring
4. **Quality Filtering**: Removes low-quality detections (blurry, too small)
5. **Embedding Extraction**: InsightFace generates 512-d vectors
6. **Staging**: Embeddings added to batch buffer (non-blocking)
7. **Merge**: Periodic atomic merge into live FAISS index
8. **Database Update**: Metadata persisted to PostgreSQL
9. **Thumbnail Generation**: 64x64 preview cached for display

### OneDrive Handling

For OneDrive-synced folders:

1. **Placeholder Detection**: Identifies online-only files via multiple methods
2. **Smart Download**: Downloads only during processing
3. **Processing**: Extracts faces, generates embeddings
4. **Revert**: Optionally reverts file to online-only state
5. **Retry Logic**: Handles transient network errors with exponential backoff

Configure in `.env`:
```ini
ONEDRIVE_ENABLED=true
ONEDRIVE_REVERT_VERIFY=true      # Revert after successful processing
ONEDRIVE_MULTI_DETECT=true       # Use multiple placeholder detection methods
ONEDRIVE_MAX_RETRIES=3
```

---

## 🛠️ Development

### Local Setup (Without Docker)

1. **Install System Dependencies** (Ubuntu/Debian):
```bash
sudo apt-get update && sudo apt-get install -y \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 \
    libxrender-dev libgomp1 gcc g++ \
    postgresql postgresql-contrib redis-server
```

2. **Create Python Virtual Environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install Python Dependencies**:
```bash
pip install -r requirements.txt
```

4. **Setup Database**:
```bash
# Create database and user
sudo -u postgres psql -c "CREATE DATABASE facetracker;"
sudo -u postgres psql -c "CREATE USER postgres WITH PASSWORD 'changeme';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE facetracker TO postgres;"

# Enable pgvector extension
psql -d facetracker -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

5. **Run the Application**:
```bash
uvicorn src.main:app --host 0.0.0.0 --port 5151 --reload
```

### Running Tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests only
pytest tests/integration/

# With coverage
pytest --cov=src --cov-report=html
```

### Code Structure

```
facetracker/
├── src/
│   ├── api/
│   │   └── routes/
│   │       ├── search.py        # Search endpoints
│   │       ├── identity.py      # Identity management
│   │       ├── files.py         # File operations
│   │       └── stats.py         # System statistics
│   ├── config.py                # Pydantic settings
│   ├── discovery/
│   │   ├── scanner.py           # Parallel file discovery
│   │   ├── watcher.py           # Real-time monitoring
│   │   ├── manifest.py          # File manifest tracking
│   │   └── onedrive.py          # OneDrive integration
│   ├── engine/
│   │   ├── detector.py          # Face detection (RetinaFace)
│   │   ├── embedder.py          # Embedding extraction (InsightFace)
│   │   ├── tracker.py           # Video tracking (DeepSORT)
│   │   └── quality.py           # Quality scoring
│   ├── identity/
│   │   ├── clusterer.py         # HDBSCAN clustering
│   │   ├── merger.py            # Cluster merging logic
│   │   └── verifier.py          # User verification queue
│   ├── pipeline/
│   │   ├── processor.py         # Main processing pipeline
│   │   └── thumbnail.py         # Thumbnail generation
│   ├── search/
│   │   ├── engine.py            # Search orchestration
│   │   └── ranker.py            # Result ranking
│   ├── storage/
│   │   ├── database.py          # SQLAlchemy models
│   │   ├── faiss_index.py       # Batched FAISS wrapper
│   │   └── thumbnail_cache.py   # Thumbnail caching
│   └── utils/
│       ├── logging.py           # Structured logging
│       └── image_ops.py         # Image utilities
├── tests/
│   ├── unit/
│   └── integration/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## ⚙️ Configuration Reference

### Key Environment Variables

| Category | Variable | Default | Description |
|----------|----------|---------|-------------|
| **Storage** | `FACE_STORAGE_ROOT` | `Y:/faces` | Root directory for embeddings, thumbnails, state |
| | `POSTGRES_DATA_PATH` | `./postgres_data` | PostgreSQL data persistence path |
| **Detection** | `MIN_FACE_AREA_PERCENT` | `5.0` | Minimum face area (% of image) |
| | `MIN_LAPLACIAN_VARIANCE` | `100.0` | Blur detection threshold |
| | `MIN_DETECTION_CONFIDENCE` | `0.5` | RetinaFace confidence threshold |
| **Indexing** | `FAISS_STAGING_SIZE` | `10000` | Vectors per batch before merge |
| | `FAISS_MERGE_TIMEOUT` | `300` | Seconds before forced merge |
| | `FAISS_INDEX_TYPE` | `HNSW64` | FAISS index type (HNSW64, IVF, etc.) |
| **Search** | `SEARCH_MIN_SIMILARITY` | `0.6` | Default minimum similarity threshold |
| | `SEARCH_TOP_K` | `100` | Default max results |
| **Video** | `VIDEO_TRACKING_FPS` | `3` | Frames per second for DeepSORT |
| | `DEEPSORT_MAX_AGE` | `30` | Frames to track lost face |
| **Clustering** | `CLUSTER_MIN_SIZE` | `5` | Minimum faces per cluster |
| | `AUTO_MERGE_THRESHOLD` | `0.75` | Similarity for auto-merge |
| | `USER_VERIFY_THRESHOLD` | `0.60` | Similarity for manual verification |
| **OneDrive** | `ONEDRIVE_ENABLED` | `true` | Enable OneDrive processing |
| | `ONEDRIVE_REVERT_VERIFY` | `true` | Revert to online-only after processing |
| **System** | `INDEX_WORKERS` | `2` | Parallel indexing threads |
| | `WATCH_POLL_INTERVAL` | `30` | File watcher poll interval (seconds) |
| | `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## 🔍 Troubleshooting

### Common Issues

**1. Container Won't Start**
```bash
# Check logs
docker-compose logs api

# Verify .env file exists and is valid
cat .env

# Ensure storage directories exist
ls -la $FACE_STORAGE_ROOT
```

**2. No Faces Detected**
- Lower `MIN_DETECTION_CONFIDENCE` (try 0.3)
- Reduce `MIN_FACE_AREA_PERCENT` (try 2.0)
- Check image format support
- Review logs for detection errors

**3. Search Returns Empty Results**
- Verify FAISS index loaded: check logs for "Loaded existing FAISS index"
- Confirm embeddings exist in database: `SELECT COUNT(*) FROM faces;`
- Lower `SEARCH_MIN_SIMILARITY` threshold

**4. OneDrive Files Not Processing**
- Ensure `ONEDRIVE_ENABLED=true`
- Check network connectivity
- Review OneDrive sync status
- Increase `ONEDRIVE_DOWNLOAD_TIMEOUT`

**5. High Memory Usage**
- Reduce `INDEX_QUEUE_SIZE`
- Lower `FAISS_STAGING_SIZE`
- Decrease video processing FPS
- Set container memory limit in `docker-compose.yml`

### Logs

View real-time logs:
```bash
docker-compose logs -f api
docker-compose logs -f postgres
docker-compose logs -f redis
```

---

## 📊 Performance Benchmarks

| Metric | Value | Hardware |
|--------|-------|----------|
| **Indexing Speed** | 10K+ faces/sec | Ryzen 9 5950X, 32GB RAM |
| **Search Latency (1M faces)** | <100ms | Same |
| **Search Latency (10M faces)** | <500ms | Same |
| **Storage per Face** | ~14KB | Includes embedding, metadata, thumbnail |
| **Memory Footprint** | ~4GB idle, ~8GB under load | Docker container |

---

## 🔒 Security Considerations

- **Local Only**: No external API calls, all processing on-premises
- **Database Passwords**: Change default `POSTGRES_PASSWORD` in production
- **CORS**: Currently allows all origins (`*`); restrict in production
- **File Access**: Ensure `FACE_STORAGE_ROOT` has appropriate permissions
- **PowerShell Commands**: OneDrive reversion uses subprocess; paths are sanitized

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 🙏 Acknowledgments

- **InsightFace**: For state-of-the-art face analysis models
- **FAISS**: Facebook AI Similarity Search library
- **DeepSORT**: Real-time multi-object tracking
- **FastAPI**: Modern async web framework
- **pgvector**: Vector similarity search in PostgreSQL

---

## 📬 Support

- **Issues**: GitHub Issues tab
- **Discussions**: GitHub Discussions for questions
- **Documentation**: See `/docs` folder for detailed guides

---

**Made with ❤️ by theprawnorganisation**

⭐ Give us a star if you find this useful!

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Isolated container development on Windows, WSL, and Linux

Use the explicit `compose.dev.yaml` on a development host. It creates a separate
`facetracker-dev` project with fresh named data volumes and loopback-only ports.
The existing deployment Compose file remains separate. Source reaches dev
containers through bind mounts; Python dependencies live in `/opt/venv`, and an
anonymous volume shields frontend `node_modules` from the host bind mount.

Run from this repository in PowerShell or a Linux shell:

~~~sh
# Prepare local settings/input without reading or overwriting an existing env file:
python -c "from pathlib import Path; Path('.env.dev').touch(exist_ok=True); Path('dev-input').mkdir(exist_ok=True)"
# Initial dev image build; repeat only when dependency manifests/system packages change:
docker compose --env-file .env.dev -f compose.dev.yaml build
# Explicit first-time acquisition of the development database image:
docker compose --env-file .env.dev -f compose.dev.yaml pull postgres
# Daily development:
docker compose --env-file .env.dev -f compose.dev.yaml up --no-build --pull never
~~~

Use `python3` if your Linux installation does not provide `python`.
Open the frontend at http://localhost:13000 and API at
http://localhost:18000. Put synthetic development input under `dev-input/`.
The supplied database password is a local development placeholder, not an account
credential; override `DEV_POSTGRES_PASSWORD` in `.env.dev` if needed.
Production `.env`, drive mounts, databases, and data volumes are not inherited.

Python polling reloaders restart application processes after source edits. Vite
uses polling and proxies API/WebSocket traffic over the development network.
This supports Windows and SMB mounts where filesystem events may be absent;
the bind-mount route requires the Docker host to access the checkout. Use the
sync overlay below when the mapped SMB drive is unavailable to the Docker host.
No source edit rebuilds an image or recreates a container.

After a dependency build, refresh **only anonymous dependency volumes**:

~~~sh
docker compose --env-file .env.dev -f compose.dev.yaml up --no-build --pull never --renew-anon-volumes
~~~

Named development database/model/data volumes are retained. Do not use
`down -v` to refresh dependencies. Dev image tags use `pull_policy: never`; a
missing image requires the explicit initial build above.

The dashboard backend is also available at http://localhost:18700. Dev input
is restricted to the dedicated directory; whole host drives are not mounted.
Model downloads, when needed by InsightFace, use the development model volume.
Both Dockerfile and Dockerfile.slim expose the same dev/production stage layout.

Production targets are named `production` and publish remotely through
`.github/workflows/docker-publish.yml` on the default branch or manual dispatch.
For an optional production download, run the explicit command:

~~~sh
docker pull ghcr.io/hongyime/facetracker/dashboard:latest
~~~

CI emits latest/default-branch and short-SHA tags (semver metadata on version
refs). It builds linux/amd64 with provenance/SBOM disabled and validates every
tagged manifest before retention. Any index, attestation, unknown manifest, or
registry error stops cleanup. Retention keeps the newest three tagged versions
plus latest, and three untagged versions; tagged history is bounded separately.
The package must grant this repository Actions admin access for deletion.
Do not switch these packages to multi-platform publication without revisiting
retention. Image sizes are unknown until CI reports compressed layer sizes;
computer-vision and ML dependencies can exceed the approximate 200 MB target.

Package visibility must be checked on the package itself. Treat 500 MB storage
and 1 GB/month transfer for private packages only as planning assumptions, and
verify current [GitHub billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-packages).
Downloads using GITHUB_TOKEN inside GitHub Actions do not count against transfer.

### Platform commands and optional Windows integrations

On Linux, macOS, or WSL, use `bash facetracker.sh build` for the initial dependency image build, then `bash facetracker.sh start` for daily development. Follow the development setup above to create your private `.env.dev` and input directory first. The wrapper uses `compose.dev.yaml`; `FACETRACKER_DEV_ENV` can select another private development environment file. `stop`, `logs`, and `status` are also available. Rebuild only after dependency manifests or system packages change; ordinary source edits reload through the mounted source. On Windows, the same documented `docker compose --env-file .env.dev -f compose.dev.yaml ...` commands work in PowerShell.

`facetracker.bat` is the legacy Windows operations menu. Its ordinary Start action uses existing local images; its separate Rebuild action is for dependency changes. OneDrive Files On-Demand eviction/auditing, Windows scheduled tasks, and Docker Desktop VHDX compaction remain optional Windows administration tools. Linux development does not require those operations, and the VHDX/OneDrive helpers have no equivalent operation on Linux.

### SMB and remote Docker hosts

When the Docker host cannot bind-mount the checkout, use Docker Compose 2.32.2+
and the explicit watch overlay after the initial dev build and database pull:

~~~sh
docker compose --env-file .env.dev -f compose.dev.yaml -f compose.watch.yaml up --no-build --pull never --watch
~~~

The first dev image includes only the ordinary application source after dependency
installation. Later edits reach the same containers through `action: sync`;
there are no rebuild rules. Python dependencies remain in `/opt/venv` and Node
dependencies stay in the image because dependency folders/manifests are excluded
from synchronization. The overlay removes the source bind mounts and anonymous
dependency volume, so the Docker host does not need access to the SMB drive.

This mode uses an empty, dedicated `dev_input` volume instead of mounting host
input data. Database, storage and model volumes remain separate from production.
The bind-mount mode above remains available for host-accessible synthetic input.
Private files are excluded from build and watch contexts, including mixed-case
environment, credential and key filenames.

After stopping the watch command, remove dev containers and networks while
retaining the database/model/input volumes:

~~~sh
docker compose --env-file .env.dev -f compose.dev.yaml -f compose.watch.yaml down --remove-orphans
~~~

For disposable tests, use a distinct `-p facetracker-smoke-dev` on every command
and add `--volumes` to that project's final `down`. Keep reusable dev images;
rebuild them only when dependency manifests or system packages change.
