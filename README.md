# PhoneDesk backend (Phase 1 foundation)

FastAPI control plane + relay. SQLite for local dev, Postgres on Render. Vanilla dashboard served
from `web/`. This is the foundation: auth, pairing, devices, presence, and the agent/viewer
WebSockets. The live video tunnel is added in Phase 1b.

## Run it locally (Windows)
```powershell
.\run-dev.ps1        # creates the venv on first run, then starts on http://localhost:8000
```
Open http://localhost:8000 → log in with **admin@local / admin1234** (change later).

## Verify it works (no phone needed)
With the backend running, in another terminal:
```powershell
.\.venv\Scripts\python.exe tools\smoke_test.py     # full automated check, prints PASSED ✅
```
Or see it in the browser:
```powershell
# 1) Dashboard → "+ Add device" → copy the code (e.g. 4F9-2KD)
.\.venv\Scripts\python.exe tools\fake_agent.py 4F9-2KD   # a "Demo phone" appears 🟢
```

## What works now
- Login (admin + VAs), JWT auth, role scoping (VAs see only assigned devices).
- "+ Add device" → pairing code → agent pairs → device registered with a device token.
- Agent phone-home WebSocket (`/ws/agent`) → live online/offline + battery in the dashboard.
- `POST /api/sessions` → 60-second scoped stream token → `/ws/viewer` validates it.

## Deploy to Render (Phase 1 hosting)
1. Push this `backend/` folder to a new GitHub repo (GitHub Desktop).
2. Render → New → **Web Service** (Docker), connect the repo, **Starter** instance.
3. Render → New → **PostgreSQL**; it sets `DATABASE_URL` automatically.
4. Set Environment vars: `JWT_SECRET`, `DEVICE_TOKEN_PEPPER`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
5. Deploy. Your dashboard is at `https://<service>.onrender.com`.

## Layout
```
app/
  main.py            app wiring + static mount + admin seed
  config.py db.py    settings + SQLAlchemy engine (SQLite/Postgres)
  models.py          users, agents, devices, pairing_codes, assignments
  security.py        pbkdf2 passwords, JWTs, device tokens
  presence.py        in-memory online/battery + live agent sockets
  deps.py            auth dependencies (current_user, require_admin)
  routers/           auth, devices, pairing, sessions
  relay/             agent_ws (phone-home), viewer_ws (stream token check)
web/                 vanilla dashboard (login, devices, va console placeholder)
tools/               smoke_test.py, fake_agent.py
```
