# JOURNAL — facetracker

## 2026-09-16 — Baseline triage wave2c

- Ran baseline triage as part of wave2c maintenance sweep
- Stack: Python application (src/, scripts/, tests/) + Docker, no JS/HTML, no package.json
- Last commit: 2026-09-07 (heartbeat sync)
- Secret scan hits reviewed:
  - src/config.py:148 postgres_password="changeme" — Pydantic settings default, overridden by .env; not a real secret
  - scripts/faiss_autotune_nlist.py:245-246 — "secret" in comments only
  - tests/comprehensive/test_comprehensive_suite.py:1454 — "secret.jpg" is a test fixture filename
- Working tree: clean
- No real security issues found; repo in stable maintenance mode

## 2026-09-27 — Isolated container development
Added explicit development Compose, bind-mounted polling reload, isolated dependency/data volumes, dev/production image stages, guarded GHCR retention and cross-platform instructions. Compose/configuration contracts, Vite configuration checks, retention fixtures, and Windows/WSL reload fixtures passed. No builds, pulls, application starts, commits or pushes were performed; deployment health and real SMB mount behavior are not claimed.

- 2026-09-27: Pre-create API development sync paths owned by appuser so initial source delivery can run without root; production is unchanged.

- 2026-09-27: Seed ordinary code during the initial dev build and add an explicit sync-only overlay for SMB/remote Docker hosts; keep source edits free of rebuilds and isolate private dev input in an empty named volume.
