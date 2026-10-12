"""
Application Layer - Traffic Service Orchestrator
Coordinates Domain State Machine, Queues, Persistence, Concurrency Locks, and Controller Port.
"""
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from app.config import (
    ALL_RED_CLEARANCE_DURATION,
    CONTROLLER_ACK_TIMEOUT,
    NORMAL_GREEN_DURATION,
    NORMAL_YELLOW_DURATION,
    SIMULATION_TIME_SCALE,
)
from app.domain.models import (
    ControllerStatus,
    Direction,
    JunctionMode,
    JunctionState,
    SensorEvent,
    SignalColor,
    TrafficPhase,
    VehicleType,
)
from app.domain.queue_manager import QueueManager
from app.domain.safety import get_phase_for_direction, is_conflicting_green
from app.domain.state_machine import JunctionStateMachine
from app.infrastructure.controller_client import SimulatedControllerAdapter
from app.infrastructure.repository import Repository


class JunctionRuntime:
    """Encapsulates in-memory runtime, state machine, queues, and concurrency lock for a single junction."""

    def __init__(self, junction_id: str, repository: Repository):
        self.junction_id = junction_id
        self.repo = repository
        self.lock = asyncio.Lock()
        self.state_machine = JunctionStateMachine(junction_id)
        self.queue_manager = QueueManager(junction_id)
        self.controller_adapter = SimulatedControllerAdapter()
        self.active_transition_task: Optional[asyncio.Task] = None
        self.time_scale: float = SIMULATION_TIME_SCALE
        self.green_duration: float = NORMAL_GREEN_DURATION
        self.yellow_duration: float = NORMAL_YELLOW_DURATION
        self.all_red_duration: float = ALL_RED_CLEARANCE_DURATION


