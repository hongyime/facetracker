from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import json
import logging
import os
import time
from typing import List, Optional, Dict, Any
from datetime import datetime
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Where the real facetracker API lives. On the docker compose network this
# resolves to the api service over the bridge; in local dev fall back to the
# host-mapped port on localhost. Settable via env so the same image works
# in either deployment.
FACETRACKER_API_URL = os.environ.get(
    "FACETRACKER_API_URL", "http://localhost:5454"
).rstrip("/")

# Shared httpx client. Created once at lifespan startup, closed at shutdown.
# Keeping a single client lets us reuse the underlying connection pool
# instead of opening + tearing down a TCP+TLS handshake every poll cycle.
_http_client: Optional[httpx.AsyncClient] = None


async def _get_http() -> httpx.AsyncClient:
    if _http_client is None:
        # Should never happen — lifespan creates it before any request can
        # come in — but explicit error beats AttributeError in production.
        raise RuntimeError("HTTP client not initialised")
    return _http_client


async def _facetracker_get(path: str, timeout: float = 3.0) -> tuple[int, Optional[Dict[str, Any]], float]:
    """GET ``{FACETRACKER_API_URL}{path}`` and return (status, body, latency_ms).

    Returns (-1, None, latency_ms) on connect/timeout error so callers can
    distinguish "service is down" from "service returned 5xx" without
    needing to catch exceptions themselves.
    """
    client = await _get_http()
    t0 = time.perf_counter()
    try:
        resp = await client.get(f"{FACETRACKER_API_URL}{path}", timeout=timeout)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        try:
            body = resp.json()
        except Exception:
            body = None
        return resp.status_code, body, dt_ms
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        logger.debug(f"facetracker GET {path} failed: {e}")
        return -1, None, dt_ms


# Lifespan replaces the deprecated @app.on_event hooks. Starlette removed
# on_event handler invocation in newer versions; using lifespan is the only
# supported path going forward and lets us cleanly cancel the broadcast task
# on shutdown instead of leaking it.
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    task = asyncio.create_task(broadcast_health_status())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await _http_client.aclose()
        _http_client = None


app = FastAPI(title="Operations Dashboard API", lifespan=lifespan)

# CORS: pin explicit origins. Browsers reject `allow_credentials=True` combined
# with `allow_origins=["*"]`, so the previous config was both insecure and
# functionally broken for credentialed requests.
_default_origins = (
    "http://localhost:5454,http://localhost:3000,http://localhost:8700,http://localhost:8701,"
    "http://127.0.0.1:5454,http://127.0.0.1:3000,http://127.0.0.1:8700,http://127.0.0.1:8701"
)
_allowed = [
    o.strip() for o in os.environ.get("DASHBOARD_CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    """WebSocket connection registry, safe under concurrent connect/disconnect/broadcast."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        # Guarded remove — disconnect can be called multiple times by both
        # the WS handler's finally-block and broadcast()'s pruning path.
        async with self._lock:
            try:
                self.active_connections.remove(websocket)
            except ValueError:
                pass  # already removed

    async def broadcast(self, message: str):
        # Iterate over a snapshot so concurrent connect/disconnect can't
        # raise RuntimeError("list changed size during iteration"). Failed
        # sockets are queued for removal and pruned after the loop so the
        # active_connections list doesn't grow forever with dead sockets.
        async with self._lock:
            snapshot = list(self.active_connections)

        dead: List[WebSocket] = []
        for connection in snapshot:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"WS broadcast send failed; pruning connection: {e}")
                dead.append(connection)

        if dead:
            async with self._lock:
                for ws in dead:
                    try:
                        self.active_connections.remove(ws)
                    except ValueError:
                        pass


manager = ConnectionManager()


# --- Exception handler --------------------------------------------------------
# The previous global handler returned HTTP 200 with `{"data":null,"error":...}`
# which (a) leaked raw exception strings to clients, and (b) defeated every
# upstream signal of failure (load balancers, browsers, fetch retry logic, the
# uptime probe in monitoring). We now return appropriate status codes and a
# generic client-facing message, while logging full server-side detail.

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"data": None, "error": exc.detail, "meta": {}},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log full traceback server-side; surface only a generic message to clients.
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"data": None, "error": "Internal server error", "meta": {}},
    )


