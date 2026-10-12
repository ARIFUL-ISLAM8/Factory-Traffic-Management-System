/**
 * Factory Traffic Management System - Client Controller
 * Live Polling, Visualizer Updater, Manual Commands, and IoT Simulator
 */

let currentJunction = "A";
let eventSequenceCounter = 1000;
let isPollingActive = true;

// -------------------------------------------------------------
// Initialization & Polling
// -------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    fetchJunctionsList();
    refreshDashboard();
    fetchAuditLogs();

    // 1-second live polling interval
    setInterval(() => {
        if (isPollingActive) {
            refreshDashboard();
        }
    }, 1000);

    // 3-second audit log refresh
    setInterval(() => {
        if (isPollingActive) {
            fetchAuditLogs();
        }
    }, 3000);
});

async function fetchJunctionsList() {
    try {
        const res = await fetch("/api/junctions");
        if (res.ok) {
            const list = await res.json();
            const select = document.getElementById("junctionSelector");
            select.innerHTML = "";
            list.forEach(j => {
                const opt = document.createElement("option");
                opt.value = j;
                opt.textContent = `Junction ${j}`;
                if (j === currentJunction) opt.selected = true;
                select.appendChild(opt);
            });
        }
    } catch (e) {
        console.warn("Could not fetch junction list", e);
    }
}

function switchJunction() {
    const sel = document.getElementById("junctionSelector");
    currentJunction = sel.value;
    document.getElementById("hubLabel").textContent = `JUNCTION ${currentJunction}`;
    refreshDashboard();
    fetchAuditLogs();
}

