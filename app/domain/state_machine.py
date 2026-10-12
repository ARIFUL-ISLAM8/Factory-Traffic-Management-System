"""
Pure Domain Layer - Junction State Machine
Deterministic state machine enforcing safety invariants during automatic, manual, and emergency modes.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from app.domain.models import (
    Direction,
    JunctionMode,
    JunctionState,
    SignalColor,
    TrafficPhase,
    ControllerStatus,
)
from app.domain.safety import (
    validate_signals_safety,
    get_phase_for_direction,
    SafetyInvariantViolation,
)


class JunctionStateMachine:
    """
    Controls signal state transitions, operating modes, and safety invariants for a junction.
    """

    def __init__(self, junction_id: str, initial_state: Optional[JunctionState] = None):
        self.junction_id = junction_id
        if initial_state:
            self.state = initial_state
        else:
            self.state = JunctionState(
                junction_id=junction_id,
                mode=JunctionMode.AUTOMATIC,
                current_phase=TrafficPhase.NORTH_SOUTH,
                is_in_transition=False,
                transition_step=None,
                phase_started_at=datetime.now(timezone.utc).timestamp(),
                controller_status=ControllerStatus.ONLINE,
                desired_signals={
                    Direction.NORTH.value: SignalColor.GREEN,
                    Direction.SOUTH.value: SignalColor.GREEN,
                    Direction.EAST.value: SignalColor.RED,
                    Direction.WEST.value: SignalColor.RED,
                },
                actual_signals={
                    Direction.NORTH.value: SignalColor.GREEN,
                    Direction.SOUTH.value: SignalColor.GREEN,
                    Direction.EAST.value: SignalColor.RED,
                    Direction.WEST.value: SignalColor.RED,
                },
            )
        validate_signals_safety(self.state.desired_signals)

    def get_desired_signals(self) -> Dict[str, SignalColor]:
        return dict(self.state.desired_signals)

    def get_actual_signals(self) -> Dict[str, SignalColor]:
        return dict(self.state.actual_signals)

    def update_controller_status(self, status: ControllerStatus, detail: Optional[str] = None):
        """Updates controller connectivity status and handles degradation."""
        self.state.controller_status = status
        if status == ControllerStatus.OFFLINE:
            self.state.mode = JunctionMode.FAILURE
            if "Controller reported OFFLINE" not in self.state.active_alerts:
                self.state.active_alerts.append("Controller reported OFFLINE")
        elif status == ControllerStatus.ONLINE:
            self.state.active_alerts = [a for a in self.state.active_alerts if "OFFLINE" not in a]
            if self.state.mode == JunctionMode.FAILURE:
                self.state.mode = JunctionMode.AUTOMATIC

    def confirm_controller_signal(self, direction: Optional[Direction], confirmed_state: SignalColor):
        """Updates actual_signals when controller confirms ACK."""
        if direction:
            self.state.actual_signals[direction.value] = confirmed_state
        else:
            # If confirmed for the entire junction / phase
            for d in Direction:
                self.state.actual_signals[d.value] = self.state.desired_signals[d.value]

    def start_transition_to_phase(self, target_phase: TrafficPhase) -> Tuple[bool, str]:
        """
        Initiates a safe transition sequence to target_phase.
        If already in target_phase or already transitioning, returns appropriate status.
        """
        if self.state.controller_status == ControllerStatus.OFFLINE:
            return False, "Cannot transition: Controller is OFFLINE (Junction in FAILURE mode)."

        if self.state.current_phase == target_phase and not self.state.is_in_transition:
            return False, f"Already in phase {target_phase}."

        if self.state.is_in_transition:
            # If already transitioning to this exact target, ignore
            if self.state.target_phase == target_phase:
                return False, f"Transition to {target_phase} already in progress."
            # If target changed (e.g. emergency preemption came in while transitioning)
            self.state.target_phase = target_phase
            return True, f"Updated target phase to {target_phase} during active transition."

        self.state.is_in_transition = True
        self.state.target_phase = target_phase
        return True, f"Transition started towards {target_phase}."

    def step_to_yellow(self) -> Dict[str, SignalColor]:
        """
        Transition Step 1: Set currently GREEN directions to YELLOW.
        Conflicting directions remain RED.
        """
        new_signals = dict(self.state.desired_signals)
        for direction, color in self.state.desired_signals.items():
            if color == SignalColor.GREEN:
                new_signals[direction] = SignalColor.YELLOW

        validate_signals_safety(new_signals)
        self.state.desired_signals = new_signals
        self.state.transition_step = "YELLOW"
        return dict(self.state.desired_signals)

    def step_to_all_red(self) -> Dict[str, SignalColor]:
        """
        Transition Step 2: Set ALL directions to RED for clearance buffer.
        """
        new_signals = {
            Direction.NORTH.value: SignalColor.RED,
            Direction.SOUTH.value: SignalColor.RED,
            Direction.EAST.value: SignalColor.RED,
            Direction.WEST.value: SignalColor.RED,
        }
        self.state.desired_signals = new_signals
        self.state.transition_step = "ALL_RED"
        return dict(self.state.desired_signals)

    def step_to_target_green(self) -> Dict[str, SignalColor]:
        """
        Transition Step 3: Set target phase directions to GREEN, conflicting to RED.
        Marks transition as complete.
        """
        if not self.state.target_phase:
            target = TrafficPhase.NORTH_SOUTH
        else:
            target = self.state.target_phase

        new_signals = {
            Direction.NORTH.value: SignalColor.RED,
            Direction.SOUTH.value: SignalColor.RED,
            Direction.EAST.value: SignalColor.RED,
            Direction.WEST.value: SignalColor.RED,
        }

        if target == TrafficPhase.NORTH_SOUTH:
            new_signals[Direction.NORTH.value] = SignalColor.GREEN
            new_signals[Direction.SOUTH.value] = SignalColor.GREEN
        elif target == TrafficPhase.EAST_WEST:
            new_signals[Direction.EAST.value] = SignalColor.GREEN
            new_signals[Direction.WEST.value] = SignalColor.GREEN

        validate_signals_safety(new_signals)
        self.state.desired_signals = new_signals
        self.state.current_phase = target
        self.state.target_phase = None
        self.state.is_in_transition = False
        self.state.transition_step = None
        self.state.phase_started_at = datetime.now(timezone.utc).timestamp()
        return dict(self.state.desired_signals)

    def request_manual_green(self, direction: Direction) -> Tuple[bool, str]:
        """
        Requests manual green for a direction.
        Sets mode to MANUAL and triggers safe transition.
        """
        if self.state.controller_status == ControllerStatus.OFFLINE:
            return False, "Cannot switch to manual mode: Controller is OFFLINE."

        target_phase = get_phase_for_direction(direction)
        self.state.mode = JunctionMode.MANUAL
        self.state.manual_requested_direction = direction
        self.state.manual_requested_at = datetime.now(timezone.utc).timestamp()

        # If already green in this phase, keep it
        if self.state.current_phase == target_phase and not self.state.is_in_transition:
            return True, f"Manual green active for {direction.value} ({target_phase.value})."

        self.start_transition_to_phase(target_phase)
        return True, f"Manual green requested for {direction.value}. Initiating safe transition."

    def return_to_automatic(self) -> Tuple[bool, str]:
        """
        Returns junction from MANUAL or EMERGENCY back to AUTOMATIC.
        """
        self.state.mode = JunctionMode.AUTOMATIC
        self.state.manual_requested_direction = None
        self.state.manual_requested_at = None
        self.state.active_emergency_directions.clear()
        return True, "Junction returned to AUTOMATIC mode."

    def trigger_emergency(self, direction: Direction) -> Tuple[bool, str]:
        """
        Triggers emergency preemption for a direction.
        Overrides normal automatic / manual scheduling and forces immediate safe transition.
        """
        if direction not in self.state.active_emergency_directions:
            self.state.active_emergency_directions.append(direction)

        self.state.mode = JunctionMode.EMERGENCY
        target_phase = get_phase_for_direction(direction)

        if self.state.current_phase == target_phase and not self.state.is_in_transition:
            return True, f"Emergency preemption active: Direction {direction.value} already has GREEN."

        self.start_transition_to_phase(target_phase)
        return True, f"Emergency preemption initiated for {direction.value}. Safe transition underway."

    def clear_emergency(self, direction: Direction) -> Tuple[bool, str]:
        """
        Clears emergency in a direction. If no other emergencies, returns to AUTOMATIC.
        """
        if direction in self.state.active_emergency_directions:
            self.state.active_emergency_directions.remove(direction)

        if not self.state.active_emergency_directions:
            if self.state.mode == JunctionMode.EMERGENCY:
                self.state.mode = JunctionMode.AUTOMATIC
            return True, f"Emergency cleared for {direction.value}. Returning to automatic mode."

        return True, f"Emergency cleared for {direction.value}. Other emergencies still active."

    def enter_safe_failure_state(self, reason: str):
        """
        Puts the junction into safe degraded/failure state: ALL_RED.
        """
        self.state.mode = JunctionMode.FAILURE
        self.state.desired_signals = {
            Direction.NORTH.value: SignalColor.RED,
            Direction.SOUTH.value: SignalColor.RED,
            Direction.EAST.value: SignalColor.RED,
            Direction.WEST.value: SignalColor.RED,
        }
        self.state.is_in_transition = False
        self.state.transition_step = None
        if reason not in self.state.active_alerts:
            self.state.active_alerts.append(reason)