# --- Routes ------------------------------------------------------------------
@app.get("/api/stats")
async def get_stats():
    """Top-line ops stats — surfaces real numbers from the facetracker API.

    Returns the same shape the legacy mock endpoint returned so existing
    frontend cards keep working without a schema change:
      - users:     total identities (people seen)
      - errorRate: failed / (failed + completed) as percentage
      - latency:   measured /health round-trip in ms
      - status:    online / degraded / offline
    """
    h_status, _, h_latency_ms = await _facetracker_get("/health")
    s_status, s_body, _ = await _facetracker_get("/api/v1/stats")

    if h_status != 200:
        return {
            "data": {
                "users": "—",
                "errorRate": "—",
                "latency": "—",
                "status": "offline",
            },
            "error": "facetracker /health unreachable",
            "meta": {"upstream": FACETRACKER_API_URL},
        }

    if s_status != 200 or not isinstance(s_body, dict):
        return {
            "data": {
                "users": "—",
                "errorRate": "—",
                "latency": f"{h_latency_ms:.0f}ms",
                "status": "degraded",
            },
            "error": f"facetracker /api/v1/stats returned {s_status}",
            "meta": {"upstream": FACETRACKER_API_URL},
        }

    completed = int(s_body.get("indexing", {}).get("files_processed", 0) or 0)
    failed = int(s_body.get("indexing", {}).get("files_failed", 0) or 0)
    total = completed + failed
    err_pct = (failed / total * 100.0) if total else 0.0
    identities = int(s_body.get("total_identities", 0) or 0)

    return {
        "data": {
            "users": f"{identities:,}",
            "errorRate": f"{err_pct:.2f}%",
            "latency": f"{h_latency_ms:.0f}ms",
            "status": "online",
            # bonus: extra fields the SPA can opt into without breaking older cards
            "total_faces": int(s_body.get("total_faces", 0) or 0),
            "total_images": int(s_body.get("total_images", 0) or 0),
            "total_videos": int(s_body.get("total_videos", 0) or 0),
            "files_processed": completed,
            "files_failed": failed,
            "faces_per_image_avg": s_body.get("indexing", {}).get("faces_per_image_avg", 0),
        },
        "error": None,
        "meta": {"upstream": FACETRACKER_API_URL},
    }


@app.get("/api/{service}/stats")
async def get_service_stats(service: str):
    """Per-service detail — used by the dashboard's service drilldown cards.

    Recognised services map to facetracker capabilities:
      - indexing-engine -> /api/v1/stats/scan-progress + /api/v1/stats
      - search-api      -> /health round-trip + /api/v1/stats faces total
      - vector-db       -> /api/v1/stats (faces present implies the index is loaded)

    Unknown service names return 404 rather than fabricating mock data.
    """
    if service == "indexing-engine":
        sp_status, sp_body, sp_latency = await _facetracker_get("/api/v1/stats/scan-progress")
        st_status, st_body, _ = await _facetracker_get("/api/v1/stats")
        if sp_status != 200 or not isinstance(sp_body, dict):
            return {
                "data": {"service": service, "status": "offline"},
                "error": f"upstream returned {sp_status}",
                "meta": {},
            }
        return {
            "data": {
                "service": service,
                "status": "processing" if sp_body.get("is_scanning") else "idle",
                "is_scanning": bool(sp_body.get("is_scanning", False)),
                "current_file": sp_body.get("current_file"),
                "files_scanned": sp_body.get("files_scanned", 0),
                "files_total": sp_body.get("files_total", 0),
                "progress_percent": sp_body.get("progress_percent", 0),
                "eta_seconds": sp_body.get("eta_seconds"),
                "files_processed": (st_body or {}).get("indexing", {}).get("files_processed", 0),
                "files_failed": (st_body or {}).get("indexing", {}).get("files_failed", 0),
                "latency_ms": round(sp_latency, 1),
            },
            "error": None,
            "meta": {},
        }

    if service == "search-api":
        status_code, _, latency_ms = await _facetracker_get("/health")
        return {
            "data": {
                "service": service,
                "status": "online" if status_code == 200 else "offline",
                "latency_ms": round(latency_ms, 1),
            },
            "error": None if status_code == 200 else f"/health returned {status_code}",
            "meta": {},
        }

    if service == "vector-db":
        st_status, st_body, st_latency = await _facetracker_get("/api/v1/stats")
        if st_status != 200 or not isinstance(st_body, dict):
            return {
                "data": {"service": service, "status": "offline"},
                "error": f"upstream returned {st_status}",
                "meta": {},
            }
        return {
            "data": {
                "service": service,
                "status": "online",
                "total_faces": int(st_body.get("total_faces", 0) or 0),
                "total_identities": int(st_body.get("total_identities", 0) or 0),
                "latency_ms": round(st_latency, 1),
            },
            "error": None,
            "meta": {},
        }

    raise HTTPException(status_code=404, detail=f"unknown service: {service}")


