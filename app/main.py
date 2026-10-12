"""
Main Application Entry Point
FastAPI app configuration, lifespan manager, static files, and router integration.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

from app.infrastructure.database import init_database
from app.infrastructure.repository import Repository
from app.application.traffic_service import TrafficService
from app.api.routes_junctions import router as junctions_router
from app.api.routes_events import router as events_router
from app.api.routes_history import router as history_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB schema & traffic service workers
    init_database()
    repo = Repository()
    traffic_service = TrafficService(repo)
    app.state.traffic_service = traffic_service
    await traffic_service.start()
    yield
    # Shutdown: Stop workers cleanly
    await traffic_service.stop()


app = FastAPI(
    title="Factory Traffic Management System",
    description="Event-Driven Traffic Control System for Industrial Automation and Factory Roads",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware for open accessibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(junctions_router)
app.include_router(events_router)
app.include_router(history_router)

# Mount static files for the dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Factory Traffic Management System API is running. Visit /docs for OpenAPI documentation."}
