"""
Unit Tests: Queue Manager & Scheduling Priorities
Verifies queue floor invariants, priority weights, and starvation protection.
"""
import time
from app.domain.models import Direction, TrafficPhase, VehicleType
from app.domain.queue_manager import QueueManager


def test_queue_never_drops_below_zero():
    """Ensure queue counts never become negative (-1)."""
    qm = QueueManager("A")
    assert qm.get_counts()[Direction.NORTH.value] == 0

    # Removing from empty queue returns False and leaves count at 0
    removed = qm.remove_vehicle("VH-NONEXISTENT", Direction.NORTH)
    assert not removed
    assert qm.get_counts()[Direction.NORTH.value] == 0


def test_vehicle_arrival_and_clearance():
    """Vehicles enqueue correctly and clear cleanly."""
    qm = QueueManager("A")

    added = qm.add_vehicle("VH-101", VehicleType.TRUCK, Direction.NORTH, 1, "2026-10-08T10:00:00Z")
    assert added
    assert qm.get_counts()[Direction.NORTH.value] == 1

    # Adding same vehicle to same direction is rejected
    duplicate_added = qm.add_vehicle("VH-101", VehicleType.TRUCK, Direction.NORTH, 2, "2026-10-08T10:01:00Z")
    assert not duplicate_added
    assert qm.get_counts()[Direction.NORTH.value] == 1

    # Clear vehicle
    cleared = qm.remove_vehicle("VH-101", Direction.NORTH)
    assert cleared
    assert qm.get_counts()[Direction.NORTH.value] == 0


def test_priority_scheduling_preference():
    """High priority TRUCK gives higher phase score than EMPLOYEE_VEHICLE."""
    qm = QueueManager("A")
    now = time.time()

    # 1 Employee vehicle on NORTH (NORTH_SOUTH phase)
    qm.add_vehicle("VH-EMP", VehicleType.EMPLOYEE_VEHICLE, Direction.NORTH, 1, "t0", server_timestamp=now)

    # 1 Truck on EAST (EAST_WEST phase)
    qm.add_vehicle("VH-TRK", VehicleType.TRUCK, Direction.EAST, 2, "t0", server_timestamp=now)

    ns_score = qm.calculate_phase_score(TrafficPhase.NORTH_SOUTH, current_time=now)
    ew_score = qm.calculate_phase_score(TrafficPhase.EAST_WEST, current_time=now)

    # Truck has weight 50, Employee vehicle has weight 10 -> EW score should be significantly higher
    assert ew_score > ns_score


def test_starvation_prevention():
    """Prolonged wait time increases score to prevent starvation."""
    qm = QueueManager("A")
    now = time.time()

    # Add vehicle arrived 70 seconds ago (starvation threshold is 60s)
    qm.add_vehicle("VH-OLD", VehicleType.EMPLOYEE_VEHICLE, Direction.EAST, 1, "t0", server_timestamp=now - 70.0)

    score = qm.calculate_phase_score(TrafficPhase.EAST_WEST, current_time=now)
    # Score should include starvation bonus (>200)
    assert score > 200.0
