"""Start a control session: checks permission + device is online, mints a 60s stream token."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Assignment, Device
from ..presence import presence
from ..security import make_session_token

router = APIRouter()


class SessionIn(BaseModel):
    device_id: str


@router.post("/sessions")
def start_session(body: SessionIn, response: Response,
                  user=Depends(current_user), db: Session = Depends(get_db)):
    device = db.get(Device, body.device_id)
    if not device:
        raise HTTPException(404, "device not found")

    if user.role != "admin":
        grant = db.query(Assignment).filter_by(device_id=device.id, user_id=user.id).first()
        if not grant:
            raise HTTPException(403, "you are not assigned to this device")

    if not presence.is_online(device.id):
        raise HTTPException(409, "device is offline")

    session_id = str(uuid.uuid4())
    token = make_session_token(user.id, device.id, session_id)
    # The browser sends this cookie on the /stream/ WebSocket handshake; the tunnel validates it.
    response.set_cookie("pd_stream", token, max_age=3600, httponly=True, samesite="lax", path="/")
    return {
        "session_id": session_id,
        "token": token,
        "serial": device.serial,
        "public_id": device.public_id,
    }
