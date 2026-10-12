"""
Unit Tests: Pure Domain State Machine
Tests core traffic logic in isolation without HTTP requests or database queries.
"""
import pytest
from app.domain.models import (
    Direction,
    JunctionMode,
    SignalColor,
    TrafficPhase,
    ControllerStatus,
)
from app.domain.state_machine import JunctionStateMachine
from app.domain.safety import SafetyInvariantViolation, is_conflicting_green


def test_initial_state_safety():
    """Initial junction state must be safe (no conflicting green)."""
    sm = JunctionStateMachine("A")
    signals = sm.get_desired_signals()
    assert signals[Direction.NORTH.value] == SignalColor.GREEN
    assert signals[Direction.SOUTH.value] == SignalColor.GREEN
    assert signals[Direction.EAST.value] == SignalColor.RED
    assert signals[Direction.WEST.value] == SignalColor.RED
    assert not is_conflicting_green(signals)


def test_deterministic_three_step_transition():
    """Transitions must follow GREEN -> YELLOW -> ALL_RED -> TARGET GREEN sequence."""
    sm = JunctionStateMachine("A")
    assert sm.state.current_phase == TrafficPhase.NORTH_SOUTH

    # Start transition to EAST_WEST
    started, _ = sm.start_transition_to_phase(TrafficPhase.EAST_WEST)
    assert started
    assert sm.state.is_in_transition

    # Step 1: YELLOW
    yellow_signals = sm.step_to_yellow()
    assert yellow_signals[Direction.NORTH.value] == SignalColor.YELLOW
    assert yellow_signals[Direction.SOUTH.value] == SignalColor.YELLOW
    assert yellow_signals[Direction.EAST.value] == SignalColor.RED
    assert yellow_signals[Direction.WEST.value] == SignalColor.RED
    assert not is_conflicting_green(yellow_signals)

    # Step 2: ALL_RED Clearance
    all_red_signals = sm.step_to_all_red()
    assert all(color == SignalColor.RED for color in all_red_signals.values())
    assert not is_conflicting_green(all_red_signals)

    # Step 3: TARGET GREEN
    target_signals = sm.step_to_target_green()
    assert target_signals[Direction.EAST.value] == SignalColor.GREEN
    assert target_signals[Direction.WEST.value] == SignalColor.GREEN
    assert target_signals[Direction.NORTH.value] == SignalColor.RED
    assert target_signals[Direction.SOUTH.value] == SignalColor.RED
    assert not is_conflicting_green(target_signals)
    assert sm.state.current_phase == TrafficPhase.EAST_WEST
    assert not sm.state.is_in_transition


def test_manual_override_and_return():
    """Manual override forces target phase safely and can return to automatic."""
    sm = JunctionStateMachine("A")
    assert sm.state.mode == JunctionMode.AUTOMATIC

    # Request manual green for EAST
    success, msg = sm.request_manual_green(Direction.EAST)
    assert success
    assert sm.state.mode == JunctionMode.MANUAL
    assert sm.state.target_phase == TrafficPhase.EAST_WEST
    assert sm.state.is_in_transition

    # Return to automatic
    success, msg = sm.return_to_automatic()
    assert success
    assert sm.state.mode == JunctionMode.AUTOMATIC
    assert sm.state.manual_requested_direction is None


def test_emergency_preemption_and_clearance():
    """Emergency vehicle forces priority phase and clears safely."""
    sm = JunctionStateMachine("A")
    assert sm.state.mode == JunctionMode.AUTOMATIC

    # Emergency from WEST while NORTH_SOUTH is GREEN
    success, _ = sm.trigger_emergency(Direction.WEST)
    assert success
    assert sm.state.mode == JunctionMode.EMERGENCY
    assert Direction.WEST in sm.state.active_emergency_directions
    assert sm.state.target_phase == TrafficPhase.EAST_WEST

    # Clear emergency
    success, _ = sm.clear_emergency(Direction.WEST)
    assert success
    assert sm.state.mode == JunctionMode.AUTOMATIC
    assert len(sm.state.active_emergency_directions) == 0


def test_controller_offline_safe_failure():
    """Controller failure must force ALL_RED safe degraded state."""
    sm = JunctionStateMachine("A")
    sm.update_controller_status(ControllerStatus.OFFLINE)
    sm.enter_safe_failure_state("Controller OFFLINE")

    assert sm.state.mode == JunctionMode.FAILURE
    assert sm.state.controller_status == ControllerStatus.OFFLINE
    signals = sm.get_desired_signals()
    assert all(c == SignalColor.RED for c in signals.values())
