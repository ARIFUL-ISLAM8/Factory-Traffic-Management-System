"""
System Configuration & Tunable Parameters
"""
import os

# Default durations according to spec
NORMAL_GREEN_DURATION: float = float(os.getenv("NORMAL_GREEN_DURATION", "30.0"))
NORMAL_YELLOW_DURATION: float = float(os.getenv("NORMAL_YELLOW_DURATION", "5.0"))
ALL_RED_CLEARANCE_DURATION: float = float(os.getenv("ALL_RED_CLEARANCE_DURATION", "2.0"))

# Controller communication parameters
CONTROLLER_ACK_TIMEOUT: float = float(os.getenv("CONTROLLER_ACK_TIMEOUT", "5.0"))
MAX_CONTROLLER_RETRIES: int = int(os.getenv("MAX_CONTROLLER_RETRIES", "2"))

# Database path (SQLite)
DB_PATH: str = os.getenv("DB_PATH", "traffic_management.db")

# Time scale factor for testing/demo (1.0 = real time, >1.0 speeds up timer steps)
# In tests or fast-demo mode, we can scale time to allow rapid transitions.
SIMULATION_TIME_SCALE: float = float(os.getenv("SIMULATION_TIME_SCALE", "1.0"))

# Vehicle Priority Scoring Weights
PRIORITY_WEIGHTS = {
    "EMERGENCY": 1000.0,
    "TRUCK": 50.0,
    "FORKLIFT": 30.0,
    "EMPLOYEE_VEHICLE": 10.0,
}

# Starvation & Queue scoring
QUEUE_SIZE_WEIGHT: float = 15.0
WAIT_TIME_WEIGHT_PER_SECOND: float = 2.0
MAX_STARVATION_SECONDS: float = 60.0
