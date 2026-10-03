# Container development checkpoint — 2026-09-27

Applied an explicit, isolated `compose.dev.yaml` with Python/Vite polling reload,
dependency isolation, and local images that cannot pull implicitly. Added dev
and production stages, remote GHCR publication with guarded retention, and
Windows/Linux instructions. Production Compose defaults are preserved.

Validation: Compose parsing and configuration contracts pass; facetracker
frontend `tsc --noEmit` passes in an isolated dependency fixture. Vite proxy and
polling checks, 12 retention tests, and watchfiles process reload fixtures on
Windows and WSL pass. No container images were built, pulled, or started; actual
SMB bind-mount behavior, app integration, and image sizes remain to verify on a
development host / in CI. Historical status below describes earlier work.

# STATE — facetracker

Last updated: 2026-09-16
Updated by: opencode (baseline triage wave2c)

## Stack
- Python application (src/, scripts/, tests/) + Docker (Dockerfile, docker-compose.yml)
- requirements.txt, pytest.ini, SPEC.md present
- No package.json / Node dependencies
- GitHub Actions CI (trufflehog, deepsource)

## Last Commit
- Hash: 293f320
- Date: 2026-09-07
- Message: chore: sync heartbeat [skip ci]

## Status
CLEAN — no real secrets found.

## Notes
- src/config.py line 148: `postgres_password: str = "changeme"` — Pydantic settings
  default, overridden by .env file at runtime. .env.example confirms pattern.
  Not a hardcoded secret.
- scripts/faiss_autotune_nlist.py: "secret" appears in comments only (sed-equivalent note).
- tests/comprehensive/test_comprehensive_suite.py: "secret.jpg" is a test fixture filename.

## Next Steps
None required. Repo is in maintenance mode (legacy face tracker tool).

2026-09-27: Backported merged SMB development Watch and explicit PostgreSQL driver maintenance to this checkout with guarded, narrow edits. Four local synthetic URL checks and the merged local Compose parse passed (three application services, four sync rules, no source binds or implicit application pulls). Existing production Docker stages, dependency manifests, branch, HEAD, staged index, and prior local work were preserved. The separate isolated runtime verification passed 26 checks; this exact canonical Docker recipe was not rebuilt or launched. No canonical commit, push, reset, or stash was performed.
