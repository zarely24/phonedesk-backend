"""End-to-end smoke test for the backend foundation — no phone or Electron needed.

Start the backend first (run-dev.ps1 or uvicorn), then:
    .venv\\Scripts\\python.exe tools\\smoke_test.py
"""
import asyncio
import json
import sys

import httpx
import websockets

try:  # Windows consoles default to cp1252 and choke on ✓/emoji
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://localhost:8000"
WSBASE = "ws://localhost:8000"
ADMIN = {"email": "admin@local", "password": "admin1234"}


async def main() -> None:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.post("/api/auth/login", json=ADMIN)
        r.raise_for_status()
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        print("1. admin login OK")

        r = c.post("/api/pairing-codes", headers=headers)
        r.raise_for_status()
        code = r.json()["code"]
        print(f"2. pairing code created: {code}")

        r = c.post("/api/devices/pair", json={
            "code": code, "brand": "Samsung", "model": "SM-S911B",
            "android_version": "14", "name": "Test phone", "os": "win",
        })
        r.raise_for_status()
        dev = r.json()
        device_token, device_id = dev["device_token"], dev["device_id"]
        print(f"3. device paired: public_id={dev['public_id']}")

        async with websockets.connect(f"{WSBASE}/ws/agent?token={device_token}") as agent:
            await agent.send(json.dumps({"op": "meta", "data": {"battery": 83}}))
            await agent.send(json.dumps({"op": "heartbeat", "battery": 83}))
            await asyncio.sleep(0.5)
            print("4. agent connected + heartbeat sent")

            r = c.get("/api/devices", headers=headers)
            r.raise_for_status()
            d0 = next((x for x in r.json() if x["id"] == device_id), None)
            assert d0 and d0["online"] and d0["battery"] == 83, f"device not online: {d0}"
            print("5. device shows ONLINE with battery 83% ✓")

            r = c.post("/api/sessions", headers=headers, json={"device_id": device_id})
            r.raise_for_status()
            stream_token = r.json()["token"]
            print("6. session token minted ✓")

            async with websockets.connect(f"{WSBASE}/ws/viewer?token={stream_token}") as viewer:
                msg = json.loads(await asyncio.wait_for(viewer.recv(), timeout=5))
                assert msg.get("op") == "info", f"unexpected viewer msg: {msg}"
                print("7. viewer reached the device through the relay ✓")

        await asyncio.sleep(0.3)
        r = c.get("/api/devices", headers=headers)
        d0 = next((x for x in r.json() if x["id"] == device_id), None)
        assert d0 and not d0["online"], "device should be offline after agent disconnect"
        print("8. device went OFFLINE after agent disconnected ✓")

    print("\nSMOKE TEST PASSED ✅")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nSMOKE TEST FAILED ❌: {exc!r}")
        sys.exit(1)
