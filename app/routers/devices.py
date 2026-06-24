import os
import re
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user, require_admin
from ..models import Agent, Assignment, Device
from ..presence import presence
from ..relay.agent_ws import _lookup_device
from ..security import hash_device_token
from ..transfers import transfers

router = APIRouter()


def _safe_name(name: str) -> str:
    """Reduce an uploaded filename to a safe basename (no path traversal, sane charset)."""
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    return name[:120] or "file"


def _view(d: Device, can_control: bool = True) -> dict:
    p = presence.get(d.id)
    return {
        "id": d.id,
        "can_control": can_control,  # may this viewer push controls (upload, switch, refresh…)?
        "public_id": d.public_id,
        "name": d.name,
        "brand": d.brand,
        "model": d.model,
        "android_version": d.android_version,
        "serial": d.serial,
        "online": bool(p.get("online")),
        "battery": p.get("battery"),
        "charging": p.get("charging"),          # live: is the phone drawing charge right now?
        "charge_status": p.get("charge_status"),  # agent-reported: firmware / poll / unavailable / off
        "last_seen": p.get("last_seen"),
        "users": p.get("users", []),            # Android users (profiles) the agent reported
        "current_user": p.get("current_user"),  # active profile id
        "charge_limit_enabled": d.charge_limit_enabled,
        "charge_stop": d.charge_stop,
        "charge_resume": d.charge_resume,
        "upload_status": p.get("upload_status"),  # last upload-to-gallery result the agent reported
    }


