"""
Infrastructure Layer - Controller Port and REST Simulator
Decouples domain logic from hardware protocols (REST simulation / MQTT).
"""
import uuid
from typing import Optional, Protocol
from app.domain.models import Direction, SignalColor


class ControllerPort(Protocol):
    """Abstract port for communicating with physical traffic controllers."""

    async def send_signal_command(
        self, junction_id: str, direction: Optional[Direction], requested_state: SignalColor
    ) -> str:
        """Sends command to controller and returns command_id."""
        ...


class SimulatedControllerAdapter:
    """
    Simulated Controller Adapter conforming to ControllerPort.
    Generates unique cmd-XXXX identifiers.
    Can be seamlessly substituted with an MQTTAdapter in production.
    """

    def __init__(self, auto_ack: bool = True):
        self.auto_ack = auto_ack
        self._command_counter = 8000

    async def send_signal_command(
        self, junction_id: str, direction: Optional[Direction], requested_state: SignalColor
    ) -> str:
        self._command_counter += 1
        command_id = f"cmd-{self._command_counter}"
        # In real MQTT/REST client, this publishes to broker or calls external device
        return command_id
