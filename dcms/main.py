import copy
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


DEVICES = {
    "lamp_01": {"device_type": "lamp", "state": {"power": "off"}},
    "thermostat_01": {
        "device_type": "thermostat",
        "state": {"power": "on", "target_temperature": 21, "current_temperature": 22.5},
    },
    "lock_01": {"device_type": "lock", "state": {"locked": True}},
}
FACTORY = copy.deepcopy(DEVICES)
SIMULATION_MODE = os.getenv("SIMULATION_MODE") == "1"


class ActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] | None = None


app = FastAPI(title="DCMS")


def get_device(device_id: str) -> dict[str, Any]:
    device = DEVICES.get(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"unknown device '{device_id}'")
    return device


def apply_action(device: dict[str, Any], action: str, payload: dict[str, Any]) -> None:
    device_type = device["device_type"]
    state = device["state"]

    if action == "read_status":
        pass
    elif device_type in ("lamp", "thermostat") and action in ("turn_on", "turn_off"):
        state["power"] = "on" if action == "turn_on" else "off"
    elif device_type == "thermostat" and action == "set_temperature":
        temperature = payload.get("temperature")
        if not isinstance(temperature, (int, float)):
            raise HTTPException(status_code=422, detail="payload.temperature must be a number")
        state["target_temperature"] = temperature
    elif device_type == "lock" and action in ("lock", "unlock"):
        state["locked"] = action == "lock"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"action '{action}' is not supported by '{device_type}' devices",
        )


def same_kind(reported: Any, current: Any) -> bool:
    if isinstance(current, bool) or isinstance(reported, bool):
        return isinstance(current, bool) and isinstance(reported, bool)
    if isinstance(current, (int, float)):
        return isinstance(reported, (int, float))
    return isinstance(reported, type(current))


@app.get("/health")
def health():
    return {"status": "ok", "simulation_mode": SIMULATION_MODE}


@app.post("/reset")
def reset():
    if not SIMULATION_MODE:
        raise HTTPException(status_code=403, detail="reset is only available in simulation mode")
    for device_id, device in FACTORY.items():
        DEVICES[device_id]["state"] = copy.deepcopy(device["state"])
    return DEVICES


@app.get("/devices")
def list_devices():
    return DEVICES


@app.get("/devices/{device_id}")
def read_device(device_id: str):
    return {"device_id": device_id, **get_device(device_id)}


@app.post("/devices/{device_id}/telemetry")
def report_telemetry(device_id: str, reading: dict[str, Any]):
    """State reported by the device itself: a sensor reading, or a change made
    by hand (a key in the lock, the wall switch). It is not a user request."""
    device = get_device(device_id)
    state = device["state"]
    unknown = sorted(set(reading) - set(state))
    if unknown or not reading:
        raise HTTPException(
            status_code=400,
            detail=f"'{device['device_type']}' devices do not report {unknown or 'an empty reading'}",
        )
    for key, value in reading.items():
        if not same_kind(value, state[key]):
            raise HTTPException(status_code=422, detail=f"'{key}' has the wrong type")
    state.update(reading)
    return {"device_id": device_id, **device}


@app.post("/devices/{device_id}/actions")
def run_action(device_id: str, req: ActionRequest):
    device = get_device(device_id)
    apply_action(device, req.action, req.payload or {})
    return {"device_id": device_id, **device}
