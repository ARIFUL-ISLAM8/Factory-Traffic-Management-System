"""
Infrastructure Layer - Repositories
Implements durable storage and retrieval for state, events, audit logs, and commands.
"""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional
from app.domain.models import (
    Direction,
    JunctionMode,
    JunctionState,
    SignalColor,
    TrafficPhase,
    ControllerStatus,
    VehicleRecord,
    VehicleType,
)
from app.infrastructure.database import get_db_connection


class Repository:
    """Consolidated repository for junction state, queues, event deduplication, and audit trail."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

    # -------------------------------------------------------------
    # Junction State Persistence
    # -------------------------------------------------------------
    def save_junction(self, state: JunctionState) -> None:
        conn = self._conn()
        try:
            now = datetime.now(timezone.utc).timestamp()
            desired_json = json.dumps({k: v.value for k, v in state.desired_signals.items()})
            actual_json = json.dumps({k: v.value for k, v in state.actual_signals.items()})

            conn.execute(
                """
                INSERT INTO junctions (junction_id, mode, current_phase, controller_status, desired_signals, actual_signals, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(junction_id) DO UPDATE SET
                    mode=excluded.mode,
                    current_phase=excluded.current_phase,
                    controller_status=excluded.controller_status,
                    desired_signals=excluded.desired_signals,
                    actual_signals=excluded.actual_signals,
                    updated_at=excluded.updated_at
                """,
                (
                    state.junction_id,
                    state.mode.value,
                    state.current_phase.value,
                    state.controller_status.value,
                    desired_json,
                    actual_json,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_junction(self, junction_id: str) -> Optional[JunctionState]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM junctions WHERE junction_id = ?", (junction_id,)).fetchone()
            if not row:
                return None

            desired_dict = json.loads(row["desired_signals"])
            actual_dict = json.loads(row["actual_signals"])

            desired_signals = {k: SignalColor(v) for k, v in desired_dict.items()}
            actual_signals = {k: SignalColor(v) for k, v in actual_dict.items()}

            return JunctionState(
                junction_id=row["junction_id"],
                mode=JunctionMode(row["mode"]),
                current_phase=TrafficPhase(row["current_phase"]),
                controller_status=ControllerStatus(row["controller_status"]),
                desired_signals=desired_signals,
                actual_signals=actual_signals,
                is_in_transition=False,
                phase_started_at=row["updated_at"],
            )
        finally:
            conn.close()

    def list_junction_ids(self) -> List[str]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT junction_id FROM junctions ORDER BY junction_id ASC").fetchall()
            return [r["junction_id"] for r in rows]
        finally:
            conn.close()

    # -------------------------------------------------------------
    # Event Deduplication
    # -------------------------------------------------------------
    def is_event_processed(self, event_id: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute("SELECT 1 FROM sensor_events WHERE event_id = ?", (event_id,)).fetchone()
            return row is not None
        finally:
            conn.close()

    def record_sensor_event(
        self,
        event_id: str,
        junction_id: str,
        direction: str,
        event_type: str,
        vehicle_id: str,
        vehicle_type: Optional[str],
        sequence_no: int,
        sensor_timestamp: str,
    ) -> bool:
        """
        Inserts sensor event. If duplicate, returns False.
        """
        conn = self._conn()
        try:
            now = datetime.now(timezone.utc).timestamp()
            conn.execute(
                """
                INSERT INTO sensor_events (event_id, junction_id, direction, event_type, vehicle_id, vehicle_type, sequence_no, sensor_timestamp, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    junction_id,
                    direction,
                    event_type,
                    vehicle_id,
                    vehicle_type,
                    sequence_no,
                    sensor_timestamp,
                    now,
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    # -------------------------------------------------------------
    # Persistent Queues (For Server Crash Recovery)
    # -------------------------------------------------------------
    def persist_enqueue_vehicle(self, junction_id: str, record: VehicleRecord) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO vehicle_queues (junction_id, direction, vehicle_id, vehicle_type, sequence_no, sensor_timestamp, arrived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    junction_id,
                    record.direction.value,
                    record.vehicle_id,
                    record.vehicle_type.value,
                    record.sequence_no,
                    record.sensor_timestamp,
                    record.server_arrived_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def persist_dequeue_vehicle(self, junction_id: str, direction: str, vehicle_id: str) -> None:
        conn = self._conn()
        try:
            # If vehicle_id exists in queue, delete it
            cur = conn.execute(
                "DELETE FROM vehicle_queues WHERE junction_id = ? AND direction = ? AND vehicle_id = ?",
                (junction_id, direction, vehicle_id),
            )
            if cur.rowcount == 0:
                # Fallback: remove oldest FIFO
                conn.execute(
                    """
                    DELETE FROM vehicle_queues WHERE id = (
                        SELECT id FROM vehicle_queues WHERE junction_id = ? AND direction = ? ORDER BY id ASC LIMIT 1
                    )
                    """,
                    (junction_id, direction),
                )
            conn.commit()
        finally:
            conn.close()

    def load_persisted_queues(self, junction_id: str) -> Dict[str, List[VehicleRecord]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM vehicle_queues WHERE junction_id = ? ORDER BY id ASC",
                (junction_id,),
            ).fetchall()
            result: Dict[str, List[VehicleRecord]] = {
                Direction.NORTH.value: [],
                Direction.SOUTH.value: [],
                Direction.EAST.value: [],
                Direction.WEST.value: [],
            }
            for r in rows:
                v = VehicleRecord(
                    vehicle_id=r["vehicle_id"],
                    vehicle_type=VehicleType(r["vehicle_type"]),
                    direction=Direction(r["direction"]),
                    sequence_no=r["sequence_no"],
                    sensor_timestamp=r["sensor_timestamp"],
                    server_arrived_at=r["arrived_at"],
                )
                if r["direction"] in result:
                    result[r["direction"]].append(v)
            return result
        finally:
            conn.close()

    # -------------------------------------------------------------
    # Controller Commands
    # -------------------------------------------------------------
    def record_controller_command(
        self,
        command_id: str,
        junction_id: str,
        direction: Optional[str],
        requested_state: str,
    ) -> None:
        conn = self._conn()
        try:
            now = datetime.now(timezone.utc).timestamp()
            conn.execute(
                """
                INSERT INTO controller_commands (command_id, junction_id, direction, requested_state, status, created_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?)
                """,
                (command_id, junction_id, direction, requested_state, now),
            )
            conn.commit()
        finally:
            conn.close()

    def acknowledge_controller_command(
        self,
        command_id: str,
        status: str,
        actual_state: Optional[str],
    ) -> bool:
        conn = self._conn()
        try:
            now = datetime.now(timezone.utc).timestamp()
            cur = conn.execute(
                """
                UPDATE controller_commands
                SET status = ?, actual_state = ?, acknowledged_at = ?
                WHERE command_id = ?
                """,
                (status, actual_state, now, command_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_controller_command(self, command_id: str) -> Optional[dict]:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM controller_commands WHERE command_id = ?", (command_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # -------------------------------------------------------------
    # Audit Logs (Section 11)
    # -------------------------------------------------------------
    def log_audit(
        self,
        junction_id: str,
        event_type: str,
        direction: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        command_id: Optional[str] = None,
        detail: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        conn = self._conn()
        try:
            ts = timestamp or datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO audit_logs (junction_id, event_type, direction, previous_state, new_state, command_id, detail, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (junction_id, event_type, direction, previous_state, new_state, command_id, detail, ts),
            )
            conn.commit()
        finally:
            conn.close()

    def get_audit_logs(self, junction_id: str, limit: int = 50) -> List[Dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT junction_id, event_type, direction, previous_state, new_state, command_id, detail, timestamp
                FROM audit_logs
                WHERE junction_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (junction_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