async function changeSimSpeed() {
    const speed = parseFloat(document.getElementById("speedSelector").value);
    try {
        await fetch(`/api/junctions/${currentJunction}/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ time_scale: speed })
        });
    } catch (e) {
        console.error("Failed to update simulation speed", e);
    }
}

// -------------------------------------------------------------
// Dashboard State Refresh & Visualizer Sync
// -------------------------------------------------------------
async function refreshDashboard() {
    try {
        const res = await fetch(`/api/junctions/${currentJunction}/status`);
        if (!res.ok) {
            showErrorBanner(`Failed to fetch status: HTTP ${res.status}`);
            return;
        }

        const data = await res.json();
        updateVisualizer(data);
        clearErrorBanner();
    } catch (err) {
        showErrorBanner("Backend server unavailable or network error.");
    }
}

function updateVisualizer(data) {
    // 1. Header & Badges
    const headerMode = document.getElementById("headerMode");
    headerMode.textContent = data.mode;
    headerMode.className = `value badge-mode mode-${data.mode.toLowerCase()}`;

    const ctrlStatus = document.getElementById("headerControllerStatus");
    ctrlStatus.textContent = data.controller_status;
    ctrlStatus.className = data.controller_status === "ONLINE" ? "value badge-online" : "value badge-offline";

    const phaseDisplay = document.getElementById("phaseDisplay");
    phaseDisplay.textContent = `PHASE: ${data.phase}` + (data.is_in_transition ? ` [${data.transition_step || 'TRANSITION'}]` : "");

    // 2. Queues
    document.getElementById("queueNorth").textContent = data.queues.NORTH ?? 0;
    document.getElementById("queueSouth").textContent = data.queues.SOUTH ?? 0;
    document.getElementById("queueEast").textContent = data.queues.EAST ?? 0;
    document.getElementById("queueWest").textContent = data.queues.WEST ?? 0;

    // 3. Traffic Signal Lights
    setSignalLight("North", data.desired_signals.NORTH);
    setSignalLight("South", data.desired_signals.SOUTH);
    setSignalLight("East", data.desired_signals.EAST);
    setSignalLight("West", data.desired_signals.WEST);

    // 4. Telemetry Bar
    document.getElementById("desiredSignalsText").textContent =
        `N:${data.desired_signals.NORTH} S:${data.desired_signals.SOUTH} E:${data.desired_signals.EAST} W:${data.desired_signals.WEST}`;

    document.getElementById("actualSignalsText").textContent =
        `N:${data.actual_signals.NORTH} S:${data.actual_signals.SOUTH} E:${data.actual_signals.EAST} W:${data.actual_signals.WEST}`;

    document.getElementById("pendingCmdText").textContent = data.pending_command_id || "None";

    // 5. Active Alerts / Emergency Display
    const banner = document.getElementById("alertBanner");
    const alertMsg = document.getElementById("alertMessage");

    if (data.mode === "EMERGENCY") {
        banner.className = "alert-banner";
        alertMsg.textContent = `🚨 EMERGENCY PREEMPTION ACTIVE on Junction ${data.junction_id}! Priority clearance in progress.`;
    } else if (data.controller_status === "OFFLINE" || data.mode === "FAILURE") {
        banner.className = "alert-banner";
        alertMsg.textContent = `⚠️ CONTROLLER FAILURE: Device is OFFLINE. System operating in safe failure state (ALL_RED).`;
    } else if (data.active_alerts && data.active_alerts.length > 0) {
        banner.className = "alert-banner";
        alertMsg.textContent = `⚠️ Alert: ${data.active_alerts.join("; ")}`;
    } else {
        banner.className = "alert-banner hidden";
    }
}

function setSignalLight(direction, color) {
    const redLight = document.getElementById(`signal${direction}Red`);
    const yellowLight = document.getElementById(`signal${direction}Yellow`);
    const greenLight = document.getElementById(`signal${direction}Green`);

    redLight.classList.remove("active");
    yellowLight.classList.remove("active");
    greenLight.classList.remove("active");

    if (color === "RED") {
        redLight.classList.add("active");
    } else if (color === "YELLOW") {
        yellowLight.classList.add("active");
    } else if (color === "GREEN") {
        greenLight.classList.add("active");
    }
}

// -------------------------------------------------------------
// Manual Override Commands (Section 8)
// -------------------------------------------------------------
async function requestManualGreen(direction) {
    try {
        const res = await fetch(`/api/junctions/${currentJunction}/commands`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                command: "MANUAL_GREEN_REQUEST",
                direction: direction
            })
        });
        const json = await res.json();
        if (!res.ok) {
            alert(`Command Rejected: ${json.detail || json.message}`);
        }
        refreshDashboard();
        fetchAuditLogs();
    } catch (e) {
        alert("Network error sending manual command.");
    }
}

async function returnToAutomatic() {
    try {
        const res = await fetch(`/api/junctions/${currentJunction}/commands`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                command: "RETURN_TO_AUTOMATIC"
            })
        });
        refreshDashboard();
        fetchAuditLogs();
    } catch (e) {
        alert("Network error returning to automatic.");
    }
}

// -------------------------------------------------------------
// Traffic Simulator (Section 14.8)
// -------------------------------------------------------------
async function simulateVehicleArrival() {
    eventSequenceCounter++;
    const dir = document.getElementById("simDirection").value;
    const vType = document.getElementById("simVehicleType").value;
    const vId = document.getElementById("simVehicleId").value.trim() || `VH-${eventSequenceCounter}`;

    const payload = {
        event_id: `evt-${Date.now()}-${eventSequenceCounter}`,
        junction_id: currentJunction,
        direction: dir,
        event_type: "VEHICLE_ARRIVED",
        vehicle_id: vId,
        vehicle_type: vType,
        sequence_no: eventSequenceCounter,
        timestamp: new Date().toISOString()
    };

    try {
        const res = await fetch("/api/sensor-events", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        refreshDashboard();
        fetchAuditLogs();
    } catch (e) {
        alert("Failed to submit sensor event.");
    }
}

async function simulateVehicleClearance() {
    eventSequenceCounter++;
    const dir = document.getElementById("simDirection").value;
    const vId = document.getElementById("simVehicleId").value.trim() || `VH-${eventSequenceCounter}`;

    const payload = {
        event_id: `evt-${Date.now()}-${eventSequenceCounter}`,
        junction_id: currentJunction,
        direction: dir,
        event_type: "VEHICLE_CLEARED",
        vehicle_id: vId,
        sequence_no: eventSequenceCounter,
        timestamp: new Date().toISOString()
    };

    try {
        const res = await fetch("/api/sensor-events", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        refreshDashboard();
        fetchAuditLogs();
    } catch (e) {
        alert("Failed to submit clearance event.");
    }
}

async function toggleControllerStatus(status) {
    try {
        await fetch("/api/controller-events", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                junction_id: currentJunction,
                status: status,
                device_type: "SIGNAL_CONTROLLER"
            })
        });
        refreshDashboard();
        fetchAuditLogs();
    } catch (e) {
        alert("Failed to toggle controller status.");
    }
}

async function simulateManualAck() {
    try {
        await fetch("/api/controller-events", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                command_id: `cmd-manual-${Date.now()}`,
                junction_id: currentJunction,
                status: "ACK",
                actual_state: "GREEN"
            })
        });
        refreshDashboard();
        fetchAuditLogs();
    } catch (e) {
        alert("Failed to send controller ACK.");
    }
}

// -------------------------------------------------------------
// Audit Log Viewer (Section 11 & 14.7)
// -------------------------------------------------------------
async function fetchAuditLogs() {
    try {
        const res = await fetch(`/api/junctions/${currentJunction}/history?limit=25`);
        if (!res.ok) return;

        const logs = await res.json();
        const container = document.getElementById("auditLogList");
        if (logs.length === 0) {
            container.innerHTML = '<div class="audit-item placeholder">No activity recorded yet.</div>';
            return;
        }

        container.innerHTML = "";
        logs.forEach(log => {
            const div = document.createElement("div");
            const isAlert = log.event_type.includes("FAILURE") || log.event_type.includes("EMERGENCY");
            const isSuccess = log.event_type.includes("RETURN") || log.event_type.includes("CHANGED");
            div.className = `audit-item ${isAlert ? 'alert' : (isSuccess ? 'success' : '')}`;

            const timeStr = new Date(log.timestamp).toLocaleTimeString();
            div.innerHTML = `<span class="timestamp">[${timeStr}]</span> <strong>${log.event_type}</strong>: ${log.detail || ''}`;
            container.appendChild(div);
        });
    } catch (e) {
        console.warn("Could not load audit logs", e);
    }
}

function showErrorBanner(msg) {
    const banner = document.getElementById("alertBanner");
    const alertMsg = document.getElementById("alertMessage");
    banner.className = "alert-banner";
    alertMsg.textContent = msg;
}

function clearErrorBanner() {
    // Only clears if no active backend failure
}
