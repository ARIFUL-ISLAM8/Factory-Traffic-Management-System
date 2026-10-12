# Factory Traffic Management System (FTMS)
### Industrial IoT & Factory Automation Traffic Controller

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/Database-SQLite%20(WAL)-lightgrey.svg)](https://www.sqlite.org/)
[![Tests](https://img.shields.io/badge/tests-20%20passed%20(100%25)-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

An event-driven, safety-critical traffic management and signal automation platform designed for internal roadways inside high-throughput manufacturing plants (e.g. textile, garment, and logistics facilities). Built with a decoupled pure domain state machine, non-blocking asynchronous event loop, crash-resilient persistence, and a real-time web operations dashboard.

---

## Visual Showcase & System UI

### Real-Time Operations Dashboard
The web dashboard provides full situational awareness, streaming live signal colors, directional vehicle queues, operating modes, and hardware telemetry without requiring manual page reloads.

![Picture 1: Real-Time Operations Dashboard](Photo/Picture%201.png)
*Figure 1: Full Operations Dashboard showing active EAST_WEST phase, live queues, manual override controls, and audit history.*

---

### Safety Enforcement & Hardware Failure Mode
When an IoT controller goes offline or drops communication, the system immediately trips into a fail-safe state, switching desired signals to an all-red clearance to avert collisions.

![Picture 2: Controller Failure & Degraded State](Photo/Picture%202.png)
*Figure 2: Fail-Safe State triggered on controller disconnection. Signals transition safely to ALL_RED and warning alerts are surfaced immediately.*

---

### Core UI Modules

| Module 1: Intersection Visualizer | Module 2: Control & Simulation Console |
| :---: | :---: |
| ![Picture 3: Live Intersection Visualizer](Photo/Picture%203.png) | ![Picture 4: Manual Control & Simulator](Photo/Picture%204.png) |
| *Figure 3: Live 4-way intersection visualizer displaying real-time signal colors, queue badges, and desired vs. controller-confirmed states.* | *Figure 4: Operator manual override buttons and interactive IoT hardware simulation tools.* |

---

## Table of Contents
1. [Key Features & Highlights](#key-features--highlights)
2. [System Architecture](#system-architecture)
3. [Traffic Control & Scheduling Algorithm](#traffic-control--scheduling-algorithm)
4. [Signal State Transitions & Safety Invariants](#signal-state-transitions--safety-invariants)
5. [Database Design & Durability](#database-design--durability)
6. [API Reference & OpenAPI Docs](#api-reference--openapi-docs)
7. [Installation & Getting Started](#installation--getting-started)
8. [Interactive Scenarios & Demonstration Guide](#interactive-scenarios--demonstration-guide)
9. [Automated Testing Suite](#automated-testing-suite)
10. [Engineering Decisions & Design Rationale](#engineering-decisions--design-rationale)

---

## Key Features & Highlights

* **Safety Invariant Enforcement**: Conflicting phases (`NORTH_SOUTH` vs. `EAST_WEST`) can mathematically never receive `GREEN` simultaneously.
* **Deterministic 3-Step Transitions**: Transitions always step through `GREEN` $\to$ `YELLOW` (5s) $\to$ `ALL_RED` (2s clearance buffer) $\to$ `TARGET GREEN` (30s).
* **Emergency Vehicle Preemption**: Ambulances or fire vehicles trigger an immediate, non-blocking preemption sequence that safely overrides normal timers and manual commands.
* **Anti-Starvation Priority Algorithm**: Dynamic multi-factor scoring balances vehicle weights (`EMERGENCY > TRUCK > FORKLIFT > EMPLOYEE_VEHICLE`) with waiting times, guaranteeing lower-priority traffic is never trapped indefinitely.
* **Decoupled Hexagonal Architecture**: Pure domain business logic with zero framework or database dependencies, allowing rapid unit testing and seamless protocol swapping (REST $\leftrightarrow$ MQTT).
* **Crash-Resilient Persistence**: Powered by SQLite in Write-Ahead Logging (`WAL`) mode with automatic recovery to a safe state (`ALL_RED`) upon server reboot.
* **Idempotent Sensor Event Ingestion**: Strictly deduplicates sensor events based on authoritative `event_id`, preventing race conditions and duplicated queue increments.
* **Interactive Control & Simulation Dashboard**: Self-contained HTML5/CSS3/JS operations console with vehicle event generation and hardware fault injection.

---

## System Architecture

The project adheres to **Clean / Hexagonal Architecture** principles. Traffic decision logic is completely isolated from HTTP transports, database drivers, and frontend code.

```
                              ┌─────────────────────────────────────────┐
                              │           Frontend Dashboard            │
                              │        (HTML5 / CSS3 / Vanilla JS)      │
                              └──────────────────┬──────────────────────┘
                                                 │ HTTP / JSON Polling
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   FASTAPI ROUTER LAYER                                 │
│  - /api/junctions          - /api/sensor-events         - /api/controller-events        │
│  - /api/junctions/:id/status                           - /api/junctions/:id/history    │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              APPLICATION ORCHESTRATION                                 │
│  - TrafficService: Per-junction asyncio.Lock serializing concurrent events             │
│  - Asyncio Background Engine: Non-blocking Green/Yellow/All-Red phase countdowns       │
│  - Crash Recovery: Startup state reconciliation and queue reconstruction               │
└──────────────────┬─────────────────────────────────────────────────┬───────────────────┘
                   │                                                 │
                   ▼                                                 ▼
┌────────────────────────────────────────┐       ┌───────────────────────────────────────┐
│           PURE DOMAIN LAYER            │       │         INFRASTRUCTURE LAYER          │
│   (Zero External Dependencies)         │       │  - SQLite Database (WAL Mode)         │
│  - JunctionStateMachine (Mode & FSM)   │       │  - Repositories (Deduplication,       │
│  - QueueManager (Priority & Starvation)│       │    queues, commands, audit logs)      │
│  - Safety Guards (Invariant checkers)  │       │  - Controller Port & REST Simulator   │
│  - Pure Domain Entities & Value Objects│       │    (Ready for MQTT adapter swap)      │
└────────────────────────────────────────┘       └───────────────────────────────────────┘
```

---

## Traffic Control & Scheduling Algorithm

Automated phase rotation is calculated using a multi-factor priority scoring function evaluated at the end of each green cycle:

$$\text{Phase Score} = (\text{Queue Count} \times 15) + \text{Highest Priority Bonus} + (\text{Max Wait Time (s)} \times 2) + \text{Starvation Bonus}$$

### Scoring Breakdown:
1. **Queue Size Weight ($15 \times N$)**: Ensures roads with high congestion receive natural clearing priority.
2. **Vehicle Priority Weights**:
   * `EMERGENCY`: **1,000 pts** (forces immediate preemption sequence)
   * `TRUCK`: **50 pts** (raw materials and heavy delivery)
   * `FORKLIFT`: **30 pts** (internal logistics and pallet transit)
   * `EMPLOYEE_VEHICLE`: **10 pts** (worker transport)
3. **Wait Time Weight ($2 \times \Delta t$)**: Increases continuously for each second the oldest vehicle in the queue has been waiting.
4. **Starvation Protection ($+200\text{ pts} + 10 \times (\Delta t - 60)$)**: If any vehicle waits longer than **60 seconds**, an aggressive anti-starvation bonus is granted to force a phase switch, preventing employee cars from being blocked by a continuous stream of forklifts.
5. **Switching Hysteresis ($+5\text{ pts}$)**: Prevents rapid, wasteful signal oscillation when scores are nearly identical.

---

## Signal State Transitions & Safety Invariants

### Supported Physical Signal States
* `RED`: Stop
* `YELLOW`: Prepare to stop (~5 seconds)
* `GREEN`: Proceed (~30 seconds)

### Traffic Phases
* `NORTH_SOUTH`: North & South Green; East & West Red.
* `EAST_WEST`: East & West Green; North & South Red.
* `ALL_RED`: Clearance buffer between conflicting phases.

```
[CURRENT PHASE GREEN] (e.g. NORTH_SOUTH)
        │
        ▼
[STEP 1: YELLOW] (~5 seconds)
  - Active Green lights transition to YELLOW
  - Conflicting lights remain RED
        │
        ▼
[STEP 2: ALL_RED CLEARANCE] (~2 seconds)
  - All 4 directions set to RED
  - Safe physical intersection clearance
        │
        ▼
[STEP 3: TARGET PHASE GREEN] (~30 seconds)
  - Target directions switch to GREEN
  - Previous directions remain RED
```

### Safety Invariants Enforced Centrally
1. **Invariant 1**: Conflicting traffic phases (`NORTH_SOUTH` and `EAST_WEST`) **never simultaneously receive GREEN**. Validated in code via `validate_signals_safety()`.
2. **Invariant 2**: A GREEN phase **never transitions directly into a conflicting GREEN phase**. It must always step through intermediate `YELLOW` and `ALL_RED`.
3. **Invariant 3**: Manual overrides and emergency preemptions **never bypass** the safe transition sequence.
4. **Invariant 4**: In the event of a controller failure or offline signal, the junction defaults safely to **ALL_RED** in `FAILURE / DEGRADED` mode.

---

## Database Design & Durability

The system uses SQLite configured with Write-Ahead Logging (`WAL` mode) and busy timeouts for high read/write concurrency:

```sql
-- Junction Configuration & State
CREATE TABLE junctions (
    junction_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    current_phase TEXT NOT NULL,
    controller_status TEXT NOT NULL,
    desired_signals TEXT NOT NULL,
    actual_signals TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- Sensor Event Deduplication Store
CREATE TABLE sensor_events (
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

-- Durable Queues for Crash Recovery
CREATE TABLE vehicle_queues (
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

-- Controller Commands & Acknowledgements
CREATE TABLE controller_commands (
    command_id TEXT PRIMARY KEY,
    junction_id TEXT NOT NULL,
    direction TEXT,
    requested_state TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_state TEXT,
    created_at REAL NOT NULL,
    acknowledged_at REAL
);

-- Audit History Log
CREATE TABLE audit_logs (
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
```

---

## API Reference & OpenAPI Docs

When the backend runs, complete interactive Swagger documentation is available at **`/docs`** (and ReDoc at **`/redoc`**).

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/junctions` | Returns all registered junctions (`["A", "B", ...]`). |
| `POST` | `/api/junctions` | Creates a new junction dynamically. |
| `GET` | `/api/junctions/:id/status` | Returns live status (signals, queues, mode, alerts, commands). |
| `POST` | `/api/sensor-events` | Ingests vehicle arrival or clearance event (idempotent). |
| `POST` | `/api/junctions/:id/commands` | Issues manual override (`MANUAL_GREEN_REQUEST`, `RETURN_TO_AUTOMATIC`). |
| `POST` | `/api/controller-events` | Simulates hardware controller ACK, OFFLINE, or ONLINE response. |
| `GET` | `/api/junctions/:id/history` | Fetches system audit trail and state transition history. |
| `POST` | `/api/junctions/:id/config` | Configures simulation speed multiplier (1x, 5x, 10x). |

---

## Installation & Getting Started

### Prerequisites
* Python 3.10 or higher
* pip package manager

### 1. Clone & Install
```bash
git clone https://github.com/your-username/Factory-Traffic-Management-System.git
cd "Factory Traffic Management System"

pip install -r requirements.txt
```

### 2. Start the Server
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Open in Browser
* **Operations Dashboard**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
* **Interactive API Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **Postman Collection**: Import `postman_collection.json` directly into Postman.

---

## Interactive Scenarios & Demonstration Guide

You can test and demonstrate all major operational flows using the web dashboard:

### 1. Normal Traffic Flow
1. In the **Vehicle Detection** form, select `NORTH`, type vehicle ID `VH-1`, click **Simulate Arrival**.
2. Select `SOUTH`, type vehicle ID `VH-2`, click **Simulate Arrival**.
3. **Result**: The NORTH and SOUTH queue badges increment. Signals cycle automatically based on queue volume.

### 2. Vehicle Priority Scoring
1. In the simulation form, select `EAST`, set vehicle type to **TRUCK**, and click **Simulate Arrival**.
2. **Result**: The higher priority weight of the truck influences the queue score, triggering a safe phase transition towards `EAST_WEST`.

### 3. Emergency Vehicle Preemption
1. In the simulation form, select `WEST`, select **Emergency Vehicle (Preemptive)**, and click **Simulate Arrival**.
2. **Result**: An emergency banner activates (`🚨 EMERGENCY PREEMPTION ACTIVE`). The system immediately begins safe clearance (`YELLOW` $\to$ `ALL_RED` $\to$ `WEST GREEN`), prioritizing the ambulance without skipping safety buffers.

### 4. Administrator Manual Override
1. In the **Manual Traffic Control** panel, click **Force East Green**.
2. **Result**: System mode switches to `MANUAL`. The intersection transitions safely to `EAST_WEST GREEN`.
3. Click **Return to Automatic Control** to hand scheduling back to the automated algorithm.

### 5. Idempotent Deduplication
1. Send the same sensor payload twice using the API or automated tests (`s5-unique-evt-999`).
2. **Result**: First call returns `201 Created`. Second call returns `200 OK` (idempotent). The queue count only increments once.

### 6. Hardware Failure & Degraded Safe State
1. In the **Hardware Controller** panel, click **Simulate Controller OFFLINE**.
2. **Result**: Header changes to `OFFLINE`, mode switches to `FAILURE`, and all traffic lights safely drop to `ALL_RED`.
3. Click **Simulate Controller ONLINE** to restore normal operations.

---

## Automated Testing Suite

The project includes unit and integration tests covering domain logic, invariants, and end-to-end scenarios.

Run the test suite:
```bash
python -m pytest -v
```

### Test Results Summary:
```text
tests/test_api_scenarios.py::test_scenario_1_normal_traffic PASSED          [  5%]
tests/test_api_scenarios.py::test_scenario_2_priority_traffic PASSED        [ 10%]
tests/test_api_scenarios.py::test_scenario_3_emergency_preemption PASSED    [ 15%]
tests/test_api_scenarios.py::test_scenario_4_manual_override PASSED         [ 20%]
tests/test_api_scenarios.py::test_scenario_5_duplicate_event_idempotency PASSED [ 25%]
tests/test_api_scenarios.py::test_scenario_6_vehicle_clearance PASSED       [ 30%]
tests/test_api_scenarios.py::test_scenario_7_controller_failure PASSED      [ 35%]
tests/test_api_scenarios.py::test_scenario_8_restart_recovery PASSED        [ 40%]
tests/test_api_scenarios.py::test_scenario_9_concurrent_events PASSED       [ 45%]
tests/test_domain_state_machine.py::test_initial_state_safety PASSED        [ 50%]
tests/test_domain_state_machine.py::test_deterministic_three_step_transition PASSED [ 55%]
tests/test_domain_state_machine.py::test_manual_override_and_return PASSED  [ 60%]
tests/test_domain_state_machine.py::test_emergency_preemption_and_clearance PASSED [ 65%]
tests/test_domain_state_machine.py::test_controller_offline_safe_failure PASSED [ 70%]
tests/test_queue_manager.py::test_queue_never_drops_below_zero PASSED       [ 75%]
tests/test_queue_manager.py::test_vehicle_arrival_and_clearance PASSED      [ 80%]
tests/test_queue_manager.py::test_priority_scheduling_preference PASSED     [ 85%]
tests/test_queue_manager.py::test_starvation_prevention PASSED              [ 90%]
tests/test_safety_invariants.py::test_conflicting_green_detection PASSED    [ 95%]
tests/test_safety_invariants.py::test_illegal_direct_transition_prohibited PASSED [100%]

======================== 20 passed, 1 warning in 1.31s ========================
```

---

## Engineering Decisions & Design Rationale

| Requirement / Ambiguity | Engineering Decision & Rationale |
| :--- | :--- |
| **Why FastAPI over Django?** | Traffic systems are event-driven control loops with timing constraints. FastAPI’s native `asyncio` event loop manages non-blocking countdowns (`await asyncio.sleep()`) cleanly without needing Celery or Redis. |
| **Authoritative Event ID & Deduplication** | `event_id` is authoritative for deduplication in the persistence layer. Duplicates return `200 OK` idempotently and are logged to audit history without modifying queue counts. |
| **Sensor Timestamp vs. Server Timestamp** | Sensor timestamp is stored for sensor telemetry auditing, but **server arrival timestamp** is authoritative for wait-time calculation to prevent clock-drift exploitation. |
| **Clearance without Arrival** | If a `VEHICLE_CLEARED` event arrives for an unknown vehicle ID or empty queue, it pops the oldest FIFO vehicle if present. Queue count is clamped with a floor at 0 (never negative). |
| **Emergency vs. Manual Override** | **Emergency mode strictly overrides manual override**. An administrator cannot force a manual green that conflicts with an active emergency vehicle. |
| **Hardware Controller Failure State** | If a controller disconnects or reports `OFFLINE`, the junction immediately transitions into `FAILURE` mode with an `ALL_RED` state. |
| **Crash Recovery Strategy** | On reboot, if the database reveals the server crashed mid-transition, the engine automatically defaults to `ALL_RED` clearance before resuming normal cycles. |
| **Per-Junction Concurrency Lock** | An `asyncio.Lock` is maintained per junction runtime. Multiple concurrent HTTP requests affecting the same junction are serialized, eliminating race conditions while allowing independent junctions (A, B, C) to run in parallel. |

---

## License

This project is licensed under the MIT License - feel free to use and adapt it for industrial automation and smart factory research.
