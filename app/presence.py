"""In-memory presence + the live agent connections.

For the MVP (one backend instance, <=10 phones) this is all we need — no Redis.
When you scale to multiple backend instances, this is the piece that moves to Redis.
"""
import time
from typing import Any


class Presence:
    def __init__(self) -> None:
        self._conns: dict[str, Any] = {}          # device_id -> agent WebSocket
        self._meta: dict[str, dict] = {}          # device_id -> {online, battery, last_seen}

    def set_online(self, device_id: str, conn: Any, meta: dict | None = None) -> None:
        self._conns[device_id] = conn
        m = self._meta.setdefault(device_id, {})
        m.update({"online": True, "last_seen": time.time()})
        if meta:
            m.update(meta)

    def set_offline(self, device_id: str) -> None:
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
        return device_id in self._conns

    def conn(self, device_id: str) -> Any:
        return self._conns.get(device_id)

    def get(self, device_id: str) -> dict:
        return self._meta.get(device_id, {"online": False})


presence = Presence()