class TrafficService:
    """
    Central application service managing junctions, background loops,
    sensor events, manual commands, and crash recovery.
    """

    def __init__(self, repository: Repository):
        self.repo = repository
        self._runtimes: Dict[str, JunctionRuntime] = {}
        self._background_tasks: List[asyncio.Task] = []
        self._running = False

    def get_or_create_runtime(self, junction_id: str) -> JunctionRuntime:
        if junction_id not in self._runtimes:
            runtime = JunctionRuntime(junction_id, self.repo)
            # Try loading saved state
            saved_state = self.repo.get_junction(junction_id)
            if saved_state:
                runtime.state_machine = JunctionStateMachine(junction_id, saved_state)
            else:
                self.repo.save_junction(runtime.state_machine.state)

            # Load any persisted queues
            persisted_queues = self.repo.load_persisted_queues(junction_id)
            for d, v_list in persisted_queues.items():
                runtime.queue_manager._queues[d] = v_list

            self._runtimes[junction_id] = runtime

        return self._runtimes[junction_id]

    async def start(self):
        """Starts background workers on application startup."""
        self._running = True
        # Ensure default Junction A exists
        runtime_a = self.get_or_create_runtime("A")
        # Recover safe state if needed
        await self._recover_junction_state(runtime_a)
        # Launch automatic scheduling background loop
        task = asyncio.create_task(self._automatic_scheduling_loop("A"))
        self._background_tasks.append(task)

    async def stop(self):
        """Cancels background tasks on shutdown."""
        self._running = False
        for t in self._background_tasks:
            t.cancel()
        self._background_tasks.clear()

    async def _recover_junction_state(self, runtime: JunctionRuntime):
        """
        Crash Recovery (Section 6 & 12):
        If the server restarted while in an intermediate transition or waiting for ACK,
        safely place signals into ALL_RED clearance before resuming to prevent any conflicting green states.
        """
        async with runtime.lock:
            state = runtime.state_machine.state
            if state.is_in_transition or is_conflicting_green(state.desired_signals):
                runtime.state_machine.step_to_all_red()
                runtime.state_machine.state.mode = JunctionMode.AUTOMATIC
                self.repo.save_junction(runtime.state_machine.state)
                self.repo.log_audit(
                    junction_id=runtime.junction_id,
                    event_type="RESTART_RECOVERY",
                    detail="Server recovered from restart. Reset to safe ALL_RED clearance before resuming.",
                )

    # -------------------------------------------------------------
    # Sensor Events Processing (Section 4 & 10.2)
    # -------------------------------------------------------------
    async def process_sensor_event(self, event: SensorEvent) -> Tuple[bool, str, int]:
        """
        Processes vehicle detection events.
        Enforces idempotency, deduplication, queue bounds, and emergency preemption.
        Returns: (success, message, http_status_code)
        """
        runtime = self.get_or_create_runtime(event.junction_id)

        # 1. Deduplication check (Idempotency)
        if self.repo.is_event_processed(event.event_id):
            self.repo.log_audit(
                junction_id=event.junction_id,
                event_type="DUPLICATE_SENSOR_EVENT",
                direction=event.direction.value,
                detail=f"Duplicate event_id '{event.event_id}' rejected idempotently.",
            )
            return True, f"Event {event.event_id} already processed (idempotent).", 200

        # Validate vehicle type if provided
        v_type = event.vehicle_type or VehicleType.EMPLOYEE_VEHICLE

        async with runtime.lock:
            # Record into deduplication store
            self.repo.record_sensor_event(
                event_id=event.event_id,
                junction_id=event.junction_id,
                direction=event.direction.value,
                event_type=event.event_type,
                vehicle_id=event.vehicle_id,
                vehicle_type=v_type.value,
                sequence_no=event.sequence_no,
                sensor_timestamp=event.timestamp,
            )

            if event.event_type == "VEHICLE_ARRIVED":
                now_ts = datetime.now(timezone.utc).timestamp()
                added = runtime.queue_manager.add_vehicle(
                    vehicle_id=event.vehicle_id,
                    vehicle_type=v_type,
                    direction=event.direction,
                    sequence_no=event.sequence_no,
                    sensor_timestamp=event.timestamp,
                    server_timestamp=now_ts,
                )
                if added:
                    v_record = runtime.queue_manager.get_vehicles(event.direction)[-1]
                    self.repo.persist_enqueue_vehicle(event.junction_id, v_record)

                self.repo.log_audit(
                    junction_id=event.junction_id,
                    event_type="VEHICLE_DETECTED",
                    direction=event.direction.value,
                    detail=f"Vehicle {event.vehicle_id} ({v_type.value}) arrived at {event.direction.value}.",
                )

                # Emergency Preemption Trigger (Section 7)
                if v_type == VehicleType.EMERGENCY:
                    self.repo.log_audit(
                        junction_id=event.junction_id,
                        event_type="EMERGENCY_DETECTED",
                        direction=event.direction.value,
                        detail=f"Emergency vehicle {event.vehicle_id} detected. Initiating immediate preemption.",
                    )
                    runtime.state_machine.trigger_emergency(event.direction)
                    self._trigger_transition_if_needed(runtime)

            elif event.event_type == "VEHICLE_CLEARED":
                runtime.queue_manager.remove_vehicle(
                    vehicle_id=event.vehicle_id, direction=event.direction
                )
                self.repo.persist_dequeue_vehicle(
                    junction_id=event.junction_id,
                    direction=event.direction.value,
                    vehicle_id=event.vehicle_id,
                )

                self.repo.log_audit(
                    junction_id=event.junction_id,
                    event_type="VEHICLE_CLEARED",
                    direction=event.direction.value,
                    detail=f"Vehicle {event.vehicle_id} cleared from {event.direction.value}.",
                )

                # If this cleared an emergency vehicle, check if emergency mode should end
                if not runtime.queue_manager.has_emergency(event.direction):
                    runtime.state_machine.clear_emergency(event.direction)
                    self.repo.log_audit(
                        junction_id=event.junction_id,
                        event_type="EMERGENCY_CLEARED",
                        direction=event.direction.value,
                        detail=f"Emergency cleared for {event.direction.value}.",
                    )

            else:
                return False, f"Unknown event_type: {event.event_type}", 400

            self.repo.save_junction(runtime.state_machine.state)
            return True, "Event processed successfully.", 201

    # -------------------------------------------------------------
    # Manual Commands (Section 8 & 10.4)
    # -------------------------------------------------------------
    async def process_manual_command(
        self, junction_id: str, command: str, direction: Optional[Direction]
    ) -> Tuple[bool, str, int]:
        """
        Executes manual administrator overrides.
        Supports MANUAL_GREEN_REQUEST and RETURN_TO_AUTOMATIC.
        """
        runtime = self.get_or_create_runtime(junction_id)

        async with runtime.lock:
            if command == "MANUAL_GREEN_REQUEST":
                if not direction:
                    return False, "Direction is required for MANUAL_GREEN_REQUEST.", 400

                # Emergency override rule: Emergency vehicle takes precedence over manual override
                if (
                    runtime.state_machine.state.mode == JunctionMode.EMERGENCY
                    and runtime.state_machine.state.active_emergency_directions
                ):
                    return (
                        False,
                        "Manual command rejected: Active EMERGENCY has higher priority.",
                        409,
                    )

                success, msg = runtime.state_machine.request_manual_green(direction)
                if not success:
                    return False, msg, 400

                self.repo.log_audit(
                    junction_id=junction_id,
                    event_type="MANUAL_OVERRIDE",
                    direction=direction.value,
                    detail=f"Administrator requested MANUAL GREEN for {direction.value}.",
                )
                self.repo.save_junction(runtime.state_machine.state)
                self._trigger_transition_if_needed(runtime)
                return True, msg, 200

            elif command == "RETURN_TO_AUTOMATIC":
                runtime.state_machine.return_to_automatic()
                self.repo.log_audit(
                    junction_id=junction_id,
                    event_type="RETURN_TO_AUTOMATIC",
                    detail="Administrator returned junction to AUTOMATIC control.",
                )
                self.repo.save_junction(runtime.state_machine.state)
                return True, "Junction returned to AUTOMATIC mode.", 200

            return False, f"Invalid command: {command}", 400

    # -------------------------------------------------------------
    # Controller Responses & Acknowledgements (Section 9 & 10.5)
    # -------------------------------------------------------------
    async def process_controller_event(
        self,
        command_id: Optional[str],
        junction_id: str,
        status: str,
        actual_state: Optional[SignalColor] = None,
        device_type: Optional[str] = None,
        direction: Optional[Direction] = None,
    ) -> Tuple[bool, str, int]:
        """
        Simulates controller ACK or device failure events.
        """
        runtime = self.get_or_create_runtime(junction_id)

        async with runtime.lock:
            if status == "OFFLINE":
                runtime.state_machine.update_controller_status(ControllerStatus.OFFLINE)
                runtime.state_machine.enter_safe_failure_state(
                    f"Controller reported OFFLINE ({device_type or 'SIGNAL_CONTROLLER'})"
                )
                self.repo.log_audit(
                    junction_id=junction_id,
                    event_type="DEVICE_FAILURE",
                    detail=f"Device {device_type} reported OFFLINE. Switched to safe failure mode (ALL_RED).",
                )
                self.repo.save_junction(runtime.state_machine.state)
                return True, "Junction placed into safe FAILURE mode.", 200

            elif status == "ONLINE":
                runtime.state_machine.update_controller_status(ControllerStatus.ONLINE)
                self.repo.log_audit(
                    junction_id=junction_id,
                    event_type="CONTROLLER_RECONNECTED",
                    detail="Controller reported ONLINE. Resuming operations.",
                )
                self.repo.save_junction(runtime.state_machine.state)
                return True, "Controller back ONLINE.", 200

            elif status == "ACK":
                if command_id:
                    self.repo.acknowledge_controller_command(
                        command_id=command_id,
                        status="ACK",
                        actual_state=actual_state.value if actual_state else None,
                    )
                    runtime.state_machine.state.pending_command_id = None

                if actual_state:
                    runtime.state_machine.confirm_controller_signal(direction, actual_state)

                self.repo.log_audit(
                    junction_id=junction_id,
                    event_type="CONTROLLER_ACKNOWLEDGEMENT",
                    command_id=command_id,
                    detail=f"Controller confirmed state {actual_state.value if actual_state else 'MATCH'} for {command_id}.",
                )
                self.repo.save_junction(runtime.state_machine.state)
                return True, "Acknowledgement recorded.", 200

            return False, f"Unhandled controller status: {status}", 400

    # -------------------------------------------------------------
    # Transition Execution (Non-Blocking Async Engine)
    # -------------------------------------------------------------
    def _trigger_transition_if_needed(self, runtime: JunctionRuntime):
        """Spawns an async transition worker if not already running."""
        if (
            runtime.state_machine.state.is_in_transition
            and (runtime.active_transition_task is None or runtime.active_transition_task.done())
        ):
            runtime.active_transition_task = asyncio.create_task(
                self._execute_safe_transition_sequence(runtime)
            )

    async def _execute_safe_transition_sequence(self, runtime: JunctionRuntime):
        """
        Executes the mandatory safety sequence without blocking request threads:
        Current GREEN -> YELLOW (~5s) -> ALL_RED (~2s clearance) -> Target GREEN (~30s).
        """
        try:
            scale = max(0.1, runtime.time_scale)

            # --- STEP 1: YELLOW ---
            async with runtime.lock:
                if runtime.state_machine.state.controller_status == ControllerStatus.OFFLINE:
                    return

                prev_phase = runtime.state_machine.state.current_phase.value
                runtime.state_machine.step_to_yellow()
                cmd_id = await runtime.controller_adapter.send_signal_command(
                    runtime.junction_id, None, SignalColor.YELLOW
                )
                runtime.state_machine.state.pending_command_id = cmd_id
                self.repo.record_controller_command(
                    cmd_id, runtime.junction_id, None, SignalColor.YELLOW.value
                )
                self.repo.log_audit(
                    junction_id=runtime.junction_id,
                    event_type="SIGNAL_TRANSITION_STARTED",
                    previous_state=prev_phase,
                    new_state="YELLOW",
                    command_id=cmd_id,
                    detail="Transitioning phase to YELLOW.",
                )
                self.repo.save_junction(runtime.state_machine.state)

            # Non-blocking sleep for YELLOW duration
            await asyncio.sleep(runtime.yellow_duration / scale)

            # Auto-ACK for simulator
            async with runtime.lock:
                runtime.state_machine.confirm_controller_signal(None, SignalColor.YELLOW)

            # --- STEP 2: ALL_RED Clearance ---
            async with runtime.lock:
                if runtime.state_machine.state.controller_status == ControllerStatus.OFFLINE:
                    return

                runtime.state_machine.step_to_all_red()
                cmd_id = await runtime.controller_adapter.send_signal_command(
                    runtime.junction_id, None, SignalColor.RED
                )
                runtime.state_machine.state.pending_command_id = cmd_id
                self.repo.record_controller_command(
                    cmd_id, runtime.junction_id, None, SignalColor.RED.value
                )
                self.repo.log_audit(
                    junction_id=runtime.junction_id,
                    event_type="SIGNAL_CLEARANCE",
                    new_state="ALL_RED",
                    command_id=cmd_id,
                    detail="All signals RED for safe intersection clearance.",
                )
                self.repo.save_junction(runtime.state_machine.state)

            # Non-blocking sleep for ALL_RED duration
            await asyncio.sleep(runtime.all_red_duration / scale)

            # Auto-ACK for simulator
            async with runtime.lock:
                runtime.state_machine.confirm_controller_signal(None, SignalColor.RED)

            # --- STEP 3: TARGET GREEN ---
            async with runtime.lock:
                if runtime.state_machine.state.controller_status == ControllerStatus.OFFLINE:
                    return

                runtime.state_machine.step_to_target_green()
                cmd_id = await runtime.controller_adapter.send_signal_command(
                    runtime.junction_id, None, SignalColor.GREEN
                )
                runtime.state_machine.state.pending_command_id = cmd_id
                self.repo.record_controller_command(
                    cmd_id, runtime.junction_id, None, SignalColor.GREEN.value
                )
                self.repo.log_audit(
                    junction_id=runtime.junction_id,
                    event_type="SIGNAL_CHANGED",
                    new_state=runtime.state_machine.state.current_phase.value,
                    command_id=cmd_id,
                    detail=f"Target phase {runtime.state_machine.state.current_phase.value} is now GREEN.",
                )
                self.repo.save_junction(runtime.state_machine.state)

            # Auto-ACK for simulator
            async with runtime.lock:
                runtime.state_machine.confirm_controller_signal(None, SignalColor.GREEN)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.repo.log_audit(
                junction_id=runtime.junction_id,
                event_type="TRANSITION_ERROR",
                detail=f"Transition failed: {str(e)}",
            )

    # -------------------------------------------------------------
    # Automatic Scheduling Loop (Section 6)
    # -------------------------------------------------------------
    async def _automatic_scheduling_loop(self, junction_id: str):
        """
        Background loop for automatic junction scheduling.
        Evaluates queue scores, priority, and waiting durations to switch phases.
        """
        while self._running:
            try:
                runtime = self.get_or_create_runtime(junction_id)
                scale = max(0.1, runtime.time_scale)

                await asyncio.sleep(1.0 / scale)

                async with runtime.lock:
                    state = runtime.state_machine.state

                    # Only manage automatic transitions if currently in AUTOMATIC mode
                    if (
                        state.mode == JunctionMode.AUTOMATIC
                        and not state.is_in_transition
                        and state.controller_status == ControllerStatus.ONLINE
                    ):
                        now = datetime.now(timezone.utc).timestamp()
                        elapsed = now - state.phase_started_at
                        min_green_time = runtime.green_duration / scale

                        # Check if phase green time has expired or high priority waiting
                        if elapsed >= min_green_time:
                            next_phase, reason = runtime.queue_manager.select_next_phase(
                                state.current_phase, current_time=now
                            )
                            if next_phase != state.current_phase:
                                started, msg = runtime.state_machine.start_transition_to_phase(
                                    next_phase
                                )
                                if started:
                                    self.repo.log_audit(
                                        junction_id=junction_id,
                                        event_type="AUTOMATIC_PHASE_DECISION",
                                        detail=f"Scheduler chosen {next_phase.value}: {reason}",
                                    )
                                    self._trigger_transition_if_needed(runtime)

            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(1.0)

    # -------------------------------------------------------------
    # Read Views for APIs & Dashboard
    # -------------------------------------------------------------
    def get_junction_status(self, junction_id: str) -> Optional[Dict]:
        runtime = self.get_or_create_runtime(junction_id)
        sm = runtime.state_machine
        qm = runtime.queue_manager

        return {
            "junction_id": junction_id,
            "mode": sm.state.mode.value,
            "phase": sm.state.current_phase.value,
            "controller_status": sm.state.controller_status.value,
            "is_in_transition": sm.state.is_in_transition,
            "transition_step": sm.state.transition_step,
            "desired_signals": {k: v.value for k, v in sm.state.desired_signals.items()},
            "actual_signals": {k: v.value for k, v in sm.state.actual_signals.items()},
            "queues": qm.get_counts(),
            "active_alerts": sm.state.active_alerts,
            "pending_command_id": sm.state.pending_command_id,
        }

    def get_junction_history(self, junction_id: str, limit: int = 50) -> List[Dict]:
        return self.repo.get_audit_logs(junction_id, limit=limit)

    def list_all_junctions(self) -> List[str]:
        # Return at least ["A"] and any created in DB
        db_list = self.repo.list_junction_ids()
        if "A" not in db_list:
            db_list.insert(0, "A")
        return list(dict.fromkeys(db_list + list(self._runtimes.keys())))
