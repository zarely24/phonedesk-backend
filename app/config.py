"""Central configuration, read from environment variables.

Locally everything has dev-safe defaults so you can just run it. On Render you set the
real values in the Environment tab (never in code) — same pattern as your CRM.
"""
import os
import tempfile


class Settings:
    # SQLite locally (zero setup); Render injects a Postgres DATABASE_URL automatically.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./phonedesk.db")

    # Secrets — OVERRIDE THESE on Render (Environment tab).
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-insecure-change-me")
    DEVICE_TOKEN_PEPPER: str = os.getenv("DEVICE_TOKEN_PEPPER", "dev-pepper-change-me")

    JWT_ALG: str = "HS256"
    ACCESS_TTL: int = int(os.getenv("ACCESS_TTL", str(60 * 60 * 24 * 30)))   # 30d - VAs stay signed in across shifts
    # Stream pass lifetime. The stream page auto-renews it every ~25 min, so a session never expires
    # while it's open; 24h is just a big safety margin (covers a laptop sleeping mid-shift).
    SESSION_TOKEN_TTL: int = int(os.getenv("SESSION_TOKEN_TTL", str(60 * 60 * 24)))  # 24h

    # Bootstrap admin (created on first startup if no such user exists).
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@local").lower()
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin1234")

    # Media upload-to-gallery. Files only live here transiently — they're pushed to the phone
    # by the agent within seconds, then deleted (so Render's ephemeral disk is fine). UPLOAD_DIR
    # defaults to a temp dir; MAX_UPLOAD_MB caps a single file; abandoned transfers (agent went
    # offline before fetching) are swept after UPLOAD_TTL_SEC.
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", os.path.join(tempfile.gettempdir(), "phonedesk-uploads"))
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "500"))
    UPLOAD_TTL_SEC: int = int(os.getenv("UPLOAD_TTL_SEC", str(30 * 60)))  # 30 min


settings = Settings()
