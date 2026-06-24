"""Bring a FAKE device 'online' so you can see the dashboard work without a real phone.

1) In the dashboard, click "+ Add device" to get a code (e.g. 4F9-2KD).
2) .venv\\Scripts\\python.exe tools\\fake_agent.py 4F9-2KD
3) Refresh the dashboard — a "Demo phone" shows up 🟢. Ctrl-C to take it offline.

This fake agent also exercises the newer relay ops so you can test without a real phone:
  - heartbeats include a `charging` flag (toggles as the simulated battery crosses the
    stored charge limit), so the dashboard battery indicator updates;
  - it prints any `set_charge_policy` / `create_profiles` ops the backend relays;
  - on `create_profiles` it replies with a `meta` op adding fake users, so the new profiles
    show up in the dashboard and the stream-page profile switcher;
  - on `upload_media` it fetches each file back over HTTP, checks the byte count matches what
    the backend advertised (proving the bytes survive intact / full quality), and replies with
    an `upload_result` op so the dashboard shows per-file ✅/❌.

Run several copies with different pairing codes to simulate many phones on one computer.
"""
import asyncio
import json
import sys

import httpx
import websockets

BASE = "http://localhost:8000"
WSBASE = "ws://localhost:8000"


class FakeDevice:
    def __init__(self, name: str) -> None:
        self.name = name
        self.token = ""   # device token, set after pairing (used to fetch uploaded media)
        self.battery = 78
        self.charging = True
        # Charge policy the backend pushes on connect / via set_charge_policy.
        self.limit_enabled = True
        self.stop = 80
        self.resume = 25
        self.users = [{"id": 0, "name": "Owner"}]
        self.current_user = 0

    def step_battery(self) -> None:
        """Simulate the charge-limit loop: charge up to `stop`, then sit until `resume`."""
        if self.charging:
            self.battery = min(100, self.battery + 3)
            if self.limit_enabled and self.battery >= self.stop:
                self.charging = False  # hit the cap — stop charging, keep USB-C alive
        else:
            self.battery = max(0, self.battery - 2)
            if self.battery <= self.resume:
                self.charging = True   # dropped to the floor — resume charging

    def meta(self) -> dict:
        return {"op": "meta", "data": {
            "battery": self.battery, "charging": self.charging,
            "users": self.users, "current_user": self.current_user,
        }}


async def _send_loop(ws, dev: FakeDevice) -> None:
    await ws.send(json.dumps(dev.meta()))
    while True:
        dev.step_battery()
        await ws.send(json.dumps({
            "op": "heartbeat", "battery": dev.battery, "charging": dev.charging,
        }))
        await asyncio.sleep(10)


async def _recv_loop(ws, dev: FakeDevice) -> None:
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        op = msg.get("op")
        if op == "set_charge_policy":
            dev.limit_enabled = bool(msg.get("enabled", True))
            dev.stop = int(msg.get("stop", dev.stop))
            dev.resume = int(msg.get("resume", dev.resume))
            print(f"[{dev.name}] set_charge_policy -> enabled={dev.limit_enabled} "
                  f"stop={dev.stop} resume={dev.resume}")
        elif op == "create_profiles":
            count = int(msg.get("count", 0))
            prefix = msg.get("name_prefix", "Profile")
            pkg = msg.get("package", "")
            print(f"[{dev.name}] create_profiles -> count={count} package='{pkg}' prefix='{prefix}'")
            next_id = max((u["id"] for u in dev.users), default=0) + 1
            for i in range(count):
                dev.users.append({"id": next_id + i, "name": f"{prefix} {next_id + i}"})
            await ws.send(json.dumps(dev.meta()))  # report the new users back
        elif op == "upload_media":
            transfer_id = msg.get("transfer_id", "")
            files = msg.get("files", [])
            print(f"[{dev.name}] upload_media -> {len(files)} file(s), transfer={transfer_id}")
            results = []
            for f in files:
                idx, name, want = f.get("idx"), f.get("name"), f.get("size")
                try:
                    url = f"{BASE}/api/devices/media/{transfer_id}/{idx}?token={dev.token}"
                    got = await asyncio.to_thread(lambda: httpx.get(url, timeout=60).content)
                    ok = len(got) == want
                    err = None if ok else f"size mismatch {len(got)}!={want}"
                    print(f"    {'OK' if ok else 'BAD'} {name} ({len(got)} bytes)")
                    results.append({"name": name, "ok": ok, "error": err})
                except Exception as e:
                    print(f"    FAIL {name}: {e}")
                    results.append({"name": name, "ok": False, "error": str(e)})
            await ws.send(json.dumps({
                "op": "upload_result", "transfer_id": transfer_id, "results": results,
            }))
        elif op in ("refresh", "switch_user", "rename_user", "unpair"):
            print(f"[{dev.name}] {op} {msg}")
        else:
            print(f"[{dev.name}] (unhandled op) {msg}")


async def main(code: str) -> None:
    dev = FakeDevice("Demo phone")
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.post("/api/devices/pair", json={
            "code": code, "brand": "Google", "model": "Pixel 8",
            "android_version": "15", "name": dev.name, "os": "win",
        })
        r.raise_for_status()
        paired = r.json()
    dev.token = paired["device_token"]
    print(f"paired '{paired['public_id']}' — keeping it online (Ctrl-C to stop)")
    async with websockets.connect(f"{WSBASE}/ws/agent?token={paired['device_token']}") as ws:
        await asyncio.gather(_send_loop(ws, dev), _recv_loop(ws, dev))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python fake_agent.py <PAIRING-CODE>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
