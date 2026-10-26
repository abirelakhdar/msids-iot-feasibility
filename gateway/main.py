import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.trace_schema import ExecutionTrace, TraceContext, TraceStatus, TraceTarget


UMMS_URL = os.getenv("UMMS_URL", "http://localhost:8003")
IDMS_URL = os.getenv("IDMS_URL", "http://localhost:8001")
DCMS_URL = os.getenv("DCMS_URL", "http://localhost:8002")
TRACE_LOG = Path(os.getenv("TRACE_LOG", "data/traces.jsonl"))
# Dataset generation only: lets the simulator stamp traces with simulated time.
SIMULATION_MODE = os.getenv("SIMULATION_MODE") == "1"


class DeviceRequest(BaseModel):
    user_id: str
    device_id: str
    action: str
    payload: dict[str, Any] | None = None
    origin: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=5.0)
    yield
    await app.state.client.aclose()


app = FastAPI(title="MS Gateway", lifespan=lifespan)


def log_trace(trace: ExecutionTrace) -> None:
    TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_LOG.open("a", encoding="utf-8") as f:
        f.write(trace.model_dump_json() + "\n")


def finish(
    trace: ExecutionTrace,
    status: TraceStatus,
    http_status: int,
    reason: str,
    device: dict[str, Any] | None = None,
) -> JSONResponse:
    trace.status = status
    log_trace(trace)
    return JSONResponse(
        status_code=http_status,
        content={
            "trace_id": trace.trace_id,
            "status": trace.status,
            "decision": trace.decision,
            "reason": reason,
            "device": device,
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "simulation_mode": SIMULATION_MODE}


@app.post("/request")
async def handle_request(req: DeviceRequest, x_sim_time: datetime | None = Header(default=None)):
    client: httpx.AsyncClient = app.state.client
    simulated = SIMULATION_MODE and x_sim_time is not None

    try:
        found = await client.get(f"{DCMS_URL}/devices/{req.device_id}")
        if found.status_code == 404:
            raise HTTPException(status_code=404, detail=f"unknown device '{req.device_id}'")
        found.raise_for_status()
        device = found.json()
        device_type = device["device_type"]

        auth = await client.post(
            f"{UMMS_URL}/authorize",
            json={"user_id": req.user_id, "device_type": device_type, "action": req.action},
        )
        auth.raise_for_status()
        auth = auth.json()

        trace = ExecutionTrace(
            trace_id=f"tr_{uuid.uuid4().hex}",
            timestamp=x_sim_time if simulated else datetime.now(timezone.utc),
            context=TraceContext(
                user_id=req.user_id,
                user_role=auth["user_role"],
                origin=req.origin,
            ),
            target=TraceTarget(
                service="DCMS",
                device_id=req.device_id,
                device_type=device_type,
            ),
            action=req.action,
            payload=req.payload,
            device_state=device.get("state"),
            status="pending",
        )
        trace.trace_hash = trace.compute_hash()

        if not auth["allowed"]:
            return finish(trace, "denied", 403, auth["reason"])

        verdict = await client.post(f"{IDMS_URL}/analyze", json=trace.model_dump(mode="json"))
        verdict.raise_for_status()
        verdict = verdict.json()
        trace.decision = verdict["decision"]

        if trace.decision != "ALLOW":
            return finish(trace, "blocked", 403, verdict["reason"])

        result = await client.post(
            f"{DCMS_URL}/devices/{req.device_id}/actions",
            json={"action": req.action, "payload": req.payload},
        )
        if result.is_error:
            return finish(trace, "failed", result.status_code, result.json()["detail"])

        return finish(trace, "success", 200, verdict["reason"], device=result.json())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"downstream service unavailable: {exc}")
