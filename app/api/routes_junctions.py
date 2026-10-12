"""
API Routes - Junctions and Manual Control
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import Dict, List
from app.api.schemas import (
    CommandResponse,
    CreateJunctionRequest,
    JunctionStatusResponse,
    ManualCommandRequest,
    SimSpeedRequest,
)
from app.application.traffic_service import TrafficService

router = APIRouter(prefix="/api/junctions", tags=["Junctions"])


def get_traffic_service(request: Request) -> TrafficService:
    return request.app.state.traffic_service


@router.get("", response_model=List[str], summary="List all junctions")
async def list_junctions(service: TrafficService = Depends(get_traffic_service)):
    return service.list_all_junctions()


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a new junction")
async def create_junction(
    payload: CreateJunctionRequest,
    service: TrafficService = Depends(get_traffic_service),
):
    jid = payload.junction_id.upper()
    service.get_or_create_runtime(jid)
    return {"message": f"Junction {jid} created successfully.", "junction_id": jid}


@router.get("/{junction_id}", summary="Get junction summary")
async def get_junction_summary(
    junction_id: str,
    service: TrafficService = Depends(get_traffic_service),
):
    jid = junction_id.upper()
    status_data = service.get_junction_status(jid)
    if not status_data:
        raise HTTPException(status_code=404, detail=f"Junction {jid} not found.")
    return status_data


@router.get("/{junction_id}/status", response_model=JunctionStatusResponse, summary="Get junction status")
async def get_junction_status(
    junction_id: str,
    service: TrafficService = Depends(get_traffic_service),
):
    jid = junction_id.upper()
    status_data = service.get_junction_status(jid)
    if not status_data:
        raise HTTPException(status_code=404, detail=f"Junction {jid} not found.")
    return status_data


@router.post("/{junction_id}/commands", response_model=CommandResponse, summary="Execute manual override command")
async def execute_command(
    junction_id: str,
    payload: ManualCommandRequest,
    service: TrafficService = Depends(get_traffic_service),
):
    jid = junction_id.upper()
    success, message, code = await service.process_manual_command(
        junction_id=jid,
        command=payload.command,
        direction=payload.direction,
    )
    if not success:
        raise HTTPException(status_code=code, detail=message)
    return CommandResponse(success=True, message=message)


@router.post("/{junction_id}/config", summary="Update junction simulation speed and durations")
async def configure_simulation(
    junction_id: str,
    payload: SimSpeedRequest,
    service: TrafficService = Depends(get_traffic_service),
):
    jid = junction_id.upper()
    runtime = service.get_or_create_runtime(jid)
    runtime.time_scale = payload.time_scale
    if payload.green_duration:
        runtime.green_duration = payload.green_duration
    if payload.yellow_duration:
        runtime.yellow_duration = payload.yellow_duration

    return {
        "message": f"Junction {jid} configuration updated.",
        "time_scale": runtime.time_scale,
        "green_duration": runtime.green_duration,
        "yellow_duration": runtime.yellow_duration,
    }
