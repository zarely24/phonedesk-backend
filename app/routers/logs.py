"""Admin-only view of an agent's recent log lines (forwarded live over /ws/agent).

Logs can contain serials/IPs, so this is admin-only — VAs never see them. The buffer is
in-memory in Presence (per device), so it survives socket reconnects and clears on restart.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import Device
from ..presence import presence

router = APIRouter()


@router.get("/devices/{device_id}/logs")
def get_device_logs(device_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    return {"logs": presence.get_logs(device_id), "online": presence.is_online(device_id)}
