"""
Domain Models and Enums
Clean domain entities with zero external framework dependencies.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class Direction(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class SignalColor(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


class TrafficPhase(str, Enum):
    NORTH_SOUTH = "NORTH_SOUTH"
    EAST_WEST = "EAST_WEST"
    ALL_RED = "ALL_RED"


class VehicleType(str, Enum):
    EMERGENCY = "EMERGENCY"
    TRUCK = "TRUCK"
    FORKLIFT = "FORKLIFT"
    EMPLOYEE_VEHICLE = "EMPLOYEE_VEHICLE"


class JunctionMode(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    FAILURE = "FAILURE"


class ControllerStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


@dataclass
class VehicleRecord:
    vehicle_id: str
    vehicle_type: VehicleType
    direction: Direction
    sequence_no: int
    sensor_timestamp: str
    server_arrived_at: float  # Unix timestamp for starvation tracking


@dataclass
class SensorEvent:
    event_id: str
    junction_id: str
    direction: Direction
    event_type: str  # VEHICLE_ARRIVED, VEHICLE_CLEARED
    vehicle_id: str
    vehicle_type: Optional[VehicleType] = None
    sequence_no: int = 0
    timestamp: str = ""


@dataclass
class ControllerCommand:
    command_id: str
    junction_id: str
    direction: Optional[Direction]
    requested_state: SignalColor
    created_at: float
    status: str = "PENDING"  # PENDING, ACK, TIMEOUT, FAILED
    actual_state: Optional[SignalColor] = None
    acknowledged_at: Optional[float] = None


@dataclass
class JunctionState:
    junction_id: str
    mode: JunctionMode = JunctionMode.AUTOMATIC
    current_phase: TrafficPhase = TrafficPhase.NORTH_SOUTH
    target_phase: Optional[TrafficPhase] = None
    is_in_transition: bool = False
    transition_step: Optional[str] = None  # None, "YELLOW", "ALL_RED"
    phase_started_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    controller_status: ControllerStatus = ControllerStatus.ONLINE
    desired_signals: Dict[str, SignalColor] = field(default_factory=lambda: {
        Direction.NORTH.value: SignalColor.GREEN,
        Direction.SOUTH.value: SignalColor.GREEN,
        Direction.EAST.value: SignalColor.RED,
        Direction.WEST.value: SignalColor.RED,
    })
    actual_signals: Dict[str, SignalColor] = field(default_factory=lambda: {
        Direction.NORTH.value: SignalColor.GREEN,
        Direction.SOUTH.value: SignalColor.GREEN,
        Direction.EAST.value: SignalColor.RED,
        Direction.WEST.value: SignalColor.RED,
    })
    manual_requested_direction: Optional[Direction] = None
    manual_requested_at: Optional[float] = None
    active_emergency_directions: List[Direction] = field(default_factory=list)
    pending_command_id: Optional[str] = None
    active_alerts: List[str] = field(default_factory=list)