@router.get("/devices")
def list_devices(user=Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        rows = db.query(Device).order_by(Device.created_at).all()
        return [_view(d, True) for d in rows]
    # VA: only assigned devices; carry each assignment's can_control through to the view.
    cc = {a.device_id: bool(a.can_control)
          for a in db.query(Assignment).filter(Assignment.user_id == user.id).all()}
    q = db.query(Device).filter(Device.id.in_(list(cc) or ["__none__"]))
    return [_view(d, cc.get(d.id, False)) for d in q.order_by(Device.created_at).all()]


@router.get("/devices/{device_id}")
def get_device(device_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    can_control = True
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a:
            raise HTTPException(403, "not assigned")
        can_control = bool(a.can_control)
    return _view(d, can_control)


class RenameIn(BaseModel):
    name: str


@router.patch("/devices/{device_id}")
def rename_device(device_id: str, body: RenameIn,
                  admin=Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    d.name = body.name.strip() or d.name
    db.commit()
    return _view(d)


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Remove a phone. The owner's app is told to forget its token (frees a pairing slot);
    if the app is offline, its next connect gets a 4401 and it cleans itself up."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    conn = presence.conn(device_id)
    if conn is not None:
        try:
            await conn.send_json({"op": "unpair"})
        except Exception:
            pass
    db.query(Assignment).filter_by(device_id=device_id).delete()
    agent_id = d.agent_id
    db.delete(d)
    db.flush()   # the device row must go before its agent (devices.agent_id FK)
    db.query(Agent).filter_by(id=agent_id).delete()   # token hash gone -> later connects rejected (4401)
    db.commit()
    presence.set_offline(device_id)
    return {"ok": True}


class SwitchUserIn(BaseModel):
    user_id: int


@router.post("/devices/{device_id}/switch-user")
async def switch_user(device_id: str, body: SwitchUserIn,
                      user=Depends(current_user), db: Session = Depends(get_db)):
    """Switch the phone's active Android user (profile); the agent also cycles airplane mode for a fresh IP."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    conn = presence.conn(device_id)
    if conn is None:
        raise HTTPException(409, "device offline")
    await conn.send_json({"op": "switch_user", "user_id": body.user_id})
    return {"ok": True}


@router.post("/devices/{device_id}/refresh")
async def refresh_device(device_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    """VA-triggered remote refresh: tell the owner's app to restart adb + the screen engine and
    reconnect - recovers a stuck/frozen phone without the owner touching anything (no prompt)."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    conn = presence.conn(device_id)
    if conn is None:
        raise HTTPException(409, "device offline")
    await conn.send_json({"op": "refresh"})
    return {"ok": True}


class RenameUserIn(BaseModel):
    user_id: int
    name: str


@router.post("/devices/{device_id}/rename-user")
async def rename_user(device_id: str, body: RenameUserIn,
                      user=Depends(current_user), db: Session = Depends(get_db)):
    """Rename an Android user (profile). The agent renames it on the phone itself where the
    Android version allows; otherwise it keeps the name locally and reports it in every meta."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    name = body.name.strip()[:24]
    if not name:
        raise HTTPException(422, "empty name")
    conn = presence.conn(device_id)
    if conn is None:
        raise HTTPException(409, "device offline")
    await conn.send_json({"op": "rename_user", "user_id": body.user_id, "name": name})
    return {"ok": True}


class ChargePolicyIn(BaseModel):
    enabled: bool = True
    stop: int = 80
    resume: int = 25


@router.post("/devices/{device_id}/charge-policy")
async def set_charge_policy(device_id: str, body: ChargePolicyIn,
                           user=Depends(current_user), db: Session = Depends(get_db)):
    """Set the battery charge-limit policy. The phone stays plugged in continuously; the
    owner's app stops charging at `stop`% and resumes at `resume`%, keeping the USB-C
    data/control link alive the whole time. Persisted so it's re-applied on reconnect."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    if not (0 < body.resume < body.stop <= 100):
        raise HTTPException(422, "need 0 < resume < stop <= 100")
    d.charge_limit_enabled = body.enabled
    d.charge_stop = body.stop
    d.charge_resume = body.resume
    db.commit()
    conn = presence.conn(device_id)
    if conn is not None:
        try:
            await conn.send_json({"op": "set_charge_policy", "enabled": body.enabled,
                                  "stop": body.stop, "resume": body.resume})
        except Exception:
            pass  # offline/stale socket — the policy is persisted and re-sent on reconnect
    return _view(d)


class CreateProfilesIn(BaseModel):
    count: int
    package: str = ""
    name_prefix: str = "Profile"


@router.post("/devices/{device_id}/create-profiles")
async def create_profiles(device_id: str, body: CreateProfilesIn,
                          user=Depends(current_user), db: Session = Depends(get_db)):
    """Bulk-create Android user profiles (GrapheneOS). The agent runs `pm create-user` for
    each and clones the given app into every new profile, then reports the new users back in
    its next meta op (which populates the profile switcher)."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    if not (1 <= body.count <= 50):
        raise HTTPException(422, "count must be 1..50")
    conn = presence.conn(device_id)
    if conn is None:
        raise HTTPException(409, "device offline")
    await conn.send_json({"op": "create_profiles", "count": body.count,
                          "package": body.package.strip(),
                          "name_prefix": (body.name_prefix.strip() or "Profile")[:24]})
    return {"ok": True}


@router.post("/devices/{device_id}/upload-media")
async def upload_media(device_id: str, files: list[UploadFile] = File(...),
                       user=Depends(current_user), db: Session = Depends(get_db)):
    """Upload photos/videos straight into the phone's gallery (DCIM/Camera), full quality.

    The bytes are streamed to a transient temp dir and the agent is handed a job ticket; it
    pulls the bytes back over HTTP, `adb push`es them to the active profile and triggers a
    media scan, then the temp files are deleted. Nothing is recompressed end-to-end."""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a or not a.can_control:
            raise HTTPException(403, "not allowed")
    if not files or not (1 <= len(files) <= 50):
        raise HTTPException(422, "attach 1..50 files")
    conn = presence.conn(device_id)
    if conn is None:
        raise HTTPException(409, "device offline")

    transfers.sweep()  # opportunistically drop abandoned transfers
    transfer_id = transfers.new_id()
    tdir = transfers.dir_for(transfer_id)
    os.makedirs(tdir, exist_ok=True)
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    entries, manifest = [], []
    try:
        for idx, uf in enumerate(files):
            name = _safe_name(uf.filename)
            path = os.path.join(tdir, f"{idx}_{name}")
            size = 0
            with open(path, "wb") as out:
                while True:
                    chunk = await uf.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(413, f"{name} exceeds {settings.MAX_UPLOAD_MB} MB")
                    out.write(chunk)
            await uf.close()
            entries.append({"idx": idx, "name": name, "size": size, "path": path})
            manifest.append({"idx": idx, "name": name, "size": size})
    except HTTPException:
        shutil.rmtree(tdir, ignore_errors=True)
        raise

    transfers.register(transfer_id, device_id, entries)
    try:
        await conn.send_json({"op": "upload_media", "transfer_id": transfer_id, "files": manifest})
    except Exception:
        transfers.cleanup(transfer_id)
        raise HTTPException(409, "device offline")
    return {"ok": True, "transfer_id": transfer_id, "count": len(entries)}


@router.get("/devices/media/{transfer_id}/{idx}")
def download_media(transfer_id: str, idx: int, token: str = ""):
    """Agent-only: stream one file of a transfer back to the agent. Authenticated by the
    device token (same secret the agent uses for /ws/agent), and it must own the transfer."""
    dev_id = _lookup_device(hash_device_token(token))
    if not dev_id:
        raise HTTPException(401, "bad token")
    rec = transfers.get(transfer_id)
    if not rec or rec["device_id"] != dev_id:
        raise HTTPException(404, "no such transfer")
    fp = transfers.file_path(transfer_id, idx)
    if not fp:
        raise HTTPException(404, "no such file")
    path, name = fp
    if not os.path.exists(path):
        raise HTTPException(404, "gone")
    return FileResponse(path, filename=name)


@router.get("/devices/{device_id}/upload-status/{transfer_id}")
def upload_status(device_id: str, transfer_id: str,
                  user=Depends(current_user), db: Session = Depends(get_db)):
    """Poll the result of an upload. While pending the agent hasn't reported yet; once done
    it carries per-file ok/error. (Also mirrored into the device's presence as upload_status.)"""
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404, "not found")
    if user.role != "admin":
        a = db.query(Assignment).filter_by(device_id=device_id, user_id=user.id).first()
        if not a:
            raise HTTPException(403, "not assigned")
    rec = transfers.get(transfer_id)
    if rec is not None and rec["device_id"] == device_id:
        return {"status": rec["status"], "result": rec["result"]}
    # Transfer already cleaned up after completion — fall back to the last status in presence.
    p = presence.get(device_id)
    st = p.get("upload_status")
    if st and st.get("transfer_id") == transfer_id:
        return {"status": "done", "result": st.get("results")}
    return {"status": "unknown", "result": None}
