"""
Pure Domain Layer - Safety Invariants and Validation
Protects the system against conflicting green lights, direct state jumps, and illegal commands.
"""
from typing import Dict
from app.domain.models import Direction, SignalColor, TrafficPhase, JunctionState


class SafetyInvariantViolation(Exception):
    """Raised when an operation would violate safety invariants."""
    pass


def is_conflicting_green(signals: Dict[str, SignalColor]) -> bool:
    """
    Returns True if conflicting traffic phases simultaneously receive GREEN.
    NORTH or SOUTH is GREEN at the same time as EAST or WEST is GREEN.
    """
    ns_green = (signals.get(Direction.NORTH.value) == SignalColor.GREEN or
                signals.get(Direction.SOUTH.value) == SignalColor.GREEN)
    ew_green = (signals.get(Direction.EAST.value) == SignalColor.GREEN or
                signals.get(Direction.WEST.value) == SignalColor.GREEN)
    return ns_green and ew_green


def validate_signals_safety(signals: Dict[str, SignalColor]) -> None:
    """
    Asserts that signal assignments do not violate safety rules.
    Raises SafetyInvariantViolation if unsafe.
    """
    if is_conflicting_green(signals):
        raise SafetyInvariantViolation(
            f"Safety Invariant 1 Violated: Conflicting phases cannot both have GREEN! Signals: {signals}"
        )


def validate_transition_path(from_phase: TrafficPhase, to_phase: TrafficPhase, intermediate_step: str) -> None:
    """
    Asserts that a GREEN phase does not transition directly into a conflicting GREEN phase.
    Transition must move through YELLOW and ALL_RED.
    """
    if from_phase != to_phase and intermediate_step not in ("YELLOW", "ALL_RED"):
        raise SafetyInvariantViolation(
            f"Safety Invariant 2 Violated: Direct transition from {from_phase} to {to_phase} is strictly prohibited."
        )


def get_phase_for_direction(direction: Direction) -> TrafficPhase:
    """
    Maps a direction to its corresponding traffic phase.
    """
    if direction in (Direction.NORTH, Direction.SOUTH):
        return TrafficPhase.NORTH_SOUTH
    return TrafficPhase.EAST_WEST


def get_conflicting_phase(phase: TrafficPhase) -> TrafficPhase:
    """
    Returns the conflicting phase for a given phase.
    """
    if phase == TrafficPhase.NORTH_SOUTH:
        return TrafficPhase.EAST_WEST
    elif phase == TrafficPhase.EAST_WEST:
        return TrafficPhase.NORTH_SOUTH
    return TrafficPhase.ALL_RED
