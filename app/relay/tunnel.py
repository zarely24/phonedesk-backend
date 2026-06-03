"""The streaming tunnel: browser <-> backend <-> agent <-> agent's local ws-scrcpy <-> phone.

ws-scrcpy's client opens ONE multiplexer WebSocket (ManagerClient). We serve that client from the
backend at /stream/, so the socket comes back to us at /stream/. We then bridge it to the owner's
agent over a per-stream socket (/ws/agent-stream); the agent pipes it into its LOCAL ws-scrcpy.

Auth: clicking Connect sets a short-lived 'pd_stream' cookie (a stream JWT). The browser sends it on
the /stream/ WebSocket handshake; we validate it -> device -> the agent's live phone-home socket.

Pairing: the viewer arrives first and signals the agent; the agent then connects a /ws/agent-stream
socket. The AGENT-side handler runs the byte-pump (it has both sockets); the viewer-side handler
parks until the pump ends (so neither socket is read by two coroutines at once).
"""
import asyncio
import uuid

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketState

from ..db import SessionLocal
from ..models import Agent, Device
from ..presence import presence
from ..security import decode_token, hash_device_token

router = APIRouter()

# stream_id -> {"viewer": WebSocket, "paired": Future, "done": Future}
_pending: dict[str, dict] = {}


def _device_for_agent_token(token_hash: str):
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter_by(device_token_hash=token_hash, revoked=False).first()
        if not agent:
            return None
        device = db.query(Device).filter_by(agent_id=agent.id).first()
        return device.id if device else None
    finally:
        db.close()


async def _pump(src: WebSocket, dst: WebSocket):
    while True:
        msg = await src.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        if msg.get("bytes") is not None:
            await dst.send_bytes(msg["bytes"])
        elif msg.get("text") is not None:
            await dst.send_text(msg["text"])


async def _bridge(a: WebSocket, b: WebSocket):
    t1 = asyncio.create_task(_pump(a, b))
    t2 = asyncio.create_task(_pump(b, a))
    try:
        await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (t1, t2):
            t.cancel()


async def _close(ws: WebSocket):
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.close()
    except Exception:
        pass


@router.websocket("/stream/")
@router.websocket("/stream")
async def viewer_stream(ws: WebSocket):
    """The ws-scrcpy client's multiplexer socket (served from /stream/) lands here."""
    token = ws.cookies.get("pd_stream", "")
    try:
        claims = decode_token(token)
        if claims.get("type") != "stream":
            raise ValueError("bad token type")
    except Exception:
        await ws.close(code=4401)
        return

    device_id = claims["dev"]
    agent_home = presence.conn(device_id)
    await ws.accept()
    if agent_home is None:
        await ws.send_json({"op": "error", "msg": "device offline"})
        await ws.close()
        return

    loop = asyncio.get_event_loop()
    stream_id = uuid.uuid4().hex
    entry = {"viewer": ws, "paired": loop.create_future(), "done": loop.create_future()}
    _pending[stream_id] = entry
    try:
        # Forward the viewer's query string so the agent opens the MATCHING ws-scrcpy endpoint:
        # `action=multiplex` for the device list, `action=proxy-adb&remote=...&udid=...` for the
        # live video. Without this, every viewer was forced onto the multiplexer, so the raw video
        # handshake hit the multiplex parser ("Unsupported message type") and no frames flowed.
        target_query = ws.scope.get("query_string", b"").decode("latin-1")
        await agent_home.send_json({"op": "open_stream", "stream_id": stream_id, "query": target_query})
        await asyncio.wait_for(entry["paired"], timeout=10)  # agent connected its side
        await entry["done"]                                   # park until the pump ends
    except Exception:
        pass
    finally:
        _pending.pop(stream_id, None)
        await _close(ws)


@router.websocket("/ws/agent-stream")
async def agent_stream(ws: WebSocket):
    """The agent opens one of these per viewer, after an 'open_stream' signal. It runs the pump."""
    token = ws.query_params.get("token", "")
    stream_id = ws.query_params.get("stream_id", "")
    if not _device_for_agent_token(hash_device_token(token)):
        await ws.close(code=4401)
        return
    await ws.accept()

    entry = _pending.get(stream_id)
    if entry is None or entry["paired"].done():
        await ws.close()
        return
    entry["paired"].set_result(True)
    try:
        await _bridge(entry["viewer"], ws)
    finally:
        if not entry["done"].done():
            entry["done"].set_result(True)
        await _close(ws)
