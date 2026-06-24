"""Transient media-transfer store for upload-to-gallery.

A file uploaded from the dashboard lives here only briefly: the backend writes the bytes to a
temp dir, hands the agent a job ticket over the WebSocket, the agent pulls the bytes back over
HTTP and pushes them to the phone, then the files are deleted. So nothing here is durable — it
just bridges the gap between "admin clicked upload" and "agent fetched the bytes". That makes
Render's ephemeral filesystem a non-issue (files never need to survive a restart).

In-memory, single-instance — same trade-off as presence.py. If you ever run multiple backend
instances this (like presence) is what would move to shared storage.
"""
import os
import secrets
import shutil
import time
from typing import Any

from .config import settings


class Transfers:
    def __init__(self) -> None:
        # transfer_id -> {device_id, dir, files:[{idx,name,size,path}], created, status, result}
        self._t: dict[str, dict] = {}

    def new_id(self) -> str:
        return secrets.token_urlsafe(16)

    def dir_for(self, transfer_id: str) -> str:
        return os.path.join(settings.UPLOAD_DIR, transfer_id)

    def register(self, transfer_id: str, device_id: str, files: list[dict]) -> dict:
        """Record a transfer whose files have already been written to its dir.

        `files` is a list of {idx, name, size, path}.
        """
        rec = {
            "device_id": device_id,
            "dir": self.dir_for(transfer_id),
            "files": files,
            "created": time.time(),
            "status": "pending",
            "result": None,
        }
        self._t[transfer_id] = rec
        return rec

    def get(self, transfer_id: str) -> dict | None:
        return self._t.get(transfer_id)

    def file_path(self, transfer_id: str, idx: int) -> tuple[str, str] | None:
        """Return (path, name) for one file of a transfer, or None if unknown."""
        rec = self._t.get(transfer_id)
        if not rec:
            return None
        for f in rec["files"]:
            if f["idx"] == idx:
                return f["path"], f["name"]
        return None

    def set_result(self, transfer_id: str, results: list[dict]) -> None:
        rec = self._t.get(transfer_id)
        if not rec:
            return
        rec["result"] = results
        rec["status"] = "done"

    def cleanup(self, transfer_id: str) -> None:
        """Delete a transfer's files + record (called once the phone has them)."""
        rec = self._t.pop(transfer_id, None)
        if rec:
            shutil.rmtree(rec["dir"], ignore_errors=True)

    def sweep(self, ttl: int | None = None) -> int:
        """Drop transfers older than the TTL (agent never came to fetch them). Returns count."""
        ttl = settings.UPLOAD_TTL_SEC if ttl is None else ttl
        now = time.time()
        stale = [tid for tid, rec in self._t.items() if now - rec["created"] > ttl]
        for tid in stale:
            self.cleanup(tid)
        return len(stale)


transfers = Transfers()
