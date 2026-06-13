"""In-memory presence + the live agent connections.

For the MVP (one backend instance, <=10 phones) this is all we need — no Redis.
When you scale to multiple backend instances, this is the piece that moves to Redis.
"""
import time
from typing import Any

# A healthy agent sends a meta heartbeat every 10s (and answers ws ping/pong). Treat a device as
# online only while we've heard from it inside this window, so a half-open/dead socket that stops
# sending stops showing ONLINE on its own — no background sweep needed (checked on read).
ONLINE_TIMEOUT = 40.0


class Presence:
    def __init__(self) -> None:
        self._conns: dict[str, Any] = {}          # device_id -> agent WebSocket
        self._meta: dict[str, dict] = {}          # device_id -> {online, battery, last_seen}

    def _fresh(self, m: dict) -> bool:
        return bool(m.get("online") and (time.time() - m.get("last_seen", 0) < ONLINE_TIMEOUT))

    def set_online(self, device_id: str, conn: Any, meta: dict | None = None) -> None:
        self._conns[device_id] = conn
        m = self._meta.setdefault(device_id, {})
        m.update({"online": True, "last_seen": time.time()})
        if meta:
            m.update(meta)

    def set_offline(self, device_id: str, conn: Any | None = None) -> None:
        # Only the CURRENT socket may take a device offline. When the agent recycles a half-open
        # link it reconnects (a new socket calls set_online); the old socket's late close must NOT
        # then wipe the freshly-online connection. Pass conn=None to force offline (device deleted).
        if conn is not None and self._conns.get(device_id) is not conn:
            return
        self._conns.pop(device_id, None)
        if device_id in self._meta:
            self._meta[device_id]["online"] = False
            self._meta[device_id]["last_seen"] = time.time()

    def touch(self, device_id: str, battery: int | None = None) -> None:
        m = self._meta.setdefault(device_id, {})
        m["online"] = True
        m["last_seen"] = time.time()
        if battery is not None:
            m["battery"] = battery

    def update(self, device_id: str, data: dict) -> None:
        m = self._meta.setdefault(device_id, {})
        m.update(data)
        m["online"] = True
        m["last_seen"] = time.time()

    def is_online(self, device_id: str) -> bool:
        m = self._meta.get(device_id)
        return bool(m and self._fresh(m) and device_id in self._conns)

    def conn(self, device_id: str) -> Any:
        return self._conns.get(device_id)

    def get(self, device_id: str) -> dict:
        m = self._meta.get(device_id)
        if not m:
            return {"online": False}
        # Report online off the heartbeat freshness, not just a sticky flag, so a phone that went
        # dark without a clean socket close still flips to offline within ONLINE_TIMEOUT.
        return {**m, "online": self._fresh(m)}


presence = Presence()
