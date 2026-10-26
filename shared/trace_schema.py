import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


TraceStatus = Literal["pending", "success", "denied", "blocked", "failed"]

HASHED_FIELDS = {
    "trace_id",
    "timestamp",
    "context",
    "target",
    "action",
    "payload",
    "device_state",
}


class TraceContext(BaseModel):
    user_id: str
    user_role: str
    origin: str | None = None


class TraceTarget(BaseModel):
    service: str
    device_id: str
    device_type: str


class ExecutionTrace(BaseModel):
    trace_id: str
    timestamp: datetime
    source: str = "gateway"

    context: TraceContext
    target: TraceTarget

    action: str
    payload: dict[str, Any] | None = None
    device_state: dict[str, Any] | None = None
    status: TraceStatus

    decision: str | None = None
    trace_hash: str | None = None

    def compute_hash(self) -> str:
        body = self.model_dump_json(include=HASHED_FIELDS)
        return hashlib.sha256(body.encode()).hexdigest()
