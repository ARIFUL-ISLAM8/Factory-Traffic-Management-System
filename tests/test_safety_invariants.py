"""
Unit Tests: Safety Invariants
Asserts mathematical guarantees against conflicting green signals.
"""
import pytest
from app.domain.models import Direction, SignalColor, TrafficPhase
from app.domain.safety import (
    SafetyInvariantViolation,
    is_conflicting_green,
    validate_signals_safety,
    validate_transition_path,
)


def test_conflicting_green_detection():
    """Detects when NS and EW are green at the same time."""
    safe_ns = {
        Direction.NORTH.value: SignalColor.GREEN,
        Direction.SOUTH.value: SignalColor.GREEN,
        Direction.EAST.value: SignalColor.RED,
        Direction.WEST.value: SignalColor.RED,
    }
    assert not is_conflicting_green(safe_ns)

    unsafe_mix = {
        Direction.NORTH.value: SignalColor.GREEN,
        Direction.SOUTH.value: SignalColor.RED,
        Direction.EAST.value: SignalColor.GREEN,
        Direction.WEST.value: SignalColor.RED,
    }
    assert is_conflicting_green(unsafe_mix)

    with pytest.raises(SafetyInvariantViolation):
        validate_signals_safety(unsafe_mix)


def test_illegal_direct_transition_prohibited():
    """A GREEN phase must never transition directly into a conflicting GREEN phase."""
    with pytest.raises(SafetyInvariantViolation):
        validate_transition_path(
            from_phase=TrafficPhase.NORTH_SOUTH,
            to_phase=TrafficPhase.EAST_WEST,
            intermediate_step="DIRECT_GREEN",
        )
