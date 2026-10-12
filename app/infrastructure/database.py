"""
Infrastructure Layer - SQLite Database Connection & Schema Migration
Provides durable persistence for junction state, queues, event deduplication, and audit logs.
"""
import sqlite3
import os
from typing import Optional
from app.config import DB_PATH


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates a connection to SQLite database with row factory enabled."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for high concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_database(db_path: Optional[str] = None) -> None:
    """Initializes tables and indexes if they do not exist."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.executescript("""
    -- Junction configuration and state
    CREATE TABLE IF NOT EXISTS junctions (
        junction_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        current_phase TEXT NOT NULL,
        controller_status TEXT NOT NULL,
        desired_signals TEXT NOT NULL,
        actual_signals TEXT NOT NULL,
        updated_at REAL NOT NULL
    );

    -- Deduplication and event store
    CREATE TABLE IF NOT EXISTS sensor_events (
        event_id TEXT PRIMARY KEY,
        junction_id TEXT NOT NULL,
        direction TEXT NOT NULL,
        event_type TEXT NOT NULL,
        vehicle_id TEXT NOT NULL,
        vehicle_type TEXT,
        sequence_no INTEGER DEFAULT 0,
        sensor_timestamp TEXT NOT NULL,
        processed_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sensor_events_junction ON sensor_events(junction_id);

    -- Queued vehicles for durable restart recovery
    CREATE TABLE IF NOT EXISTS vehicle_queues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        junction_id TEXT NOT NULL,
        direction TEXT NOT NULL,
        vehicle_id TEXT NOT NULL,
        vehicle_type TEXT NOT NULL,
        sequence_no INTEGER DEFAULT 0,
        sensor_timestamp TEXT NOT NULL,
        arrived_at REAL NOT NULL,
        UNIQUE(junction_id, direction, vehicle_id)
    );
    CREATE INDEX IF NOT EXISTS idx_vehicle_queues ON vehicle_queues(junction_id, direction);

    -- Controller commands & ACKs
    CREATE TABLE IF NOT EXISTS controller_commands (
        command_id TEXT PRIMARY KEY,
        junction_id TEXT NOT NULL,
        direction TEXT,
        requested_state TEXT NOT NULL,
        status TEXT NOT NULL,
        actual_state TEXT,
        created_at REAL NOT NULL,
        acknowledged_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_controller_commands_status ON controller_commands(junction_id, status);

    -- Audit history log (mandatory per Section 11)
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        junction_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        direction TEXT,
        previous_state TEXT,
        new_state TEXT,
        command_id TEXT,
        detail TEXT,
        timestamp TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_audit_logs_junction ON audit_logs(junction_id, id DESC);
    """)

    conn.commit()
    conn.close()
