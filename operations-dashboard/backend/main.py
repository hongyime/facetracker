from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json
import logging
from typing import List
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Operations Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to WS: {e}")

manager = ConnectionManager()

# --- Exception Handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=200, # Never return 500 for expected failures as per spec
        content={"data": None, "error": str(exc), "meta": {}}
    )

# --- Routes ---
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

# --- WebSocket ---
@app.websocket("/ws/health")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # heartbeat
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def broadcast_health_status():
    while True:
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
        await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_health_status())

import os

# Fallback for SPA
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8700, reload=True)