"""Pairing: admin generates a code; the owner's agent submits it to register a phone."""
import secrets
import string
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import Agent, Device, PairingCode, _now
from ..security import new_device_token

router = APIRouter()

_ALPHABET = string.ascii_uppercase + string.digits  # no lowercase → easy to read/type


def _gen_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(6))
    return f"{raw[:3]}-{raw[3:]}"


@router.post("/pairing-codes")
def create_pairing_code(admin=Depends(require_admin), db: Session = Depends(get_db)):
    code = _gen_code()
    pc = PairingCode(code=code, created_by=admin.id, expires_at=_now() + timedelta(minutes=30))
    db.add(pc)
    db.commit()
    return {"code": code, "expires_at": pc.expires_at.isoformat()}


class PairIn(BaseModel):
    code: str
    name: str = "New phone"
    brand: str = ""
    model: str = ""
    android_version: str = ""
    serial: str = ""
    os: str = ""


@router.post("/devices/pair")
def pair(body: PairIn, db: Session = Depends(get_db)):
    """Called by the desktop agent. Returns a device token it stores and uses to phone home."""
    pc = db.get(PairingCode, body.code.strip().upper())
    if not pc or pc.consumed or pc.expires_at < _now():
        raise HTTPException(400, "invalid or expired pairing code")

    raw_token, token_hash = new_device_token()
    agent = Agent(device_token_hash=token_hash, os=body.os)
    db.add(agent)
    db.flush()  # get agent.id

    device = Device(
        agent_id=agent.id,
        name=(body.name.strip() or body.model.strip() or "New phone"),
        brand=body.brand, model=body.model,
        android_version=body.android_version, serial=body.serial,
    )
    db.add(device)
    pc.consumed = True
    db.commit()

    return {"device_token": raw_token, "device_id": device.id, "public_id": device.public_id}
