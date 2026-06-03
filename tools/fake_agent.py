"""Bring a FAKE device 'online' so you can see the dashboard work without a real phone.

1) In the dashboard, click "+ Add device" to get a code (e.g. 4F9-2KD).
2) .venv\\Scripts\\python.exe tools\\fake_agent.py 4F9-2KD
3) Refresh the dashboard — a "Demo phone" shows up 🟢. Ctrl-C to take it offline.
"""
import asyncio
import json
import sys

import httpx
import websockets

BASE = "http://localhost:8000"
WSBASE = "ws://localhost:8000"


async def main(code: str) -> None:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.post("/api/devices/pair", json={
            "code": code, "brand": "Google", "model": "Pixel 8",
            "android_version": "15", "name": "Demo phone", "os": "win",
        })
        r.raise_for_status()
        dev = r.json()
    print(f"paired '{dev['public_id']}' — keeping it online (Ctrl-C to stop)")
    async with websockets.connect(f"{WSBASE}/ws/agent?token={dev['device_token']}") as ws:
        await ws.send(json.dumps({"op": "meta", "data": {"battery": 91}}))
        while True:
            await ws.send(json.dumps({"op": "heartbeat", "battery": 91}))
            await asyncio.sleep(10)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python fake_agent.py <PAIRING-CODE>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
