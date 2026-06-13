"""The phone-home socket. The owner's agent connects here (outbound) and stays connected.

For the foundation step this carries presence + heartbeats. The live stream tunnel
(browser <-> relay <-> agent <-> local ws-scrcpy) is added on top of this in Phase 1b.
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..db import SessionLocal
from ..models import Agent, Device, _now
from ..presence import presence
from ..security import hash_device_token

router = APIRouter()


def _lookup_device(token_hash: str):
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter_by(device_token_hash=token_hash, revoked=False).first()
        if not agent:
            return None
        device = db.query(Device).filter_by(agent_id=agent.id).first()
        return device.id if device else None
    finally:
        db.close()


def _persist_last_seen(device_id: str):
    db = SessionLocal()
    try:
        d = db.get(Device, device_id)
        if d:
            d.last_seen = _now()
            db.commit()
    finally:
        db.close()


@router.websocket("/ws/agent")
async def agent_ws(ws: WebSocket):
    token = ws.query_params.get("token", "")
    device_id = await asyncio.to_thread(_lookup_device, hash_device_token(token))
    if not device_id:
        await ws.close(code=4401)  # bad/unknown device token
        return

    await ws.accept()
    presence.set_online(device_id, ws)
    try:
        while True:
            msg = await ws.receive_json()
            op = msg.get("op")
            if op == "heartbeat":
                presence.touch(device_id, msg.get("battery"))
            elif op == "meta":
                presence.update(device_id, msg.get("data", {}))
            elif op == "log":
                # The agent forwards its local agent.log lines here for the admin log view.
                presence.add_log(device_id, str(msg.get("line", ""))[:2000])
            # op == "tunnel" handled in Phase 1b
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # Pass our own socket: if the agent already reconnected (a newer socket is current),
        # this stale close becomes a no-op instead of knocking the live device offline.
        presence.set_offline(device_id, ws)
        await asyncio.to_thread(_persist_last_seen, device_id)
