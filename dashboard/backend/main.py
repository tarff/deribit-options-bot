"""
VEGA Terminal FastAPI Backend

Provides REST endpoints and WebSocket connection for the React dashboard.
Serves the built React frontend from the dist/ directory.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Add parent directory to path for importing bot modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from routers import market, positions, trades, historical, stats
from websocket_manager import ConnectionManager
from services.live_data_service import LiveDataService

# Path to the built React frontend
DIST_DIR = Path(__file__).parent.parent / "dist"


# Global instances
connection_manager = ConnectionManager()
live_data_service: LiveDataService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle."""
    global live_data_service

    # Startup
    print("Starting VEGA Terminal API...")
    live_data_service = LiveDataService()
    await live_data_service.start()

    # Attach to app.state for access in routers
    app.state.live_data = live_data_service

    # Start background task for pushing live updates
    broadcast_task = asyncio.create_task(broadcast_live_data())

    yield

    # Shutdown
    print("Shutting down VEGA Terminal API...")
    broadcast_task.cancel()
    try:
        await broadcast_task
    except asyncio.CancelledError:
        pass
    await live_data_service.stop()


app = FastAPI(
    title="VEGA Terminal API",
    description="Backend API for the VEGA Terminal trading dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

def _dashboard_token() -> str:
    """Return optional dashboard API token."""
    return os.environ.get("DASHBOARD_API_TOKEN", "")


def _request_has_dashboard_token(request: Request) -> bool:
    expected = _dashboard_token()
    if not expected:
        return True

    bearer = request.headers.get("authorization", "")
    if bearer == f"Bearer {expected}":
        return True
    return request.headers.get("x-dashboard-token") == expected


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/") and not _request_has_dashboard_token(request):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(DashboardAuthMiddleware)

# No-cache middleware for API endpoints
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(historical.router, prefix="/api/historical", tags=["historical"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "vega-terminal-api"}


@app.get("/api/debug/status")
async def debug_status():
    """Debug endpoint showing service status."""
    return {
        "deribit_connected": live_data_service.client is not None if live_data_service else False,
        "websocket_clients": len(connection_manager.active_connections),
        "cache_keys": list(live_data_service._cache.keys()) if live_data_service else [],
        "has_bot_modules": live_data_service is not None,
    }


@app.get("/api/account")
async def get_account():
    """Get account information."""
    if live_data_service is None:
        return {"error": "Service not initialized"}

    account = await live_data_service.get_account()
    return account


@app.websocket("/api/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for live data updates."""
    expected_token = _dashboard_token()
    if expected_token and websocket.query_params.get("token") != expected_token:
        await websocket.close(code=1008)
        return

    await connection_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for client messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Handle ping/pong or client commands if needed
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat", "timestamp": get_timestamp()})
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        connection_manager.disconnect(websocket)


async def broadcast_live_data():
    """Background task to broadcast live data to all connected clients."""
    broadcast_count = 0
    while True:
        try:
            if live_data_service is not None and connection_manager.active_connections:
                # Get live data
                market_data = await live_data_service.get_market_data()
                positions = await live_data_service.get_positions()
                account = await live_data_service.get_account()
                greeks = await live_data_service.get_portfolio_greeks()

                timestamp = get_timestamp()
                broadcast_count += 1

                # Log every 12th broadcast (once per minute at 5s interval)
                if broadcast_count % 12 == 1:
                    price = market_data.get("price", 0)
                    currency = market_data.get("currency", "BTC")
                    clients = len(connection_manager.active_connections)
                    print(f"[Broadcast #{broadcast_count}] {currency}: ${price:,.0f} | Clients: {clients}")

                # Broadcast market data
                await connection_manager.broadcast({
                    "type": "market",
                    "data": market_data,
                    "timestamp": timestamp,
                })

                # Broadcast positions
                await connection_manager.broadcast({
                    "type": "positions",
                    "data": positions,
                    "timestamp": timestamp,
                })

                # Broadcast account
                await connection_manager.broadcast({
                    "type": "account",
                    "data": account,
                    "timestamp": timestamp,
                })

                # Broadcast portfolio Greeks
                await connection_manager.broadcast({
                    "type": "greeks",
                    "data": greeks,
                    "timestamp": timestamp,
                })

            # Wait before next broadcast (5 seconds)
            await asyncio.sleep(5)

        except asyncio.CancelledError:
            print("Broadcast task cancelled, shutting down")
            break
        except Exception as e:
            print(f"Broadcast error: {e}")
            await asyncio.sleep(5)


def get_timestamp() -> str:
    """Get current ISO timestamp."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# Serve static files from React build (must be after API routes)
if DIST_DIR.exists():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    # Serve other static files (favicon, etc.)
    @app.get("/vite.svg")
    async def serve_favicon():
        return FileResponse(DIST_DIR / "vite.svg")

    # Catch-all route for client-side routing - serves index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for any non-API route."""
        # Don't intercept API routes
        if full_path.startswith("api/"):
            return {"error": "Not found"}
        return FileResponse(DIST_DIR / "index.html")
else:
    print(f"Warning: Frontend dist directory not found at {DIST_DIR}")
    print("Run 'npm run build' in the dashboard directory to build the frontend.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[".", "../src"],
    )
