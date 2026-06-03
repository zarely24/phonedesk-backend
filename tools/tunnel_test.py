"""Directly test the streaming tunnel without a browser:
login -> session (token) -> connect the viewer WS with the cookie -> expect bytes from the phone."""
import asyncio
import sys

import httpx
import websockets

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:8080"
WS = "ws://127.0.0.1:8080/stream/?action=multiplex"


async def main():
    c = httpx.Client(base_url=BASE, timeout=10)
    t = c.post("/api/auth/login", json={"email": "admin@local", "password": "admin1234"}).json()["access_token"]
    devs = c.get("/api/devices", headers={"Authorization": f"Bearer {t}"}).json()
    did = devs[0]["id"]
    s = c.post("/api/sessions", headers={"Authorization": f"Bearer {t}"}, json={"device_id": did}).json()
    token = s["token"]
    print("session ok, serial =", s.get("serial"))

    try:
        async with websockets.connect(WS, additional_headers={"Cookie": f"pd_stream={token}"}, max_size=None) as ws:
            print("VIEWER WS CONNECTED")
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=6)
                n = len(msg) if hasattr(msg, "__len__") else msg
                print(f"GOT DATA through tunnel: {type(msg).__name__} {n}")
            except asyncio.TimeoutError:
                print("connected but NO DATA in 6s (agent/local ws-scrcpy not piping)")
    except Exception as e:
        print("VIEWER WS FAILED:", repr(e))


asyncio.run(main())
