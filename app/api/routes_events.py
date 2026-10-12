"""
API Routes - Sensor Events and Controller Simulation
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from app.api.schemas import (
    ControllerEventRequest,
    SensorEventRequest,
    SensorEventResponse,
)
from app.application.traffic_service import TrafficService
from app.domain.models import SensorEvent

router = APIRouter(prefix="/api", tags=["Events"])


def get_traffic_service(request: Request) -> TrafficService:
    return request.app.state.traffic_service


@router.post("/sensor-events", summary="Submit a vehicle detection event")
async def receive_sensor_event(
    payload: SensorEventRequest,
    response: Response,
    service: TrafficService = Depends(get_traffic_service),
):
    event = SensorEvent(
        event_id=payload.event_id,
        junction_id=payload.junction_id.upper(),
        direction=payload.direction,
        event_type=payload.event_type,
        vehicle_id=payload.vehicle_id,
        vehicle_type=payload.vehicle_type,
        sequence_no=payload.sequence_no,
        timestamp=payload.timestamp,
    )

    success, message, code = await service.process_sensor_event(event)
    response.status_code = code

    if not success and code >= 400:
        raise HTTPException(status_code=code, detail=message)

    return SensorEventResponse(
        success=success,
        message=message,
        event_id=payload.event_id,
    )


@router.post("/controller-events", summary="Simulate controller response or ACK")
async def receive_controller_event(
    payload: ControllerEventRequest,
    service: TrafficService = Depends(get_traffic_service),
):
    success, message, code = await service.process_controller_event(
        command_id=payload.command_id,
        junction_id=payload.junction_id.upper(),
        status=payload.status,
        actual_state=payload.actual_state,
        device_type=payload.device_type,
        direction=payload.direction,
    )

    if not success:
        raise HTTPException(status_code=code, detail=message)

    return {"success": True, "message": message}
