"""FastAPI app: REST API + agent/viewer WebSockets + serves the static dashboard."""
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal, init_db
from .models import User
from .relay import agent_ws, tunnel, viewer_ws
from .routers import auth, devices, logs, pairing, sessions
from .security import hash_password

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
WEB_DIR = os.path.join(BASE_DIR, "web")

app = FastAPI(title="PhoneDesk backend")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    _seed_admin()


def _seed_admin() -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if not existing:
            db.add(User(
                email=settings.ADMIN_EMAIL,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                role="admin",
                full_name="Admin",
            ))
            db.commit()
    finally:
        db.close()


@app.get("/healthz")
def healthz():
    return {"ok": True}


# REST API (registered before the static catch-all so /api/* wins)
app.include_router(auth.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(pairing.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")

# WebSockets
app.include_router(agent_ws.router)
app.include_router(viewer_ws.router)
app.include_router(tunnel.router)  # /stream/ (viewer) + /ws/agent-stream — registered before the static mount

# Static dashboard (serves index.html, login.html, va.html, css/js). Mounted last.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
