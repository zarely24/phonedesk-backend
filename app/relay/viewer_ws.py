"""The VA's browser connects here with a short-lived stream token.

Foundation step: validate the token + device presence, then report status. The actual
bidirectional media/input tunnel to the agent is added in Phase 1b.
"""
from fastapi import APIRouter, WebSocket

from ..presence import presence
from ..security import decode_token

router = APIRouter()


@router.websocket("/ws/viewer")
async def viewer_ws(ws: WebSocket):
    token = ws.query_params.get("token", "")
    try:
        claims = decode_token(token)
        if claims.get("type") != "stream":
            raise ValueError("wrong token type")
    except Exception:
        await ws.close(code=4401)
        return

    await ws.accept()
    device_id = claims["dev"]
    if not presence.is_online(device_id):
        await ws.send_json({"op": "error", "msg": "device offline"})
        await ws.close()
        return

    await ws.send_json({
        "op": "info",
        "msg": "Relay reached this device. Live screen + control arrive in Phase 1b "
               "(needs the desktop agent running ws-scrcpy).",
    })
    await ws.close()
