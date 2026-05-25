from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json
import logging
import os
from typing import List
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Operations Dashboard API")

# CORS: pin explicit origins. Browsers reject `allow_credentials=True` combined
# with `allow_origins=["*"]`, so the previous config was both insecure and
# functionally broken for credentialed requests.
_default_origins = (
    "http://localhost:5151,http://localhost:3000,http://localhost:8700,"
    "http://127.0.0.1:5151,http://127.0.0.1:3000,http://127.0.0.1:8700"
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
    return {
        "data": {
            "users": "1,204",
            "errorRate": "0.12%",
            "latency": "45ms",
            "status": "online"
        },
        "error": None,
        "meta": {}
    }


@app.get("/api/{service}/stats")
async def get_service_stats(service: str):
    return {"data": {"service": service, "status": "online"}, "error": None, "meta": {}}


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
    while True:
        try:
            mock_data = [
                {
                    "service": "indexing-engine",
                    "status": "processing",
                    "latency_ms": 12,
                    "updated_at": datetime.now().isoformat()
                },
                {
                    "service": "search-api",
                    "status": "online",
                    "latency_ms": 5,
                    "updated_at": datetime.now().isoformat()
                },
                {
                    "service": "vector-db",
                    "status": "online",
                    "latency_ms": 2,
                    "updated_at": datetime.now().isoformat()
                }
            ]
            await manager.broadcast(json.dumps(mock_data))
        except Exception as e:
            logger.error(f"broadcast loop error: {e}")
        await asyncio.sleep(5)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_health_status())


# Fallback for SPA — mount static last so API/WS routes aren't shadowed.
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8700, reload=True)