# --- WebSocket ---------------------------------------------------------------
@app.websocket("/ws/health")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # heartbeat — wait for client pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WS endpoint error: {e}")
        await manager.disconnect(websocket)


async def broadcast_health_status():
    """Push real per-service health to all connected dashboard websockets.

    Every 5 seconds, probe the facetracker API on the compose network and
    emit a snapshot the SPA can render directly. Three services are
    surfaced — same names the legacy mock used so the frontend doesn't
    need a schema change:
      - indexing-engine: scan progress + processing/idle state
      - search-api: /health round-trip
      - vector-db: total_faces / total_identities

    Any one probe failing turns that service's status to "offline" but
    does NOT abort the broadcast — partial visibility is more useful
    than blackout.
    """
    while True:
        try:
            sp_status, sp_body, sp_latency = await _facetracker_get("/api/v1/stats/scan-progress")
            h_status, _, h_latency = await _facetracker_get("/health")
            st_status, st_body, st_latency = await _facetracker_get("/api/v1/stats")

            now_iso = datetime.now().isoformat()

            indexing_payload = {
                "service": "indexing-engine",
                "status": (
                    "processing" if sp_status == 200 and isinstance(sp_body, dict) and sp_body.get("is_scanning")
                    else "idle" if sp_status == 200
                    else "offline"
                ),
                "latency_ms": round(sp_latency, 1),
                "updated_at": now_iso,
            }
            if sp_status == 200 and isinstance(sp_body, dict):
                indexing_payload["files_scanned"] = sp_body.get("files_scanned", 0)
                indexing_payload["files_total"] = sp_body.get("files_total", 0)
                indexing_payload["progress_percent"] = sp_body.get("progress_percent", 0)

            search_payload = {
                "service": "search-api",
                "status": "online" if h_status == 200 else "offline",
                "latency_ms": round(h_latency, 1),
                "updated_at": now_iso,
            }

            vector_payload = {
                "service": "vector-db",
                "status": "online" if st_status == 200 else "offline",
                "latency_ms": round(st_latency, 1),
                "updated_at": now_iso,
            }
            if st_status == 200 and isinstance(st_body, dict):
                vector_payload["total_faces"] = int(st_body.get("total_faces", 0) or 0)
                vector_payload["total_identities"] = int(st_body.get("total_identities", 0) or 0)

            await manager.broadcast(json.dumps([indexing_payload, search_payload, vector_payload]))
        except asyncio.CancelledError:
            # Lifespan shutdown — bubble up so the lifespan finally-block
            # observes the cancellation cleanly.
            raise
        except Exception as e:
            logger.error(f"broadcast loop error: {e}")
        await asyncio.sleep(5)


# Fallback for SPA — mount static last so API/WS routes aren't shadowed.
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8700, reload=True)
