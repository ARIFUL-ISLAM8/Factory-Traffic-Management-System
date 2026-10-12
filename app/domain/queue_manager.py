"""
Pure Domain Layer - Queue Management & Priority Scheduling
Manages waiting traffic, vehicle types, clearance, and starvation-free phase selection.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from app.domain.models import Direction, TrafficPhase, VehicleRecord, VehicleType
from app.config import (
    PRIORITY_WEIGHTS,
    QUEUE_SIZE_WEIGHT,
    WAIT_TIME_WEIGHT_PER_SECOND,
    MAX_STARVATION_SECONDS,
)


class QueueManager:
    """
    Maintains queues of waiting vehicles per direction and determines scheduling priorities.
    """
    def __init__(self, junction_id: str):
        self.junction_id = junction_id
        # Direction -> List of VehicleRecord
        self._queues: Dict[str, List[VehicleRecord]] = {
            Direction.NORTH.value: [],
            Direction.SOUTH.value: [],
            Direction.EAST.value: [],
            Direction.WEST.value: [],
        }

    def get_counts(self) -> Dict[str, int]:
        """Returns vehicle count per direction. Always >= 0."""
        return {d: len(vehicles) for d, vehicles in self._queues.items()}

    def get_vehicles(self, direction: Direction) -> List[VehicleRecord]:
        return list(self._queues.get(direction.value, []))

    def add_vehicle(
        self,
        vehicle_id: str,
        vehicle_type: VehicleType,
        direction: Direction,
        sequence_no: int,
        sensor_timestamp: str,
        server_timestamp: Optional[float] = None,
    ) -> bool:
        """
        Enqueues a vehicle if not already present in this direction.
        Returns True if added, False if duplicate vehicle in queue.
        """
        dir_queue = self._queues[direction.value]
        # Check if this vehicle is already in the queue
        for existing in dir_queue:
            if existing.vehicle_id == vehicle_id:
                return False  # Already waiting

        arrival_time = server_timestamp if server_timestamp is not None else datetime.now(timezone.utc).timestamp()
        record = VehicleRecord(
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            direction=direction,
            sequence_no=sequence_no,
            sensor_timestamp=sensor_timestamp,
            server_arrived_at=arrival_time,
        )
        dir_queue.append(record)
        return True

    def remove_vehicle(self, vehicle_id: str, direction: Direction) -> bool:
        """
        Removes a vehicle by vehicle_id from the direction queue.
        If vehicle_id is unknown or queue is empty, safely removes oldest vehicle (FIFO) if available.
        Ensures queue count never drops below 0.
        """
        dir_queue = self._queues[direction.value]
        if not dir_queue:
            return False  # Nothing to remove, queue remains 0

        # Try to find specific vehicle
        for idx, v in enumerate(dir_queue):
            if v.vehicle_id == vehicle_id:
                dir_queue.pop(idx)
                return True

        # If vehicle_id didn't match, pop oldest FIFO to maintain correct physical count
        dir_queue.pop(0)
        return True

    def calculate_phase_score(self, phase: TrafficPhase, current_time: Optional[float] = None) -> float:
        """
        Calculates scheduling priority score for a traffic phase.
        Score = (Queue Count * Weight) + Highest Priority Bonus + (Waiting Time * Weight) + Starvation Bonus
        """
        now = current_time if current_time is not None else datetime.now(timezone.utc).timestamp()
        directions = (
            [Direction.NORTH.value, Direction.SOUTH.value]
            if phase == TrafficPhase.NORTH_SOUTH
            else [Direction.EAST.value, Direction.WEST.value]
        )

        total_vehicles = 0
        max_priority_weight = 0.0
        max_wait_seconds = 0.0

        for d in directions:
            vehicles = self._queues[d]
            total_vehicles += len(vehicles)
            for v in vehicles:
                p_weight = PRIORITY_WEIGHTS.get(v.vehicle_type.value, 10.0)
                if p_weight > max_priority_weight:
                    max_priority_weight = p_weight

                wait_time = max(0.0, now - v.server_arrived_at)
                if wait_time > max_wait_seconds:
                    max_wait_seconds = wait_time

        if total_vehicles == 0:
            return 0.0

        score = (
            (total_vehicles * QUEUE_SIZE_WEIGHT)
            + max_priority_weight
            + (max_wait_seconds * WAIT_TIME_WEIGHT_PER_SECOND)
        )

        # Starvation protection: if vehicles have waited beyond threshold, boost heavily
        if max_wait_seconds > MAX_STARVATION_SECONDS:
            score += 200.0 + (max_wait_seconds - MAX_STARVATION_SECONDS) * 10.0

        return score

    def select_next_phase(
        self, current_phase: TrafficPhase, current_time: Optional[float] = None
    ) -> Tuple[TrafficPhase, str]:
        """
        Evaluates current queues and returns the recommended next phase and reasoning.
        Avoids unnecessary switching if the other phase has no waiting traffic.
        """
        ns_score = self.calculate_phase_score(TrafficPhase.NORTH_SOUTH, current_time)
        ew_score = self.calculate_phase_score(TrafficPhase.EAST_WEST, current_time)

        # If neither has vehicles, stay in current phase
        if ns_score == 0 and ew_score == 0:
            return current_phase, "No waiting traffic detected on either phase. Staying in current phase."

        # Switching threshold: only switch if the competing phase has meaningfully higher score
        # to avoid unnecessary rapid oscillating
        SWITCH_THRESHOLD = 5.0

        if current_phase == TrafficPhase.NORTH_SOUTH:
            if ew_score > ns_score + SWITCH_THRESHOLD:
                return TrafficPhase.EAST_WEST, f"EAST_WEST score ({ew_score:.1f}) exceeds NORTH_SOUTH ({ns_score:.1f}). Switching."
            return TrafficPhase.NORTH_SOUTH, f"NORTH_SOUTH serving active traffic (Score: {ns_score:.1f} vs EW: {ew_score:.1f})."
        else:
            if ns_score > ew_score + SWITCH_THRESHOLD:
                return TrafficPhase.NORTH_SOUTH, f"NORTH_SOUTH score ({ns_score:.1f}) exceeds EAST_WEST ({ew_score:.1f}). Switching."
            return TrafficPhase.EAST_WEST, f"EAST_WEST serving active traffic (Score: {ew_score:.1f} vs NS: {ns_score:.1f})."

    def has_emergency(self, direction: Direction) -> bool:
        """Returns True if any vehicle in the direction is an EMERGENCY vehicle."""
        for v in self._queues[direction.value]:
            if v.vehicle_type == VehicleType.EMERGENCY:
                return True
        return False
