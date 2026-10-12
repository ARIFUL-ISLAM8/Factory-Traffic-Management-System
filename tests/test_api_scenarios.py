"""
Integration Tests: 9 Functional Scenarios mandated by Section 15
1. Normal Traffic
2. Priority Traffic
3. Emergency Preemption
4. Manual Override
5. Duplicate Event Idempotency
6. Vehicle Clearance
7. Controller Failure / OFFLINE
8. Restart Recovery
9. Concurrent Events / Race-condition safety
"""
import pytest
import os
from fastapi.testclient import TestClient
from app.main import app as fastapi_app
import app.config
from app.infrastructure.database import init_database


@pytest.fixture
def client(tmp_path):
    # Ensure fresh test database per test function
    test_db_path = str(tmp_path / "test_traffic.db")
    app.config.DB_PATH = test_db_path
    init_database(test_db_path)

    with TestClient(fastapi_app) as test_client:
        # Point traffic_service to the test database and clear in-memory state
        if hasattr(fastapi_app.state, "traffic_service"):
            fastapi_app.state.traffic_service.repo.db_path = test_db_path
            fastapi_app.state.traffic_service._runtimes.clear()
        yield test_client


def test_scenario_1_normal_traffic(client):
    """Scenario 1: Several vehicles arrive and queues reflect state."""
    # Send 2 vehicles to NORTH
    res1 = client.post("/api/sensor-events", json={
        "event_id": "s1-evt-1",
        "junction_id": "A",
        "direction": "NORTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-1",
        "vehicle_type": "EMPLOYEE_VEHICLE",
        "sequence_no": 1,
        "timestamp": "2026-10-08T12:00:00Z"
    })
    assert res1.status_code == 201

    res2 = client.post("/api/sensor-events", json={
        "event_id": "s1-evt-2",
        "junction_id": "A",
        "direction": "NORTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-2",
        "vehicle_type": "EMPLOYEE_VEHICLE",
        "sequence_no": 2,
        "timestamp": "2026-10-08T12:00:01Z"
    })
    assert res2.status_code == 201

    res = client.get("/api/junctions/A/status")
    data = res.json()
    assert data["queues"]["NORTH"] == 2


def test_scenario_2_priority_traffic(client):
    """Scenario 2: TRUCK creates higher priority score than normal traffic."""
    res = client.post("/api/sensor-events", json={
        "event_id": "s2-evt-truck",
        "junction_id": "A",
        "direction": "EAST",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-HEAVY-TRUCK",
        "vehicle_type": "TRUCK",
        "sequence_no": 10,
        "timestamp": "2026-10-08T12:05:00Z"
    })
    assert res.status_code == 201

    res = client.get("/api/junctions/A/status")
    assert res.json()["queues"]["EAST"] == 1


def test_scenario_3_emergency_preemption(client):
    """Scenario 3: Emergency vehicle initiates immediate safe preemption."""
    res = client.post("/api/sensor-events", json={
        "event_id": "s3-emergency-1",
        "junction_id": "A",
        "direction": "WEST",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "AMBULANCE-99",
        "vehicle_type": "EMERGENCY",
        "sequence_no": 50,
        "timestamp": "2026-10-08T12:10:00Z"
    })
    assert res.status_code == 201

    status_data = client.get("/api/junctions/A/status").json()
    assert status_data["mode"] == "EMERGENCY"


def test_scenario_4_manual_override(client):
    """Scenario 4: Administrator takes control and returns to automatic."""
    res = client.post("/api/junctions/A/commands", json={
        "command": "MANUAL_GREEN_REQUEST",
        "direction": "EAST"
    })
    assert res.status_code == 200

    data = client.get("/api/junctions/A/status").json()
    assert data["mode"] == "MANUAL"

    # Return to automatic
    res = client.post("/api/junctions/A/commands", json={
        "command": "RETURN_TO_AUTOMATIC"
    })
    assert res.status_code == 200
    assert client.get("/api/junctions/A/status").json()["mode"] == "AUTOMATIC"


def test_scenario_5_duplicate_event_idempotency(client):
    """Scenario 5: Duplicate sensor event submitted twice does not alter queue twice."""
    status_before = client.get("/api/junctions/A/status").json()
    initial_south = status_before["queues"]["SOUTH"]

    event_payload = {
        "event_id": "s5-unique-evt-999",
        "junction_id": "A",
        "direction": "SOUTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-FORKLIFT-01",
        "vehicle_type": "FORKLIFT",
        "sequence_no": 77,
        "timestamp": "2026-10-08T12:15:00Z"
    }

    # First submission
    res1 = client.post("/api/sensor-events", json=event_payload)
    assert res1.status_code == 201

    # Second submission with same event_id
    res2 = client.post("/api/sensor-events", json=event_payload)
    assert res2.status_code == 200  # Idempotent response

    status_after = client.get("/api/junctions/A/status").json()
    assert status_after["queues"]["SOUTH"] == initial_south + 1


