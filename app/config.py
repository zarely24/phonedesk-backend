"""Central configuration, read from environment variables.

Locally everything has dev-safe defaults so you can just run it. On Render you set the
real values in the Environment tab (never in code) — same pattern as your CRM.
"""
import os


class Settings:
    # SQLite locally (zero setup); Render injects a Postgres DATABASE_URL automatically.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./phonedesk.db")

    # Secrets — OVERRIDE THESE on Render (Environment tab).
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-insecure-change-me")
    DEVICE_TOKEN_PEPPER: str = os.getenv("DEVICE_TOKEN_PEPPER", "dev-pepper-change-me")

    JWT_ALG: str = "HS256"
    ACCESS_TTL: int = int(os.getenv("ACCESS_TTL", str(60 * 60 * 12)))   # 12h (dev-friendly)
    SESSION_TOKEN_TTL: int = int(os.getenv("SESSION_TOKEN_TTL", "3600"))  # stream cookie lifetime

    # Bootstrap admin (created on first startup if no such user exists).
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@local").lower()
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin1234")


settings = Settings()
