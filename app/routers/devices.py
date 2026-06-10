from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_admin
from ..models import Assignment, Device
from ..presence import presence

router = APIRouter()


def _view(d: Device) -> dict:
    p = presence.get(d.id)
    return {
        "id": d.id,
        "public_id": d.public_id,
        "name": d.name,
        "brand": d.brand,
        "model": d.model,
        "android_version": d.android_version,
        "serial": d.serial,
        "online": bool(p.get("online")),
        "battery": p.get("battery"),
        "last_seen": p.get("last_seen"),
        "users": p.get("users", []),            # Android users (profiles) the agent reported
        "current_user": p.get("current_user"),  # active profile id
    }


@router.get("/devices")
def list_devices(user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Device)
    if user.role != "admin":
        ids = [row[0] for row in
               db.query(Assignment.device_id).filter(Assignment.user_id == user.id).all()]
        q = q.filter(Device.id.in_(ids or ["__none__"]))
    return [_view(d) for d in q.order_by(Device.created_at).all()]


@router.get("/devices/{device_id}")
def get_device(device_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a:
            raise HTTPException(403, "not assigned")
    return _view(d)


class RenameIn(BaseModel):
    name: str


@router.patch("/devices/{device_id}")
def rename_device(device_id: str, body: RenameIn,
                  admin=Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    d.name = body.name.strip() or d.name
    db.commit()
    return _view(d)


class SwitchUserIn(BaseModel):
    user_id: int


@router.post("/devices/{device_id}/switch-user")
async def switch_user(device_id: str, body: SwitchUserIn,
                      user=Depends(current_user), db: Session = Depends(get_db)):
    """Switch the phone's active Android user (profile); the agent also cycles airplane mode for a fresh IP."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    conn = presence.conn(device_id)
    if conn is None:
        raise HTTPException(409, "device offline")
    await conn.send_json({"op": "switch_user", "user_id": body.user_id})
    return {"ok": True}


class RenameUserIn(BaseModel):
    user_id: int
    name: str


@router.post("/devices/{device_id}/rename-user")
async def rename_user(device_id: str, body: RenameUserIn,
                      user=Depends(current_user), db: Session = Depends(get_db)):
    """Rename an Android user (profile). The agent renames it on the phone itself where the
    Android version allows; otherwise it keeps the name locally and reports it in every meta."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    name = body.name.strip()[:24]
    if not name:
        raise HTTPException(422, "empty name")
    conn = presence.conn(device_id)
    if conn is None:
        raise HTTPException(409, "device offline")
    await conn.send_json({"op": "rename_user", "user_id": body.user_id, "name": name})
    return {"ok": True}
