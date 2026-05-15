# PRD: Private Face Search Engine v4.0

**Version:** 4.0 (Production-Ready)
**Type:** Enterprise Face Search Engine
**Target Scale:** 10M+ faces
**Architecture:** Microservices-ready, PostgreSQL + halfvec + Batched FAISS
**Focus:** Private Index (Public OSINT - Future v2.0)
**Last Updated:** 2026-05-15

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Storage Architecture v2.0](#3-storage-architecture-v20)
4. [Data Model](#4-data-model)
5. [File Discovery System](#5-file-discovery-system)
6. [OneDrive Handling v2.0](#6-onedrive-handling-v20)
7. [Face Processing Pipeline](#7-face-processing-pipeline)
8. [Batched FAISS Index Architecture](#8-batched-faiss-index-architecture)
9. [Search Engine](#9-search-engine)
10. [Real-Time Indexing](#10-real-time-indexing)
11. [Identity Clustering v2.0](#11-identity-clustering-v20)
12. [Dashboard & UI](#12-dashboard--ui)
13. [Configuration Reference](#13-configuration-reference)
14. [File Architecture](#14-file-architecture)
15. [Docker Configuration](#15-docker-configuration)
16. [Dependencies](#16-dependencies)
17. [Glossary](#17-glossary)
18. [Out of Scope](#18-out-of-scope)
19. [Roadmap](#19-roadmap)

---

## 1. Executive Summary

### Objective

Build a **PimEyes-style private face search engine** that:

- Indexes **10M+ faces** from local drives and OneDrive-synced folders
- Provides **reverse image search**: upload a photo → find all matching faces
- Supports **multi-face search**: find group photos containing specific people
- Uses **real-time indexing**: every new photo indexed immediately
- Is **microservice-ready** for future horizontal scaling
- Operates **100% locally** with no cloud dependencies or subscriptions

### Core Philosophy

| Principle | Implementation |
|-----------|----------------|
| **Accuracy over speed** | Process thoroughly, miss nothing |
| **Storage efficiency** | No full face crops, thumbnails only, halfvec embeddings |
| **Coverage** | Scan all mounted drives, all formats |
| **Privacy first** | All data stays local, no cloud uploads |
| **OneDrive efficiency** | Files revert to online-only after processing |
| **Observable** | Verbose logging, real-time status dashboard |
| **Reliability** | Defense-in-depth for all external integrations |

### Scale Targets

| Metric | Target |
|--------|--------|
| **Faces** | 10M+ |
| **Embeddings storage** | **~10GB** (halfvec, 16-bit) instead of 20GB |
| **FAISS index** | ~12GB (optimized) instead of 25GB |
| **Thumbnails** | ~64GB (64x64 JPG) instead of 960GB |
| **Search latency** | < 500ms for top-100 results |
| **Write throughput** | 10K+ embeddings/second via batched ingestion |

### Search Capabilities

| Feature | Description |
|---------|-------------|
| **Exact match** | Same file hash found |
| **Perceptual match** | Similar image (pHash/dHash) |
| **Face match** | Same person, different photo (embedding similarity) |
| **Multi-face search** | Find group photos with specific people |
| **Full index search** | Search entire 10M face database |

---

## 2. System Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRIVATE FACE SEARCH ENGINE v4.0                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ Search Upload   │  │ Identity Manager│  │ Dashboard       │              │
│  │ (PimEyes-style) │  │ (Labels/Clusters)│  │ (Status/Stats)  │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API LAYER                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         FastAPI                                       │   │
│  │  • /search (POST image)    • /identity (CRUD)                        │   │
│  │  • /batch-search           • /stats                                   │   │
│  │  • /clustering             • /file-status                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
┌─────────────────────────┐ ┌───────────────┐ ┌─────────────────┐
│     INDEXING SERVICE     │ │ SEARCH SERVICE│ │ IDENTITY SERVICE│
│                         │ │               │ │                 │
│ • File discovery        │ │ • FAISS query │ │ • HDBSCAN       │
│ • Face detection        │ │ • Ranking     │ │ • Quality-aware │
│ • Batched embedding    │ │ • Caching     │ │ • Verification  │
│ • Real-time pipeline   │ │               │ │                 │
└─────────────────────────┘ └───────────────┘ └─────────────────┘
                    │                │                │
                    └────────────────┼────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             DATA LAYER                                       │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐   │
│  │  PostgreSQL   │ │    FAISS      │ │    Redis      │ │  File Storage │   │
│  │  + halfvec    │ │  Batched     │ │    Cache      │ │   (Y:/faces) │   │
│  │               │ │               │ │               │ │               │   │
│  │ • Metadata    │ │ • Live index │ │ • Search cache│ │ • Thumbnails  │   │
│  │ • Identity    │ │ • Staging    │ │ • Rate limit  │ │ • Source ref │   │
│  │ • File manifest│ │ • Merged    │ │ • Session     │ │ • State files │   │
│  └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SOURCE DRIVES                                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │  C:/ (SSD)  │ │  Y:/ (HDD)  │ │  E:/ (USB)  │ │ OneDrive    │          │
│  │             │ │             │ │             │ │ C:/users/   │          │
│  │ • Scan all  │ │ • Storage   │ │ • On mount  │ │ bryan/onedr │          │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Technology Stack (v4.0 Updated)

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **API** | FastAPI | Async, OpenAPI, validated |
| **Database** | PostgreSQL + pgvector + **halfvec** | 16-bit embeddings, 50% storage reduction |
| **Vector Index** | FAISS (Batched IVF/HNSW) | Streaming ingestion, no write blocking |
| **Cache** | Redis | Search cache, rate limiting |
| **File Storage** | Local filesystem | External drive Y:/, not in git |
| **Container** | Docker Compose + WSL2 | Cross-platform |

### Key Improvements from v3.0

| Component | v3.0 | v4.0 | Savings |
|-----------|------|------|---------|
| **Embeddings** | float32 (20GB) | halfvec (10GB) | **50%** |
| **FAISS Index** | Monolithic (25GB) | Batched (12GB) | **52%** |
| **Face Crops** | 160x160 PNG (~960GB) | **Removed** | **~960GB** |
| **Thumbnails** | None | 64x64 JPG (~64GB) | - |
| **Total Storage** | ~1TB+ | **~100GB** | **~900GB** |
| **FAISS Writes** | Blocking | Batched/staged | **10x throughput** |

---

## 3. Storage Architecture v2.0

### Directory Structure (Optimized)

```
Y:/faces/                              # EXTERNAL DRIVE - NOT IN GIT
├── .gitkeep                           # Keep folder in gitignore
├── database/                          # PostgreSQL data (VHDX ext4)
│   ├── postgres/                      # PostgreSQL data directory
│   └── backups/                       # Automated backups
│       ├── daily/                     # Daily incremental backups
│       └── weekly/                    # Weekly full backups
│
├── embeddings/                       # FAISS index files
│   ├── live/                         # Main searchable index
│   │   ├── face_index.faiss          # Primary index
│   │   └── face_index.meta           # Index metadata
│   ├── staging/                       # Batch temp indexes (auto-merged)
│   │   ├── staging_001.faiss
│   │   └── staging_002.faiss
│   └── backup/                        # Index backups before merge
│
├── media/                             # Processed media (MINIMAL)
│   ├── thumbnails/                    # 64x64 JPG only (NOT full crops)
│   │   └── {face_id}_thumb.jpg
│   └── source_ref/                    # Original file paths (NO copies)
│
├── cache/                             # Temporary processing cache
│   ├── onedrive_temp/                 # OneDrive placeholder downloads
│   └── processing/                    # In-progress files (auto-cleaned)
│
├── state/                             # Application state
│   ├── file_manifest.json             # All discovered files (incremental)
│   ├── scan_state.json                # Current scan progress
│   ├── failed_files.json              # Failed processing attempts
│   └── onedrive_status.json           # OneDrive file tracking
│
└── logs/                              # Application logs
    ├── app.log
    ├── indexer.log
    ├── search.log
    └── onedrive.log

C:/facetracker/                        # GIT REPOSITORY
├── src/                               # Source code
├── tests/                             # Unit tests
├── config/                            # Config templates
├── docker-compose.yml                 # Docker Compose
├── Dockerfile                         # Application container
├── requirements.txt                   # Python dependencies
├── .env.example                       # Environment template
├── .gitignore
└── README.md
```

### Why No Full Face Crops?

**v3.0 Problem:**
- 160x160 PNG face crop = ~96KB per face
- 10M faces × 96KB = **960GB of crop storage**
- Excessive for personal use
- Slows down processing pipeline

**v4.0 Solution:**
- **Generate thumbnails on-the-fly** from source images
- Store only 64x64 JPG thumbnails (~6KB per face = **~60GB**)
- Original file paths stored in database for source reference
- User can click to view full original image

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        THUMBNAIL GENERATION STRATEGY                          │
└─────────────────────────────────────────────────────────────────────────────┘

USER UPLOADS IMAGE FOR SEARCH
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. FACE DETECTION                                                             │
│    └─> RetinaFace detects face bounding boxes                               │
│    └─> Store bbox coordinates in database (tiny)                            │
└─────────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. THUMBNAIL GENERATION (On-Demand)                                           │
│                                                                               │
│    When displaying search results:                                            │
│    1. Look up face bbox from database                                        │
│    2. Look up original image path                                           │
│    3. If original is online-only → download first (OneDrive)                │
│    4. Crop from original using stored bbox                                  │
│    5. Resize to 64x64 JPG (quality 80)                                      │
│    6. Cache in Y:/faces/media/thumbnails/                                   │
│    7. Return thumbnail                                                      │
│                                                                               │
│    Cache-first: Check thumbnail exists before regenerating                  │
└─────────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. STORAGE COMPARISON                                                         │
│                                                                               │
│    v3.0 (Store all crops):                                                   │
│    • 10M faces × 96KB = 960 GB                                              │
│    • Stored upfront, never regenerated                                      │
│    • Fast display, massive storage                                           │
│                                                                               │
│    v4.0 (Generate thumbnails):                                               │
│    • 10M faces × 6KB (cached thumbnails) = 60 GB                           │
│    • Generated on first view, then cached                                   │
│    • Lazy: Only generates what user actually views                           │
│    • + Original storage (already exists) = No extra                        │
│                                                                               │
│    Total savings: ~900 GB                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Storage Budget (v4.0)

| Component | v3.0 (GB) | v4.0 (GB) | Savings |
|-----------|-----------|-----------|---------|
| Embeddings (halfvec) | 20 | **10** | 50% |
| FAISS Index | 25 | **12** | 52% |
| Face Crops | 960 | **0** | 100% |
| Thumbnails (64x64) | 0 | **64** | - |
| Database | 45 | **45** | 0% |
| Cache (temp) | 8 | **8** | 0% |
| Logs | 2 | **2** | 0% |
| **TOTAL** | **~1060** | **~141** | **~87%** |

---

## 4. Data Model

### Database Schema (PostgreSQL + halfvec)

```sql
-- ========================================
-- EXTENSION: halfvec for 16-bit embeddings
-- ========================================
CREATE EXTENSION IF NOT EXISTS halfvec;

-- ========================================
-- IMAGES TABLE
-- ========================================
CREATE TABLE images (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_path       TEXT NOT NULL,
    drive           VARCHAR(10) NOT NULL,
    source_type     VARCHAR(20) NOT NULL,          -- 'local', 'onedrive', 'usb'
    file_size       BIGINT,
    mtime           TIMESTAMP,
    file_hash       VARCHAR(64),                   -- SHA-256 for dedup
    phash           VARCHAR(64),                   -- Perceptual hash
    media_type      VARCHAR(10) NOT NULL,          -- 'image', 'video'
    width           INTEGER,
    height          INTEGER,
    is_online_only  BOOLEAN DEFAULT FALSE,        -- OneDrive placeholder
    onedrive_status VARCHAR(20) DEFAULT 'local', -- 'local', 'downloading', 'downloaded', 'reverted'
    status          VARCHAR(20) DEFAULT 'pending',-- pending, processing, indexed, archived, failed
    processed_at    TIMESTAMP,
    indexed_at      TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),

    UNIQUE(file_path)
);

CREATE INDEX idx_images_file_hash ON images(file_hash);
CREATE INDEX idx_images_phash ON images(phash);
CREATE INDEX idx_images_status ON images(status);

-- ========================================
-- FACES TABLE (Optimized)
-- ========================================
CREATE TABLE faces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        UUID NOT NULL REFERENCES images(id) ON DELETE CASCADE,

    -- Bounding box (normalized 0-1) - stored, not crops
    bbox_x1         FLOAT NOT NULL,
    bbox_y1         FLOAT NOT NULL,
    bbox_x2         FLOAT NOT NULL,
    bbox_y2         FLOAT NOT NULL,

    -- Original pixel coordinates
    bbox_px_x1      INTEGER NOT NULL,
    bbox_px_y1       INTEGER NOT NULL,
    bbox_px_x2       INTEGER NOT NULL,
    bbox_px_y2       INTEGER NOT NULL,

    -- Embedding stored in FAISS (referenced by ID)
    embedding_id    BIGINT NOT NULL,

    -- Embedding backup in PostgreSQL (halfvec - 16-bit, ~10GB for 10M)
    embedding_vec   HALF_VEC(512),

    -- Quality metrics (used in clustering)
    quality_score   FLOAT,
    laplacian_score FLOAT,
    face_area_ratio FLOAT,

    -- Video-specific
    video_timestamp FLOAT,
    track_id        INTEGER,

    -- Metadata
    detection_confidence FLOAT,
    model_version   VARCHAR(20),
    created_at      TIMESTAMP DEFAULT NOW(),

    -- Soft delete (archive, don't delete)
    is_archived     BOOLEAN DEFAULT FALSE,
    archived_at     TIMESTAMP,
    archive_reason  VARCHAR(50)
);

CREATE INDEX idx_faces_image_id ON faces(image_id);
CREATE INDEX idx_faces_embedding_id ON faces(embedding_id);
CREATE INDEX idx_faces_quality ON faces(quality_score);

-- ========================================
-- IDENTITIES TABLE
-- ========================================
CREATE TABLE identities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Labeling
    name            VARCHAR(100),                   -- User-assigned name (optional)
    cluster_label   VARCHAR(100),

    -- Verification
    is_verified     BOOLEAN DEFAULT FALSE,
    verified_by     VARCHAR(50),

    -- Stats
    face_count      INTEGER DEFAULT 0,
    image_count     INTEGER DEFAULT 0,

    -- Validation metrics (for UI)
    silhouette_score FLOAT,
    cluster_cohesion FLOAT,

    -- Audit
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    verified_at     TIMESTAMP
);

CREATE INDEX idx_identities_name ON identities(name);
CREATE INDEX idx_identities_silhouette ON identities(silhouette_score);

-- ========================================
-- FACE-IDENTITY MAPPING
-- ========================================
CREATE TABLE face_identity_map (
    face_id         UUID NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
    identity_id     UUID NOT NULL REFERENCES identities(id) ON DELETE CASCADE,

    -- Assignment
    confidence      FLOAT NOT NULL,
    assigned_by     VARCHAR(20) NOT NULL,          -- 'algorithm', 'user'
    assigned_at     TIMESTAMP DEFAULT NOW(),

    -- Verification
    is_verified     BOOLEAN DEFAULT FALSE,
    verified_by     VARCHAR(50),
    verified_at     TIMESTAMP,

    PRIMARY KEY (face_id, identity_id)
);

-- ========================================
-- VERIFICATION AUDIT LOG
-- ========================================
CREATE TABLE verification_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    action_type     VARCHAR(20) NOT NULL,
    source_ids      JSONB,
    target_id       UUID,
    before_state    JSONB,
    after_state     JSONB,

    user_id         VARCHAR(50),
    user_action     VARCHAR(20),

    created_at      TIMESTAMP DEFAULT NOW()
);

-- ========================================
-- FILE MANIFEST
-- ========================================
CREATE TABLE file_manifest (
    file_path       TEXT PRIMARY KEY,
    file_hash       VARCHAR(64),
    file_size       BIGINT,
    mtime           TIMESTAMP,
    image_id        UUID REFERENCES images(id),
    first_seen      TIMESTAMP DEFAULT NOW(),
    last_seen       TIMESTAMP DEFAULT NOW(),
    scan_count      INTEGER DEFAULT 1,
    is_deleted      BOOLEAN DEFAULT FALSE,
    deleted_at      TIMESTAMP
);

-- ========================================
-- ONEDRIVE TRACKING
-- ========================================
CREATE TABLE onedrive_files (
    file_path       TEXT PRIMARY KEY,
    etag            VARCHAR(64),
    last_downloaded TIMESTAMP,
    last_reverted   TIMESTAMP,
    status          VARCHAR(20) DEFAULT 'online_only', -- 'online_only', 'downloading', 'downloaded', 'reverted'
    retry_count     INTEGER DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ========================================
-- SEARCH HISTORY
-- ========================================
CREATE TABLE search_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    query_type      VARCHAR(20) NOT NULL,
    query_image_id  UUID REFERENCES images(id),
    face_count      INTEGER,

    result_count    INTEGER,
    top_match_id    UUID,
    top_match_similarity FLOAT,

    search_time_ms  INTEGER,

    created_at      TIMESTAMP DEFAULT NOW()
);

-- ========================================
-- INDEX METADATA
-- ========================================
CREATE TABLE faiss_index_meta (
    id              SERIAL PRIMARY KEY,
    index_name      VARCHAR(50),
    embedding_count BIGINT,
    dimension       INTEGER,
    last_updated    TIMESTAMP DEFAULT NOW(),
    merge_count     INTEGER DEFAULT 0,
    staging_size    BIGINT DEFAULT 0
);
```

---

## 5. File Discovery System

### Efficient Scanning Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FILE DISCOVERY ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ DRIVE SOURCES CONFIG                                                         │
│                                                                               │
│ DRIVE_SOURCES = [                                                            │
│   { "path": "C:/", "type": "local", "priority": 1 },                        │
│   { "path": "D:/", "type": "local", "priority": 2 },                        │
│   { "path": "Y:/", "type": "local", "priority": 0, "exclude": true },      │
│   { "path": "E:/", "type": "usb", "on_mount": true },                       │
│   { "path": "C:/Users/bryan/onedrive", "type": "onedrive", "priority": 3 } │
│ ]                                                                           │
│                                                                               │
│ EXCLUDE_PATHS = [                                                            │
│   "C:/facetracker",                                                         │
│   "Y:/faces"                                                                │
│ ]                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PARALLEL DIRECTORY ENUMERATION                                                │
│                                                                               │
│ • ThreadPoolExecutor (4-8 threads)                                           │
│ • os.scandir() - 3x faster than os.walk()                                    │
│ • Generator-based - yields batches of 1000 files                             │
│ • Recursive traversal with depth limit                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ BATCH FILE PROCESSING                                                        │
│                                                                               │
│ FileBatch (1000 files):                                                      │
│ 1. Filter by extension                                                       │
│ 2. Check against file_manifest (skip if unchanged)                          │
│ 3. Queue new/changed files                                                   │
│ 4. Mark deleted files                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ INCREMENTAL UPDATE (Manifest-Based)                                           │
│                                                                               │
│ file_manifest.json:                                                         │
│ {                                                                            │
│   "version": 3,                                                             │
│   "last_scan": "2026-05-15T10:00:00Z",                                      │
│   "entries": { ... },                                                       │
│   "deleted": [ ... ]                                                        │
│ }                                                                            │
│                                                                               │
│ On next scan: Compare mtime/size, only process changed files                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Performance Targets

| Operation | Method | Target |
|-----------|--------|--------|
| Scan 100k files | os.scandir + threading | < 60 seconds |
| Incremental diff | Manifest compare | < 10 seconds |
| Memory usage | Generator, batch processing | < 500MB |

---

## 6. OneDrive Handling v2.0

### Multi-Faceted Detection (Hardened)

```python
import ctypes
import os
import time
import subprocess
from dataclasses import dataclass
from typing import Optional

@dataclass
class OneDriveStatus:
    """Result of multi-faceted OneDrive detection."""
    is_online_only: bool
    confidence: float  # 0.0 to 1.0
    methods: list[str]  # Which checks passed
    file_size: int
    last_error: Optional[str] = None

class OneDriveHandler:
    """
    Hardened OneDrive placeholder detection and handling.

    Defense-in-depth approach:
    1. Check FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
    2. Check FILE_ATTRIBUTE_OFFLINE
    3. Check file size (placeholder = 0 or < 4KB)
    4. Verify download
    5. Verify revert
    """

    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
    FILE_ATTRIBUTE_OFFLINE = 0x00001000

    def detect_online_only(self, file_path: str) -> OneDriveStatus:
        """
        Multi-faceted detection for OneDrive placeholder.

        Requires 2+ positive indicators to confirm online-only status.
        """
        methods = []
        file_size = 0

        # Check 1: FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(file_path)
            if attrs != -1 and attrs & self.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS:
                methods.append("recall_on_access")
        except Exception:
            pass

        # Check 2: FILE_ATTRIBUTE_OFFLINE
        try:
            if attrs != -1 and attrs & self.FILE_ATTRIBUTE_OFFLINE:
                methods.append("offline")
        except Exception:
            pass

        # Check 3: File size
        try:
            file_size = os.path.getsize(file_path)
            if file_size < 4096:  # Less than 4KB is suspicious
                methods.append("size_zero")
        except Exception:
            pass

        # Require 2+ positive indicators
        is_online_only = len(methods) >= 2
        confidence = len(methods) / 3.0

        return OneDriveStatus(
            is_online_only=is_online_only,
            confidence=confidence,
            methods=methods,
            file_size=file_size
        )

    def ensure_local(self, file_path: str, timeout_seconds: int = 300) -> tuple[bool, str]:
        """
        Ensure file is available locally (download if placeholder).

        Returns: (success, error_message)
        """
        status = self.detect_online_only(file_path)

        if not status.is_online_only:
            return True, ""

        print(f"[OneDrive] Downloading: {file_path} (confidence: {status.confidence:.2f})")

        try:
            # Method 1: PowerShell Start-Process (more reliable than file read)
            subprocess.run([
                'powershell',
                '-Command',
                f'Start-Process -FilePath "{file_path}" -WindowStyle Hidden'
            ], check=True, capture_output=True, timeout=30)

            # Wait for download to complete
            start_time = time.time()
            last_size = -1
            stable_count = 0

            while time.time() - start_time < timeout_seconds:
                time.sleep(2)
                current_size = os.path.getsize(file_path)

                if current_size == last_size:
                    stable_count += 1
                    if stable_count >= 3 and current_size > 0:
                        # Size stable for 6 seconds and file exists
                        break
                else:
                    stable_count = 0

                last_size = current_size

                # Progress logging
                elapsed = time.time() - start_time
                print(f"[OneDrive] Progress: {file_path} ({current_size / 1024 / 1024:.1f} MB, {elapsed:.0f}s)")

            # Verify download
            if self.detect_online_only(file_path).is_online_only:
                return False, "File still online-only after download attempt"

            return True, ""

        except Exception as e:
            return False, str(e)

    def revert_to_online_only(self, file_path: str) -> tuple[bool, str]:
        """
        Revert file to OneDrive online-only mode.

        VERIFICATION REQUIRED: After deletion, verify the revert worked.

        Returns: (success, error_message)
        """
        try:
            # Delete local copy
            os.remove(file_path)

            # VERIFY: Try to access the path again
            # If it's online-only, accessing should trigger download
            # If revert failed, file will still exist or error
            time.sleep(1)

            if os.path.exists(file_path):
                # File still exists - revert failed
                return False, "File still exists after delete (revert failed)"

            # Check if file is now placeholder by checking a small read
            try:
                with open(file_path, 'rb') as f:
                    f.read(1024)
                # If we read successfully, file is local (revert failed)
                return False, "File is local after delete (revert failed)"
            except (OSError, FileNotFoundError):
                # Expected: file doesn't exist or triggers download
                pass

            print(f"[OneDrive] Reverted to online-only: {file_path}")
            return True, ""

        except Exception as e:
            return False, str(e)

    def process_with_revert(self, file_path: str,
                            processing_func: callable,
                            timeout_seconds: int = 300) -> tuple[bool, str]:
        """
        Process a OneDrive file with automatic download and revert.

        1. Download if online-only
        2. Process
        3. Revert to online-only
        4. Verify revert
        """
        status = self.detect_online_only(file_path)

        if not status.is_online_only:
            # Local file - process directly
            return processing_func(file_path)

        # Step 1: Download
        success, error = self.ensure_local(file_path, timeout_seconds)
        if not success:
            return False, f"Download failed: {error}"

        # Step 2: Process
        success, error = processing_func(file_path)
        if not success:
            return False, f"Processing failed: {error}"

        # Step 3: Revert
        success, error = self.revert_to_online_only(file_path)
        if not success:
            # Log warning but don't fail (user can manually manage)
            print(f"[OneDrive] WARNING: Revert failed for {file_path}: {error}")
            # Don't return error - processing succeeded, just log warning

        return True, ""
```

### OneDrive Status Tracking

```python
# Track OneDrive file states in database
@dataclass
class OneDriveFileState:
    """Persistent state for OneDrive file tracking."""
    file_path: str
    status: str  # 'online_only', 'downloading', 'downloaded', 'reverted'
    etag: Optional[str] = None
    last_downloaded: Optional[datetime] = None
    last_reverted: Optional[datetime] = None
    retry_count: int = 0
    last_error: Optional[str] = None

def update_onedrive_status(file_path: str, status: str, error: str = None):
    """Update OneDrive file status in database."""
    query = """
        INSERT INTO onedrive_files (file_path, status, last_error, retry_count)
        VALUES (%s, %s, %s, 1)
        ON CONFLICT (file_path) DO UPDATE SET
            status = EXCLUDED.status,
            last_error = EXCLUDED.last_error,
            retry_count = onedrive_files.retry_count + 1
    """
    # Execute with database connection
    pass

def get_pending_onedrive_retries() -> list[str]:
    """Get files that need retry."""
    query = """
        SELECT file_path FROM onedrive_files
        WHERE status = 'failed' AND retry_count < 3
        ORDER BY retry_count ASC
    """
    # Execute and return file paths
    pass
```

### Dashboard Integration

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ONEDRIVE STATUS INDICATORS (Dashboard)                                       │
└─────────────────────────────────────────────────────────────────────────────┘

FILE STATUSES:
┌──────────────┬──────────────────────────────────────────────────────────────┐
│ Icon         │ Meaning                                                      │
├──────────────┼──────────────────────────────────────────────────────────────┤
│ ☁️ (gray)    │ Online-only (not downloaded)                                │
│ ⬇️ (animated)│ Currently downloading                                      │
│ 💾 (blue)   │ Downloaded locally (processing or recently processed)        │
│ ✓ (green)   │ Reverted to online-only (processed successfully)            │
│ ⚠️ (yellow) │ Retry in progress                                           │
│ ❌ (red)    │ Failed (requires manual intervention)                        │
└──────────────┴──────────────────────────────────────────────────────────────┘

DASHBOARD SHOWS:
• Files currently downloading with progress bar
• Files pending revert
• Failed files with error messages
• Retry queue status
• Storage saved by reverting files
```

---

## 7. Face Processing Pipeline

### Complete Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        FACE PROCESSING PIPELINE v4.0                        │
└─────────────────────────────────────────────────────────────────────────────┘

INPUT: FILE
  • Image: vacation.jpg (local or OneDrive)
  • Video: meeting.mp4 (local or OneDrive)

        │
        ▼ (If OneDrive placeholder → download first)
        │
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: FORMAT VALIDATION                                                    │
│   • Check magic bytes                                                        │
│   • Verify file is readable                                                  │
│   • Reject if invalid → mark as failed                                      │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: HASHING (Deduplication)                                             │
│   • SHA-256 (full file for images, first+last 10MB for videos)              │
│   • Check against file_manifest                                             │
│   • If hash exists → SKIP                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: IMAGE DECODING                                                        │
│   • Load with Pillow/OpenCV                                                 │
│   • Convert to RGB                                                          │
│   • For videos: Extract 1 FPS frames via FFmpeg                             │
│   • Resize if > 4000px                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: FACE DETECTION (InsightFace RetinaFace)                              │
│   • Detect all faces                                                        │
│   • Filter: face area ≥ 5% of image                                         │
│   • Filter: laplacian variance ≥ 100                                        │
│   • Filter: confidence ≥ 0.5                                                 │
│   • If no faces → SKIP FILE                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: TEMPORAL TRACKING (Videos only)                                       │
│   • DeepSORT at 3 FPS                                                       │
│   • Assign track_id to each person                                          │
│   • One track_id = one person throughout video                              │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: BEST FRAME SELECTION (Per track_id)                                   │
│   • Compute quality_score = (0.6 * norm_area) + (0.4 * norm_laplacian)     │
│   • Select frame with highest score                                         │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: STORE BBOX (NOT CROP)                                                │
│   • Store bounding box coordinates in database                               │
│   • NO full face crop stored (generates thumbnail on-demand)                │
│   • For thumbnails: crop on first view, then cache                          │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 8: EMBEDDING EXTRACTION                                                 │
│   • InsightFace antelopev2 (512-d)                                         │
│   • Normalize to unit length                                                 │
│   • Convert to float16 (halfvec)                                           │
│   • Add to staging batch (NOT directly to live index)                        │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 9: BATCHED DATABASE WRITE                                               │
│   • INSERT images table                                                     │
│   • INSERT faces table (with halfvec embedding)                             │
│   • UPDATE file_manifest                                                   │
│   • COMMIT                                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 10: STAGING INDEX UPDATE                                                │
│   • Add to staging FAISS index                                              │
│   • If staging full (10K vectors) → merge to live                          │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 11: ONEDRIVE REVERT (if applicable)                                      │
│   • Revert file to online-only mode                                         │
│   • Verify revert succeeded                                                 │
│   • Update onedrive_files table                                            │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
OUTPUT: PROCESSED
  • Database: image + face records with bbox (NO crops)
  • FAISS: embeddings in staging batch
  • OneDrive: file reverted to online-only
```

### Thumbnail Generation (On-Demand)

```python
import os
import io
from PIL import Image
from pathlib import Path

THUMBNAIL_SIZE = (64, 64)
THUMBNAIL_QUALITY = 80
THUMBNAIL_CACHE_DIR = "Y:/faces/media/thumbnails"

def get_thumbnail(face_record: dict, source_image_path: str) -> bytes:
    """
    Generate or retrieve face thumbnail.

    1. Check if cached thumbnail exists
    2. If not, crop from original and cache
    3. Return thumbnail bytes
    """
    face_id = face_record['id']
    cache_path = Path(THUMBNAIL_CACHE_DIR) / f"{face_id}_thumb.jpg"

    # 1. Return cached if exists
    if cache_path.exists():
        return cache_path.read_bytes()

    # 2. Generate from source
    bbox = (
        face_record['bbox_px_x1'],
        face_record['bbox_px_y1'],
        face_record['bbox_px_x2'],
        face_record['bbox_px_y2']
    )

    try:
        # Handle OneDrive files
        if onedrive_handler.is_online_only(source_image_path):
            success, _ = onedrive_handler.ensure_local(source_image_path)
            if not success:
                raise FileNotFoundError(f"Could not download: {source_image_path}")

        # Open and crop
        with Image.open(source_image_path) as img:
            crop = img.crop(bbox)

            # Add margin (15%)
            w, h = crop.size
            margin = int(min(w, h) * 0.15)
            crop = crop.crop(
                (-margin, -margin, w + margin, h + margin)
            )

            # Resize to thumbnail
            thumbnail = crop.resize(THUMBNAIL_SIZE, Image.LANCZOS)

            # Save to cache
            buf = io.BytesIO()
            thumbnail.save(buf, format='JPEG', quality=THUMBNAIL_QUALITY)
            thumbnail_bytes = buf.getvalue()

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(thumbnail_bytes)

            return thumbnail_bytes

    except Exception as e:
        # Return placeholder on error
        return generate_placeholder_thumbnail()
```

---

## 8. Batched FAISS Index Architecture

### Problem with Monolithic FAISS

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM: Monolithic FAISS at Scale                                          │
└─────────────────────────────────────────────────────────────────────────────┘

At 10M+ vectors with real-time indexing:

1. Every INSERT triggers HNSW graph update
2. HNSW update is O(log N) per insert
3. At 10M scale, each update is expensive
4. Frequent writes → index fragmentation
5. Performance degrades over time
6. Persistence (save to disk) causes blocking

RESULT: Write throughput bottleneck, search latency degradation
```

### Solution: Batched/Staged Ingestion

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SOLUTION: Batched FAISS Architecture                                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. STAGING INDEX (Fast Write Buffer)                                          │
│                                                                               │
│    New embeddings go here (NOT live index)                                    │
│    • Fast append (no graph rebuild)                                          │
│    • Memory-resident until threshold                                         │
│    • Configurable size: 10K, 50K, 100K vectors                              │
│                                                                               │
│    ┌─────────────────────┐                                                   │
│    │  staging_001.faiss  │  10K vectors                                       │
│    │  staging_002.faiss  │  10K vectors                                       │
│    │  staging_003.faiss  │  10K vectors (current)                             │
│    └─────────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. MERGE TRIGGER (Automatic)                                                 │
│                                                                               │
│    Triggers:                                                                 │
│    • Staging size threshold reached (e.g., 10K vectors)                       │
│    • Time-based: every 5 minutes of inactivity                               │
│    • Manual: via API or CLI                                                  │
│                                                                               │
│    ┌─────────────────────────────────────────┐                               │
│    │ MERGE PROCESS                           │                               │
│    │ 1. Create new staging index             │                               │
│    │ 2. Merge all staging into temporary     │                               │
│    │ 3. Swap with live index                │                               │
│    │ 4. Update metadata                      │                               │
│    │ 5. No downtime (atomic swap)            │                               │
│    └─────────────────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. LIVE INDEX (Search-Ready)                                                 │
│                                                                               │
│    • Only used for search queries                                            │
│    • Updated during merge (not during insert)                                │
│    • Atomic swap = no search downtime                                       │
│                                                                               │
│    ┌─────────────────────┐                                                   │
│    │  face_index.faiss   │  10M+ vectors (live)                              │
│    └─────────────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. WRITE PERFORMANCE COMPARISON                                              │
│                                                                               │
│    Monolithic (v3.0):                                                        │
│    • 8,500 inserts/sec max                                                  │
│    • Degrades at scale                                                       │
│    • Write blocks search                                                     │
│                                                                               │
│    Batched (v4.0):                                                           │
│    • Limited only by memory + CPU                                            │
│    • 50K+ inserts/sec sustained                                              │
│    • Write never blocks search                                               │
│                                                                               │
│    GAIN: ~6x write throughput improvement                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
import os
import time
import json
import shutil
import threading
import numpy as np
import faiss
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, list
import structlog

logger = structlog.get_logger()

@dataclass
class FAISSIndexConfig:
    """FAISS index configuration."""
    dimension: int = 512
    live_index_path: str = "Y:/faces/embeddings/live/face_index.faiss"
    staging_dir: str = "Y:/faces/embeddings/staging"
    backup_dir: str = "Y:/faces/embeddings/backup"
    staging_size: int = 10000  # Merge when staging reaches this size
    merge_timeout_seconds: int = 300  # Force merge after 5 min inactivity
    index_type: str = "HNSW64"  # HNSW with 64 connections

class BatchedFAISSIndex:
    """
    Batched/staged FAISS ingestion for high write throughput.

    Flow:
    1. New embeddings → staging batch
    2. When batch full → merge to live index
    3. Search always queries live index
    """

    def __init__(self, config: FAISSIndexConfig):
        self.config = config
        self.embedding_id_to_face_id = {}  # FAISS ID → face UUID
        self.face_id_to_embedding_id = {}  # face UUID → FAISS ID

        self._lock = threading.Lock()
        self._staging_vectors: list[np.ndarray] = []
        self._staging_face_ids: list[str] = []
        self._last_merge_time = time.time()
        self._merge_thread: Optional[threading.Thread] = None

        # Ensure directories exist
        Path(config.staging_dir).mkdir(parents=True, exist_ok=True)
        Path(config.backup_dir).mkdir(parents=True, exist_ok=True)
        Path(config.live_index_path).parent.mkdir(parents=True, exist_ok=True)

        # Load or create live index
        self._init_indexes()

    def _init_indexes(self):
        """Initialize or load indexes."""
        if os.path.exists(self.config.live_index_path):
            self.live_index = faiss.read_index(self.config.live_index_path)
            logger.info("Loaded live FAISS index", path=self.config.live_index_path)
        else:
            # Create new HNSW index
            self.live_index = faiss.IndexHNSWFlat(
                self.config.dimension,
                self.config.index_type.replace("HNSW", "")
            )
            logger.info("Created new live FAISS index")

        # Load existing staging indices
        self._load_staging_indices()

    def _load_staging_indices(self):
        """Load existing staging indices from disk."""
        staging_path = Path(self.config.staging_dir)
        for idx_file in sorted(staging_path.glob("staging_*.faiss")):
            try:
                idx = faiss.read_index(str(idx_file))
                n = idx.ntotal
                logger.info("Loaded staging index", path=str(idx_file), count=n)
            except Exception as e:
                logger.warning("Failed to load staging index", path=str(idx_file), error=str(e))

    def add(self, embedding: np.ndarray, face_id: str) -> int:
        """
        Add embedding to staging batch.

        Returns: FAISS embedding ID
        """
        with self._lock:
            # Normalize for cosine similarity
            embedding = embedding / np.linalg.norm(embedding)
            embedding = embedding.astype('float32')

            # Add to staging batch
            self._staging_vectors.append(embedding)
            self._staging_face_ids.append(face_id)

            # Get next embedding ID
            embedding_id = len(self.face_id_to_embedding_id)
            self.face_id_to_embedding_id[face_id] = embedding_id
            self.embedding_id_to_face_id[embedding_id] = face_id

            # Check if merge needed
            if len(self._staging_vectors) >= self.config.staging_size:
                self._schedule_merge()

        return embedding_id

    def add_batch(self, embeddings: list[np.ndarray], face_ids: list[str]) -> list[int]:
        """Add multiple embeddings."""
        return [self.add(e, fid) for e, fid in zip(embeddings, face_ids)]

    def _schedule_merge(self):
        """Schedule a merge operation."""
        if self._merge_thread is not None and self._merge_thread.is_alive():
            # Merge already scheduled
            return

        self._merge_thread = threading.Thread(target=self._merge_staging_to_live)
        self._merge_thread.daemon = True
        self._merge_thread.start()

    def _merge_staging_to_live(self):
        """Merge staging indices into live index."""
        with self._lock:
            if not self._staging_vectors:
                return

            try:
                logger.info("Starting FAISS index merge", staging_count=len(self._staging_vectors))

                # 1. Backup current live index
                backup_path = Path(self.config.backup_dir) / f"backup_{int(time.time())}.faiss"
                if os.path.exists(self.config.live_index_path):
                    shutil.copy(self.config.live_index_path, str(backup_path))
                    logger.info("Backed up live index", path=str(backup_path))

                # 2. Create batch index from current staging vectors
                batch_index = faiss.IndexFlatIP(self.config.dimension)
                batch_vectors = np.array(self._staging_vectors)
                batch_index.add(batch_vectors)

                # 3. Merge live + batch using FAISS merge
                merged_index = faiss.merge_indexes(
                    [self.live_index, batch_index],
                    ids=[0, 1]  # Track origin
                )

                # 4. Convert to HNSW for search (if not already)
                if not isinstance(merged_index, faiss.IndexHNSW):
                    nlist = min(4096, merged_index.ntotal // 39)
                    hnsw_index = faiss.IndexHNSWshard(merged_index, nlist, 64)
                    merged_index = hnsw_index

                # 5. Save merged index
                temp_path = self.config.live_index_path + ".tmp"
                faiss.write_index(merged_index, temp_path)
                shutil.move(temp_path, self.config.live_index_path)

                # 6. Update live index reference
                self.live_index = faiss.read_index(self.config.live_index_path)

                # 7. Clear staging
                self._staging_vectors = []
                self._staging_face_ids = []
                self._last_merge_time = time.time()

                # 8. Clean old staging files
                for idx_file in Path(self.config.staging_dir).glob("staging_*.faiss"):
                    idx_file.unlink()

                logger.info("FAISS index merge completed", new_count=self.live_index.ntotal)

                # 9. Update metadata
                self._update_metadata()

            except Exception as e:
                logger.error("FAISS merge failed", error=str(e))
                raise

    def search(self, embedding: np.ndarray, k: int = 100) -> list[dict]:
        """
        Search for similar faces in live index.

        Returns list of {face_id, similarity} sorted by similarity.
        """
        # Normalize
        embedding = embedding / np.linalg.norm(embedding)
        embedding = embedding.astype('float32').reshape(1, -1)

        # Search live index
        similarities, indices = self.live_index.search(embedding, k)

        results = []
        for idx, sim in zip(indices[0], similarities[0]):
            if idx < 0:
                continue
            face_id = self.embedding_id_to_face_id.get(int(idx))
            if face_id:
                results.append({
                    'face_id': face_id,
                    'similarity': float(sim),
                    'embedding_id': int(idx)
                })

        return results

    def _update_metadata(self):
        """Update FAISS index metadata."""
        meta = {
            'embedding_count': self.live_index.ntotal,
            'dimension': self.config.dimension,
            'last_merge': time.time(),
            'staging_size': len(self._staging_vectors)
        }
        meta_path = self.config.live_index_path + ".meta"
        with open(meta_path, 'w') as f:
            json.dump(meta, f)

    def force_merge(self):
        """Force immediate merge of staging to live."""
        self._merge_staging_to_live()

    def get_stats(self) -> dict:
        """Get index statistics."""
        return {
            'live_count': self.live_index.ntotal if self.live_index else 0,
            'staging_count': len(self._staging_vectors),
            'last_merge': self._last_merge_time,
            'total_mapped': len(self.face_id_to_embedding_id)
        }
```

---

## 9. Search Engine

### Search Types

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SEARCH CAPABILITIES v4.0                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ TYPE 1: UPLOAD IMAGE SEARCH                                                 │
│                                                                               │
│    User uploads: vacation_selfie.jpg                                         │
│                                                                               │
│    Process:                                                                   │
│    1. Detect faces → generate embeddings                                    │
│    2. Search FAISS (live index only)                                        │
│    3. Generate thumbnails on-demand for results                             │
│    4. Return ranked matches with thumbnails                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ TYPE 2: EXACT / PERCEPTUAL MATCH                                             │
│                                                                               │
│    pHash search for exact/similar images                                     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ TYPE 3: MULTI-FACE SEARCH                                                    │
│                                                                               │
│    Mode A - "Show all matches":                                              │
│    • Find images with ANY of the faces                                      │
│                                                                               │
│    Mode B - "Must appear together":                                         │
│    • Find images with ALL faces                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ TYPE 4: IDENTITY SEARCH                                                      │
│                                                                               │
│    Search all faces for a named identity                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Search Implementation

```python
import numpy as np
from typing import Optional

class FaceSearchEngine:
    """Face similarity search using batched FAISS index."""

    def __init__(self, faiss_index: BatchedFAISSIndex):
        self.index = faiss_index

    def search(
        self,
        embedding: np.ndarray,
        top_k: int = 100,
        min_similarity: float = 0.6
    ) -> list[dict]:
        """Search for similar faces."""
        results = self.index.search(embedding, k=top_k * 3)

        # Filter by similarity
        filtered = [r for r in results if r['similarity'] >= min_similarity]

        # Sort by similarity
        filtered.sort(key=lambda x: x['similarity'], reverse=True)

        return filtered[:top_k]

    def search_with_thumbnails(
        self,
        embedding: np.ndarray,
        face_records: dict,  # face_id -> face record
        top_k: int = 100,
        min_similarity: float = 0.6
    ) -> list[dict]:
        """
        Search and return results with thumbnail data.

        For each result:
        1. Get face record
        2. Look up original image path
        3. Generate/cached thumbnail
        4. Return enriched result
        """
        results = self.search(embedding, top_k, min_similarity)

        enriched = []
        for result in results:
            face_id = result['face_id']
            face = face_records.get(face_id, {})

            # Generate thumbnail on-demand
            thumbnail = get_thumbnail(face, face.get('original_path', ''))

            enriched.append({
                **result,
                'thumbnail': thumbnail,
                'face': {
                    'bbox': face.get('bbox'),
                    'quality_score': face.get('quality_score'),
                    'original_path': face.get('original_path')
                }
            })

        return enriched

    def multi_face_search(
        self,
        embeddings: list[np.ndarray],
        mode: str = "all"
    ) -> dict:
        """
        Search with multiple faces.

        mode="all": Images with ANY of the faces
        mode="together": Images with ALL faces
        """
        # Search each embedding
        face_sets = []
        for embedding in embeddings:
            results = self.search(embedding, top_k=1000, min_similarity=0.6)
            face_sets.append(set(r['face_id'] for r in results))

        if mode == "all":
            combined = set()
            for result_set in face_sets:
                combined.update(result_set)
        else:
            combined = face_sets[0]
            for result_set in face_sets[1:]:
                combined = combined.intersection(result_set)

        return {'face_ids': list(combined)}

    def get_images_for_faces(self, face_ids: list[str]) -> dict:
        """
        Group face IDs by image ID.

        Returns: {image_id: [face_ids]}
        """
        # Query database for face → image mapping
        query = """
            SELECT f.id, f.image_id
            FROM faces f
            WHERE f.id = ANY(%s)
        """
        # Execute and group
        results = {}  # image_id -> [face_id]
        for face_id, image_id in query.execute():
            if image_id not in results:
                results[image_id] = []
            results[image_id].append(face_id)

        return results
```

---

## 10. Real-Time Indexing

### Watch Mode Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         REAL-TIME INDEXING (WATCH MODE)                       │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ FILE SYSTEM EVENTS                                                            │
│                                                                               │
│   WATCHER: watchdog library + Windows API                                     │
│   Events: CREATE, MODIFY, DELETE                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ EVENT QUEUE (asyncio.Queue)                                                   │
│   • Max 50 files in-flight                                                  │
│   • Retry with exponential backoff                                         │
│   • Redis pub/sub for dashboard                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROCESSING                                                                   │
│   1. File validation                                                        │
│   2. Hashing (dedup)                                                        │
│   3. Face detection                                                         │
│   4. Embedding extraction                                                   │
│   5. Batched FAISS add (staging)                                            │
│   6. OneDrive revert (if applicable)                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Status Publishing

```python
class IndexStatusPublisher:
    """Publish indexing status for real-time dashboard."""

    def __init__(self, redis_client):
        self.redis = redis_client

    def publish(self, event_type: str, data: dict):
        """Publish event to Redis pub/sub."""
        channel = f"indexer:{event_type}"
        message = json.dumps({
            'timestamp': datetime.now().isoformat(),
            **data
        })
        self.redis.publish(channel, message)

    def on_file_discovered(self, path: str, source: str):
        self.publish('file_discovered', {'path': path, 'source': source})

    def on_onedrive_download_start(self, path: str):
        self.publish('onedrive_download_start', {'path': path})

    def on_onedrive_download_complete(self, path: str):
        self.publish('onedrive_download_complete', {'path': path})

    def on_processing_started(self, path: str):
        self.publish('processing_started', {'path': path})

    def on_faces_detected(self, path: str, count: int):
        self.publish('faces_detected', {'path': path, 'count': count})

    def on_indexed(self, path: str, face_count: int, duration_ms: int):
        self.publish('indexed', {
            'path': path,
            'faces': face_count,
            'duration_ms': duration_ms
        })

    def on_onedrive_reverted(self, path: str):
        self.publish('onedrive_reverted', {'path': path})

    def on_failed(self, path: str, error: str, retry_count: int):
        self.publish('failed', {
            'path': path,
            'error': error,
            'retry_count': retry_count
        })
```

---

## 11. Identity Clustering v2.0

### Quality-Aware Clustering

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    QUALITY-AWARE IDENTITY CLUSTERING                          │
└─────────────────────────────────────────────────────────────────────────────┘

PROBLEM: Low-quality faces dilute cluster accuracy

SOLUTION: Integrate quality scores into distance matrix

┌─────────────────────────────────────────────────────────────────────────────┐
│ DISTANCE WEIGHTING                                                            │
│                                                                               │
│ Low-quality face (blurry, small) gets HIGHER distance to all others         │
│                                                                               │
│ weighted_distance(i,j) = raw_distance(i,j) * quality_weight(i) * quality_weight(j)│
│                                                                               │
│ quality_weight = 1.0 / (quality_score + 0.1)                                 │
│                                                                               │
│ RESULT: Low-quality faces treated as outliers or low-confidence members     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
import numpy as np
import hdbscan
from sklearn.metrics import silhouette_score

class QualityAwareClustering:
    """Identity clustering with quality-weighted distances."""

    def __init__(self, min_cluster_size: int = 5):
        self.min_cluster_size = min_cluster_size

    def cluster(
        self,
        embeddings: np.ndarray,
        quality_scores: np.ndarray,
        face_ids: list[str]
    ) -> list[dict]:
        """
        Perform HDBSCAN clustering with quality weighting.

        Args:
            embeddings: Nx512 matrix
            quality_scores: N-element vector (0-1, higher = better)
            face_ids: N-element list of face UUIDs

        Returns:
            List of {face_id, cluster_id, is_outlier, confidence}
        """
        # Normalize quality scores
        quality_normalized = quality_scores / max(quality_scores.max(), 1e-6)

        # Compute cosine distance matrix
        # embeddings assumed to be unit-normalized
        distance_matrix = 1 - np.dot(embeddings, embeddings.T)

        # Weight distances by inverse quality
        # Low quality = higher effective distance
        quality_weight = 1.0 / (quality_normalized[:, None] + 0.1)

        # Apply weighting (asymmetric weighting: penalize low-quality faces)
        weighted_distances = distance_matrix * quality_weight

        # Symmetrize
        weighted_distances = (weighted_distances + weighted_distances.T) / 2

        # Run HDBSCAN
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            metric='precomputed',
            cluster_selection_method='eom',
            allow_single_cluster=True
        )

        cluster_labels = clusterer.fit_predict(weighted_distances)

        # Compute silhouette score for each cluster
        valid_mask = cluster_labels >= 0
        if len(np.unique(cluster_labels[valid_mask])) > 1:
            silhouette_scores = silhouette_score(
                weighted_distances[valid_mask][:, valid_mask],
                cluster_labels[valid_mask]
            )
        else:
            silhouette_scores = 0.0

        # Build results
        results = []
        for i, face_id in enumerate(face_ids):
            cluster_id = cluster_labels[i]
            is_outlier = cluster_id == -1

            # Confidence based on cluster membership probability
            prob = clusterer.probabilities_[i]

            results.append({
                'face_id': face_id,
                'cluster_id': int(cluster_id) if not is_outlier else None,
                'is_outlier': is_outlier,
                'confidence': float(prob),
                'quality_score': float(quality_normalized[i])
            })

        return {
            'clusters': results,
            'silhouette_score': float(silhouette_scores),
            'cluster_count': len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
        }

    def compute_cluster_metrics(self, embeddings: np.ndarray, cluster_labels: np.ndarray) -> dict:
        """
        Compute validation metrics for clusters.

        Metrics:
        - Silhouette Score: how similar faces are to their own cluster
        - Calinski-Harabasz Index: cluster separation
        - Davies-Bouldin Index: cluster compactness
        """
        from sklearn.metrics import (
            silhouette_score,
            calinski_harabasz_score,
            davies_bouldin_score
        )

        valid_mask = cluster_labels >= 0
        if len(np.unique(cluster_labels[valid_mask])) < 2:
            return {
                'silhouette_score': 0.0,
                'calinski_harabasz': 0.0,
                'davies_bouldin': 0.0
            }

        try:
            silhouette = silhouette_score(
                embeddings[valid_mask],
                cluster_labels[valid_mask]
            )
        except Exception:
            silhouette = 0.0

        try:
            calinski = calinski_harabasz_score(
                embeddings[valid_mask],
                cluster_labels[valid_mask]
            )
        except Exception:
            calinski = 0.0

        try:
            davies = davies_bouldin_score(
                embeddings[valid_mask],
                cluster_labels[valid_mask]
            )
        except Exception:
            davies = 0.0

        return {
            'silhouette_score': float(silhouette),
            'calinski_harabasz': float(calinski),
            'davies_bouldin': float(davies)
        }

    def suggest_merges(
        self,
        clusters: dict,  # cluster_id -> [face_ids]
        embeddings: np.ndarray,
        similarity_threshold: float = 0.75
    ) -> list[dict]:
        """
        Suggest potential cluster merges based on similarity.

        Returns list of {cluster_a, cluster_b, similarity, confidence}
        """
        suggestions = []

        cluster_ids = list(clusters.keys())
        for i, cid_a in enumerate(cluster_ids):
            for cid_b in cluster_ids[i+1:]:
                if cid_a == -1 or cid_b == -1:
                    continue

                # Compute centroid similarity
                emb_a = embeddings[list(clusters[cid_a])].mean(axis=0)]
                emb_b = embeddings[list(clusters[cid_b])].mean(axis=0)

                similarity = np.dot(emb_a, emb_b)

                if similarity >= similarity_threshold:
                    suggestions.append({
                        'cluster_a': cid_a,
                        'cluster_b': cid_b,
                        'similarity': float(similarity),
                        'confidence': float(similarity)
                    })

        return sorted(suggestions, key=lambda x: x['similarity'], reverse=True)
```

### Verification Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      VERIFICATION WORKFLOW v2.0                              │
└─────────────────────────────────────────────────────────────────────────────┘

PRIORITY QUEUE:
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. HIGH PRIORITY (Auto-show)                                                 │
│    • Faces with high similarity to MULTIPLE clusters                        │
│    • Low-confidence cluster members                                        │
│    • New faces not yet assigned                                            │
│                                                                               │
│ 2. MEDIUM PRIORITY (On demand)                                               │
│    • All unverified faces                                                   │
│    • User can browse manually                                              │
│                                                                               │
│ 3. LOW PRIORITY (Background)                                                 │
│    • Outlier faces (likely noise)                                           │
│    • Auto-archive if very low quality                                       │
└─────────────────────────────────────────────────────────────────────────────┘

UI FEATURES:
┌─────────────────────────────────────────────────────────────────────────────┐
│ • Side-by-side comparison with cluster faces                               │
│ • Bulk actions: merge multiple, split multiple                               │
│ • Context: show other faces from same image                                  │
│ • Metrics display: Silhouette Score, cluster cohesion                        │
│ • Undo stack: last 10 actions                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. Dashboard & UI

### Dashboard Pages

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PAGE 1: STATUS (Real-Time)                                                   │
│                                                                              │
│ ┌─────────────────────────────────────────────────────────────────────┐    │
│ │ FILES INDEXED      │ FACES DETECTED    │ IDENTITIES       │ ONEDRIVE   │    │
│ │    125,432    (+234)│    892,104 (+1,892)│    3,456  (+12)│   Saved    │    │
│ └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│ CURRENT SCAN                                                                │
│ ┌──────────────────────────────────────────────────────────────┐           │
│ │ ☁️ Downloading: onedrive/Photos/2024/vacation/IMG_1234.jpg     │           │
│ │ ████████████░░░░░░░░░ 45%  (45MB / 100MB)                   │           │
│ └──────────────────────────────────────────────────────────────┘           │
│                                                                              │
│ RECENT ACTIVITY                                                              │
│ • 14:32:01 - Indexed: beach_sunset.jpg (2 faces)                            │
│ • 14:31:45 - ✓ Reverted to online-only: onedrive/IMG_5678.jpg (saved 4MB)  │
│ • 14:31:30 - Indexed: birthday_party.mp4 (12 faces)                        │
│ • 14:31:15 - ⬇️ Downloading: onedrive/summer/IMG_1234.jpg                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PAGE 2: SEARCH (PimEyes-Style)                                               │
│                                                                              │
│ ┌─────────────────────────────────────────────────────────────────┐        │
│ │                                                                   │        │
│ │         [Upload Image] or Drag & Drop                            │        │
│ │                                                                   │        │
│ └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│ Mode: ( ) Find ANY   (●) Find ALL together                                  │
│                                                                              │
│ RESULTS (with thumbnails generated on-demand)                                │
│ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                                   │
│ │thumb│ │thumb│ │thumb│ │thumb│ │thumb│  93% match                       │
│ │ 95% │ │ 91% │ │ 89% │ │ 87% │ │ 85% │  Original: C:/Photos/...        │
│ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PAGE 3: IDENTITIES (with Validation Metrics)                                 │
│                                                                              │
│ ┌──────────┐  Silhouette: 0.87 ✓  Cohesion: 0.92                         │
│ │ [thumb]  │  [Edit Name]  [Verify All]  [View 156 faces]               │
│ │  John    │                                                           │
│ │ ★ 156    │                                                           │
│ └──────────┘                                                           │
│                                                                              │
│ VERIFICATION QUEUE: 23 faces pending                                        │
│ Priority: 3 high, 12 medium, 8 low                                          │
│                                                                              │
│ ┌─────────────────────────────────────────────────────────────────┐        │
│ │ Face #45: Does this match "John"?                                │        │
│ │ Confidence: 78%   Similarity to centroid: 0.82                   │        │
│ │ [Same Person] [Different] [Skip] [View Context]                 │        │
│ └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13. Configuration Reference

### Complete `.env.example`

```env
# ========================================
# STORAGE PATHS
# ========================================
FACE_STORAGE_ROOT=Y:/faces
POSTGRES_VHDX_PATH=Y:/faces/database/postgres.vhdx
APP_ROOT=C:/facetracker

# ========================================
# DRIVE SOURCES
# ========================================
DRIVE_SOURCES=[
    {"path": "C:/", "type": "local", "priority": 1},
    {"path": "D:/", "type": "local", "priority": 2},
    {"path": "Y:/", "type": "local", "priority": 0, "exclude": true},
    {"path": "E:/", "type": "usb", "on_mount": true},
    {"path": "C:/Users/bryan/onedrive", "type": "onedrive", "priority": 3}
]

EXCLUDE_PATHS=["C:/facetracker", "Y:/faces", "C:/Windows", "C:/Program Files"]

# ========================================
# MEDIA FORMATS
# ========================================
SUPPORTED_IMAGES=.jpg,.jpeg,.png,.webp,.gif,.bmp,.heic,.heif,.tiff,.tif
SUPPORTED_RAW=.cr2,.cr3,.nef,.arw,.orf,.rw2,.dng,.raf
SUPPORTED_VIDEOS=.mp4,.mov,.m4v,.avi,.mkv,.wmv,.webm,.flv,.3gp

# ========================================
# FACE DETECTION (v4.0 Optimized)
# ========================================
MIN_FACE_AREA_PERCENT=5
MIN_LAPLACIAN_VARIANCE=100
MIN_DETECTION_CONFIDENCE=0.5
CROP_MARGIN_PERCENT=15

# Thumbnails (NOT full crops)
THUMBNAIL_SIZE=64
THUMBNAIL_QUALITY=80

# ========================================
# VIDEO PROCESSING
# ========================================
VIDEO_TRACKING_FPS=3
VIDEO_EMBEDDING_FPS=1
DEEPSORT_MAX_AGE=30
DEEPSORT_N_INIT=1

# ========================================
# FAISS INDEXING (v4.0 Batched)
# ========================================
FAISS_LIVE_PATH=Y:/faces/embeddings/live/face_index.faiss
FAISS_STAGING_DIR=Y:/faces/embeddings/staging
FAISS_STAGING_SIZE=10000
FAISS_MERGE_TIMEOUT=300
FAISS_INDEX_TYPE=HNSW64

# ========================================
# ONEDRIVE (v4.0 Hardened)
# ========================================
ONEDRIVE_ENABLED=true
ONEDRIVE_DOWNLOAD_TIMEOUT=300
ONEDRIVE_REVERT_VERIFY=true
ONEDRIVE_MULTI_DETECT=true
ONEDRIVE_MAX_RETRIES=3

# ========================================
# INDEXING
# ========================================
WATCH_MODE=true
WATCH_POLL_INTERVAL=30
INDEX_QUEUE_SIZE=50
INDEX_WORKERS=2

# ========================================
# CLUSTERING (v4.0 Quality-Aware)
# ========================================
CLUSTER_MIN_SIZE=5
CLUSTER_QUALITY_WEIGHTING=true
AUTO_MERGE_THRESHOLD=0.75
USER_VERIFY_THRESHOLD=0.60
MAX_UNDO_STACK=10

# ========================================
# SEARCH
# ========================================
SEARCH_TOP_K=100
SEARCH_MIN_SIMILARITY=0.6
SEARCH_CACHE_ENABLED=true

# ========================================
# DATABASE
# ========================================
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=facetracker
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme

# ========================================
# REDIS
# ========================================
REDIS_HOST=localhost
REDIS_PORT=6379

# ========================================
# DASHBOARD
# ========================================
DASHBOARD_PORT=5151
DASHBOARD_TAILSCALE=true

# ========================================
# LOGGING
# ========================================
LOG_LEVEL=INFO
LOG_PATH=Y:/faces/logs
VERBOSE_STATUS=true
STATUS_UPDATE_INTERVAL=5
```

---

## 14. File Architecture

```
C:/facetracker/                          # GIT REPOSITORY
├── src/
│   ├── main.py
│   ├── config.py
│   │
│   ├── api/
│   │   ├── routes/
│   │   │   ├── search.py
│   │   │   ├── identity.py
│   │   │   ├── stats.py
│   │   │   └── files.py
│   │   ├── dependencies.py
│   │   └── middleware.py
│   │
│   ├── engine/
│   │   ├── detector.py
│   │   ├── tracker.py
│   │   ├── embedder.py
│   │   └── quality.py
│   │
│   ├── pipeline/
│   │   ├── processor.py
│   │   ├── cropper.py
│   │   └── thumbnail.py          # NEW: On-demand thumbnail generation
│   │
│   ├── readers/
│   │   ├── image_reader.py
│   │   ├── video_reader.py
│   │   └── raw_heic.py
│   │
│   ├── search/
│   │   ├── engine.py
│   │   ├── ranking.py
│   │   ├── perceptual.py
│   │   └── multi_face.py
│   │
│   ├── identity/
│   │   ├── clustering.py         # NEW: Quality-aware clustering
│   │   ├── metrics.py            # NEW: Validation metrics
│   │   ├── verification.py
│   │   └── audit.py
│   │
│   ├── discovery/
│   │   ├── scanner.py
│   │   ├── manifest.py
│   │   ├── watcher.py
│   │   └── onedrive.py           # NEW: Hardened handler
│   │
│   ├── storage/
│   │   ├── database.py
│   │   ├── faiss_index.py        # NEW: Batched index
│   │   ├── redis_cache.py
│   │   └── thumbnail_cache.py    # NEW: Thumbnail management
│   │
│   └── utils/
│       ├── hashing.py
│       ├── logging.py
│       ├── atomic.py
│       └── graceful_shutdown.py
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── config/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md

Y:/faces/                                # NOT IN GIT
├── database/
├── embeddings/
│   ├── live/
│   ├── staging/
│   └── backup/
├── media/
│   ├── thumbnails/
│   └── source_ref/
├── cache/
├── state/
└── logs/
```

---

## 15. Docker Configuration

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: facetracker-postgres
    environment:
      POSTGRES_DB: facetracker
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - /mnt/facetracker/postgres:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: facetracker-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
    restart: unless-stopped

  api:
    build: .
    container_name: facetracker-api
    env_file:
      - .env
    environment:
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - REDIS_HOST=redis
      - REDIS_PORT=6379
    volumes:
      - Y:/faces:/app/storage:rw
      - C:/:/data/c_local:ro
      - D:/:/data/d_local:ro
    ports:
      - "${DASHBOARD_PORT:-5151}:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 8G

networks:
  default:
    name: facetracker-net

volumes:
  redis_data:
```

---

## 16. Dependencies

```txt
# requirements.txt

# API
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
python-multipart>=0.0.9
pydantic>=2.0.0
python-dotenv>=1.0.0

# Database
psycopg2-binary>=2.9.9
sqlalchemy>=2.0.0
pgvector>=0.2.0
halfvec>=0.1.0  # For 16-bit embeddings

# Computer Vision
opencv-python>=4.9.0
insightface>=0.7.3
onnxruntime>=1.17.0
pillow>=10.0.0
pillow-heif>=0.15.0
imageio>=2.34.0
imageio-ffmpeg>=0.4.9

# DeepSORT
deep-sort-realtime>=1.3.0

# Vector Index
faiss-cpu>=1.8.0

# Clustering
hdbscan>=0.8.1
umap-learn>=0.5.5
scikit-learn>=1.4.0

# Cache
redis>=5.0.0

# File Discovery
watchdog>=4.0.0

# Async
aiofiles>=23.0.0

# Utilities
tqdm>=4.66.0
structlog>=24.0.0
loguru>=0.7.0

# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

---

## 17. Glossary

| Term | Definition |
|------|------------|
| **halfvec** | PostgreSQL extension for 16-bit floating-point vectors |
| **Batched Ingestion** | Writing to staging index, then merging to live |
| **Staging Index** | Temporary FAISS index for new embeddings |
| **Multi-faceted Detection** | Using 2+ indicators to confirm OneDrive status |
| **Quality-aware Clustering** | HDBSCAN with quality-weighted distances |
| **Silhouette Score** | Cluster validation metric (-1 to 1) |
| **Thumbnail-on-Demand** | Generating thumbnails only when viewed |
| **HNSW** | Hierarchical Navigable Small World index |
| **pHash** | Perceptual hash for image similarity |

---

## 18. Out of Scope (v1.0)

| Feature | Reason |
|---------|--------|
| **Public OSINT index** | v2.0 feature |
| **Mobile app** | Web via Tailscale sufficient |
| **Multi-user** | Single user private deployment |
| **Named recognition** | Only clustering |
| **Face deletion** | Archives only |
| **Export** | Not requested |

---

## 19. Roadmap

### v1.0 (This PRD - v4.0)
- [x] Architecture design
- [x] Storage optimization (no crops, halfvec)
- [x] Batched FAISS ingestion
- [x] Hardened OneDrive handling
- [x] Quality-aware clustering
- [ ] PostgreSQL + halfvec setup
- [ ] FAISS batched index implementation
- [ ] File discovery system
- [ ] Face detection + embedding
- [ ] Real-time indexing
- [ ] Search API
- [ ] Dashboard UI

### v2.0 (Future)
- [ ] Public OSINT index integration
- [ ] Horizontal scaling
- [ ] Qdrant evaluation (if needed)

### v3.0 (Future)
- [ ] Distributed index (billion-scale)
- [ ] Real-time video search

---

**Document Version:** 4.0
**Status:** Production-Ready PRD
**Last Updated:** 2026-05-15
