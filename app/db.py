"""Database engine + session. SQLite locally, Postgres on Render — same code."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

# Render gives DATABASE_URL as postgres://… ; SQLAlchemy + psycopg3 wants postgresql+psycopg://…
url = settings.DATABASE_URL
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://") and "+psycopg" not in url:
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency: one Session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
