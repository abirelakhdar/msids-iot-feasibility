from fastapi import FastAPI
from pydantic import BaseModel


USERS = {
    "admin_01": "admin",
    "user_01": "user",
    "guest_01": "guest",
}

PERMISSIONS = {
    "admin": {"lamp", "thermostat", "lock"},
    "user": {"lamp", "thermostat"},
    "guest": {"lamp"},
}


class AuthRequest(BaseModel):
    user_id: str
    device_type: str
    action: str


class AuthResponse(BaseModel):
    allowed: bool
    user_role: str
    reason: str


app = FastAPI(title="UMMS")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/authorize")
def authorize(req: AuthRequest) -> AuthResponse:
    role = USERS.get(req.user_id)
    if role is None:
        return AuthResponse(allowed=False, user_role="unknown", reason="unknown user")

    if req.device_type not in PERMISSIONS[role]:
        return AuthResponse(
            allowed=False,
            user_role=role,
            reason=f"role '{role}' may not control '{req.device_type}' devices",
        )

    return AuthResponse(allowed=True, user_role=role, reason="authorized")
