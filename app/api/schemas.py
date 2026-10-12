"""
API Schemas - Request and Response validation using Pydantic v2
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from app.domain.models import Direction, SignalColor, VehicleType


# -------------------------------------------------------------
# Sensor Event Schemas
# -------------------------------------------------------------
class SensorEventRequest(BaseModel):
    event_id: str = Field(..., json_schema_extra={"example": "evt-10001"}, description="Unique sensor event identifier")
    junction_id: str = Field(..., json_schema_extra={"example": "A"}, description="Target junction ID")
    direction: Direction = Field(..., json_schema_extra={"example": "NORTH"}, description="Direction of the vehicle")
    event_type: str = Field(..., json_schema_extra={"example": "VEHICLE_ARRIVED"}, description="VEHICLE_ARRIVED or VEHICLE_CLEARED")
    vehicle_id: str = Field(..., json_schema_extra={"example": "VH-501"}, description="Vehicle ID")
    vehicle_type: Optional[VehicleType] = Field(None, json_schema_extra={"example": "TRUCK"}, description="Vehicle category")
    sequence_no: int = Field(0, json_schema_extra={"example": 1501}, description="Sensor event sequence number")
    timestamp: str = Field(..., json_schema_extra={"example": "2026-10-05T10:15:20Z"}, description="Sensor UTC ISO timestamp")


class SensorEventResponse(BaseModel):
    success: bool
    message: str
    event_id: str


# -------------------------------------------------------------
# Manual Command Schemas
# -------------------------------------------------------------
class ManualCommandRequest(BaseModel):
    command: str = Field(..., json_schema_extra={"example": "MANUAL_GREEN_REQUEST"}, description="MANUAL_GREEN_REQUEST or RETURN_TO_AUTOMATIC")
    direction: Optional[Direction] = Field(None, json_schema_extra={"example": "WEST"}, description="Direction to prioritize")


class CommandResponse(BaseModel):
    success: bool
    message: str


# -------------------------------------------------------------
# Controller Event / Acknowledgement Schemas
# -------------------------------------------------------------
class ControllerEventRequest(BaseModel):
    command_id: Optional[str] = Field(None, json_schema_extra={"example": "cmd-8001"}, description="Command ID being acknowledged")
    junction_id: str = Field(..., json_schema_extra={"example": "A"}, description="Junction ID")
    status: str = Field(..., json_schema_extra={"example": "ACK"}, description="ACK, OFFLINE, ONLINE, or ERROR")
    actual_state: Optional[SignalColor] = Field(None, json_schema_extra={"example": "GREEN"}, description="Controller-confirmed signal state")
    device_type: Optional[str] = Field(None, json_schema_extra={"example": "SIGNAL_CONTROLLER"}, description="Device type")
    direction: Optional[Direction] = Field(None, json_schema_extra={"example": "SOUTH"}, description="Device direction")
    timestamp: Optional[str] = Field(None, json_schema_extra={"example": "2026-10-05T10:31:00Z"})


# -------------------------------------------------------------
# Junction Status Schemas
# -------------------------------------------------------------
class JunctionStatusResponse(BaseModel):
    junction_id: str
    mode: str
    phase: str
    controller_status: str
    is_in_transition: bool
    transition_step: Optional[str] = None
    desired_signals: Dict[str, str]
    actual_signals: Dict[str, str]
    queues: Dict[str, int]
    active_alerts: List[str] = []
    pending_command_id: Optional[str] = None


class CreateJunctionRequest(BaseModel):
    junction_id: str = Field(..., json_schema_extra={"example": "B"}, description="ID of the new junction")


# -------------------------------------------------------------
# Audit History Response
# -------------------------------------------------------------
class AuditLogEntry(BaseModel):
    junction_id: str
    event_type: str
    direction: Optional[str] = None
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    command_id: Optional[str] = None
    detail: Optional[str] = None
    timestamp: str


# -------------------------------------------------------------
# Simulation Speed Configuration
# -------------------------------------------------------------
class SimSpeedRequest(BaseModel):
    time_scale: float = Field(..., ge=0.1, le=50.0, json_schema_extra={"example": 5.0}, description="Multiplier for signal countdowns")
    green_duration: Optional[float] = Field(None, ge=1.0, json_schema_extra={"example": 30.0})
    yellow_duration: Optional[float] = Field(None, ge=1.0, json_schema_extra={"example": 5.0})