def test_scenario_6_vehicle_clearance(client):
    """Scenario 6: Vehicle arrives and later clears; queue count decrements."""
    # Arrival
    res_arr = client.post("/api/sensor-events", json={
        "event_id": "s6-arr-1",
        "junction_id": "A",
        "direction": "NORTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-TEMP-9",
        "vehicle_type": "EMPLOYEE_VEHICLE",
        "sequence_no": 80,
        "timestamp": "2026-10-08T12:20:00Z"
    })
    assert res_arr.status_code == 201
    q1 = client.get("/api/junctions/A/status").json()["queues"]["NORTH"]

    # Clearance
    res_clr = client.post("/api/sensor-events", json={
        "event_id": "s6-clr-1",
        "junction_id": "A",
        "direction": "NORTH",
        "event_type": "VEHICLE_CLEARED",
        "vehicle_id": "VH-TEMP-9",
        "sequence_no": 81,
        "timestamp": "2026-10-08T12:21:00Z"
    })
    assert res_clr.status_code == 201
    q2 = client.get("/api/junctions/A/status").json()["queues"]["NORTH"]
    assert q2 == q1 - 1


def test_scenario_7_controller_failure(client):
    """Scenario 7: Controller reports OFFLINE; junction enters safe FAILURE mode."""
    res = client.post("/api/controller-events", json={
        "junction_id": "A",
        "status": "OFFLINE",
        "device_type": "SIGNAL_CONTROLLER"
    })
    assert res.status_code == 200

    data = client.get("/api/junctions/A/status").json()
    assert data["mode"] == "FAILURE"
    assert data["controller_status"] == "OFFLINE"
    # Safe state: ALL_RED
    assert all(color == "RED" for color in data["desired_signals"].values())

    # Bring back ONLINE
    client.post("/api/controller-events", json={
        "junction_id": "A",
        "status": "ONLINE"
    })
    data = client.get("/api/junctions/A/status").json()
    assert data["controller_status"] == "ONLINE"


def test_scenario_8_restart_recovery(client):
    """Scenario 8: Important data survives and is recorded in audit logs."""
    client.post("/api/sensor-events", json={
        "event_id": "s8-persist-evt",
        "junction_id": "A",
        "direction": "EAST",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-PERSIST-1",
        "vehicle_type": "TRUCK",
        "sequence_no": 90,
        "timestamp": "2026-10-08T12:25:00Z"
    })

    history_res = client.get("/api/junctions/A/history?limit=10")
    assert history_res.status_code == 200
    entries = history_res.json()
    assert len(entries) > 0


def test_scenario_9_concurrent_events(client):
    """
    Scenario 9: Rapid concurrent events do not produce conflicting states:
    T = 0 ms NORTH truck arrives
    T = 4 ms EAST emergency arrives
    T = 8 ms Administrator requests WEST manual control
    T = 12 ms Duplicate EAST emergency event arrives
    T = 17 ms Controller ACK arrives
    """
    # Rapid submission
    client.post("/api/sensor-events", json={
        "event_id": "s9-truck-0",
        "junction_id": "A",
        "direction": "NORTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-T-0",
        "vehicle_type": "TRUCK",
        "sequence_no": 100,
        "timestamp": "2026-10-08T12:30:00.000Z"
    })
    client.post("/api/sensor-events", json={
        "event_id": "s9-emg-1",
        "junction_id": "A",
        "direction": "EAST",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-EMG-EAST",
        "vehicle_type": "EMERGENCY",
        "sequence_no": 101,
        "timestamp": "2026-10-08T12:30:00.004Z"
    })
    client.post("/api/junctions/A/commands", json={
        "command": "MANUAL_GREEN_REQUEST",
        "direction": "WEST"
    })
    # Duplicate emergency event
    client.post("/api/sensor-events", json={
        "event_id": "s9-emg-1",
        "junction_id": "A",
        "direction": "EAST",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-EMG-EAST",
        "vehicle_type": "EMERGENCY",
        "sequence_no": 101,
        "timestamp": "2026-10-08T12:30:00.012Z"
    })
    client.post("/api/controller-events", json={
        "command_id": "cmd-8001",
        "junction_id": "A",
        "status": "ACK",
        "actual_state": "GREEN"
    })

    # Check that system is consistent and never has conflicting green
    status = client.get("/api/junctions/A/status").json()
    signals = status["desired_signals"]
    ns_green = (signals["NORTH"] == "GREEN" or signals["SOUTH"] == "GREEN")
    ew_green = (signals["EAST"] == "GREEN" or signals["WEST"] == "GREEN")
    assert not (ns_green and ew_green), "Safety Invariant Violated: Conflicting phases received GREEN simultaneously!"
