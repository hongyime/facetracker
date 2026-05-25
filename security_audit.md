# Security Audit

Earlier versions of this file declared the codebase "SAFE / no issues
found". That was wrong and has been replaced. The actual security
findings and fixes:

1. PowerShell command injection — three call sites in
   `src/discovery/onedrive.py` interpolated user-controlled file paths
   into PowerShell script source. A filename containing a single quote
   could break out of the quoted argument and execute arbitrary
   PowerShell. Fixed: paths are now passed as a separate argv element
   and read from `$args[0]` inside the script with `Get-Item
   -LiteralPath`. `attrib +U <path>` likewise uses argv splitting.

2. Dashboard CORS — `operations-dashboard/backend/main.py` used
   `allow_origins=["*"]` with `allow_credentials=True`. That combination
   is rejected by browsers and, where the policy was honoured, allowed
   any origin to issue credentialed cross-site requests. Fixed: explicit
   allowlist via the `DASHBOARD_CORS_ORIGINS` env var (defaults to a
   localhost set).

3. Information disclosure — the dashboard's global exception handler
   returned the raw exception string to clients with HTTP 200. Fixed:
   tracebacks are logged server-side, clients receive a generic
   `"Internal server error"` message and a real status code.

4. Auth — there is none. The FastAPI app has no authentication and no
   tenant isolation. This is acceptable for a single-user host-only
   deployment (Y:/faces, Postgres on localhost) but the service must
   not be exposed off-host without a reverse proxy that adds
   authentication.

5. Secrets handling — `.env` contains a Postgres password. It is
   gitignored. `test_manager_locally.py` contains the literal string
   `***` as a placeholder password (intentional, not a leak). No
   secrets were checked into VCS by this audit.

6. Subprocess hardening — every `subprocess.run` call in the audited
   code uses argv lists (no `shell=True`), bounded timeouts, and
   captured output. No string interpolation into shell commands
   remains.
